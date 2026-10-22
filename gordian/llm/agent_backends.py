"""Agent backends: Claude Code and Codex CLIs driven headlessly.

Both run inside the task's working directory with file tools enabled, so the
model can read the C sources, run small experiments (gcc, python) and write
the requested output files itself.  ``complete()`` is also supported (a plain
prompt with no tools) so these backends can be used anywhere an API backend
can.

Claude Code can be pointed at any Anthropic-compatible endpoint through
``extra_env`` (``ANTHROPIC_BASE_URL``, ``ANTHROPIC_AUTH_TOKEN``, model slot
overrides).  ``gordian.llm.gateway`` provides such an endpoint for
OpenAI-compatible providers (e.g. DeepSeek), see ``factory.py``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .base import Backend, LLMResponse, TaskResult, TaskSpec, Usage
from ..log import get_logger

log = get_logger(__name__)

AGENT_TASK_PREAMBLE = """You are working inside the directory {workdir}. It contains the input files listed below.
Do the task described, then write every required output file into this directory at the exact relative path given.
Do not ask questions; make reasonable assumptions and state them in a comment inside the output file.
Do not modify the input files. Do not create files other than the required outputs (scratch files go in ./scratch/).
You may compile and run small C or Python experiments to check your work{shell_note}, but do not build
whole libraries or test rigs: a `clang -fsyntax-only` check of your output is enough.  You have about
{minutes} minutes of wall-clock time for this task; finish well within it and always leave the output files
on disk even if imperfect.

Input files: {inputs}
Required output files: {outputs}

