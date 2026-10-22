"""Argument/environment boundary for ``python -m gordian.demo``."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from ..config import load_settings
from ..docker import Container
from ..log import configure
from .model import api_key, endpoint_config, make_client
from .workflow import run_demo


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="One-example KLEE / Gordian trig demo (external libm)")
    result.add_argument("--root", type=Path, help="repository root containing gordian.yaml")
    result.add_argument("--provider", choices=("openrouter", "deepinfra", "custom"), default="openrouter")
    result.add_argument("--base-url", help="OpenAI-compatible API base, including its v1 path")
    result.add_argument("--key-env", help="environment variable holding your key; the value is never saved")
    result.add_argument("--model", help="exact endpoint model ID; required unless --baseline-only")
    result.add_argument("--request-seconds", type=positive_int, default=60, help="SDK request timeout; retries disabled")
    result.add_argument("--klee-seconds", type=positive_int, default=10, help="budget for EACH KLEE run")
    result.add_argument("--solver-seconds", type=positive_int, default=2)
    result.add_argument("--replay-seconds", type=positive_int, default=2, help="timeout per native replay")
    result.add_argument("--max-tests", type=positive_int, default=32, help="replay cap per KLEE run; all tests retained")
    result.add_argument("--name", help="new run directory name, without path separators")
    result.add_argument("--pause", action="store_true", help="wait for Enter before the main demo steps")
    result.add_argument("--baseline-only", action="store_true", help="KLEE and replay only; no endpoint required")
    return result


def run_from_args(args, environment: dict[str, str], emit, pause) -> int:
    settings = load_settings(args.root)
    root = settings.project_root.resolve()
    name = args.name or time.strftime("trig-demo_%Y%m%d-%H%M%S")
    if name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("--name must be one directory name")
    directory = (settings.runs / name).resolve()
    directory.relative_to(root)  # all execution artifacts must be in the mounted project
    client = None
    url = key_name = None
    if not args.baseline_only:
        if not args.model:
            raise ValueError("--model is required unless --baseline-only is set")
        url, key_name = endpoint_config(args.provider, args.base_url, args.key_env)
        client = make_client(url, api_key(environment, key_name), args.request_seconds)
    options = dict(model=args.model, provider=args.provider, base_url=url, key_env=key_name,
                   request_seconds=args.request_seconds, klee_seconds=args.klee_seconds,
                   solver_seconds=args.solver_seconds, replay_seconds=args.replay_seconds,
                   max_tests=args.max_tests, baseline_only=args.baseline_only)
    example = root / "demos/trig"
    try:
        report = run_demo(Container(settings, settings.std, is_float=False), root, directory,
                          (example / "driver.c").read_text(), (example / "guard.inc").read_text(),
                          options, client, emit, pause if args.pause else None)
    finally:
        if client is not None:
            client.close()
    return 0 if report["status"] in ("improved", "baseline_only", "baseline_already_succeeds") else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    configure("INFO")
    try:
        return run_from_args(args, dict(os.environ), lambda text: print(text, flush=True), input)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Demo stopped: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Demo interrupted; inspect retained artifacts before retrying with a new name.", file=sys.stderr)
        return 130
