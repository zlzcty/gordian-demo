"""Independent demo stages: orchestration over target, model and execution boundaries."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from .example import source_diff
from .execution import (build_original_replay, explore_variant, prepare_variant,
                        replay_tests, require_prepared_container)
from .model import request_rewrite
from .target import build_prompt, load_target, parse_surrogate, snapshot_target, witnesses
from .workflow import save_report


def seal_snapshot(directory: Path) -> None:
    files = [directory / "target.json", *sorted((directory / "original").glob("*")),
             *sorted((directory / "library").glob("*"))]
    hashes = {str(file.relative_to(directory)): hashlib.sha256(file.read_bytes()).hexdigest()
              for file in files if file.is_file()}
    (directory / "snapshot.json").write_text(json.dumps(hashes, indent=2))


def verify_snapshot(directory: Path) -> None:
    hashes = json.loads((directory / "snapshot.json").read_text())
    for name, expected in hashes.items():
        file = directory / name
        file.resolve().relative_to(directory.resolve())
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError(f"original snapshot changed: {name}")


def inherit_snapshot(source: Path, directory: Path) -> dict:
    verify_snapshot(source)
    for name in ("original", "library"):
        shutil.copytree(source / name, directory / name)
    for name in ("target.json", "snapshot.json"):
        shutil.copyfile(source / name, directory / name)
    return load_target(directory / "target.json")


def read_stage(source: Path, expected: str) -> dict:
    report = json.loads((source / "result.json").read_text())
    statuses = {"baseline": ("baseline_missing", "baseline_already_succeeds"), "generate": ("generated",)}
    if report.get("stage") != expected or report.get("status") not in statuses[expected]:
        raise ValueError(f"--from-run must be a completed {expected} stage")
    return report


def observe(container, root: Path, directory: Path, driver: Path, target: dict,
            options: dict, emit) -> dict:
    executable = build_original_replay(container, directory / "original/driver.c",
                                       directory / "native", directory / "library")
    exploration = explore_variant(container, root, driver, directory / "exploration",
                                  directory / "library", options["klee_seconds"],
                                  options["solver_seconds"], emit)
    observations = replay_tests(container, executable, exploration["ktests"], directory / "replay",
                                options["replay_seconds"], options["max_tests"], emit, target)
    evidence = witnesses(observations, target["outcomes"])
    if not evidence:
        raise RuntimeError("no valid original-code replay observations")
    return dict(exploration=exploration, observations=observations, witnesses=evidence)


def show_original(directory: Path, emit) -> None:
    emit("ORIGINAL GUARD\n" + (directory / "original/guard.inc").read_text())


def generation_prompt(directory: Path, target: dict, previous: dict) -> str:
    original = (directory / "original/guard.inc").read_text()
    diagnostics = previous["baseline"]["exploration"]["diagnostics"]
    return build_prompt(target, original, diagnostics, previous["missing"])


def baseline_stage(container, root, directory, target_path, options, emit) -> dict:
    require_prepared_container(container)
    target = snapshot_target(target_path, directory)
    seal_snapshot(directory)
    show_original(directory, emit)
    evidence = observe(container, root, directory, directory / "original/driver.c", target, options, emit)
    missing = [value for value in target["outcomes"] if str(value) not in evidence["witnesses"]]
    emit(f"Missing outcomes: {missing}")
    return dict(status="baseline_missing" if missing else "baseline_already_succeeds",
                baseline=evidence, missing=missing)


def write_surrogate(directory, target, response, emit) -> str:
    guard, notes = parse_surrogate(response, target)
    prepare_variant(directory / "surrogate", (directory / "original/driver.c").read_text(), guard)
    (directory / "surrogate/notes.md").write_text(notes)
    diff = source_diff((directory / "original/guard.inc").read_text(), guard)
    (directory / "surrogate.patch").write_text(diff)
    emit("GENERATED CODE DIFF\n" + diff)
    return hashlib.sha256(guard.encode()).hexdigest()


def generate_stage(directory, source, options, client, emit) -> dict:
    previous = read_stage(source, "baseline")
    target = inherit_snapshot(source, directory)
    prompt = generation_prompt(directory, target, previous)
    response, usage = request_rewrite(client, options["model"], prompt, directory / "llm", emit)
    guard_hash = write_surrogate(directory, target, response, emit)
    return dict(status="generated", baseline=previous["baseline"], missing=previous["missing"],
                llm_usage=usage, guard_sha256=guard_hash)


def copy_surrogate(source: Path, directory: Path, previous: dict) -> Path:
    guard = (source / "surrogate/guard.inc").read_text()
    if hashlib.sha256(guard.encode()).hexdigest() != previous["guard_sha256"]:
        raise ValueError("generated guard changed; use a new generation stage")
    driver = (directory / "original/driver.c").read_text()
    return prepare_variant(directory / "surrogate", driver, guard)


def assisted_stage(container, root, directory, source, options, emit) -> dict:
    previous = read_stage(source, "generate")
    target = inherit_snapshot(source, directory)
    driver = copy_surrogate(source, directory, previous)
    require_prepared_container(container)
    evidence = observe(container, root, directory, driver, target, options, emit)
    complete = all(str(outcome) in evidence["witnesses"] for outcome in target["outcomes"])
    added = sorted(set(evidence["witnesses"]) - set(previous["baseline"]["witnesses"]))
    emit("SUCCESS" if complete else "INCOMPLETE")
    return dict(status="success" if complete else "incomplete", assisted=evidence,
                baseline=previous["baseline"], added_outcomes=added)


def execute_stage(stage, container, root, directory, source, target_path, options, client, emit) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    report = dict(stage=stage, status="running", options=options, source_run=str(source) if source else None)
    started = time.monotonic()
    save_report(directory, report)
    try:
        report.update(dispatch_stage(stage, container, root, directory, source, target_path, options, client, emit))
        return report
    except KeyboardInterrupt:
        report.update(status="interrupted")
        raise
    except Exception as exc:
        report.update(status="error", error=str(exc))
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        save_report(directory, report)
        emit(f"Artifacts retained in {directory}")


def dispatch_stage(stage, container, root, directory, source, target_path, options, client, emit) -> dict:
    if stage == "baseline":
        return baseline_stage(container, root, directory, target_path, options, emit)
    if stage == "generate":
        return generate_stage(directory, source, options, client, emit)
    return assisted_stage(container, root, directory, source, options, emit)
