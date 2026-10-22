"""Line coverage of the *original* program by replaying ktests.

The target's sources (never the LLM-generated variants) are compiled natively
with clang's source-based coverage instrumentation and linked against
``libkleeRuntest``; each ktest is replayed by setting ``KTEST_FILE``; the
profiles are merged and ``llvm-cov export`` gives per-file, per-line counts.
Ghost harnesses are allowed to replace the harness (they are drivers, not the
code under test); LLM-rewritten *library/program* files are never linked here.
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .docker import Container
from .targets import Target
from .log import get_logger

log = get_logger(__name__)

FLUSHCOV_SOURCE = r'''
/* gordian replay helper: flush llvm profile counters when the program crashes, aborts or runs
   past the per-test deadline (GORDIAN_REPLAY_TIMEOUT seconds), so coverage of crashing tests is kept. */
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>
int __llvm_profile_write_file(void);
static void gordian_flush_and_exit(int sig) { __llvm_profile_write_file(); _exit(128 + sig); }
__attribute__((constructor)) static void gordian_install(void) {
    int sigs[] = {SIGSEGV, SIGBUS, SIGFPE, SIGILL, SIGABRT, SIGALRM, SIGTERM, SIGINT};
    for (unsigned i = 0; i < sizeof sigs / sizeof *sigs; i++) {
        struct sigaction sa; sa.sa_handler = gordian_flush_and_exit; sigemptyset(&sa.sa_mask); sa.sa_flags = SA_RESETHAND;
        sigaction(sigs[i], &sa, 0);
    }
    const char *t = getenv("GORDIAN_REPLAY_TIMEOUT");
    if (t && atoi(t) > 0) alarm((unsigned)atoi(t));
}
'''


@dataclass
class FileCoverage:
    path: str
    covered: set[int] = field(default_factory=set)
    uncovered: set[int] = field(default_factory=set)
    text: dict[int, str] = field(default_factory=dict)   # line -> source text for coverable lines

    @property
    def total(self) -> int:
        return len(self.covered) + len(self.uncovered)

    @property
    def ratio(self) -> float:
        return len(self.covered) / self.total if self.total else 0.0


@dataclass
class CoverageReport:
    files: dict[str, FileCoverage]
    ktests: int
    replay_failures: int = 0
    log: str = ""

    def total(self) -> tuple[int, int]:
        c = sum(len(f.covered) for f in self.files.values())
        t = sum(f.total for f in self.files.values())
        return c, t

    def as_dict(self) -> dict:
        c, t = self.total()
        return {"ktests": self.ktests, "replay_failures": self.replay_failures, "covered": c, "total": t,
                "ratio": round(c / t, 4) if t else 0.0,
                "files": {k: {"covered": sorted(f.covered), "uncovered": sorted(f.uncovered), "total": f.total,
                              "ratio": round(f.ratio, 4)} for k, f in self.files.items()}}

    def union(self, other: "CoverageReport") -> "CoverageReport":
        files = {}
        for k in set(self.files) | set(other.files):
            a, b = self.files.get(k), other.files.get(k)
            if a is None or b is None:
                files[k] = a or b
                continue
            cov = a.covered | b.covered
            files[k] = FileCoverage(k, cov, (a.uncovered | b.uncovered) - cov, {**a.text, **b.text})
        return CoverageReport(files, self.ktests + other.ktests, self.replay_failures + other.replay_failures)


def normalize_ktests(ktests: list[Path], out_dir: Path) -> list[Path]:
    """Copy ktests for replay, dropping runtime-internal objects (``model_version`` from the
    KLEE-Float POSIX runtime) that libkleeRuntest of a different KLEE version does not expect."""
    from .ktest import read_ktest, write_ktest
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, k in enumerate(ktests):
        try:
            objs = read_ktest(k)
        except Exception as exc:  # noqa: BLE001
            log.warning("skipping unreadable ktest %s: %s", k, exc)
            continue
        objs = [o for o in objs if o["name"] != "model_version"]
        dst = out_dir / f"{i:05d}_{k.stem}.ktest"
        write_ktest(dst, objs)
        out.append(dst)
    return out


# klee_assert_soft is defined on the compiler command line (REPLAY_FLAGS) rather than by lines prepended to
# the copy: clang's coverage mapping uses physical line numbers and ignores #line, so any added line
# would shift every reported line of that file.
KLEE_ASSERT_SOFT = 'klee_assert_soft(c)=do { if (!(c)) fprintf(stderr, "GORDIAN_BOMB_REACHED %s:%d\\n", __FILE__, __LINE__); } while (0)'
REPLAY_FLAGS = ["-include", "stdio.h", "-D" + KLEE_ASSERT_SOFT]


def _replay_source(src: Path, dst: Path) -> None:
    """Copy a source for native replay, neutralising klee_assert so the bomb branch does not abort.
    The copy has exactly the original's lines (see REPLAY_FLAGS)."""
    text = src.read_text(errors="replace")
    dst.write_text(re.sub(r"\bklee_assert\s*\(", "klee_assert_soft(", text))


