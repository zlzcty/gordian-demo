"""Shared machinery for pipeline stages: run context, variant execution,
coverage accounting and source annotation for prompts."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..budget import Budget
from ..config import Settings
from ..coverage import CoverageReport, build_replay_binary, replay_coverage, uncovered_lines_outside_main
from ..docker import Runtime, Container
from ..klee import compile_bitcode, run_klee
from ..llm import Backend
from ..targets import Target
from ..log import get_logger

log = get_logger(__name__)

ORIG_MAIN_RENAME = "gordian_original_main"


@dataclass
class TestSuite:
    """Ktests grouped by the harness they must be replayed with (None = target's own harness/main)."""
    groups: list[tuple[Optional[Path], list[Path]]] = field(default_factory=list)

    def add(self, harness: Optional[Path], ktests: list[Path]) -> None:
        if ktests:
            self.groups.append((harness, list(ktests)))

    @property
    def count(self) -> int:
        return sum(len(k) for _, k in self.groups)


@dataclass
class RunState:
    coverage: Optional[CoverageReport] = None     # union over everything so far (original program)
    suite: TestSuite = field(default_factory=TestSuite)
    history: list[dict] = field(default_factory=list)   # per-variant records
    bombs: set[str] = field(default_factory=set)
    klee_notes: dict[str, list[str]] = field(default_factory=dict)   # variant label -> KLEE warnings


class Context:
    def __init__(self, settings: Settings, runtime: Runtime, target: Target, backend: Backend, run_dir: Path,
                 budget: Budget, *, solver_timeout_s: Optional[int] = None):
        self.settings = settings
        self.rt = runtime
        self.target = target
        self.backend = backend
        self.run_dir = run_dir
        self.budget = budget
        self.root = settings.project_root
        self.solver_timeout_s = solver_timeout_s or settings.solver_timeout_s
        self.context_mode = "file"      # what {CODE} in the prompts is: the whole file or a slice (--context)
        self.state = RunState()
        self._replay_exe: dict[Optional[str], Path] = {}
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # ---- containers ----------------------------------------------------------
    @property
    def klee_container(self) -> Container:
        return self.rt.get(self.target.float)

    @property
    def replay_container(self) -> Container:
        return self.rt.std

    # ---- helpers ---------------------------------------------------------------
    def coverage_files(self) -> list[Path]:
        return self.target.resolve_coverage_files(self.root)

    def has_harness(self) -> bool:
        return self.target.harness is not None

    def replay_exe(self, harness: Optional[Path]) -> Optional[Path]:
        """Native coverage binary of the ORIGINAL sources with the given harness (cached)."""
        key = str(harness) if harness else None
        if key in self._replay_exe:
            return self._replay_exe[key]
        name = "orig" if harness is None else re.sub(r"[^A-Za-z0-9_]", "_", harness.stem)
        bdir = self.run_dir / "replay_builds" / name
        if harness is not None and not self.has_harness():
            # single-file program: the original main() must give way to the ghost harness
            exe, _ = build_replay_binary(self.replay_container, self.target, self.root, bdir, harness=harness,
                                         source_cflags=[f"-Dmain={ORIG_MAIN_RENAME}"])
        else:
            exe, _ = build_replay_binary(self.replay_container, self.target, self.root, bdir, harness=harness)
        self._replay_exe[key] = exe
        return exe

    def evaluate(self, harness: Optional[Path], ktests: list[Path], label: str) -> Optional[CoverageReport]:
        """Replay ktests on the original program, merge into the global coverage, record history."""
        exe = self.replay_exe(harness)
        if exe is None or not ktests:
            return None
        rep = replay_coverage(self.replay_container, self.target, self.root, exe, ktests,
                              self.run_dir / "coverage" / label, timeout_s=self.settings.replay_timeout_s,
                              max_tests=self.settings.replay_max_tests)
        bombs = self.run_dir / "coverage" / label / "bombs_reached.json"
        if bombs.exists():
            self.state.bombs |= set(json.loads(bombs.read_text()))
        before = self.state.coverage.total()[0] if self.state.coverage else 0
        self.state.coverage = rep if self.state.coverage is None else self.state.coverage.union(rep)
        after, total = self.state.coverage.total()
        self.state.suite.add(harness, ktests)
        rec = dict(label=label, ktests=len(ktests), new_lines=after - before, covered=after, total=total,
                   t=round(self.budget.elapsed), harness=str(harness) if harness else None)
        self.state.history.append(rec)
        log.info("[%s] %d ktests -> +%d lines (%d/%d = %.1f%%)", label, len(ktests), after - before, after, total,
                 100.0 * after / total if total else 0)
        self.save_state()
        return rep

    def uncovered(self) -> dict[str, list[tuple[int, str]]]:
        if self.state.coverage is None:
            return {}
        return uncovered_lines_outside_main(self.state.coverage, self.root)

    def save_state(self) -> None:
        d = dict(target=self.target.name, budget=dict(total=self.budget.total, elapsed=round(self.budget.elapsed)),
                 coverage=self.state.coverage.as_dict() if self.state.coverage else None,
                 bombs_reached=sorted(self.state.bombs), history=self.state.history,
                 suite=[dict(harness=str(h) if h else None, ktests=[str(k) for k in ks]) for h, ks in self.state.suite.groups],
                 llm_usage=self.backend.usage.as_dict())
        (self.run_dir / "state.json").write_text(json.dumps(d, indent=2))

    # ---- running a variant -------------------------------------------------------
    def run_variant(self, label: str, *, budget_s: float, sources: Optional[list[Path]] = None,
                    harness: Optional[Path] = None, replay_harness: Optional[Path] = None,
                    solver_timeout_s: Optional[int] = None, extra_cflags: Optional[list[str]] = None,
                    klee_extra: Optional[list[str]] = None, container: Optional[Container] = None,
                    evaluate: bool = True, only_new: bool = True) -> tuple[list[Path], Optional[CoverageReport]]:
        """Compile (sources + harness) -> KLEE for budget_s -> replay ktests on the ORIGINAL program.

        ``sources`` replaces the target's sources for the KLEE build only (e.g. a surrogate model);
        ``harness`` replaces the harness for KLEE; ``replay_harness`` is the harness used for replay
        (defaults to ``harness``).  For single-file targets a ghost harness implies renaming the
        original main().
        """
        c = container or self.klee_container
        vdir = self.run_dir / "variants" / label
        vdir.mkdir(parents=True, exist_ok=True)
        t = self.target
        cflags = list(extra_cflags or [])
        if harness is not None and not self.has_harness():
            cflags.append(f"-Dmain={ORIG_MAIN_RENAME}")
            # the harness itself must keep its main(): compile it separately without the rename
            build = compile_bitcode(c, t, self.root, vdir / "build", sources=sources, harness=None, extra_flags=cflags)
            if build.ok:
                hb = compile_bitcode(c, t, self.root, vdir / "build_harness", sources=[harness], harness=None)
                if hb.ok:
                    tools = c.tools
                    merged = vdir / "build" / "module_with_harness.bc"
                    r = c.exec(f"{tools.llvm_link} {c.path(build.bitcode)} {c.path(hb.bitcode)} -o {c.path(merged)}", timeout=300)
                    if r.returncode == 0:
                        build.bitcode = merged
                    else:
                        build.ok = False
                        build.log += r.stderr
                else:
                    build.ok = False
                    build.log += hb.log
        else:
            build = compile_bitcode(c, t, self.root, vdir / "build", sources=sources, harness=harness, extra_flags=cflags)
        if not build.ok:
            (vdir / "FAILED_BUILD").write_text(build.log)
            self.state.history.append(dict(label=label, error="build failed", t=round(self.budget.elapsed)))
            self.last_build_log = build.log
            return [], None
        self.last_build_log = ""
        kt = t
        if harness is not None and t.posix_runtime and not _main_has_args(harness):
            import copy
            kt = copy.deepcopy(t)
            kt.posix_runtime = False   # KLEE refuses --posix-runtime when main() takes no arguments
        kr = run_klee(c, kt, build.bitcode, vdir / "klee", budget_s=int(max(5, budget_s)),
                      solver_timeout_s=solver_timeout_s or self.solver_timeout_s, search=self.settings.search,
                      extra=klee_extra, only_new=only_new and label != "00_explore")
        if not kr.ktests and "Broken module" in kr.log_tail and "-g0" not in cflags:
            log.warning("[%s] KLEE rejected the module's debug info; rebuilding with -g0", label)
            return self.run_variant(label, budget_s=budget_s, sources=sources, harness=harness,
                                    replay_harness=replay_harness, solver_timeout_s=solver_timeout_s,
                                    extra_cflags=cflags + ["-g0"], klee_extra=klee_extra, container=container,
                                    evaluate=evaluate, only_new=only_new)
        if kr.warnings:
            self.state.klee_notes[label] = kr.warnings
        if not evaluate:
            return kr.ktests, None
        rep = self.evaluate(replay_harness if replay_harness is not None else harness, kr.ktests, label)
        return kr.ktests, rep


def _main_has_args(path: Optional[Path]) -> bool:
    if path is None:
        return True
    m = re.search(r"\bint\s+main\s*\(([^)]*)\)", path.read_text(errors="replace"))
    return bool(m) and m.group(1).strip() not in ("", "void")


# ---- source annotation for prompts ---------------------------------------------------
def annotate_source(path: Path, uncovered: set[int], *, number: bool = True, max_chars: int = 120_000,
                    focus: Optional[set[int]] = None, context: int = 40, keep: Optional[set[int]] = None) -> str:
    """Numbered listing with ``// UNCOVERED`` markers.  If the file exceeds ``max_chars`` only windows
    around the focus lines are kept (with ``... omitted ...`` markers); an explicit ``keep`` set (see
    ``slice_lines``) restricts the listing to those lines regardless of size."""
    lines = path.read_text(errors="replace").splitlines()
    total_len = sum(len(l) + 12 for l in lines)
    if keep is None and total_len > max_chars:
        focus = focus or uncovered
        keep = set()
        for ln in focus:
            keep.update(range(max(1, ln - context), min(len(lines), ln + context) + 1))
    out, last = [], 0
    for i, l in enumerate(lines, 1):
        if keep is not None and i not in keep:
            continue
        if keep is not None and i != last + 1:
            out.append(f"/* ... lines {last + 1}-{i - 1} omitted ... */")
        if i in uncovered:
            # block comment, placed before a trailing backslash so macro continuations stay intact
            if l.rstrip().endswith("\\"):
                body = l.rstrip()[:-1].rstrip()
                l = f"{body} /* UNCOVERED */ \\"
            else:
                l = f"{l} /* UNCOVERED */"
        out.append(f"{i:5d}| {l}" if number else l)
        last = i
    if keep is not None and last < len(lines):
        out.append(f"/* ... lines {last + 1}-{len(lines)} omitted ... */")
    return "\n".join(out)


# `type name(args) {`, `name(args,` (return type on the previous line), K&R `	double f(x)`: the name is
# the identifier right before the first `(`; keywords are filtered out below.
_FUNC_HEAD_RE = re.compile(r"^\s*(?:[\w\*\s,]*?[\s\*])?([A-Za-z_]\w*)\s*\([^;{}]*\)?\s*\{?\s*$")
_NOT_FUNC = ("if", "else", "for", "while", "switch", "return", "do", "case", "typedef", "struct", "union", "enum", "sizeof")


def function_ranges(lines: list[str]) -> list[tuple[str, int, int]]:
    """(name, start, end) of every function definition found by a brace-matching scan (heuristic: a
    header line that looks like ``type name(args)`` followed by a ``{`` before any ``);``).  The scan
    skips a found function's body, so call statements inside it cannot be mistaken for headers."""
    out = []
    i = 0
    while i < len(lines):
        l = lines[i]
        m = _FUNC_HEAD_RE.match(l) if l.strip() and not l.lstrip().startswith("#") else None
        if not m or m.group(1) in _NOT_FUNC or l.rstrip().endswith(";"):
            i += 1
            continue
        depth, seen, j = 0, False, i
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            if "{" in lines[j]:
                seen = True
            if seen and depth <= 0:
                break
            if not seen and lines[j].rstrip().endswith(");"):
                break   # a prototype (or a call statement), not a definition; K&R `double x;` lines pass
            j += 1
        if seen:
            out.append((m.group(1), i + 1, min(j, len(lines) - 1) + 1))
            i = j + 1
        else:
            i += 1
    return out


def slice_lines(path: Path, focus: set[int], *, preamble_max: int = 200, window: int = 40) -> set[int]:
    """The lines of ``path`` that make up the prompt slice for ``focus``: the file preamble (includes,
    macros, types, globals before the first function), the functions enclosing the focus lines, the
    functions they call directly, and main() (the symbolic-input interface).  Focus lines outside any
    detected function keep a +-``window`` neighbourhood."""
    lines = path.read_text(errors="replace").splitlines()
    funcs = function_ranges(lines)
    keep: set[int] = set()
    first = min((s for _, s, _ in funcs), default=len(lines) + 1)
    keep.update(range(1, min(first, preamble_max + 1)))
    by_name = {n: (s, e) for n, s, e in funcs}
    enclosing = [(n, s, e) for n, s, e in funcs if any(s <= ln <= e for ln in focus)]
    for ln in focus:
        if not any(s <= ln <= e for _, s, e in enclosing):
            keep.update(range(max(1, ln - window), min(len(lines), ln + window) + 1))
    for n, s, e in enclosing:
        keep.update(range(s, e + 1))
        body = "\n".join(lines[s - 1:e])
        for callee in set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", body)):
            if callee != n and callee in by_name:
                cs, ce = by_name[callee]
                keep.update(range(cs, ce + 1))
    if "main" in by_name:
        keep.update(range(by_name["main"][0], by_name["main"][1] + 1))
    return keep


OMITTED_RE = re.compile(r"[ \t]*/\* \.\.\. lines (\d+)-(\d+) omitted \.\.\. \*/[ \t]*")


def restore_omitted(text: str, original_lines: list[str]) -> str:
    """Expand the ``/* ... lines a-b omitted ... */`` markers of a sliced listing that an LLM copied into
    its output back to the original lines, so a file produced from a slice is complete again."""
    return OMITTED_RE.sub(lambda m: "\n".join(original_lines[int(m.group(1)) - 1:int(m.group(2))]), text)


def prompt_source(ctx: "Context", path: Path, uncovered: set[int], focus: Optional[set[int]] = None, *,
                  number: bool = False) -> str:
    """{CODE} for a prompt: the annotated file, or (``--context slice``) the annotated slice around ``focus``."""
    keep = slice_lines(path, focus or uncovered) if ctx.context_mode == "slice" and (focus or uncovered) else None
    return annotate_source(path, uncovered, number=number, keep=keep)


def slice_note(ctx: "Context", listing: str = "") -> str:
    """The prompt note explaining the omitted-lines markers: for slices and for listings windowed by size."""
    from .. import prompts
    return prompts.SLICE_NOTE if ctx.context_mode == "slice" or "omitted ... */" in listing else ""


def group_uncovered(uncovered: list[tuple[int, str]], gap: int = 2) -> list[tuple[int, int]]:
    """Group uncovered line numbers into contiguous regions [(start, end), ...]."""
    regions: list[list[int]] = []
    for ln, _ in sorted(uncovered):
        if regions and ln - regions[-1][1] <= gap:
            regions[-1][1] = ln
        else:
            regions.append([ln, ln])
    return [(a, b) for a, b in regions]


def rank_regions(regions: list[tuple[int, int]], uncovered_set: set[int]) -> list[tuple[int, int]]:
    """Ranking heuristic: prefer regions high in the file (earlier control flow) that guard more
    still-uncovered code (region size)."""
    def key(r):
        size = sum(1 for ln in range(r[0], r[1] + 1) if ln in uncovered_set)
        return (-size, r[0])
    return sorted(regions, key=key)


def copy_into(src: Path, dst_dir: Path, name: Optional[str] = None) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / (name or src.name)
    shutil.copy2(src, dst)
    return dst


KLEE_NOTES_HEADER = """# KLEE diagnostics from previous runs on this program
# Each line is a KLEE warning/error.  The most important kind is
#   "silently concretizing (reason: floating point) expression ... to value ... (file:line)"
# standard KLEE cannot reason about floating-point operations on symbolic values: at that point the
# symbolic input is replaced by ONE concrete value and every branch after it is explored with that value
# only.  To keep inputs symbolic, the code must branch on integer bit patterns (memcpy the double into a
# uint64_t / use the __HI_model/__LO_model word accessors) and do integer arithmetic; floating-point
# arithmetic may only be applied to concrete values (e.g. inside a case split).
# "calling external: f(...)" means f ran natively on concrete arguments (no symbolic reasoning through it).
"""


def write_klee_notes(ctx: "Context", work: Path) -> list[str]:
    """Write klee_notes.txt into a task directory; returns the input list entry (or empty)."""
    lines = []
    for label, warns in ctx.state.klee_notes.items():
        lines.append(f"## {label}")
        lines.extend(warns[:60])
    if not lines:
        return []
    (work / "klee_notes.txt").write_text(KLEE_NOTES_HEADER + "\n".join(lines) + "\n")
    return ["klee_notes.txt"]


MARKER_RE = re.compile(r"\s*(/\*\s*(UNCOVERED|TARGET)\s*\*/|//\s*(UNCOVERED|TARGET)\b[^\n]*)")


def strip_markers(text: str) -> str:
    """Remove the UNCOVERED / TARGET annotations an LLM may have copied into its output."""
    return MARKER_RE.sub("", text)


def fix_compile_errors(ctx: "Context", src: Path, build_log: str, label: str, extra_inputs: Optional[list[Path]] = None) -> Optional[Path]:
    """One LLM round to repair a file that does not compile; returns the repaired file or None."""
    from ..llm import TaskSpec
    work = src.parent / f"fix_{src.stem}"
    work.mkdir(parents=True, exist_ok=True)
    copy_into(src, work, src.name)
    (work / "compile_errors.txt").write_text(build_log[-6000:])
    inputs = [src.name, "compile_errors.txt"]
    for e in extra_inputs or []:
        copy_into(e, work); inputs.append(e.name)
    instr = (f"`{src.name}` does not compile; `compile_errors.txt` has the compiler output (clang, C99, KLEE headers available). "
             "Fix ONLY the compile errors (missing includes, declarations, stray annotations, unbalanced braces, "
             "macro continuations, typos) without changing the intended behaviour, and write the corrected file back "
             f"as `{src.name}`.")
    spec = TaskSpec(name=f"fix_{label}", instructions=instr, workdir=work, inputs=inputs, outputs=[src.name],
                    timeout_s=int(min(600, max(60, ctx.budget.remaining - 60))), allow_shell=True)
    res = ctx.backend.run_task(spec)
    out = work / src.name
    if res.ok and out.exists():
        fixed = src.with_name(src.stem + ".fixed.c")
        fixed.write_text(strip_markers(out.read_text(errors="replace")))
        return fixed
    return None
