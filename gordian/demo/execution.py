"""Explicit filesystem/container boundary for KLEE and original-code replay."""
from __future__ import annotations

import json
import struct
from collections.abc import Callable
from pathlib import Path

from ..docker import Container
from ..klee import compile_bitcode, run_klee
from ..ktest import read_ktest, write_ktest
from ..targets import Target
from .example import input_value, replay_outcome
from .fdlibm import compile_flags, source_paths


def require_prepared_container(container: Container) -> None:
    """Check the existing mount and probe tools without starting/pulling containers."""
    if not container.running() or not container.mount_ok():
        raise RuntimeError(
            f"{container.spec.name} must already be running with this repository mounted "
            f"at {container.settings.mount_path}; the demo never starts or pulls containers")
    container.probe(force=True)


def prepare_variant(directory: Path, driver: str, guard: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "driver.c").write_text(driver)
    (directory / "guard.inc").write_text(guard)
    return directory / "driver.c"


def variant_target(root: Path, driver: Path, library: Path) -> Target:
    relative = str(driver.relative_to(root))
    sources = [relative] + [str(path.relative_to(root)) for path in source_paths(library)]
    return Target(name="demo_trig", sources=sources, coverage_files=[relative],
                  include_dirs=[str(library.relative_to(root))],
                  family="demo", libc="none", posix_runtime=False, external_calls="none",
                  cflags=compile_flags())


def explore_variant(container: Container, root: Path, driver: Path, directory: Path,
                    library: Path, budget_s: int, solver_timeout_s: int,
                    emit: Callable[[str], None]) -> dict:
    target = variant_target(root, driver, library)
    build = compile_bitcode(container, target, root, directory / "build")
    if not build.ok:
        raise RuntimeError(f"bitcode compilation failed; see {directory / 'build/build.log'}")
    result = run_klee(container, target, build.bitcode, directory / "klee",
                      budget_s=budget_s, solver_timeout_s=solver_timeout_s,
                      search="bfs", only_new=False)
    emit("KLEE DIAGNOSTICS\n" + ("\n".join(result.warnings) or "No captured warnings."))
    emit(f"KLEE: {len(result.ktests)} tests, {len(result.errors)} errors, "
         f"{result.seconds:.1f}s, exit={result.returncode}")
    if result.returncode not in (0, 124, 130, 137):
        raise RuntimeError(f"KLEE failed with exit {result.returncode}; "
                           f"inspect {directory / 'klee.klee.log'}")
    if not result.ktests:
        raise RuntimeError(f"KLEE produced no tests; inspect {directory / 'klee.klee.log'}")
    return dict(ktests=result.ktests, diagnostics="\n".join(result.warnings),
                seconds=result.seconds, returncode=result.returncode,
                errors=[str(path) for path in result.errors], stats=result.stats)


def build_original_replay(container: Container, driver: Path, directory: Path, library: Path) -> Path:
    """Compile the fixed original driver/guard, without Gordian's assertion softening."""
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "original-replay"
    tools = container.tools
    command = [tools.clang, *compile_flags(), "-O0", "-DDEMO_REPLAY",
               "-I" + tools.klee_include, "-I" + container.path(library),
               container.path(driver), *[container.path(path) for path in source_paths(library)],
               "-L" + tools.klee_runtest_lib, "-Wl,-rpath," + tools.klee_runtest_lib,
               "-lkleeRuntest", "-o", container.path(executable)]
    result = container.exec(command, timeout=60)
    (directory / "build.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"native replay build failed; see {directory / 'build.log'}")
    return executable


def replay_test(container: Container, executable: Path, ktest: Path,
                directory: Path, timeout_s: int) -> dict:
    """Treat only a successful native observation of the original guard as evidence."""
    objects = read_ktest(ktest)
    value = input_value(objects)
    normalized = directory / ktest.name
    write_ktest(normalized, [obj for obj in objects if obj["name"] == "a0"])
    command = ["timeout", str(timeout_s), "env", "KTEST_FILE=" + container.path(normalized),
               container.path(executable)]
    result = container.exec(command, cwd=container.path(directory), timeout=timeout_s + 5)
    (directory / (ktest.stem + ".log")).write_text(
        result.stdout + result.stderr + f"\nexit={result.returncode}\n")
    if result.returncode:
        raise ValueError(f"native replay failed with exit {result.returncode}")
    outcome = replay_outcome(result.stdout, value)
    return dict(test=str(ktest), replay_test=str(normalized), x=value,
                input_hex=input_bytes(objects).hex(), outcome=outcome)


def input_bytes(objects: list[dict]) -> bytes:
    return next(obj["bytes"] for obj in objects if obj["name"] == "a0")


def replay_tests(container: Container, executable: Path, ktests: list[Path],
                 directory: Path, timeout_s: int, max_tests: int,
                 emit: Callable[[str], None]) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    observations = []
    for path in ktests[:max_tests]:
        try:
            row = replay_test(container, executable, path, directory, timeout_s)
            emit(f"ORIGINAL REPLAY: x={row['x']:.17g} -> outcome {row['outcome']}")
        except (ValueError, OSError, struct.error) as exc:
            row = dict(test=str(path), error=str(exc))
            emit(f"REPLAY REJECTED: {path.name}: {exc}")
        observations.append(row)
    (directory / "observations.json").write_text(json.dumps(
        dict(generated=len(ktests), replayed=len(observations),
             omitted=max(0, len(ktests) - max_tests), observations=observations), indent=2))
    if len(ktests) > max_tests:
        emit(f"Replay cap: checked {max_tests} of {len(ktests)} tests; others were retained.")
    return observations