def build_replay_binary(c: Container, target: Target, root: Path, build_dir: Path, *,
                        harness: Optional[Path] = None, source_cflags: Optional[list[str]] = None) -> tuple[Optional[Path], str]:
    """Native, coverage-instrumented binary of the ORIGINAL sources (+ chosen harness)."""
    tools = c.tools
    build_dir.mkdir(parents=True, exist_ok=True)
    srcs = target.resolve_sources(root)
    h = harness if harness is not None else target.harness_path(root)
    compile_list: list[tuple[Path, Path]] = []   # (replay copy, original) pairs
    for s in srcs + ([h] if h else []):
        if s.suffix != ".c":
            continue
        dst = build_dir / ("replay_" + s.name)
        _replay_source(s, dst)
        compile_list.append((dst, s))
    # The replay copies must keep the original file's directory for relative #includes.
    flags = ["-O0", "-g", "-fprofile-instr-generate", "-fcoverage-mapping", "-Xclang", "-disable-O0-optnone",
             "-fno-inline", "-fno-builtin", "-Wno-everything", "-I" + tools.klee_include] + REPLAY_FLAGS
    flags += target.clang_flags(root, c.path)
    objs, cmds = [], []
    for dst, orig in compile_list:
        obj = build_dir / (dst.stem + ".o")
        objs.append(obj)
        inc_dir = "-I" + c.path(orig.parent)
        extra = " ".join(shlex.quote(f) for f in (source_cflags or [])) if orig != h else ""
        cmds.append(f"{tools.clang} {' '.join(shlex.quote(f) for f in flags)} {extra} {inc_dir} -c {shlex.quote(c.path(dst))} -o {shlex.quote(c.path(obj))}")
    flush_c = build_dir / "gordian_flushcov.c"
    flush_c.write_text(FLUSHCOV_SOURCE)
    flush_o = build_dir / "gordian_flushcov.o"
    cmds.append(f"{tools.clang} -O0 -c {shlex.quote(c.path(flush_c))} -o {shlex.quote(c.path(flush_o))}")
    objs.append(flush_o)
    exe = build_dir / "replay_exe"
    link = (f"{tools.clang} -fprofile-instr-generate -fcoverage-mapping {' '.join(shlex.quote(c.path(o)) for o in objs)} "
            f"-L{tools.klee_runtest_lib} -Wl,-rpath,{tools.klee_runtest_lib} -lkleeRuntest -lm -lpthread "
            f"{' '.join(target.link_flags)} -o {shlex.quote(c.path(exe))}")
    r = c.exec("set -e\n" + "\n".join(cmds) + "\n" + link, timeout=900)
    (build_dir / "replay_build.log").write_text(r.stdout + r.stderr)
    if r.returncode != 0:
        log.error("replay build failed for %s: %s", target.name, (r.stdout + r.stderr)[-1500:])
        return None, r.stdout + r.stderr
    return exe, r.stdout + r.stderr


