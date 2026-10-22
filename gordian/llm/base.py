"""Backend-agnostic LLM interface.

Two levels of service are offered to the pipeline:

* ``complete(prompt)``  -- one prompt in, one text out (classic API usage).

* ``run_task(TaskSpec)`` -- a *task* with a working directory containing input
  files and a list of output files the model must produce.  Agent backends
  (Claude Code, Codex) execute this natively with their own tools; API backends
  emulate it by embedding the inputs in a single prompt and parsing fenced
  ``<<<FILE name>>> ... <<<END FILE>>>`` blocks out of the reply.  Every stage of
  the pipeline is written against ``run_task`` so that both modes work.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..log import get_logger

log = get_logger(__name__)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    wall_seconds: float = 0.0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls
        self.wall_seconds += other.wall_seconds

    def as_dict(self) -> dict:
        return dict(input_tokens=self.input_tokens, output_tokens=self.output_tokens,
                    calls=self.calls, wall_seconds=round(self.wall_seconds, 2))


@dataclass
class LLMResponse:
    text: str
    usage: Usage
    model: str
    cached: bool = False


@dataclass
class TaskSpec:
    """A unit of work handed to the model.

    ``workdir`` must exist and hold the input files.  ``inputs`` are paths
    relative to ``workdir`` that the model should read; ``outputs`` are paths
    relative to ``workdir`` the model must write.  ``instructions`` is the
    task text (what to do, constraints, output contract).  ``name`` is used for
    log file names.
    """
    name: str
    instructions: str
    workdir: Path
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    max_turns: int = 60
    timeout_s: int = 1800
    allow_shell: bool = True


@dataclass
class TaskResult:
    ok: bool
    outputs: dict[str, str]          # relative path -> content, for files that exist
    missing: list[str]
    transcript: str
    usage: Usage
    error: Optional[str] = None


FILE_BLOCK_RE = re.compile(r"<<<FILE\s+(?P<name>[^\n>]+?)\s*>>>\n(?P<body>.*?)\n?<<<END FILE>>>", re.S)


def parse_file_blocks(text: str) -> dict[str, str]:
    """Extract ``<<<FILE name>>> ... <<<END FILE>>>`` blocks from a model reply.

    Markdown code fences immediately inside the block are stripped so that a
    model which wraps the body in ```c ... ``` still parses.
    """
    out: dict[str, str] = {}
    for m in FILE_BLOCK_RE.finditer(text):
        name = m.group("name").strip().strip("`'\"")
        body = m.group("body")
        fence = re.match(r"^```[a-zA-Z0-9_+-]*\n(?P<inner>.*)\n```\s*$", body, re.S)
        if fence:
            body = fence.group("inner")
        out[name] = body if body.endswith("\n") else body + "\n"
    return out


class Backend(ABC):
    """Base class.  Subclasses implement ``_complete`` and optionally ``_run_task``."""

    name: str = "base"
    model: str = ""
    is_agent: bool = False

    def __init__(self, log_dir: Optional[Path] = None, cache: Optional["ResponseCache"] = None):
        self.log_dir = Path(log_dir) if log_dir else None
        self.cache = cache
        self.usage = Usage()
        self._counter = 0

    # ---- plain completion -------------------------------------------------
    def complete(self, prompt: str, system: Optional[str] = None, tag: str = "prompt") -> LLMResponse:
        key = self._cache_key(prompt, system)
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                self._log(tag, prompt, hit, cached=True)
                return LLMResponse(text=hit, usage=Usage(), model=self.model, cached=True)
        t0 = time.time()
        resp = self._complete(prompt, system)
        resp.usage.wall_seconds = time.time() - t0
        resp.usage.calls = max(resp.usage.calls, 1)
        self.usage.add(resp.usage)
        if self.cache is not None:
            self.cache.put(key, resp.text)
        self._log(tag, prompt, resp.text, cached=False, usage=resp.usage)
        return resp

    @abstractmethod
    def _complete(self, prompt: str, system: Optional[str]) -> LLMResponse: ...

    # ---- task execution ---------------------------------------------------
    def run_task(self, task: TaskSpec) -> TaskResult:
        task.workdir = Path(task.workdir)
        task.workdir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            result = self._run_task(task)
        except Exception as exc:  # noqa: BLE001 - surface any backend failure as a result
            log.exception("task %s failed in backend %s", task.name, self.name)
            result = TaskResult(ok=False, outputs={}, missing=list(task.outputs), transcript="",
                                usage=Usage(), error=f"{type(exc).__name__}: {exc}")
        result.usage.wall_seconds = max(result.usage.wall_seconds, time.time() - t0)
        # Re-scan the workdir so outputs written by an agent are picked up.
        outputs, missing = {}, []
        for rel in task.outputs:
            p = task.workdir / rel
            if p.exists():
                outputs[rel] = p.read_text(encoding="utf-8", errors="replace")
            else:
                missing.append(rel)
        result.outputs, result.missing = outputs, missing
        result.ok = result.ok and not missing
        if self.log_dir:
            (self.log_dir / f"{self._next_id()}.task.{task.name}.json").write_text(json.dumps(dict(
                name=task.name, backend=self.name, model=self.model, ok=result.ok, missing=missing,
                error=result.error, usage=result.usage.as_dict(), instructions=task.instructions,
                inputs=task.inputs, outputs=list(outputs)), indent=2))
            (self.log_dir / f"{self._counter:04d}.task.{task.name}.transcript.md").write_text(result.transcript or "")
        return result

    def _run_task(self, task: TaskSpec) -> TaskResult:
        """Default emulation of a task through a single completion."""
        prompt = self.render_task_prompt(task)
        resp = self.complete(prompt, tag=f"task.{task.name}")
        blocks = parse_file_blocks(resp.text)
        written = {}
        for rel in task.outputs:
            if rel in blocks:
                p = task.workdir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(blocks[rel], encoding="utf-8")
                written[rel] = blocks[rel]
        # A model that only produced one unlabeled file for a single-output task
        if not written and len(task.outputs) == 1 and len(blocks) == 1:
            rel = task.outputs[0]
            body = next(iter(blocks.values()))
            (task.workdir / rel).write_text(body, encoding="utf-8")
            written[rel] = body
        missing = [o for o in task.outputs if o not in written]
        return TaskResult(ok=not missing, outputs=written, missing=missing, transcript=resp.text, usage=resp.usage)

    @staticmethod
    def render_task_prompt(task: TaskSpec) -> str:
        parts = [task.instructions.rstrip(), ""]
        if task.inputs:
            parts.append("## Input files")
            for rel in task.inputs:
                p = task.workdir / rel
                if not p.exists():
                    continue
                body = p.read_text(encoding="utf-8", errors="replace")
                parts.append(f"### {rel}\n```\n{body}\n```")
        parts.append("## Output contract")
        parts.append("Return every required output file verbatim, each wrapped exactly like this "
                     "(no extra prose inside the block, no markdown fences needed):\n")
        for rel in task.outputs:
            parts.append(f"<<<FILE {rel}>>>\n...file content...\n<<<END FILE>>>\n")
        parts.append("Required outputs: " + ", ".join(task.outputs))
        return "\n".join(parts)

    # ---- helpers ------------------------------------------------------------
    def _cache_key(self, prompt: str, system: Optional[str]) -> str:
        h = hashlib.sha256()
        h.update(self.model.encode()); h.update(b"\0")
        h.update((system or "").encode()); h.update(b"\0")
        h.update(prompt.encode())
        return h.hexdigest()

    def _next_id(self) -> str:
        self._counter += 1
        return f"{self._counter:04d}"

    def _log(self, tag: str, prompt: str, response: str, cached: bool, usage: Optional[Usage] = None) -> None:
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        i = self._next_id()
        (self.log_dir / f"{i}.{tag}.prompt.md").write_text(prompt, encoding="utf-8")
        suffix = "cached" if cached else "response"
        (self.log_dir / f"{i}.{tag}.{suffix}.md").write_text(response, encoding="utf-8")
        if usage is not None:
            with (self.log_dir / "usage.jsonl").open("a") as f:
                f.write(json.dumps(dict(id=i, tag=tag, model=self.model, **usage.as_dict())) + "\n")


class ResponseCache:
    """On-disk prompt cache: ``<root>/<model>/<sha256>.md``.

    Deterministic replay: the first response to a prompt is
    stored and replayed on subsequent runs.  Set ``replay_only=True`` to forbid
    network calls (raises on a miss).
    """

    def __init__(self, root: Path, model: str, replay_only: bool = False):
        self.root = Path(root).expanduser() / re.sub(r"[^A-Za-z0-9_.-]", "_", model)
        self.root.mkdir(parents=True, exist_ok=True)
        self.replay_only = replay_only

    def get(self, key: str) -> Optional[str]:
        p = self.root / f"{key}.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
        if self.replay_only:
            raise RuntimeError(f"cache miss in replay-only mode: {p}")
        return None

    def put(self, key: str, text: str) -> None:
        (self.root / f"{key}.md").write_text(text, encoding="utf-8")
