"""Compile to LLVM bitcode and run KLEE inside a container, with a wall-clock
budget and a *soft kill*: KLEE gets ``--max-time`` equal to the budget and is
additionally sent SIGINT shortly after the budget (KLEE then halts, dumps the
states it was still exploring as test cases, and exits), followed by SIGKILL
if it does not stop.
"""
from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .docker import Container
from .targets import Target
from .log import get_logger

log = get_logger(__name__)


@dataclass
class BuildResult:
    bitcode: Path                 # host path of the linked module
    objects: list[Path]
    log: str
    ok: bool


@dataclass
class KleeRun:
    out_dir: Path                 # host path of the klee output directory
    ktests: list[Path]
    seconds: float
    returncode: int
    killed: bool
    errors: list[Path] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    log_tail: str = ""
    warnings: list[str] = field(default_factory=list)   # concretization / external-call / error lines


def _ensure_klee_include(src: Path) -> None:
    """Prepend ``#include <klee/klee.h>`` to a file that uses klee_* without it."""
    text = src.read_text(errors="replace")
    if "klee_" in text and "klee/klee.h" not in text:
        src.write_text("#include <klee/klee.h>\n" + text)


def compile_bitcode(c: Container, target: Target, root: Path, build_dir: Path, *,
                    sources: Optional[list[Path]] = None, harness: Optional[Path] = None,
                    extra_flags: Optional[list[str]] = None) -> BuildResult:
    """Compile every source (+ harness) to bitcode and llvm-link them into ``build_dir/module.bc``."""
    tools = c.tools
    build_dir.mkdir(parents=True, exist_ok=True)
    srcs = list(sources) if sources is not None else target.resolve_sources(root)
    h = harness if harness is not None else target.harness_path(root)
    if h is not None:
        srcs = srcs + [h]
    flags = ["-O0", "-g", "-emit-llvm", "-c", "-Wno-everything", "-I" + tools.klee_include]
    flags += target.clang_flags(root, c.path)
    flags += extra_flags or []
    objs, logs, ok = [], [], True
    cmds = []
    for s in srcs:
        if s.suffix in (".bc", ".ll"):
            objs.append(s)
            continue
        _ensure_klee_include(s)
        obj = build_dir / (s.stem + ".bc")
        objs.append(obj)
        cmds.append(f"{tools.clang} {' '.join(shlex.quote(f) for f in flags)} {shlex.quote(c.path(s))} -o {shlex.quote(c.path(obj))}")
    # Compile with a single docker exec (much faster for multi-file targets).
    script = "set -e\n" + "\n".join(cmds)
    r = c.exec(script, timeout=900)
    logs.append(r.stdout + r.stderr)
    if r.returncode != 0:
        ok = False
    module = build_dir / "module.bc"
    if ok:
        if len(objs) == 1:
            r = c.exec(f"cp {shlex.quote(c.path(objs[0]))} {shlex.quote(c.path(module))}", timeout=60)
        else:
            r = c.exec(f"{tools.llvm_link} {' '.join(shlex.quote(c.path(o)) for o in objs)} -o {shlex.quote(c.path(module))}", timeout=300)
        logs.append(r.stdout + r.stderr)
        ok = r.returncode == 0
    (build_dir / "build.log").write_text("\n".join(logs))
    if not ok:
        log.error("bitcode build failed for %s: %s", target.name, "\n".join(logs)[-1500:])
    return BuildResult(bitcode=module, objects=objs, log="\n".join(logs), ok=ok)


