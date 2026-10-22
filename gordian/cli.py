"""``gordian`` command line."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import load_settings, Settings
from .log import configure, get_logger

log = get_logger(__name__)


def _settings(args) -> Settings:
    s = load_settings(Path(args.root) if getattr(args, "root", None) else None)
    if getattr(args, "replay_max_tests", None) is not None:
        s.replay_max_tests = args.replay_max_tests
    return s


def replay_args(p):
    p.add_argument("--replay-max-tests", type=int, default=None, metavar="N",
                   help="replay at most N (evenly spaced) tests per KLEE run; 0 = replay every test (default from gordian.yaml)")


def cmd_init(args):
    root = Path(args.root or ".").resolve()
    s = Settings(project_root=root)
    if args.klee_image:
        s.std.image = args.klee_image
    if args.float_image:
        s.float.image = args.float_image
    p = s.save()
    print(f"wrote {p}")


def cmd_docker(args):
    from .docker import Runtime
    s = _settings(args)
    rt = Runtime(s)
    if args.action == "up":
        rt.up(recreate=args.recreate, which=args.which)
    elif args.action == "down":
        rt.std.down(); rt.float.down()
    print(json.dumps(rt.status(), indent=2))


def cmd_bench(args):
    from .bench import init_targets
    from .targets import list_targets
    s = _settings(args)
    if args.action == "init":
        ts = init_targets(s.project_root, args.family or None)
        print(f"{len(ts)} targets written to {s.project_root / 'benchmarks/targets'}")
    else:
        for t in list_targets(s.project_root, args.family[0] if args.family else None):
            print(f"{t.name:32s} {t.family:12s} {'float' if t.float else 'std  '}  {t.coverage_files[0] if t.coverage_files else t.sources[0]}")


def _backend(args, s: Settings, run_dir: Path):
    from .llm import make_backend
    from .llm.factory import register_providers
    if args.providers:
        register_providers(Path(args.providers))
    cache_dir = None if args.no_cache else (Path(args.cache_dir) if args.cache_dir else s.cache)
    return make_backend(args.model, log_dir=run_dir / "llm", cache_dir=cache_dir, replay_only=args.replay_only,
                        temperature=args.temperature, effort=args.effort, max_budget_usd=args.max_budget_usd)


def _run_dir(s: Settings, name: str, target_name: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return s.runs / (name or f"{target_name}_{stamp}")


def cmd_run(args):
    from .docker import Runtime
    from .targets import find_target
    from .pipeline import run_pipeline, PipelineOptions
    s = _settings(args)
    rt = Runtime(s)
    rt.std.ensure_running()
    t = find_target(s.project_root, args.target)
    if args.float is not None:
        t.float = args.float
    if t.float:
        rt.float.ensure_running()
    stages = args.stages.split(",") if args.stages else ["partition", "rewrite", "inversion"]
    if stages != ["auto"] and not all(st in ("partition", "rewrite", "inversion") for st in stages):
        raise SystemExit(f"--stages: expected a comma list among partition,rewrite,inversion or `auto`, got {args.stages!r}")
    run_dir = _run_dir(s, args.name, t.name)
    configure(args.log_level, run_dir / "gordian.log" if run_dir.mkdir(parents=True, exist_ok=True) is None else None)
    backend = _backend(args, s, run_dir)
    opts = PipelineOptions(budget_s=args.budget, stages=stages, context=args.context, partition_variants=args.variants, inversion_candidates=args.candidates,
                           solver_timeout_s=args.solver_timeout, explore_max_s=args.explore_max, keep_tests=args.keep_tests)
    report = run_pipeline(s, rt, t, backend, run_dir, opts)
    cov = report.get("coverage", {})
    print(json.dumps(dict(run_dir=str(run_dir), coverage=f"{cov.get('covered')}/{cov.get('total')}",
                          ratio=cov.get("ratio"), tests=report.get("tests"), bombs=len(report.get("bombs_reached", [])),
                          llm_usage=report.get("llm_usage")), indent=2))


def cmd_explore(args):
    from .docker import Runtime
    from .targets import find_target
    from .budget import Budget
    from .stages.common import Context
    from .stages import explore
    s = _settings(args)
    rt = Runtime(s)
    rt.std.ensure_running()
    t = find_target(s.project_root, args.target)
    if t.float:
        rt.float.ensure_running()
    run_dir = _run_dir(s, args.name, t.name + "_explore")
    configure(args.log_level)

    class _NoLLM:  # explore needs no model
        name, model = "none", "none"
        from .llm.base import Usage
        usage = Usage()
    ctx = Context(s, rt, t, _NoLLM(), run_dir, Budget(args.budget + 60), solver_timeout_s=args.solver_timeout)
    ctx.settings.explore_solver_timeout_s = args.solver_timeout or s.solver_timeout_s
    summary = explore.run(ctx, args.budget)
    c, tot = ctx.state.coverage.total() if ctx.state.coverage else (0, 0)
    print(json.dumps(dict(run_dir=str(run_dir), coverage=f"{c}/{tot}", uncovered=summary), indent=2))


def cmd_llm(args):
    s = _settings(args)
    from .llm import make_backend, list_backends
    if args.action == "list":
        print(list_backends())
        return
    configure(args.log_level)
    cache_dir = None if args.no_cache else (Path(args.cache_dir) if args.cache_dir else s.cache)
    b = make_backend(args.model, log_dir=s.runs / "_llm_test", cache_dir=cache_dir, replay_only=args.replay_only,
                     temperature=args.temperature, effort=args.effort)
    t0 = time.time()
    r = b.complete(args.prompt or "Reply with exactly: OK <your model name>")
    print(f"[{b.name}:{b.model}] {time.time() - t0:.1f}s {r.usage.as_dict()}\n{r.text}")


def cmd_remeasure(args):
    """Replay a finished run's test suite again with the current coverage code (no LLM)."""
    from .docker import Runtime
    from .targets import load_target
    from .budget import Budget
    from .stages.common import Context
    from .pipeline import _finish
    s = _settings(args)
    rt = Runtime(s)
    rt.std.ensure_running()
    configure(args.log_level)
    for rd in args.run_dirs:
        rd = Path(rd)
        if not (rd / "state.json").exists():
            print(f"{rd}: no state.json, skipped"); continue
        state = json.loads((rd / "state.json").read_text())
        old = json.loads((rd / "report.json").read_text()) if (rd / "report.json").exists() else {}
        t = load_target(rd / "target.yaml")

        class _NoLLM:
            name, model = old.get("backend", "none:none").split(":", 1) if ":" in old.get("backend", "") else ("none", "none")
            from .llm.base import Usage
            usage = Usage()
        ctx = Context(s, rt, t, _NoLLM(), rd, Budget(10**6))
        ctx.run_dir = rd / "remeasure"
        ctx.run_dir.mkdir(exist_ok=True)
        for g in state.get("suite", []):
            kts = [Path(k) for k in g["ktests"] if Path(k).exists()]
            h = Path(g["harness"]) if g.get("harness") else None
            if kts:
                ctx.evaluate(h, kts, f"re_{len(ctx.state.history):02d}")
        rep = _finish(ctx, {"remeasured_from": str(rd), "original_coverage": old.get("coverage"), "stages": old.get("stages", {}),
                            "triage": old.get("triage")})
        rep["backend"] = old.get("backend"); rep["budget_s"] = old.get("budget_s"); rep["elapsed_s"] = old.get("elapsed_s")
        rep["llm_usage"] = old.get("llm_usage"); rep["history"] = old.get("history", []) + rep["history"]
        (rd / "report.json").write_text(json.dumps(rep, indent=2, default=str))
        c = rep["coverage"]; oc = old.get("coverage", {})
        print(f"{rd.name}: {oc.get('covered')}/{oc.get('total')} -> {c['covered']}/{c['total']}")


