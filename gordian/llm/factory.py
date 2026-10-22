"""Backend factory.

A backend is selected with a *spec* string ``provider:model`` (``model`` alone
defaults to a provider guessed from its name).  Providers:

  anthropic:<model>        Anthropic API           ANTHROPIC_API_KEY
  openai:<model>           OpenAI API              OPENAI_API_KEY
  deepseek:<model>         api.deepseek.com        DEEPSEEK_API_KEY
  openrouter:<model>       openrouter.ai           OPENROUTER_API_KEY
  closeai:<model>          api.openai-proxy.org    CLOSE_API_KEY
  pllab:<model>            llm.xmcp.ltd            PL_LAB_API_KEY
  custom:<model>           $OPENAI_BASE_URL        OPENAI_API_KEY  (any OpenAI-compatible server)
  claude-code:<model>      Claude Code CLI (agent) uses the CLI's own login / ANTHROPIC_API_KEY
  codex:<model>            Codex CLI (agent)       uses the CLI's own login / OPENAI_API_KEY
  claude-code@<provider>:<model>
                           Claude Code CLI driving an OpenAI-compatible model through the
                           built-in gateway, e.g. claude-code@deepseek:deepseek-chat or
                           claude-code@pllab:huawei/deepseek-v4.1-flash

Extra providers can be registered from a JSON file (``--providers``) mapping
name -> {"base_url": ..., "api_key_env": ...}.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Optional

from .base import Backend, ResponseCache
from ..log import get_logger

log = get_logger(__name__)

OPENAI_COMPATIBLE: dict[str, dict] = {
    "openai": {"base_url": None, "api_key_env": "OPENAI_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "closeai": {"base_url": "https://api.openai-proxy.org/v1", "api_key_env": "CLOSE_API_KEY"},
    "pllab": {"base_url": "https://llm.xmcp.ltd/v1", "api_key_env": "PL_LAB_API_KEY"},
    "custom": {"base_url": os.environ.get("OPENAI_BASE_URL"), "api_key_env": "OPENAI_API_KEY"},
}

_gateways: list = []  # keep gateway servers alive for the process lifetime


def list_backends() -> str:
    return __doc__


def register_providers(path: Path) -> None:
    data = json.loads(Path(path).read_text())
    for name, cfg in data.items():
        OPENAI_COMPATIBLE[name] = {"base_url": cfg.get("base_url"), "api_key_env": cfg.get("api_key_env", "OPENAI_API_KEY")}


def _guess_provider(model: str) -> str:
    m = model.lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith(("gpt", "o1", "o3", "o4", "codex")):
        return "openai"
    return "custom"


def parse_spec(spec: str) -> tuple[str, Optional[str], str]:
    """Return (provider, sub_provider, model)."""
    if ":" in spec:
        prov, model = spec.split(":", 1)
    else:
        prov, model = _guess_provider(spec), spec
    sub = None
    if "@" in prov:
        prov, sub = prov.split("@", 1)
    return prov, sub, model


def make_backend(spec: str, *, log_dir: Optional[Path] = None, cache_dir: Optional[Path] = None,
                 replay_only: bool = False, temperature: Optional[float] = 0.5, effort: Optional[str] = None,
                 gateway_output: Optional[Path] = None, max_budget_usd: Optional[float] = None) -> Backend:
    prov, sub, model = parse_spec(spec)
    if replay_only and prov in ("codex", "claude-code"):
        # agent backends drive a CLI that reads files and runs tools; their sessions are not cached, so a
        # replay-only run would silently call the model
        raise ValueError(f"--replay-only is only supported for API backends (anthropic, {', '.join(sorted(OPENAI_COMPATIBLE))}); "
                         f"the {prov} agent backend has no response cache")
    if replay_only and cache_dir is None:
        raise ValueError("--replay-only needs a cache directory (do not combine with --no-cache)")
    cache = ResponseCache(cache_dir, f"{prov}_{model}", replay_only) if cache_dir else None
    common = dict(log_dir=log_dir, cache=cache)
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)

    if prov == "anthropic":
        from .api_backends import AnthropicBackend
        return AnthropicBackend(model, effort=effort or "high", temperature=temperature, **common)

    if prov in OPENAI_COMPATIBLE:
        from .api_backends import OpenAICompatibleBackend
        cfg = OPENAI_COMPATIBLE[prov]
        return OpenAICompatibleBackend(model, base_url=cfg["base_url"], api_key_env=cfg["api_key_env"],
                                       temperature=temperature, reasoning_effort=effort, provider_name=prov, **common)

    if prov == "codex":
        from .agent_backends import CodexBackend
        return CodexBackend(model, reasoning_effort=effort, **common)

    if prov == "claude-code":
        from .agent_backends import ClaudeCodeBackend
        extra_env: dict = {}
        if sub:  # route Claude Code through the gateway to an OpenAI-compatible provider
            if sub not in OPENAI_COMPATIBLE:
                raise ValueError(f"unknown gateway provider {sub!r}; known: {sorted(OPENAI_COMPATIBLE)}")
            from .gateway import Gateway
            cfg = OPENAI_COMPATIBLE[sub]
            key = os.environ.get(cfg["api_key_env"])
            if not key:
                raise RuntimeError(f"{cfg['api_key_env']} is not set (needed for gateway to {sub})")
            out = Path(gateway_output or (Path(log_dir) / "gateway" if log_dir else Path("gateway-logs")))
            gw = Gateway(cfg["base_url"], key, model, out, secrets.token_urlsafe(32)).start()
            _gateways.append(gw)
            extra_env = gw.claude_env()
            log.info("gateway for %s:%s listening on %s", sub, model, gw.url)
            # Claude Code keeps per-config-dir state; isolate it so the user's own login is untouched.
            cfg_dir = out / "claude-config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            backend = ClaudeCodeBackend(model, effort=None, extra_env=extra_env, config_dir=cfg_dir, **common)
            backend.name = f"claude-code@{sub}"
            return backend
        return ClaudeCodeBackend(model, effort=effort, max_budget_usd=max_budget_usd, **common)

    raise ValueError(f"unknown provider {prov!r} in spec {spec!r}\n{__doc__}")
