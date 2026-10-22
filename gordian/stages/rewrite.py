"""Stage 2: triage of the remaining uncovered regions + surrogate models."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .common import (Context, annotate_source, copy_into, fix_compile_errors, group_uncovered, prompt_source, rank_regions,
                     restore_omitted, slice_note, strip_markers, write_klee_notes)
from .. import prompts
from ..llm import TaskSpec
from ..log import get_logger

log = get_logger(__name__)


def triage(ctx: Context, stage_dir: Path, max_regions: int = 40) -> list[dict]:
    """LLM classification of uncovered regions into partition/model/inversion/none with scores."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    unc = ctx.uncovered()
    items = []
    listing = []
    for cf in ctx.coverage_files():
        rel = str(cf.relative_to(ctx.root))
        lines = unc.get(rel, [])
        if not lines:
            continue
        unc_set = {ln for ln, _ in lines}
        regions = rank_regions(group_uncovered(lines), unc_set)[:max_regions]
        listing.append(f"### {rel}\n" + annotate_source(cf, unc_set, focus=unc_set, context=25))
        for a, b in regions:
            items.append(dict(file=rel, start=a, end=b, size=sum(1 for ln in range(a, b + 1) if ln in unc_set)))
    if not items:
        return []
    notes = "\n".join(w for ws in ctx.state.klee_notes.values() for w in ws[:40])
    prompt = (prompts.TRIAGE_TASK + ("\n\n## KLEE diagnostics (a 'silently concretizing (reason: floating point)' line means standard KLEE "
              "replaced the symbolic input by one concrete value at that point; everything after it needs integer bit-pattern "
              "reasoning, i.e. a model, or inversion)\n" + notes if notes else "")
              + "\n\n## Uncovered regions (file, start-end, #uncovered lines)\n"
              + "\n".join(f"- {it['file']} {it['start']}-{it['end']} ({it['size']})" for it in items)
              + "\n\n## Annotated sources\n" + "\n\n".join(listing))
    resp = ctx.backend.complete(prompt, tag="triage")
    m = re.search(r"\[.*\]", resp.text, re.S)
    out = []
    if m:
        try:
            out = json.loads(m.group(0))
        except json.JSONDecodeError:
            log.warning("triage: could not parse JSON")
    # attach file names by nearest region
    for o in out:
        if "file" not in o:
            best = min(items, key=lambda it: abs(it["start"] - int(o.get("start", 0))), default=None)
            o["file"] = best["file"] if best else items[0]["file"]
    (stage_dir / "triage.json").write_text(json.dumps(out, indent=2))
    return out


def generate_model(ctx: Context, stage_dir: Path, regions: list[dict], program: Path, *,
                   previous: Optional[Path] = None, round_no: int = 0) -> Optional[Path]:
    unc = ctx.uncovered()
    rel = str(program.relative_to(ctx.root))
    unc_set = {ln for ln, _ in unc.get(rel, [])}
    work = stage_dir / ("task" if round_no == 0 else f"task_round{round_no}")
    work.mkdir(parents=True, exist_ok=True)
    annotated = work / f"{program.stem}.annotated.c"
    focus = set()
    for r in regions:   # the regions to unlock and their difficult fragments
        focus.update(range(int(r.get("start", 0)), int(r.get("end", 0)) + 1))
        frag = r.get("fragment") or {}
        focus.update(range(int(frag.get("start", 0)), int(frag.get("end", 0)) + 1))
    listing = prompt_source(ctx, program, unc_set, focus & unc_set or focus)
    annotated.write_text(listing)
    for hdr in sorted(program.parent.glob("*.h")):
        copy_into(hdr, work)
    inputs = [annotated.name]
    if ctx.has_harness():
        copy_into(ctx.target.harness_path(ctx.root), work, "harness.c")
        inputs.append("harness.c")
    inputs += write_klee_notes(ctx, work)
    output = f"{program.stem}.model.c"
    extra = ""
    txt = program.read_text(errors="replace")
    if "__HI(" in txt or "__LO(" in txt or "fdlibm" in txt:
        extra = prompts.FDLIBM_HILO_EXTRA
    focus = "\n".join(f"- lines {r['start']}-{r['end']}: {r.get('reason','')} (difficult fragment: {r.get('fragment')})"
                      for r in regions)
    instructions = prompts.REWRITE_TASK.format(program=annotated.name, output=output, extra=extra,
                                               klee_rules=prompts.KLEE_RULES, notes_file="model_notes.md")
    instructions += "\nRegions to unlock (from triage):\n" + focus + "\n" + slice_note(ctx, listing)
    if ctx.backend.is_agent:
        # Large files cannot be re-emitted reliably by an agent: pre-populate the output with the original
        # (or the previous model) and ask for in-place edits.
        seed = previous if (previous is not None and previous.exists()) else program
        (work / output).write_text(strip_markers(seed.read_text(errors="replace")))
        instructions += (f"\nThe output file `{output}` ALREADY EXISTS in the working directory and is an exact copy of "
                         f"{'your previous surrogate' if seed is not program else 'the original program'} (without the "
                         "annotations).  Edit it IN PLACE with small, localized edits (Edit tool / sed): never rewrite or "
                         "re-emit the whole file, never truncate it.  Verify it still compiles with "
                         "`clang -fsyntax-only` (include paths: the working directory and its `include/` subfolder).\n")
    if previous is not None and previous.exists():
        copy_into(previous, work, "previous_model.c")
        inputs.append("previous_model.c")
        still = sorted(unc_set)
        instructions += ("\n## Feedback from the previous attempt\n"
                         "`previous_model.c` is your previous surrogate.  KLEE ran it and its test cases were replayed on the "
                         f"original program; these lines of the original are STILL uncovered: {still}.  "
                         "`klee_notes.txt` contains KLEE's diagnostics from running previous_model.c (look for concretization "
                         "warnings inside the surrogate itself, external calls, errors, and paths that terminated early).  "
                         "Start from previous_model.c, keep what worked, and fix what blocked the remaining lines: typically a "
                         "guard that still involves a symbolic floating-point value, an external call left in place, a loop "
                         "bound that is too large, or a case split that does not include the value range the remaining lines need.  "
                         "Write the improved file as the required output (same name).\n")
    spec = TaskSpec(name="model" if round_no == 0 else f"model_round{round_no}", instructions=instructions, workdir=work, inputs=inputs,
                    outputs=[output, "model_notes.md"], timeout_s=int(min(1800, max(60, min(ctx.budget.remaining - 60, max(300, ctx.budget.remaining * 0.5))))))
    res = ctx.backend.run_task(spec)
    p = work / output
    if not p.exists():
        log.warning("model task produced no file: %s", res.error)
        return None
    code = strip_markers(restore_omitted(p.read_text(errors="replace"), txt.splitlines()))
    p.write_text(code)
    # the surrogate must keep the symbolic interface: same klee_make_symbolic names
    names_orig = re.findall(r'klee_make_symbolic\s*\([^;]*?"([^"]+)"', txt)
    names_new = re.findall(r'klee_make_symbolic\s*\([^;]*?"([^"]+)"', code)
    if names_orig and sorted(names_orig) != sorted(names_new) and not ctx.has_harness():
        log.warning("model changed the symbolic interface %s -> %s; tests may not replay", names_orig, names_new)
    if (work / "model_notes.md").exists():
        copy_into(work / "model_notes.md", stage_dir, f"{program.stem}.model_notes{'' if round_no == 0 else round_no}.md")
    return copy_into(p, stage_dir, output if round_no == 0 else f"{program.stem}.model{round_no}.c")


