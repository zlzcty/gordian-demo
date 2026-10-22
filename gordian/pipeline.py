"""The Gordian pipeline.

    explore  (short, reduced solver timeout)      -> uncovered lines, ranked regions
    partition (1/3 of the remaining budget)       -> ghost harnesses with semantic topologies
    rewrite   (1/3 of the remaining budget)       -> triage + surrogate models of difficult fragments
    inversion (rest)                              -> ghost inversion for the still-uncovered, invertible regions

The stage list is the user's (``--stages``, default partition,rewrite,inversion).  With
``--stages auto`` the LLM chooses: the triage prompt classifies every uncovered region
as partition / model / inversion / none with a score, and the stages run in the order of
their summed scores; techniques no region was routed to run last with the leftover budget.

Every stage runs KLEE with a wall-clock slice and a soft kill, replays the
resulting test cases on the ORIGINAL program and adds them to the test suite.
The final report is ``<run_dir>/report.json`` (+ ``report.md``).
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .budget import Budget
from .config import Settings
from .docker import Runtime
from .llm import Backend
from .stages import explore, partition, rewrite, inversion
from .stages.common import Context
from .targets import Target
from .log import get_logger

log = get_logger(__name__)


@dataclass
class PipelineOptions:
    budget_s: int = 3600
    explore_fraction: float = 0.1       # of total, capped by explore_max_s
    explore_max_s: int = 300
    stages: list[str] = field(default_factory=lambda: ["partition", "rewrite", "inversion"])   # or ["auto"]
    context: str = "file"         # {CODE} in the prompts: "file" (whole annotated file) or "slice"
    partition_variants: int = 3
    inversion_candidates: int = 3
    solver_timeout_s: Optional[int] = None
    keep_tests: bool = False      # keep KLEE outputs, replay builds and the test suite after the run


def run_pipeline(settings: Settings, runtime: Runtime, target: Target, backend: Backend, run_dir: Path,
                 opts: PipelineOptions) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(opts.budget_s)
    ctx = Context(settings, runtime, target, backend, run_dir, budget, solver_timeout_s=opts.solver_timeout_s)
    ctx.keep_tests = opts.keep_tests
    ctx.context_mode = opts.context
    (run_dir / "target.yaml").write_text(Path(target.spec_path).read_text() if target.spec_path else json.dumps(target.as_dict()))
    (run_dir / "options.json").write_text(json.dumps(opts.__dict__, indent=2))
    log.info("=== %s: budget %ds, backend %s:%s, stages %s", target.name, opts.budget_s, backend.name, backend.model, opts.stages)

    # 0. explore
    explore_s = min(opts.explore_max_s, max(20, opts.budget_s * opts.explore_fraction))
    explore.run(ctx, explore_s)
    report = {"stages": {}}
    if ctx.state.coverage is None:
        from .coverage import static_all_uncovered
        log.warning("exploratory run produced no coverage (KLEE cannot execute the original program); "
                    "treating every line as uncovered so the ghost-code stages can still rewrite it")
        ctx.state.coverage = static_all_uncovered(target, settings.project_root)
        report["explore_failed"] = True

    def nothing_left() -> bool:
        return not any(ctx.uncovered().values())

    triage_result = None
    triage_fresh = False      # triage_result still describes the current coverage (no stage ran since)
    stage_ran_since_triage = False
    if opts.stages == ["auto"]:
        try:
            triage_result = rewrite.triage(ctx, run_dir / "00_triage") if not nothing_left() else []
        except Exception as exc:  # noqa: BLE001 - an LLM failure here must not lose the run: fall back to the default order
            log.exception("auto triage failed, using the default stage order: %s", exc)
            triage_result, report["auto_triage_error"] = None, f"{type(exc).__name__}: {exc}"
        remaining_stages = auto_stage_order(triage_result or [])
        triage_fresh = True
        report["triage"] = triage_result
        report["stage_order"] = remaining_stages
        log.info("auto stage order from triage: %s", remaining_stages)
    else:
        remaining_stages = [s for s in opts.stages if s in ("partition", "rewrite", "inversion")]
    for i, stage in enumerate(remaining_stages):
        if budget.exhausted(30):
            log.info("budget exhausted before stage %s", stage)
            break
        if nothing_left():
            log.info("100%% coverage reached; skipping %s", stage)
            break
        # equal share of the remaining budget, but never eat the minimum later stages need (LLM time
        # is not bounded by the KLEE budgets, so without a reserve the last stage gets the scraps)
        later = len(remaining_stages) - i - 1
        reserve = min(budget.remaining * 0.5, 420.0 * later)
        share = max(60.0, (budget.remaining - reserve) / (later + 1))
        t0 = time.time()
        log.info("--- stage %s: %.0fs", stage, share)
        try:
            if stage == "partition":
                report["stages"]["partition"] = partition.run(ctx, share, k=opts.partition_variants)
            elif stage == "rewrite":
                res = rewrite.run(ctx, share, triage_result=triage_result if triage_fresh else None)
                triage_result = res.get("triage")
                report["stages"]["rewrite"] = {k: v for k, v in res.items() if k != "triage"}
                report["triage"] = triage_result
            elif stage == "inversion":
                if triage_result is None or (not triage_fresh and stage_ran_since_triage):
                    triage_result = rewrite.triage(ctx, run_dir / "03_inversion")
                    report["triage"] = triage_result
                report["stages"]["inversion"] = inversion.run(ctx, share, triage_result, max_candidates=opts.inversion_candidates)
        except Exception as exc:  # noqa: BLE001 - a stage failure must not lose the earlier results
            log.exception("stage %s failed: %s", stage, exc)
            report["stages"][stage] = {"error": f"{type(exc).__name__}: {exc}"}
        report["stages"].setdefault(stage, {})["seconds"] = round(time.time() - t0)
        triage_fresh = stage == "rewrite"     # rewrite re-triages (or used a fresh one) before modelling
        stage_ran_since_triage = stage != "rewrite"
    return _finish(ctx, report)


def auto_stage_order(triage: list[dict]) -> list[str]:
    """Stage order chosen by the LLM's triage: each region votes for its technique with its score and
    the voted stages run first, by total score; techniques no region was routed to run last, with the
    leftover budget (the pipeline stops anyway once every line is covered).  An empty or unparsable
    triage gives the default order."""
    default = ["partition", "rewrite", "inversion"]
    votes = {s: 0.0 for s in default}
    for r in triage:
        tech = {"model": "rewrite"}.get(r.get("technique"), r.get("technique"))
        if tech in votes:
            votes[tech] += float(r.get("score") or 0)
    voted = [s for s, v in sorted(votes.items(), key=lambda kv: -kv[1]) if v > 0]
    return voted + [s for s in default if s not in voted]


def _finish(ctx: Context, report: dict) -> dict:
    ctx.save_state()
    cov = ctx.state.coverage
    c, t = cov.total() if cov else (0, 0)
    # collect the final test suite
    suite_dir = ctx.run_dir / "test_suite"
    if suite_dir.exists():
        shutil.rmtree(suite_dir)
    manifest = []
    for gi, (harness, ktests) in enumerate(ctx.state.suite.groups):
        gdir = suite_dir / f"group_{gi:02d}"
        gdir.mkdir(parents=True, exist_ok=True)
        if harness is not None:
            shutil.copy2(harness, gdir / "harness.c")
        # the ktests stay in their KLEE output directories (state.json lists them); only a bounded
        # sample is copied here so a run does not duplicate hundreds of thousands of files
        for k in ktests[:500]:
            shutil.copy2(k, gdir / k.name)
        manifest.append(dict(group=gi, harness=str(harness) if harness else None, ktests=len(ktests),
                             copied=min(500, len(ktests)), source_dirs=sorted({str(k.parent) for k in ktests})))
    cleanup_intermediates(ctx.run_dir, keep_tests=getattr(ctx, "keep_tests", False))
    report.update(dict(
        target=ctx.target.name, family=ctx.target.family, backend=f"{ctx.backend.name}:{ctx.backend.model}",
        budget_s=ctx.budget.total, elapsed_s=round(ctx.budget.elapsed),
        coverage=dict(covered=c, total=t, ratio=round(c / t, 4) if t else 0.0,
                      files={k: dict(covered=len(f.covered), total=f.total, ratio=round(f.ratio, 4)) for k, f in (cov.files.items() if cov else [])}),
        bombs_reached=sorted(ctx.state.bombs), tests=ctx.state.suite.count, suite=manifest,
        history=ctx.state.history, llm_usage=ctx.backend.usage.as_dict(),
        uncovered={k: [ln for ln, _ in v] for k, v in ctx.uncovered().items()}))
    (ctx.run_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (ctx.run_dir / "report.md").write_text(_markdown(report))
    log.info("=== done: %d/%d lines (%.1f%%), %d tests, %s", c, t, 100.0 * c / t if t else 0, ctx.state.suite.count,
             ctx.backend.usage.as_dict())
    return report


def cleanup_intermediates(run_dir: Path, keep_tests: bool = False) -> int:
    """Delete regenerable KLEE/replay intermediates (profiles, normalised ktests, .cov/.kquery/.smt2,
    assembly.ll, istats).  With ``keep_tests=False`` (default) the KLEE output directories, replay builds
    and the test-suite copy are removed too: a finished run then keeps only reports, state.json, logs and
    every LLM artifact (prompts, responses, ghost code), which is a few MB instead of GBs.  Use
    ``--keep-tests`` to retain the ktests (needed for `gordian remeasure`)."""
    n = 0
    if not keep_tests:
        for sub in ("variants", "coverage", "replay_builds", "test_suite", "remeasure"):
            d = run_dir / sub
            if d.exists():
                n += sum(1 for _ in d.rglob("*"))
                shutil.rmtree(d, ignore_errors=True)
        for cand in run_dir.glob("03_inversion/cand_*"):
            for d in [cand / "direct_ktests", cand / "opt_rounds"] + list(cand.glob("neigh_*")) + list(cand.glob("relax_*")):
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
        return n
    for pat in ("coverage/*/profraw", "coverage/*/ktests_norm", "remeasure/coverage/*/profraw", "remeasure/coverage/*/ktests_norm"):
        for d in run_dir.glob(pat):
            n += sum(1 for _ in d.rglob("*"))
            shutil.rmtree(d, ignore_errors=True)
    for pat in ("variants/*/klee/*.cov", "variants/*/klee/*.kquery", "variants/*/klee/*.smt2", "variants/*/klee/assembly.ll",
                "variants/*/klee/run.istats", "variants/*/klee/*.pc", "variants/*/klee/*.sym.path", "variants/*/klee/*.path"):
        for f in run_dir.glob(pat):
            try:
                f.unlink(); n += 1
            except OSError:
                pass
    return n


def _markdown(r: dict) -> str:
    cov = r.get("coverage", {})
    lines = [f"# Gordian run: {r.get('target')}", "",
             f"- backend: `{r.get('backend')}`  budget: {r.get('budget_s')}s  elapsed: {r.get('elapsed_s')}s",
             f"- line coverage: **{cov.get('covered')}/{cov.get('total')} = {100 * cov.get('ratio', 0):.1f}%**",
             f"- test cases: {r.get('tests')}  bombs reached: {len(r.get('bombs_reached', []))}",
             f"- LLM usage: {r.get('llm_usage')}", "", "## Coverage progression", "",
             "| step | ktests | new lines | covered | t (s) |", "|---|---|---|---|---|"]
    for h in r.get("history", []):
        if "error" in h:
            lines.append(f"| {h['label']} | - | {h['error']} | - | {h.get('t')} |")
        else:
            lines.append(f"| {h['label']} | {h['ktests']} | +{h['new_lines']} | {h['covered']}/{h['total']} | {h['t']} |")
    if r.get("triage"):
        lines += ["", "## Triage of uncovered regions", "", "| file | lines | technique | score | reason |", "|---|---|---|---|---|"]
        for t in r["triage"][:30]:
            lines.append(f"| {t.get('file')} | {t.get('start')}-{t.get('end')} | {t.get('technique')} | {t.get('score')} | {t.get('reason')} |")
    return "\n".join(lines) + "\n"