def _bomb_status(run_dir: Path) -> str:
    """For LogicBombs targets: 'bomb+benign', 'bomb', 'benign' or '-' from the covered lines."""
    st = run_dir / "state.json"
    if not st.exists():
        return ""
    cov = (json.loads(st.read_text()).get("coverage") or {}).get("files") or {}
    for path, f in cov.items():
        src = Path(path) if Path(path).is_absolute() else run_dir.parents[1] / path
        if not src.exists() or "logic_bombs" not in str(src):
            continue
        bomb_lines, benign_lines = bomb_and_benign_lines(src.read_text(errors="replace").splitlines())
        covered = set(f["covered"])
        bomb, benign = bool(bomb_lines & covered), bool(benign_lines & covered)
        return "+".join(x for x, ok in (("bomb", bomb), ("benign", benign)) if ok) or "-"
    return ""


def bomb_and_benign_lines(lines: list[str]) -> tuple[set[int], set[int]]:
    """Line numbers of the bomb / benign endings of a LogicBombs source: ``return BOMB_ENDING`` or
    ``klee_assert(0)`` vs ``return NORMAL_ENDING``.  A few bombs (file_posix_cp_l1) use plain
    ``return 1`` / ``return 0`` instead; those are used only when the file has no named endings."""
    import re
    bomb = {i for i, l in enumerate(lines, 1) if ("BOMB_ENDING" in l and "return" in l and "#define" not in l) or "klee_assert(0" in l}
    benign = {i for i, l in enumerate(lines, 1) if "NORMAL_ENDING" in l and "return" in l and "#define" not in l}
    if not bomb and not benign:
        bomb = {i for i, l in enumerate(lines, 1) if re.match(r"\s*return\s+1\s*;", l)}
        benign = {i for i, l in enumerate(lines, 1) if re.match(r"\s*return\s+0\s*;", l)}
    return bomb, benign