def run(ctx: Context, budget_s: float, *, triage_result: Optional[list[dict]] = None, rounds: int = 2) -> dict:
    stage_dir = ctx.run_dir / "02_rewrite"
    stage_dir.mkdir(parents=True, exist_ok=True)
    regions = triage_result if triage_result is not None else triage(ctx, stage_dir)
    model_regions = [r for r in regions if r.get("technique") in ("model", "inversion") and float(r.get("score", 0)) >= 0.2]
    result = dict(triage=regions, models=[])
    if not model_regions and regions and any(ctx.uncovered().values()):
        # Triage is only a hint: an LLM that calls everything "none"/"partition" would end the run with
        # uncovered lines left, so still try a surrogate model on the top-ranked regions.
        model_regions = [dict(r, technique="model", score=max(float(r.get("score", 0)), 0.2), reason=f"fallback ({r.get('technique')}): " + str(r.get("reason", "")))
                         for r in regions[:5]]
        log.info("rewrite: triage proposed no model/inversion regions; falling back to the top %d regions", len(model_regions))
    if not model_regions:
        log.info("rewrite: no regions classified as model/inversion; skipping")
        (stage_dir / "result.json").write_text(json.dumps(result, indent=2))
        return result
    # one model per coverage file that has regions (usually one)
    by_file: dict[str, list[dict]] = {}
    for r in model_regions:
        by_file.setdefault(r["file"], []).append(r)
    files = [ctx.root / f for f in by_file]
    t_stage = ctx.budget.elapsed
    for program in files:
        rel = str(program.relative_to(ctx.root))
        previous = None
        for rnd in range(rounds):
            if ctx.budget.exhausted(60) or not ctx.uncovered().get(rel):
                break
            if rnd > 0 and (budget_s - (ctx.budget.elapsed - t_stage)) < 300:
                break   # stage share spent: leave the rest to the inversion stage
            model = generate_model(ctx, stage_dir, by_file[rel], program, previous=previous, round_no=rnd)
            if model is None:
                break
            # leave the later rounds their share: KLEE gets at most this round's slice of what is left
            floor = min(180.0, max(45.0, ctx.budget.total * 0.05))   # see partition.py: LLM time is overhead
            klee_budget = max(floor, budget_s * 0.6 / max(1, len(files) * rounds))
            srcs = [model if s_.resolve() == program.resolve() else s_ for s_ in ctx.target.resolve_sources(ctx.root)]
            # the model keeps the original directory's headers in scope
            label = f"02_model_{program.stem}" + ("" if rnd == 0 else f"_r{rnd}")
            ktests, rep = ctx.run_variant(label, budget_s=max(floor, min(klee_budget, ctx.budget.remaining - 20)),
                                          sources=srcs, extra_cflags=["-I" + ctx.klee_container.path(program.parent)])
            if rep is None and not ktests and getattr(ctx, "last_build_log", "") and not ctx.budget.exhausted(90):
                fixed = fix_compile_errors(ctx, model, ctx.last_build_log, label)
                if fixed is not None:
                    model = fixed
                    srcs = [model if s_.resolve() == program.resolve() else s_ for s_ in ctx.target.resolve_sources(ctx.root)]
                    ktests, rep = ctx.run_variant(label + "_fixed", budget_s=min(klee_budget, ctx.budget.remaining - 20),
                                                  sources=srcs, extra_cflags=["-I" + ctx.klee_container.path(program.parent)])
            result["models"].append(dict(file=rel, round=rnd, model=str(model), ktests=len(ktests), ok=rep is not None,
                                         still_uncovered=len(ctx.uncovered().get(rel, []))))
            previous = model
            if (budget_s - (ctx.budget.elapsed - t_stage)) < floor + 150:
                break   # no time left in this stage's share for another LLM round plus a KLEE run
    (stage_dir / "result.json").write_text(json.dumps(result, indent=2))
    return result
