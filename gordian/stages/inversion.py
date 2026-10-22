"""Stage 3: ghost inversion with bidirectional constraint propagation.

For a target region guarded by a difficult fragment f (chosen by triage):
  1. the LLM writes a *ghost program* (fragment replaced by havoc of its written
     variables, target marked), ``inverse.py`` (f^-1) and ``forward.py`` (f);
  2. KLEE explores the ghost program; test cases reaching the mark give suffix
     assignments A_suf (values of the havoc variables);
  3. ``inverse.py`` propagates each A_suf backwards to a proposed pre-state
     sigma_pre (values for the original symbolic inputs);
  4. the proposal is replayed on the ORIGINAL program; if the target is not
     reached, bidirectional propagation reconciles it with the path condition:
     KLEE writes the prefix/suffix constraints of each ghost test case
     (``--write-smt2s``), Z3's optimizer computes the closest assignment to
     sigma_pre under pi_pre (l1 objective for a single numeric variable, soft
     equalities otherwise), and forward.py / OPT(pi_suf) alternate until a
     fixpoint (``exact_opt_rounds``, see ``opt.py``);
  5. remaining fallbacks, used when the loop cannot run (KLEE-Float writes no
     smt2) or does not converge: both are approximations of the OPT(dist, pi_pre)
     step that look for the feasible input closest to the inverse's proposal
     without a solver call -- concrete sampling around sigma_pre, then KLEE on
     the original program with the inputs constrained to a widening
     neighbourhood of sigma_pre (``klee_assume`` bounds; 5 %, 15 %, 50 %, 100 %).
Every resulting test case is validated by replay on the original program, so a
success recorded here is a test case that reaches the target in the original.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .common import Context, prompt_source, restore_omitted, slice_note, copy_into, write_klee_notes, strip_markers
from .. import prompts
from ..ktest import read_ktest, write_ktest, ktest_as_json
from ..llm import TaskSpec
from ..log import get_logger

log = get_logger(__name__)

MARK_SOURCE = '''#include <klee/klee.h>
/* klee_assert terminates the path at the target and reliably writes test<N>.assert.err in every KLEE version */
void klee_mark_target(void) { klee_assert(0 && "GORDIAN_TARGET"); }
'''
RELAX_FACTORS = [0.0, 0.05, 0.15, 0.5, 1.0]


def _candidates(triage: list[dict], max_n: int) -> list[dict]:
    cands = [r for r in triage if r.get("technique") == "inversion" and float(r.get("score", 0)) >= 0.3]
    cands.sort(key=lambda r: -float(r.get("score", 0)))
    return cands[:max_n]


def _symbolic_decls(code: str) -> dict[str, dict]:
    """name -> {var, ctype, is_array, length} from klee_make_symbolic(&v or v, sizeof(v), "name")."""
    out = {}
    for m in re.finditer(r'klee_make_symbolic\s*\(\s*&?\s*([A-Za-z_]\w*)[^;]*?"([^"]+)"', code):
        var, name = m.group(1), m.group(2)
        types = r"(unsigned\s+char|signed\s+char|char|unsigned\s+int|int|unsigned\s+long\s+long|long\s+long|unsigned\s+long|long|unsigned\s+short|short|float|double|u?int(?:8|16|32|64)_t)"
        # a declaration statement (not a parameter): `<type> var[...];` or `<type> var = ...;`
        decl = re.search(r"^\s*(?:static\s+)?" + types + r"\s+" + re.escape(var) + r"\s*(\[\s*(\w+)\s*\])?\s*(?:[;=,]|$)", code, re.M)
        if not decl:
            continue
        ctype = decl.group(1)
        is_array = decl.group(2) is not None
        out[name] = dict(var=var, ctype=ctype, is_array=is_array, length=decl.group(3))
    return out


def _value_from_bytes(ctype: str, b: bytes):
    import struct
    fmt = {"float": "<f", "double": "<d", "int": "<i", "unsigned int": "<I", "long": "<q", "unsigned long": "<Q",
           "long long": "<q", "unsigned long long": "<Q", "short": "<h", "unsigned short": "<H",
           "uint8_t": "<B", "int8_t": "<b", "uint16_t": "<H", "int16_t": "<h", "uint32_t": "<I", "int32_t": "<i",
           "uint64_t": "<Q", "int64_t": "<q", "char": "<b", "unsigned char": "<B", "signed char": "<b"}.get(ctype)
    if not fmt or struct.calcsize(fmt) != len(b):
        return None
    return struct.unpack(fmt, b)[0]


def _assume_lines(decl: dict, name: str, value_bytes: bytes, factor: float) -> list[str]:
    """klee_assume statements pinning object ``name`` to a neighbourhood of value_bytes."""
    var, ctype = decl["var"], decl["ctype"]
    if decl["is_array"] or ctype.endswith("char") and len(value_bytes) > 1:
        # pin every byte to a neighbourhood that widens with the factor (0 -> exact)
        signed = not ("unsigned" in ctype or "uint" in ctype)
        tol = int(round(factor * 127))
        out = []
        for i, byte in enumerate(value_bytes):
            v = int.from_bytes(value_bytes[i:i + 1], "little", signed=signed)
            if tol == 0:
                out.append(f"klee_assume({var}[{i}] == {v});")
            else:
                lo, hi = (max(-128, v - tol), min(127, v + tol)) if signed else (max(0, v - tol), min(255, v + tol))
                out.append(f"klee_assume({var}[{i}] >= {lo} && {var}[{i}] <= {hi});")
        return out
    v = _value_from_bytes(ctype, value_bytes)
    if v is None:
        return []
    if ctype in ("float", "double"):
        if v != v or v in (float("inf"), float("-inf")):
            return []
        tol = abs(v) * factor + (1e-6 if factor > 0 else 0.0)
        return [f"klee_assume({var} >= {v - tol!r});", f"klee_assume({var} <= {v + tol!r});"]
    tol = int(abs(v) * factor) + (1 if factor > 0 else 0)
    return [f"klee_assume({var} >= {v - tol});", f"klee_assume({var} <= {v + tol});"]


def _neighbourhood(objects: list[dict], decls: dict[str, dict], values: dict[str, bytes], factor: float,
                   max_n: int = 64) -> list[list[dict]]:
    """Concrete candidates around a proposal: for every inverted input, vary one scalar/byte at a time
    within a tolerance that grows with ``factor`` (bidirectional propagation realised by sampling
    and native replay, cheap compared with a solver call)."""
    import copy
    import struct
    out = []
    for name, vb in values.items():
        decl = decls.get(name)
        if decl is None:
            continue
        ctype = decl["ctype"]
        variants: list[bytes] = []
        if decl["is_array"] or ctype.endswith("char") and len(vb) > 1:
            signed = not ("unsigned" in ctype or "uint" in ctype)
            tol = max(1, int(round(factor * 127)))
            per_byte = max(2, max_n // max(1, min(len(vb), 4)))
            for i in range(min(len(vb), 4)):
                v = int.from_bytes(vb[i:i + 1], "little", signed=signed)
                lo, hi = (max(-128, v - tol), min(127, v + tol)) if signed else (max(0, v - tol), min(255, v + tol))
                step = max(1, (hi - lo) // per_byte)
                for cand in range(lo, hi + 1, step):
                    if cand == v:
                        continue
                    b = bytearray(vb)
                    b[i] = cand & 0xFF
                    variants.append(bytes(b))
        else:
            v = _value_from_bytes(ctype, vb)
            if v is None:
                continue
            if ctype in ("float", "double"):
                tol = abs(v) * factor + 1e-6
                fmt = "<f" if ctype == "float" else "<d"
                for k in range(1, max_n // 2 + 1):
                    d = tol * k / (max_n // 2)
                    variants.append(struct.pack(fmt, v + d))
                    variants.append(struct.pack(fmt, v - d))
            else:
                tol = max(1, int(abs(v) * factor))
                size = len(vb)
                signed = not ("unsigned" in ctype or "uint" in ctype)
                step = max(1, (2 * tol) // max_n)
                for cand in range(v - tol, v + tol + 1, step):
                    if cand == v:
                        continue
                    try:
                        variants.append(cand.to_bytes(size, "little", signed=signed))
                    except OverflowError:
                        continue
        for vb2 in variants[:max_n]:
            objs = copy.deepcopy(objects)
            for o in objs:
                if o["name"] == name:
                    o["bytes"] = vb2
            out.append(objs)
    return out[:max_n]


def _inject_assumes(code: str, decls: dict[str, dict], values: dict[str, bytes], factor: float) -> str:
    lines = code.splitlines()
    out = []
    for l in lines:
        out.append(l)
        m = re.search(r'klee_make_symbolic\s*\([^;]*?"([^"]+)"', l)
        if m and m.group(1) in values and m.group(1) in decls:
            indent = re.match(r"\s*", l).group(0)
            for a in _assume_lines(decls[m.group(1)], m.group(1), values[m.group(1)], factor):
                out.append(indent + a)
    return "\n".join(out) + "\n"


def _run_py(script: Path, arg: Path, timeout: int = 20) -> Optional[dict]:
    try:
        r = subprocess.run([sys.executable, "-I", str(script), str(arg)], capture_output=True, text=True, timeout=timeout,
                           cwd=str(script.parent))
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        log.debug("%s produced no JSON: %s %s", script.name, r.stdout[-300:], r.stderr[-300:])
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def exact_opt_rounds(work: Path, klee_dir: Path, reaching: list[Path], proposals: list[dict], decls: dict,
                     ghost_decls: dict, out_dir: Path, rounds: int = 3) -> tuple[list[Path], list[str]]:
    """Alg. 1: alternate f^-1 / OPT(pi_pre) / f / OPT(pi_suf) starting from each suffix assignment.

    Needs the .smt2 path condition KLEE wrote next to the ktest (standard KLEE only).  Returns the
    ktests produced (A_pre and A_suf input assignments) for validation by replay, plus a log."""
    from .opt import load_path_condition, split_pre_suf, opt_closest, value_to_bytes
    log_lines: list[str] = []
    out: list[Path] = []
    for kt in reaching:
        smt = kt.with_suffix(".smt2")
        if not smt.exists():
            continue
        try:
            conjs, arrays = load_path_condition(smt)
        except Exception as exc:  # noqa: BLE001
            log_lines.append(f"{kt.name}: cannot parse smt2: {exc}")
            continue
        pre, suf = split_pre_suf(conjs)
        base = [o for o in read_ktest(kt) if o["name"] != "model_version"]
        sizes = {o["name"]: o["size"] for o in base}
        inputs = {o["name"]: o["bytes"] for o in base if not o["name"].startswith("ghost_")}
        ghosts = {o["name"]: o["bytes"] for o in base if o["name"].startswith("ghost_")}
        in_arrays = {n: a for n, a in arrays.items() if not n.startswith("ghost_")}
        numeric = None
        scalar_inputs = [n for n in inputs if n in decls and not decls[n]["is_array"] and sizes[n] in (4, 8)]
        if len(inputs) == 1 and scalar_inputs:
            numeric = (scalar_inputs[0], decls[scalar_inputs[0]]["ctype"])
        A_suf = dict(inputs=inputs, ghosts=ghosts)
        prev = None
        for r in range(rounds):
            # sigma_pre = f^-1(A_suf|Wr)
            j = {"objects": {**{n: {"size": len(b), "hex": b.hex()} for n, b in A_suf["inputs"].items()},
                             **{n: {"size": len(b), "hex": b.hex()} for n, b in A_suf["ghosts"].items()}}}
            jp = out_dir / f"{kt.stem}_r{r}_suf.json"
            jp.write_text(json.dumps(j))
            inv = _run_py(work / "inverse.py", jp)
            if not inv or "inputs" not in inv:
                log_lines.append(f"{kt.name} r{r}: inverse.py gave nothing"); break
            sigma_pre = {}
            for n, spec_ in inv["inputs"].items():
                try:
                    b = bytes.fromhex(spec_["hex"])
                except (KeyError, ValueError):
                    continue
                if n in sizes and len(b) == sizes[n]:
                    sigma_pre[n] = b
            if not sigma_pre:
                log_lines.append(f"{kt.name} r{r}: inverse.py proposal unusable"); break
            # A_pre = OPT(dist(sigma_pre), pi_pre)
            A_pre = opt_closest(pre, in_arrays, sizes, sigma_pre, numeric=numeric) if pre or in_arrays else None
            if A_pre is None:
                A_pre = dict(sigma_pre)
                log_lines.append(f"{kt.name} r{r}: pi_pre UNSAT/timeout, using sigma_pre directly")
            objs = [dict(o, bytes=A_pre.get(o["name"], o["bytes"])) for o in base if not o["name"].startswith("ghost_")]
            p_kt = out_dir / f"{kt.stem}_r{r}_pre.ktest"
            write_ktest(p_kt, objs); out.append(p_kt)
            # sigma_out = f(A_pre): forward.py runs the original fragment standalone (not a model of it)
            fj = out_dir / f"{kt.stem}_r{r}_pre.json"
            fj.write_text(json.dumps({"inputs": {n: {"hex": b.hex()} for n, b in A_pre.items()}}))
            fwd = _run_py(work / "forward.py", fj)
            wr = (fwd or {}).get("wr") or {}
            sigma_out = {}
            for v, val in wr.items():
                gname = v if v.startswith("ghost_") else "ghost_" + v
                d = ghost_decls.get(gname)
                if gname in sizes and d:
                    b = value_to_bytes(val, d["ctype"], sizes[gname])
                    if b is not None:
                        sigma_out[gname] = b
            if not sigma_out:
                log_lines.append(f"{kt.name} r{r}: forward.py gave no usable Wr values; stopping after A_pre"); break
            # A_suf = OPT(dist(sigma_out), pi_pre & pi_suf)
            sol = opt_closest(pre + suf, arrays, sizes, {**sigma_out, **A_pre})
            if sol is None:
                log_lines.append(f"{kt.name} r{r}: pi_suf UNSAT/timeout"); break
            A_suf = dict(inputs={n: b for n, b in sol.items() if not n.startswith("ghost_")},
                         ghosts={n: b for n, b in sol.items() if n.startswith("ghost_")})
            objs = [dict(o, bytes=A_suf["inputs"].get(o["name"], o["bytes"])) for o in base if not o["name"].startswith("ghost_")]
            s_kt = out_dir / f"{kt.stem}_r{r}_suf.ktest"
            write_ktest(s_kt, objs); out.append(s_kt)
            log_lines.append(f"{kt.name} r{r}: A_pre={ {n: b.hex() for n, b in A_pre.items()} } A_suf={ {n: b.hex() for n, b in A_suf['inputs'].items()} }")
            if A_suf["inputs"] == prev:
                log_lines.append(f"{kt.name} r{r}: fixpoint"); break
            prev = A_suf["inputs"]
    (out_dir / "opt_log.txt").write_text("\n".join(log_lines) + "\n")
    return out, log_lines


def _repair_inverse(ctx: Context, work: Path, jpath: Path, idx: int) -> bool:
    """One agent round to fix inverse.py when it fails on a real ghost test case."""
    try:
        r = subprocess.run([sys.executable, "-I", str(work / "inverse.py"), str(jpath)], capture_output=True, text=True,
                           timeout=30, cwd=str(work))
        out = f"[stdout]\n{r.stdout[-3000:]}\n[stderr]\n{r.stderr[-3000:]}\nexit={r.returncode}"
    except subprocess.TimeoutExpired:
        out = "inverse.py did not finish within 30 s"
    (work / "inverse_error.txt").write_text(out)
    instr = (f"`python3 inverse.py {jpath.name}` (a real ghost test case) did not print a JSON object with an "
             "`inputs` field as required.  `inverse_error.txt` shows its output/traceback.  Fix inverse.py (and forward.py if "
             "it shares the bug) so that it prints exactly one JSON object `{\"inputs\": {\"<name>\": {\"hex\": ...}}, "
             "\"tolerance\": {...}, \"note\": ...}` with byte-exact hex of the same size as each input object, run it on "
             f"{jpath.name} to confirm, and leave the corrected inverse.py in place.")
    spec = TaskSpec(name=f"fix_inverse_{idx}", instructions=instr, workdir=work,
                    inputs=["inverse.py", "forward.py", jpath.name, "inverse_error.txt"], outputs=["inverse.py"],
                    timeout_s=int(min(600, max(60, ctx.budget.remaining - 60))))
    res = ctx.backend.run_task(spec)
    return res.ok


def _expand_to_file_lines(ann_lines: list[str], n_lines: int) -> list[str]:
    """Sliced listing -> list indexed by original line number (omitted ranges become None placeholders
    that ``_collapse_file_lines`` turns back into one marker)."""
    from .common import OMITTED_RE
    out: list = []
    for l in ann_lines:
        m = OMITTED_RE.fullmatch(l)
        if m:
            out.extend([None] * (int(m.group(2)) - int(m.group(1)) + 1))
        else:
            out.append(l)
    return out + [None] * max(0, n_lines - len(out))


def _collapse_file_lines(lines: list) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i] is None:
            j = i
            while j < len(lines) and lines[j] is None:
                j += 1
            out.append(f"/* ... lines {i + 1}-{j} omitted ... */")
            i = j
        else:
            out.append(lines[i])
            i += 1
    return out


def _region_covered(ctx: Context, rel: str, start: int, end: int) -> bool:
    if not ctx.state.coverage or rel not in ctx.state.coverage.files:
        return False
    cov = ctx.state.coverage.files[rel].covered
    return any(ln in cov for ln in range(start, end + 1))


def invert_one(ctx: Context, stage_dir: Path, cand: dict, idx: int, budget_s: float) -> dict:
    rel = cand["file"]
    program = ctx.root / rel
    start, end = int(cand["start"]), int(cand["end"])
    frag = cand.get("fragment") or {}
    fs, fe = int(frag.get("start", max(1, start - 10))), int(frag.get("end", start))
    unc = {ln for ln, _ in ctx.uncovered().get(rel, [])}
    work = stage_dir / f"cand_{idx}" / "task"
    work.mkdir(parents=True, exist_ok=True)
    src_lines = program.read_text(errors="replace").splitlines()
    annotated = prompt_source(ctx, program, unc, set(range(fs, end + 1)))
    ann_lines = annotated.splitlines()
    # a sliced or windowed (file > 120k chars) listing is shorter than the file: index it by original line
    # number via the omitted markers, so the TARGET markers land on the right lines
    ann_lines = _expand_to_file_lines(ann_lines, len(src_lines))
    for ln in range(start, end + 1):
        if 1 <= ln <= len(ann_lines):
            ann_lines[ln - 1] = (ann_lines[ln - 1].rstrip()[:-1].rstrip() + " /* TARGET */ \\") if ann_lines[ln - 1].rstrip().endswith("\\") else ann_lines[ln - 1] + " /* TARGET */"
    prog_name = f"{program.stem}.annotated.c"
    ann_lines = _collapse_file_lines(ann_lines)
    (work / prog_name).write_text("\n".join(ann_lines) + "\n")
    for hdr in sorted(program.parent.glob("*.h")):
        copy_into(hdr, work)
    inputs = [prog_name]
    if ctx.has_harness():
        copy_into(ctx.target.harness_path(ctx.root), work, "harness.c")
        inputs.append("harness.c")
    inputs += write_klee_notes(ctx, work)
    fragment = "\n".join(f"{ln:5d}| {src_lines[ln - 1]}" for ln in range(fs, min(fe, len(src_lines)) + 1))
    ghost_name = f"{program.stem}.ghost.c"
    instr = prompts.INVERSION_TASK.format(program=prog_name, frag_start=fs, frag_end=fe, fragment=fragment,
                                          ghost=ghost_name, klee_rules=prompts.KLEE_RULES)
    instr += slice_note(ctx, annotated)
    if ctx.target.family == "logic_bombs":
        instr += prompts.INVERSION_BOMB_HINT
    spec = TaskSpec(name=f"inversion_{idx}", instructions=instr, workdir=work, inputs=inputs,
                    outputs=[ghost_name, "inverse.py", "forward.py"], timeout_s=int(min(1800, max(60, min(ctx.budget.remaining - 60, max(300, budget_s * 0.5))))))
    res = ctx.backend.run_task(spec)
    rec = dict(candidate=cand, ok=False, steps=[])
    ghost = work / ghost_name
    if not ghost.exists() or not (work / "inverse.py").exists():
        rec["error"] = f"task incomplete: {res.missing} {res.error}"
        return rec
    ghost_code = restore_omitted(ghost.read_text(errors="replace"), src_lines)
    if "klee_mark_target" not in ghost_code:
        rec["error"] = "ghost has no klee_mark_target()"
        return rec
    # strip the UNCOVERED/TARGET annotations the model may have copied
    ghost_code = strip_markers(ghost_code)
    ghost_c = stage_dir / f"cand_{idx}" / ghost_name
    ghost_c.write_text(ghost_code)
    mark_c = stage_dir / f"cand_{idx}" / "gordian_mark.c"
    mark_c.write_text(MARK_SOURCE)
    # --- 2. KLEE on the ghost program
    srcs = [ghost_c if s.resolve() == program.resolve() else s for s in ctx.target.resolve_sources(ctx.root)] + [mark_c]
    ghost_budget = max(10.0, budget_s * 0.35)
    ktests, _ = ctx.run_variant(f"03_inv{idx}_ghost", budget_s=ghost_budget, sources=srcs,
                                extra_cflags=["-I" + ctx.klee_container.path(program.parent)], evaluate=False,
                                klee_extra=None if ctx.target.float else ["--write-smt2s"])   # KLEE-Float cannot write smt2
    vdir = ctx.run_dir / "variants" / f"03_inv{idx}_ghost" / "klee"
    reaching = []
    for err in sorted(vdir.glob("*.err")):
        if "GORDIAN_TARGET" in err.read_text(errors="replace"):
            kt = vdir / (err.name.split(".")[0] + ".ktest")
            if kt.exists():
                reaching.append(kt)
    rec["steps"].append(dict(step="ghost_klee", ktests=len(ktests), reaching_target=len(reaching)))
    if not reaching:
        reaching = ktests[:10]
    if not reaching:
        rec["error"] = "ghost program produced no test cases"
        return rec
    # --- 3. invert each suffix assignment
    orig_code = program.read_text(errors="replace")
    decls = _symbolic_decls(orig_code if not ctx.has_harness() else ctx.target.harness_path(ctx.root).read_text(errors="replace"))
    proposals = []
    repaired = False
    for kt in reaching[:10]:
        j = ktest_as_json(kt)
        jpath = work / (kt.stem + ".json")
        jpath.write_text(json.dumps({"objects": {o["name"]: {"size": o["size"], "hex": o["hex"]} for o in j["objects"]}}))
        inv = _run_py(work / "inverse.py", jpath)
        if (not inv or "inputs" not in inv) and not repaired and not ctx.budget.exhausted(120):
            repaired = True
            if _repair_inverse(ctx, work, jpath, idx):
                inv = _run_py(work / "inverse.py", jpath)
        if not inv or "inputs" not in inv:
            continue
        base = [o for o in read_ktest(kt) if not o["name"].startswith("ghost_") and o["name"] != "model_version"]
        values: dict[str, bytes] = {}
        for o in base:
            spec_ = inv["inputs"].get(o["name"])
            if spec_ and "hex" in spec_:
                try:
                    b = bytes.fromhex(spec_["hex"])
                except ValueError:
                    continue
                if len(b) == o["size"]:
                    o["bytes"] = b
                    values[o["name"]] = b
        if not values:
            continue
        tol = {k: float(v) for k, v in (inv.get("tolerance") or {}).items()}
        proposals.append(dict(objects=base, values=values, tolerance=tol, note=inv.get("note", "")))
    rec["steps"].append(dict(step="inverse", proposals=len(proposals)))
    if not proposals:
        rec["error"] = "inverse.py produced no usable proposal"
        return rec
    # --- 4a. direct replay of the proposals on the original program
    direct_dir = stage_dir / f"cand_{idx}" / "direct_ktests"
    direct_dir.mkdir(exist_ok=True)
    direct = []
    for i, p in enumerate(proposals):
        kt = direct_dir / f"proposal_{i}.ktest"
        write_ktest(kt, p["objects"])
        direct.append(kt)
    ctx.evaluate(None, direct, f"03_inv{idx}_direct")
    if _region_covered(ctx, rel, start, end):
        rec["ok"] = True
        rec["steps"].append(dict(step="direct_replay", covered=True))
        return rec
    rec["steps"].append(dict(step="direct_replay", covered=False))
    # --- 4b. exact bidirectional propagation (Alg. 1) with Z3 Optimize on KLEE's path conditions
    ghost_decls = _symbolic_decls(ghost_code)
    opt_dir = stage_dir / f"cand_{idx}" / "opt_rounds"
    opt_dir.mkdir(exist_ok=True)
    opt_ktests, opt_log = exact_opt_rounds(work, vdir, reaching[:5], proposals, decls, ghost_decls, opt_dir)
    if opt_ktests:
        ctx.evaluate(None, opt_ktests, f"03_inv{idx}_opt")
        covered = _region_covered(ctx, rel, start, end)
        rec["steps"].append(dict(step="opt_rounds", ktests=len(opt_ktests), covered=covered, log=opt_log[-12:]))
        if covered:
            rec["ok"] = True
            return rec
    elif opt_log:
        rec["steps"].append(dict(step="opt_rounds", ktests=0, covered=False, log=opt_log[-12:]))
    # --- 4c. concrete neighbourhood search around each proposal (cheap: native replay only).
    # Approximates OPT(dist(sigma_pre), pi_pre) by sampling: instead of asking a solver for the closest
    # feasible input, candidates at growing distances from the inverse's proposal are replayed and the
    # path condition is "checked" by the original program itself.  Used when the exact rounds found
    # nothing or could not run (no smt2 from KLEE-Float).
    for ri, factor in enumerate(f for f in RELAX_FACTORS if f > 0):
        ndir = stage_dir / f"cand_{idx}" / f"neigh_{ri}"
        ndir.mkdir(exist_ok=True)
        kts = []
        for pi, p in enumerate(proposals[:3]):
            for ci, objs in enumerate(_neighbourhood(p["objects"], decls, p["values"], factor)):
                kt = ndir / f"p{pi}_c{ci}.ktest"
                write_ktest(kt, objs)
                kts.append(kt)
        if not kts:
            break
        ctx.evaluate(None, kts, f"03_inv{idx}_neigh{ri}")
        covered = _region_covered(ctx, rel, start, end)
        rec["steps"].append(dict(step="neighbourhood", factor=factor, ktests=len(kts), covered=covered))
        if covered:
            rec["ok"] = True
            return rec
    # --- 4d. reconcile with the prefix path condition: KLEE with relaxed bounds.  The second OPT
    # approximation: the inputs are constrained (klee_assume) to a neighbourhood of the inverse's proposal
    # that widens round by round, so KLEE's own solver searches the nearest region of pi_pre for a
    # satisfying input instead of an optimizer minimising the distance.
    if ctx.has_harness():
        rec["error"] = "relaxation rounds are only implemented for programs with their own main()"
        return rec
    factors = sorted({f for f in RELAX_FACTORS} | {min(1.0, max(p["tolerance"].values(), default=0.0)) for p in proposals})
    remaining_rounds = max(1, len(factors))
    for ri, factor in enumerate(factors):
        if ctx.budget.exhausted(30):
            break
        round_budget = max(10.0, min(ctx.budget.remaining - 20, (budget_s * 0.6) / remaining_rounds))
        rdir = stage_dir / f"cand_{idx}" / f"relax_{ri}"
        rdir.mkdir(exist_ok=True)
        new_ktests = []
        for pi, p in enumerate(proposals[:3]):
            variant = rdir / f"{program.stem}.assume_{pi}.c"
            variant.write_text(_inject_assumes(orig_code, decls, p["values"], factor))
            srcs = [variant if s.resolve() == program.resolve() else s for s in ctx.target.resolve_sources(ctx.root)]
            kts, _ = ctx.run_variant(f"03_inv{idx}_relax{ri}_{pi}", budget_s=round_budget / min(3, len(proposals)),
                                     sources=srcs, extra_cflags=["-I" + ctx.klee_container.path(program.parent)],
                                     evaluate=False)
            new_ktests += kts
        ctx.evaluate(None, new_ktests, f"03_inv{idx}_relax{ri}")
        covered = _region_covered(ctx, rel, start, end)
        rec["steps"].append(dict(step="relax", factor=factor, ktests=len(new_ktests), covered=covered))
        if covered:
            rec["ok"] = True
            return rec
    rec["error"] = "target not reached within budget"
    return rec


def run(ctx: Context, budget_s: float, triage_result: list[dict], max_candidates: int = 3) -> dict:
    stage_dir = ctx.run_dir / "03_inversion"
    stage_dir.mkdir(parents=True, exist_ok=True)
    # drop candidates already covered by earlier stages
    affordable = max(1, int(budget_s // 420))   # an agent needs ~5-7 min per candidate
    cands = [c for c in _candidates(triage_result, max_candidates * 2)
             if not _region_covered(ctx, c["file"], int(c["start"]), int(c["end"]))][:min(max_candidates, affordable)]
    result = dict(candidates=cands, results=[])
    if not cands:
        log.info("inversion: no candidates with a reasonable chance of success")
        (stage_dir / "result.json").write_text(json.dumps(result, indent=2))
        return result
    for i, cand in enumerate(cands, 1):
        if ctx.budget.exhausted(60):
            break
        per = max(30.0, min(ctx.budget.remaining - 30, budget_s / len(cands)))
        rec = invert_one(ctx, stage_dir, cand, i, per)
        log.info("inversion candidate %d (%s %s-%s): %s", i, cand["file"], cand["start"], cand["end"],
                 "SUCCESS" if rec["ok"] else rec.get("error"))
        result["results"].append(rec)
        (stage_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
    return result