def cmd_report(args):
    runs = Path(args.runs_dir)
    if not runs.is_dir():
        print(f"no runs directory {runs} (runs are created by `gordian run` / `gordian explore`)", file=sys.stderr)
        return 1
    rows = []
    for rd in sorted(runs.iterdir()):
        rp = rd / "report.json"
        if not rp.exists():
            continue
        r = json.loads(rp.read_text())
        cov = r.get("coverage", {})
        rows.append((r.get("target"), r.get("backend"), cov.get("covered"), cov.get("total"), cov.get("ratio"), r.get("tests"),
                     _bomb_status(rd), r.get("elapsed_s"), (r.get("llm_usage") or {}).get("input_tokens"),
                     (r.get("llm_usage") or {}).get("output_tokens"), rd.name))
    print("target\tbackend\tcovered\ttotal\tratio\ttests\tcritical_paths\tseconds\tin_tokens\tout_tokens\trun")
    for row in rows:
        print("\t".join(str(x) for x in row))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gordian", description="Gordian: LLM-generated ghost code for KLEE")
    ap.add_argument("--root", help="project root (default: directory containing gordian.yaml)")
    ap.add_argument("--log-level", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="write gordian.yaml in the project root"); p.set_defaults(fn=cmd_init)
    p.add_argument("--klee-image"); p.add_argument("--float-image")

    p = sub.add_parser("docker", help="manage the KLEE containers"); p.set_defaults(fn=cmd_docker)
    p.add_argument("action", choices=["up", "status", "down"]); p.add_argument("--recreate", action="store_true")
    p.add_argument("--which", choices=["std", "float"])

    p = sub.add_parser("bench", help="benchmark target specs"); p.set_defaults(fn=cmd_bench)
    p.add_argument("action", choices=["init", "list"]); p.add_argument("--family", action="append")

    def model_args(p):
        p.add_argument("--model", "-m", default="anthropic:claude-sonnet-5-5", help="backend spec, see `gordian llm list`")
        p.add_argument("--temperature", type=float, default=0.5)
        p.add_argument("--effort", default=None, help="reasoning effort for models that support it")
        p.add_argument("--cache-dir", default=None); p.add_argument("--no-cache", action="store_true")
        p.add_argument("--replay-only", action="store_true", help="never call the model; fail on cache miss")
        p.add_argument("--providers", default=None, help="JSON file with extra OpenAI-compatible providers")
        p.add_argument("--max-budget-usd", type=float, default=None, help="Claude Code spend cap per task")

    p = sub.add_parser("run", help="run the full pipeline on a target"); p.set_defaults(fn=cmd_run)
    p.add_argument("target", help="target name (benchmarks/targets/<name>.yaml), a target YAML, or a .c file")
    p.add_argument("--budget", type=int, default=3600, help="total wall-clock budget in seconds")
    p.add_argument("--stages", default=None, help="comma list among partition,rewrite,inversion (default: all three, in that "
                                                  "order), or `auto`: the LLM's triage of the uncovered regions chooses the "
                                                  "order (techniques it routed nothing to run last)")
    p.add_argument("--context", choices=["file", "slice"], default="file",
                   help="what the prompts show as the program: the whole annotated file (default) or a slice "
                        "(file preamble, enclosing functions, their direct callees, main)")
    p.add_argument("--variants", type=int, default=3, help="harness variants for partitioning")
    p.add_argument("--candidates", type=int, default=3, help="inversion candidates")
    p.add_argument("--solver-timeout", type=int, default=None)
    p.add_argument("--explore-max", type=int, default=300)
    p.add_argument("--float", dest="float", action="store_true", default=None, help="force KLEE-Float")
    p.add_argument("--no-float", dest="float", action="store_false")
    p.add_argument("--name", default=None, help="run directory name under runs/")
    p.add_argument("--keep-tests", action="store_true", help="keep KLEE outputs / replay builds / test suite after the run")
    replay_args(p)
    model_args(p)

    p = sub.add_parser("explore", help="baseline KLEE run + coverage, no LLM"); p.set_defaults(fn=cmd_explore)
    p.add_argument("target"); p.add_argument("--budget", type=int, default=120)
    p.add_argument("--solver-timeout", type=int, default=None); p.add_argument("--name", default=None)
    replay_args(p)

    p = sub.add_parser("llm", help="LLM backends"); p.set_defaults(fn=cmd_llm)
    p.add_argument("action", choices=["list", "test"]); p.add_argument("--prompt", default=None)
    model_args(p)

    p = sub.add_parser("remeasure", help="re-replay finished runs' test suites with the current coverage code"); p.set_defaults(fn=cmd_remeasure)
    p.add_argument("run_dirs", nargs="+")
    replay_args(p)

    p = sub.add_parser("report", help="summarise runs/*/report.json"); p.set_defaults(fn=cmd_report)
    p.add_argument("runs_dir", nargs="?", default="runs")

    args = ap.parse_args(argv)
    configure(args.log_level)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