def replay_coverage(c: Container, target: Target, root: Path, exe: Path, ktests: Iterable[Path], work_dir: Path, *,
                    timeout_s: int = 30, max_tests: int = 0, coverage_files: Optional[list[Path]] = None) -> CoverageReport:
    """Replay every ktest on ``exe`` and compute line coverage for the coverage files.

    ``max_tests`` > 0 replays an evenly spaced sample of at most that many tests instead of all of
    them (``replay_max_tests`` in gordian.yaml / ``--replay-max-tests``); 0, the default, replays all.
    """
    tools = c.tools
    work_dir.mkdir(parents=True, exist_ok=True)
    prof_dir = work_dir / "profraw"
    c.exec(f"rm -rf {shlex.quote(c.path(prof_dir))} && mkdir -p {shlex.quote(c.path(prof_dir))}", timeout=60)
    ktests = normalize_ktests(list(ktests), work_dir / "ktests_norm")
    if not ktests:
        return CoverageReport({}, 0)
    # Per-test timeout shrinks with the number of tests (a looping program would otherwise cost
    # 30 s per test); tests are replayed 8 at a time.
    n = len(ktests)
    if max_tests > 0 and n > max_tests:
        log.info("replaying an evenly spaced sample of %d of %d tests (replay_max_tests)", max_tests, n)
        step = n / float(max_tests)
        ktests = [ktests[int(i * step)] for i in range(max_tests)]
        n = len(ktests)
    per_test = timeout_s if n <= 20 else (10 if n <= 100 else (3 if n <= 1000 else 2))
    list_file = work_dir / "ktests.txt"
    list_file.write_text("\n".join(c.path(k) for k in ktests) + "\n")
    script = f'''
cd {shlex.quote(c.path(work_dir))}
: > replay_fail.txt
W=$(pwd); export W
cat {shlex.quote(c.path(list_file))} | xargs -P 8 -I{{}} sh -c 'd=$(mktemp -d "$W/tmp_XXXXXX"); cd "$d"; GORDIAN_REPLAY_TIMEOUT={per_test} KTEST_FILE="$1" LLVM_PROFILE_FILE={shlex.quote(c.path(prof_dir))}/t_$(basename "$1" .ktest).profraw timeout -s KILL {per_test + 2} {shlex.quote(c.path(exe))} >/dev/null 2>>"$W/replay_stderr.txt" </dev/null; rc=$?; cd "$W"; rm -rf "$d"; [ $rc -ge 124 ] && echo "$1" >> replay_fail.txt; exit 0' _ {{}}
echo "REPLAY_FAILURES=$(wc -l < replay_fail.txt)"
find {shlex.quote(c.path(prof_dir))} -name '*.profraw' > profraw_list.txt
wc -l < profraw_list.txt
'''
    # Each test replays in its own scratch directory: programs that read/write relative files (the
    # file-based logic bombs write tmp.covpro in the cwd) would otherwise race 8 at a time.
    r = c.exec(script, timeout=per_test * n // 8 + 180)
    failures = 0
    m = re.search(r"REPLAY_FAILURES=(\d+)", r.stdout)
    if m:
        failures = int(m.group(1))
    merged = work_dir / "merged.profdata"
    # the profiles are passed as a list file: a shell glob exceeds the argument-length limit at ~20k tests
    r2 = c.exec(f"{tools.llvm_profdata} merge -sparse -f {shlex.quote(c.path(work_dir / 'profraw_list.txt'))} -o {shlex.quote(c.path(merged))}", timeout=600)
    if r2.returncode != 0:
        log.error("llvm-profdata merge failed: %s", r2.stderr[-1000:])
        raise RuntimeError(f"llvm-profdata merge failed for {target.name} ({len(ktests)} tests): {r2.stderr[-500:]}")
    r3 = c.exec(f"{tools.llvm_cov} export -format=text -skip-expansions -skip-functions {shlex.quote(c.path(exe))} -instr-profile={shlex.quote(c.path(merged))}", timeout=600)
    if r3.returncode != 0:
        log.error("llvm-cov export failed: %s", r3.stderr[-1000:])
        raise RuntimeError(f"llvm-cov export failed for {target.name}: {r3.stderr[-500:]}")
    (work_dir / "llvm_cov_export.json").write_text(r3.stdout)
    report = parse_llvm_cov_export(json.loads(r3.stdout), c, target, root, coverage_files)
    report.ktests = len(ktests)
    report.replay_failures = failures
    # GORDIAN_BOMB_REACHED markers
    err = work_dir / "replay_stderr.txt"
    if err.exists():
        bombs = sorted(set(re.findall(r"GORDIAN_BOMB_REACHED (\S+)", err.read_text(errors="replace"))))
        if bombs:
            (work_dir / "bombs_reached.json").write_text(json.dumps(bombs, indent=2))
    return report


def parse_llvm_cov_export(data: dict, c: Container, target: Target, root: Path,
                          coverage_files: Optional[list[Path]] = None) -> CoverageReport:
    """Map llvm-cov segments to per-line covered/uncovered sets for the coverage files."""
    wanted = {}
    for f in (coverage_files or target.resolve_coverage_files(root)):
        wanted["replay_" + f.name] = f
        # a coverage file that is #included by another source (libexpat's xmltok_impl.c) is not copied
        # for replay: llvm-cov reports it under its original path in the original directory
        wanted[f.name] = f
    files_out: dict[str, FileCoverage] = {}
    for fdata in data.get("data", [{}])[0].get("files", []):
        fpath = Path(fdata["filename"])
        name = fpath.name
        if name not in wanted:
            continue
        orig = wanted[name]
        if not name.startswith("replay_") and c is not None and str(fpath.parent) != c.path(orig.parent):
            continue   # same base name, different directory
        fc = FileCoverage(str(orig.relative_to(root)) if orig.is_relative_to(root) else str(orig))
        line_counts = _line_counts(fdata.get("segments", []))
        src_lines = orig.read_text(errors="replace").splitlines()
        for ln, cnt in line_counts.items():
            if ln - 1 >= len(src_lines):
                continue
            txt = src_lines[ln - 1].strip()
            if not txt or txt in ("{", "}", "};") or txt.startswith(("//", "/*", "*", "#")):
                continue
            fc.text[ln] = txt
            (fc.covered if cnt > 0 else fc.uncovered).add(ln)
        fc.uncovered -= fc.covered
        files_out[fc.path] = fc
    missing = [str(v) for k, v in wanted.items() if not any(Path(x).name == v.name for x in files_out)]
    if missing:
        log.warning("llvm-cov produced no data for %s (not linked, or no coverable lines)", missing)
    return CoverageReport(files_out, 0)


def _line_counts(segs: list) -> dict[int, int]:
    """Per-line execution counts from llvm-cov segments, following llvm-cov's LineCoverageStats.

    Segments are [line, col, count, hasCount, isRegionEntry, isGapRegion]. A line's count is the max
    of the segment wrapped in from earlier lines and the region-entry segments starting on it; the
    non-entry segment that resumes the outer region after e.g. ``return BOMB_ENDING;`` is ignored,
    so a branch body that never ran is not marked covered by its enclosing region.
    """
    by_line: dict[int, list] = {}
    for seg in segs:
        by_line.setdefault(seg[0], []).append(seg)
    if not by_line:
        return {}

    def is_start(s) -> bool:
        return s[3] and s[4] and not (s[5] if len(s) > 5 else False)

    counts: dict[int, int] = {}
    wrapped = None
    for ln in range(min(by_line), max(by_line) + 1):
        here = by_line.get(ln, [])
        starts = [s for s in here if is_start(s)]
        skipped = bool(here) and not here[0][3] and here[0][4]
        mapped = (not skipped and ((wrapped is not None and wrapped[3]) or bool(starts))) \
            or any(s[3] and s[4] for s in here)
        if mapped:
            counts[ln] = max([wrapped[2] if wrapped is not None else 0] + [s[2] for s in starts])
        if here:
            wrapped = here[-1]
    return counts


def uncovered_lines_outside_main(report: CoverageReport, root: Path) -> dict[str, list[tuple[int, str]]]:
    """Uncovered coverable lines per file, excluding the body of main() (the harness)."""
    out = {}
    for path, fc in report.files.items():
        src = (root / path) if not Path(path).is_absolute() else Path(path)
        lines = src.read_text(errors="replace").splitlines()
        main_range = _main_range(lines)
        sel = [(ln, fc.text.get(ln, "")) for ln in sorted(fc.uncovered) if not (main_range and main_range[0] <= ln <= main_range[1])]
        out[path] = sel
    return out


def _main_range(lines: list[str]) -> Optional[tuple[int, int]]:
    start = None
    for i, l in enumerate(lines, 1):
        if re.match(r"^\s*int\s+main\s*\(", l):
            start = i
            break
    if start is None:
        return None
    depth = 0
    seen = False
    for j in range(start - 1, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if "{" in lines[j]:
            seen = True
        if seen and depth <= 0:
            return (start, j + 1)
    return (start, len(lines))


def static_all_uncovered(target: Target, root: Path) -> CoverageReport:
    """Fallback when the original program cannot be executed by KLEE at all (threads, forks,
    unsupported externals): every coverable-looking line of the coverage files counts as uncovered,
    so the ghost-code stages still get a target list."""
    files = {}
    for f in target.resolve_coverage_files(root):
        fc = FileCoverage(str(f.relative_to(root)) if f.is_relative_to(root) else str(f))
        for ln, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            txt = line.strip()
            if not txt or txt in ("{", "}", "};") or txt.startswith(("//", "/*", "*", "#")):
                continue
            if txt.endswith(";") or txt.endswith("{") or txt.startswith(("if", "else", "for", "while", "return", "switch", "case")):
                fc.text[ln] = txt
                fc.uncovered.add(ln)
        files[fc.path] = fc
    return CoverageReport(files, 0)