def klee_command(c: Container, target: Target, bitcode_in_container: str, out_dir_in_container: str, *,
                 budget_s: int, solver_timeout_s: int, search: str = "bfs", extra: Optional[list[str]] = None,
                 only_new: bool = False) -> list[str]:
    t = c.tools
    cmd = [t.klee, f"--output-dir={out_dir_in_container}", f"--max-time={int(budget_s)}",
           f"--max-solver-time={int(solver_timeout_s)}", "--solver-backend=z3", f"--search={search}",
           "--emit-all-errors", "--write-cov", "--watchdog"]
    if target.libc and target.libc != "none":
        cmd.append(f"--libc={target.libc}")
    if target.posix_runtime:
        cmd.append("--posix-runtime")
    if t.is_float:
        cmd.append("--allow-external-sym-calls")   # KLEE-Float spelling
    else:
        cmd.append(f"--external-calls={target.external_calls}")
    cmd += target.klee_args
    cmd += extra or []
    if only_new and "--only-output-states-covering-new" not in cmd:
        cmd.append("--only-output-states-covering-new")   # KLEE rejects the flag twice
    cmd.append(bitcode_in_container)
    return cmd


def run_klee(c: Container, target: Target, bitcode: Path, out_dir: Path, *, budget_s: int, solver_timeout_s: int,
             search: str = "bfs", extra: Optional[list[str]] = None, grace_s: int = 20, only_new: bool = False) -> KleeRun:
    """Run KLEE with a hard wall-clock budget and soft kill, return the ktests."""
    if out_dir.exists():
        c.exec(f"rm -rf {shlex.quote(c.path(out_dir))}", timeout=60)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = klee_command(c, target, c.path(bitcode), c.path(out_dir), budget_s=budget_s, search=search,
                       solver_timeout_s=solver_timeout_s, extra=extra, only_new=only_new)
    # timeout(1): send SIGINT at budget+grace/2, SIGKILL grace/2 later.  KLEE's own --max-time
    # normally ends the run first; the external timeout is the safety net.
    shell = (f"timeout -s INT -k {grace_s // 2 + 5} {int(budget_s) + grace_s // 2} "
             + " ".join(shlex.quote(a) for a in cmd))
    log.info("klee[%s] budget=%ds solver=%ds -> %s", target.name, budget_s, solver_timeout_s, out_dir.name)
    t0 = time.time()
    r = c.exec(shell, cwd=c.path(out_dir.parent), timeout=budget_s + grace_s + 60)
    secs = time.time() - t0
    killed = r.returncode in (124, 137, 130) or secs >= budget_s + grace_s // 2
    (out_dir.parent / (out_dir.name + ".klee.log")).write_text(
        f"$ {shell}\n\n[stdout]\n{r.stdout}\n\n[stderr]\n{r.stderr}\n\nrc={r.returncode} seconds={secs:.1f}\n")
    ktests = sorted(out_dir.glob("*.ktest")) if out_dir.exists() else []
    errors = sorted(out_dir.glob("*.err")) if out_dir.exists() else []
    stats = _parse_info(out_dir / "info") if (out_dir / "info").exists() else {}
    log.info("klee[%s] done: %d ktests, %d errors, %.0fs, rc=%d%s", target.name, len(ktests), len(errors), secs,
             r.returncode, " (killed)" if killed else "")
    if not ktests and r.returncode not in (0, 124, 130, 137):
        log.error("klee produced no tests; stderr tail: %s", r.stderr[-1500:])
    warn = []
    for line in r.stderr.splitlines():
        if re.search(r"silently concretizing|calling external|KLEE: ERROR|undefined reference to function|Cannot handle|terminating|max-memory", line):
            line = re.sub(r"^KLEE: (WARNING( ONCE)?: )?", "", line.strip())
            if line not in warn:
                warn.append(line)
    (out_dir.parent / (out_dir.name + ".warnings.txt")).write_text("\n".join(warn[:200]) + "\n")
    return KleeRun(out_dir=out_dir, ktests=ktests, seconds=secs, returncode=r.returncode, killed=killed,
                   errors=errors, stats=stats, log_tail=r.stderr[-3000:], warnings=warn[:200])


def _parse_info(path: Path) -> dict:
    out = {}
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(r"KLEE: done: (.+?) = (\d+)", line)
        if m:
            out[m.group(1).replace(" ", "_")] = int(m.group(2))
    return out


def ktest_objects(c: Container, ktest: Path) -> list[dict]:
    """Decode a ktest into [{name, size, bytes(hex)}] with ktest-tool (or the pure-python reader)."""
    from .ktest import read_ktest
    return read_ktest(ktest)
