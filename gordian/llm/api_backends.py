"""API backends: Anthropic Messages API and any OpenAI-compatible chat endpoint."""
from __future__ import annotations

import os
from typing import Optional

from .base import Backend, LLMResponse, Usage
from ..log import get_logger

log = get_logger(__name__)


class AnthropicBackend(Backend):
    """Direct Anthropic API via the official SDK.

    ``effort`` maps to ``output_config.effort`` (low|medium|high|xhigh|max).
    ``temperature`` is only sent when explicitly given (Claude 4.6+ models reject
    sampling parameters; Claude 3.x models accept them).
    """

    name = "anthropic"

    def __init__(self, model: str, *, effort: Optional[str] = "high", temperature: Optional[float] = None,
                 max_tokens: int = 16000, base_url: Optional[str] = None, api_key_env: str = "ANTHROPIC_API_KEY",
                 fallbacks: bool = True, **kw):
        super().__init__(**kw)
        import anthropic  # local import so the package is optional for other backends
        self.model = model
        self.effort = effort
        self.temperature = temperature
        self.max_tokens = max_tokens
        key = os.environ.get(api_key_env) if api_key_env else None
        self.client = anthropic.Anthropic(api_key=key, base_url=base_url, max_retries=4, timeout=600.0)
        self.fallbacks = fallbacks and base_url is None and _is_claude_5(model)
        self._legacy = _is_legacy_claude(model)

    def _complete(self, prompt: str, system: Optional[str]) -> LLMResponse:
        import anthropic
        kwargs = dict(model=self.model, max_tokens=self.max_tokens,
                      messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = system
        if self._legacy:
            if self.temperature is not None:
                kwargs["temperature"] = self.temperature
        else:
            if self.effort:
                kwargs["output_config"] = {"effort": self.effort}
        try:
            if self.fallbacks:
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.BadRequestError as exc:
            # Older proxies / models: retry once without the newer knobs.
            log.warning("anthropic 400 (%s); retrying without effort/fallbacks", exc.message)
            kwargs.pop("output_config", None)
            resp = self.client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            detail = getattr(resp, "stop_details", None)
            raise RuntimeError(f"model refused: {getattr(detail, 'category', None)} {getattr(detail, 'explanation', '')}")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        usage = Usage(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens, calls=1)
        return LLMResponse(text=text, usage=usage, model=resp.model)


def _is_claude_5(model: str) -> bool:
    return any(t in model for t in ("-5-", "-5", "fable", "mythos")) and model.startswith("claude")


def _is_legacy_claude(model: str) -> bool:
    return model.startswith("claude-3") or "-4-0" in model or "-4-1" in model or "-4-5" in model or "sonnet-4-20" in model


class OpenAICompatibleBackend(Backend):
    """Any ``/v1/chat/completions`` endpoint: OpenAI, DeepSeek, OpenRouter, lab proxies.

    ``base_url`` and ``api_key_env`` select the provider.  Temperature is
    dropped automatically if the endpoint rejects it (reasoning models).
    """

    name = "openai-compatible"

    def __init__(self, model: str, *, base_url: Optional[str] = None, api_key_env: str = "OPENAI_API_KEY",
                 temperature: Optional[float] = 0.5, max_tokens: Optional[int] = None,
                 reasoning_effort: Optional[str] = None, provider_name: str = "openai", **kw):
        super().__init__(**kw)
        from openai import OpenAI
        self.model = model
        self.name = provider_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        key = os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(f"environment variable {api_key_env} is not set (needed for {provider_name}/{model})")
        self.client = OpenAI(api_key=key, base_url=base_url, max_retries=4, timeout=600.0)

    def _complete(self, prompt: str, system: Optional[str]) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs = dict(model=self.model, messages=messages)
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "temperature" in msg or "unsupported" in msg.lower() or "max_tokens" in msg:
                kwargs.pop("temperature", None)
                if "max_tokens" in msg and self.max_tokens:
                    kwargs.pop("max_tokens", None)
                    kwargs["max_completion_tokens"] = self.max_tokens
                log.warning("retrying %s without unsupported parameters: %s", self.model, msg[:200])
                resp = self.client.chat.completions.create(**kwargs)
            else:
                raise
        text = resp.choices[0].message.content or ""
        u = resp.usage
        usage = Usage(input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                      output_tokens=getattr(u, "completion_tokens", 0) or 0, calls=1)
        return LLMResponse(text=text, usage=usage, model=resp.model or self.model)
