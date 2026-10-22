"""Stage 1: semantic partitioning (ghost harnesses with semantic topologies)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .common import Context, prompt_source, slice_note, copy_into, write_klee_notes, strip_markers, fix_compile_errors
from .. import prompts
from ..llm import TaskSpec
from ..log import get_logger

log = get_logger(__name__)


def _unique_main(code: str) -> bool:
    return len(re.findall(r"^\s*int\s+main\s*\(", code, re.M)) == 1


def generate_harnesses(ctx: Context, k: int, stage_dir: Path, *, previous: Optional[list[Path]] = None,
                       round_no: int = 0) -> list[Path]:
    """Ask the backend for k harness variants; returns the files that exist and look sane."""
    t = ctx.target
    unc = ctx.uncovered()
    work = stage_dir / ("task" if round_no == 0 else f"task_round{round_no}")
    work.mkdir(parents=True, exist_ok=True)
    inputs = []
    listings = ""
    # annotated coverage files
    for cf in ctx.coverage_files():
        unc_set = {ln for ln, _ in unc.get(str(cf.relative_to(ctx.root)), [])}
        listing = prompt_source(ctx, cf, unc_set)
        listings += listing
        (work / f"{cf.stem}.annotated.c").write_text(listing)
        inputs.append(f"{cf.stem}.annotated.c")
    prefix = "harness_part"
    if ctx.has_harness():
        copy_into(t.harness_path(ctx.root), work, "original_harness.c")
        inputs.append("original_harness.c")
        cflags = " ".join(["-I" + str(ctx.root / d) for d in t.include_dirs] + ["-D" + d for d in t.defines])
        instructions = prompts.PARTITION_TASK.format(entry=t.entry_function, notes=t.notes or "(none)", k=k,
                                                     prefix=prefix, cflags=cflags, klee_rules=prompts.KLEE_RULES)
    else:
        prog = ctx.coverage_files()[0]
        instructions = prompts.PARTITION_SINGLE_FILE_TASK.format(program=f"{prog.stem}.annotated.c", k=k, prefix=prefix,
                                                                klee_rules=prompts.KLEE_RULES)
    instructions += slice_note(ctx, listings)
    # headers the harness may need
    for d in t.include_dirs:
        for hdr in sorted((ctx.root / d).glob("*.h"))[:40]:
            if hdr.name == "klee_extra.h" or len(inputs) > 60:
                continue
            copy_into(hdr, work / "include")
    (work / "include").mkdir(exist_ok=True)
    copy_into(ctx.root / "benchmarks" / "klee_extra.h", work / "include") if (ctx.root / "benchmarks" / "klee_extra.h").exists() else None
    inputs += write_klee_notes(ctx, work)
    outputs = [f"{prefix}{i}.c" for i in range(1, k + 1)]
    if previous:
        names = []
        for i, h in enumerate(previous, 1):
            copy_into(h, work, f"previous_harness{i}.c"); names.append(f"previous_harness{i}.c")
        inputs += names
        still = {cf.stem: sorted(ln for ln, _ in unc.get(str(cf.relative_to(ctx.root)), [])) for cf in ctx.coverage_files()}
        instructions += ("\n## Feedback from the previous attempt\n"
                         f"Your previous harness variants ({', '.join(names)}) were run and their tests replayed; these lines are "
                         f"STILL uncovered: {still}.  `klee_notes.txt` has KLEE's diagnostics from those runs.  Do not repeat the "
                         "same topologies: look at the remaining lines, work out which input structures / sizes / error paths reach "
                         "them, and write new variants aimed specifically at them (deeper nesting, boundary sizes, invalid inputs, "
                         "rarely used features, the other branches of the dispatch).\n")
    spec = TaskSpec(name="partition" if round_no == 0 else f"partition_round{round_no}", instructions=instructions, workdir=work, inputs=inputs, outputs=outputs,
                    timeout_s=int(min(1800, max(60, min(ctx.budget.remaining - 60, max(300, ctx.budget.remaining * 0.5))))))
    res = ctx.backend.run_task(spec)
    good = []
    for o in outputs:
        p = work / o
        if not p.exists():
            continue
        code = strip_markers(p.read_text(errors="replace"))
        p.write_text(code)
        if "klee_" not in code or not _unique_main(code):
            log.warning("partition: %s rejected (no klee calls or not exactly one main)", o)
            continue
        good.append(copy_into(p, stage_dir, o if round_no == 0 else o.replace(".c", f"_r{round_no}.c")))
    if res.error:
        log.warning("partition task error: %s", res.error)
    return good


def run(ctx: Context, budget_s: float, k: int = 3, rounds: int = 2) -> dict:
    stage_dir = ctx.run_dir / "01_partition"
    stage_dir.mkdir(parents=True, exist_ok=True)
    result = dict(harnesses=[], runs=[])
    previous: list[Path] = []
    t_stage = ctx.budget.elapsed
    for rnd in range(rounds):
        if ctx.budget.exhausted(60) or not any(ctx.uncovered().values()):
            break
        if rnd > 0 and (budget_s - (ctx.budget.elapsed - t_stage)) < 300:
            break   # the stage share is spent: do not take the later stages' time for a feedback round
        harnesses = generate_harnesses(ctx, k, stage_dir, previous=previous or None, round_no=rnd)
        result["harnesses"] += [str(h) for h in harnesses]
        if not harnesses:
            break
        # KLEE time per variant comes out of the stage share; LLM time is overhead that may overrun it
        # (an agent task on a large file takes 5-10 min, which at small budgets would otherwise leave
        # KLEE a few seconds).  Floor: 5 % of the total budget, 45-180 s.
        floor = min(180.0, max(45.0, ctx.budget.total * 0.05))
        per = max(floor, budget_s * 0.6 / (len(harnesses) * rounds))
        for i, h in enumerate(harnesses, 1):
            if ctx.budget.exhausted(30):
                break
            label = f"01_partition_{i}" + ("" if rnd == 0 else f"_r{rnd}")
            ktests, rep = ctx.run_variant(label, budget_s=max(floor, min(per, ctx.budget.remaining - 20)), harness=h)
            if rep is None and not ktests and getattr(ctx, "last_build_log", "") and not ctx.budget.exhausted(90):
                fixed = fix_compile_errors(ctx, h, ctx.last_build_log, label)
                if fixed is not None:
                    h = fixed
                    ktests, rep = ctx.run_variant(label + "_fixed", budget_s=max(floor, min(per, ctx.budget.remaining - 20)), harness=h)
            result["runs"].append(dict(harness=h.name, round=rnd, ktests=len(ktests), ok=rep is not None))
        previous = harnesses
        if (budget_s - (ctx.budget.elapsed - t_stage)) < len(harnesses) * floor + 120:
            break   # no time left in this stage's share for another LLM round plus KLEE runs
    (stage_dir / "result.json").write_text(json.dumps(result, indent=2))
    return result