# Task
{instructions}
"""


def _preamble(task: TaskSpec) -> str:
    return AGENT_TASK_PREAMBLE.format(
        workdir=task.workdir, inputs=", ".join(task.inputs) or "(none)", outputs=", ".join(task.outputs),
        instructions=task.instructions.rstrip(), minutes=max(1, task.timeout_s // 60),
        shell_note="" if task.allow_shell else " (but shell access is disabled for this task)")


class ClaudeCodeBackend(Backend):
    name = "claude-code"
    is_agent = True

    def __init__(self, model: str, *, effort: Optional[str] = None, extra_env: Optional[dict] = None,
                 claude_bin: str = "claude", config_dir: Optional[Path] = None, max_budget_usd: Optional[float] = None,
                 **kw):
        super().__init__(**kw)
        self.model = model
        self.effort = effort
        self.extra_env = dict(extra_env or {})
        self.bin = shutil.which(claude_bin) or claude_bin
        self.config_dir = Path(config_dir) if config_dir else None
        self.max_budget_usd = max_budget_usd
        if not shutil.which(self.bin):
            raise RuntimeError(f"claude CLI not found ({claude_bin}); install Claude Code or pass claude_bin")

    def _env(self) -> dict:
        env = dict(os.environ)
        env.update(self.extra_env)
        for k, v in list(env.items()):
            if v == "" and k.startswith("ANTHROPIC_"):
                env.pop(k)  # an empty override means "unset"
        env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
        if self.config_dir:
            env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        # Never inherit a nested-session marker from a parent Claude Code session.
        env.pop("CLAUDECODE", None)
        return env

    def _base_cmd(self, tools: list[str], max_turns: int) -> list[str]:
        cmd = [self.bin, "-p", "--output-format", "json", "--model", self.model, "--max-turns", str(max_turns),
               "--permission-mode", "bypassPermissions", "--dangerously-skip-permissions"]
        if tools:
            cmd += ["--tools", ",".join(tools), "--allowedTools", ",".join(tools)]
        else:
            cmd += ["--tools", ""]
        if self.effort:
            cmd += ["--effort", self.effort]
        if self.max_budget_usd:
            cmd += ["--max-budget-usd", str(self.max_budget_usd)]
        return cmd

    def _run(self, cmd: list[str], prompt: str, cwd: Path, env: dict, timeout_s: int) -> tuple[list[dict], str, int, bool]:
        """Run claude -p with stream-json output; on timeout send SIGINT (then SIGKILL) and keep what we got."""
        import signal
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(cwd), env=env, text=True)
        events, stderr, timed_out = [], "", False
        try:
            out, stderr = proc.communicate(input=prompt, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.send_signal(signal.SIGINT)
            try:
                out, stderr = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, stderr = proc.communicate()
        for line in (out or "").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events, stderr or "", proc.returncode, timed_out

    def _invoke(self, prompt: str, cwd: Path, tools: list[str], max_turns: int, timeout_s: int) -> tuple[str, Usage, str]:
        cmd = self._base_cmd(tools, max_turns)
        cmd[cmd.index("json")] = "stream-json"
        cmd += ["--verbose"]
        log.info("claude-code: %s (cwd=%s, turns<=%d, timeout=%ds)", self.model, cwd, max_turns, timeout_s)
        env = self._env()
        events, stderr, rc, timed_out = self._run(cmd, prompt, cwd, env, timeout_s)
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result and "Invalid API key" in str(result.get("result", "")) and env.get("ANTHROPIC_API_KEY") \
                and not self.extra_env.get("ANTHROPIC_BASE_URL"):
            log.warning("claude-code rejected ANTHROPIC_API_KEY from the environment; retrying with the CLI login")
            env.pop("ANTHROPIC_API_KEY", None)
            self.extra_env["ANTHROPIC_API_KEY"] = ""
            events, stderr, rc, timed_out = self._run(cmd, prompt, cwd, env, timeout_s)
            result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result and result.get("subtype") == "error_during_execution" and not timed_out:
            # the CLI aborted mid-task (seen under a rate-limit event): one retry after a pause; the task's
            # outputs written so far stay in the workdir, so an in-place edit task resumes from them
            import time
            log.warning("claude-code: error_during_execution after %s turns; retrying once in 30 s", result.get("num_turns"))
            time.sleep(30)
            events, stderr, rc, timed_out = self._run(cmd, prompt, cwd, env, timeout_s)
            result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        usage = Usage(calls=1)
        text = ""
        if result:
            text = result.get("result") or ""
            u = result.get("usage") or {}
            usage.input_tokens = int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
            usage.output_tokens = int(u.get("output_tokens", 0))
            if result.get("is_error") or str(result.get("subtype", "")).startswith("error"):
                # keep the whole event stream for diagnosis and surface the last assistant text
                (cwd / "claude_code_error_events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
                last = ""
                for e in events:
                    if e.get("type") == "assistant":
                        for block in (e.get("message") or {}).get("content", []):
                            if block.get("type") == "text":
                                last = block["text"]
                errs = [str(e.get("error") or e.get("message")) for e in events if e.get("type") in ("error", "system") and ("error" in e or e.get("subtype") == "error")]
                raise RuntimeError(f"claude-code error: {result.get('subtype')} {text[:300]} | last: {last[-300:]} | {' '.join(errs)[-300:]}")
        else:
            # no final result (timeout / crash): summarise the assistant turns we saw
            for e in events:
                if e.get("type") == "assistant":
                    for block in (e.get("message") or {}).get("content", []):
                        if block.get("type") == "text":
                            text += block["text"] + "\n"
                u = (e.get("message") or {}).get("usage") if e.get("type") == "assistant" else None
                if u:
                    usage.output_tokens += int(u.get("output_tokens", 0))
            if not events and rc != 0:
                raise RuntimeError(f"claude-code failed (rc={rc}): {stderr[-2000:]}")
            if timed_out:
                log.warning("claude-code task timed out after %ds; keeping files written so far", timeout_s)
        transcript = f"$ {' '.join(cmd)}\n\n" + "\n".join(json.dumps(e)[:4000] for e in events) + f"\n\n[stderr]\n{stderr[-4000:]}"
        return text, usage, transcript

    def _complete(self, prompt: str, system: Optional[str]) -> LLMResponse:
        full = (system + "\n\n" if system else "") + prompt
        with tempfile.TemporaryDirectory(prefix="gordian-cc-") as tmp:
            text, usage, _ = self._invoke(full, Path(tmp), tools=[], max_turns=1, timeout_s=1800)
        return LLMResponse(text=text, usage=usage, model=self.model)

    def _run_task(self, task: TaskSpec) -> TaskResult:
        tools = ["Read", "Write", "Edit", "Glob", "Grep"] + (["Bash"] if task.allow_shell else [])
        text, usage, transcript = self._invoke(_preamble(task), task.workdir, tools, task.max_turns, task.timeout_s)
        self.usage.add(usage)
        return TaskResult(ok=True, outputs={}, missing=[], transcript=transcript + "\n\n[final]\n" + text, usage=usage)


class CodexBackend(Backend):
    name = "codex"
    is_agent = True

    def __init__(self, model: str, *, codex_bin: str = "codex", extra_env: Optional[dict] = None,
                 reasoning_effort: Optional[str] = None, **kw):
        super().__init__(**kw)
        self.model = model
        self.bin = shutil.which(codex_bin) or codex_bin
        self.extra_env = dict(extra_env or {})
        self.reasoning_effort = reasoning_effort
        if not shutil.which(self.bin):
            raise RuntimeError(f"codex CLI not found ({codex_bin}); install OpenAI Codex or pass codex_bin")

    def _env(self) -> dict:
        env = dict(os.environ)
        env.update(self.extra_env)
        return env

    def _invoke(self, prompt: str, cwd: Path, sandbox: str, timeout_s: int) -> tuple[str, Usage, str]:
        with tempfile.NamedTemporaryFile("r", suffix=".md", prefix="codex-last-", delete=False) as last:
            last_path = last.name
        cmd = [self.bin, "exec", "--json", "-C", str(cwd), "-s", sandbox, "--skip-git-repo-check", "--ephemeral", "-o", last_path]
        if self.model and self.model != "default":
            cmd += ["-m", self.model]
        if self.reasoning_effort:
            cmd += ["-c", f'model_reasoning_effort="{self.reasoning_effort}"']
        cmd.append("-")  # read prompt from stdin
        log.info("codex: %s (cwd=%s, sandbox=%s)", self.model, cwd, sandbox)
        proc = subprocess.run(cmd, input=prompt, cwd=str(cwd), env=self._env(), text=True,
                              capture_output=True, timeout=timeout_s)
        usage = Usage(calls=1)
        errors = []
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") in ("error", "turn.failed"):
                errors.append(str(ev.get("message") or ev.get("error")))
            u = ev.get("usage") or (ev.get("msg") or {}).get("usage") or (ev.get("info") or {}).get("total_token_usage")
            if isinstance(u, dict):
                usage.input_tokens = int(u.get("input_tokens", usage.input_tokens))
                usage.output_tokens = int(u.get("output_tokens", usage.output_tokens))
        text = Path(last_path).read_text(encoding="utf-8", errors="replace") if Path(last_path).exists() else ""
        if Path(last_path).exists():
            os.unlink(last_path)
        if (proc.returncode != 0 or errors) and not text.strip():
            raise RuntimeError(f"codex failed (rc={proc.returncode}): {' | '.join(errors)[-1500:]} {proc.stderr[-800:]}")
        transcript = f"$ {' '.join(cmd)}\n\n{proc.stdout[-20000:]}\n\n[stderr]\n{proc.stderr[-4000:]}"
        return text, usage, transcript

    def _complete(self, prompt: str, system: Optional[str]) -> LLMResponse:
        full = (system + "\n\n" if system else "") + prompt
        with tempfile.TemporaryDirectory(prefix="gordian-codex-") as tmp:
            text, usage, _ = self._invoke(full, Path(tmp), sandbox="read-only", timeout_s=1800)
        return LLMResponse(text=text, usage=usage, model=self.model)

    def _run_task(self, task: TaskSpec) -> TaskResult:
        sandbox = "workspace-write" if task.allow_shell else "read-only"
        text, usage, transcript = self._invoke(_preamble(task), task.workdir, sandbox, task.timeout_s)
        self.usage.add(usage)
        return TaskResult(ok=True, outputs={}, missing=[], transcript=transcript + "\n\n[final]\n" + text, usage=usage)
