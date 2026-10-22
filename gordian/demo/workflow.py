"""The single-example sequence, with explicit dependencies and saved evidence."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from .example import branch_witnesses, comparison, source_diff, surrogate_from_response
from .execution import (build_original_replay, explore_variant, prepare_variant,
                        replay_tests, require_prepared_container)
from .model import request_rewrite, rewrite_prompt


def save_report(directory: Path, report: dict) -> None:
    (directory / "result.json").write_text(json.dumps(report, indent=2, default=str))


def show_step(title: str, emit: Callable[[str], None],
              pause: Callable[[str], None] | None) -> None:
    emit("\n" + title)
    if pause is not None:
        pause("Press Enter to continue: ")


def observe_variant(container, root: Path, driver: Path, directory: Path,
                    executable: Path, options: dict, emit: Callable[[str], None]) -> dict:
    exploration = explore_variant(container, root, driver, directory,
                                  options["klee_seconds"], options["solver_seconds"], emit)
    observations = replay_tests(container, executable, exploration["ktests"],
                                directory / "replay", options["replay_seconds"],
                                options["max_tests"], emit)
    return {**exploration, "observations": observations}


def assist(container, root: Path, directory: Path, driver: str, guard: str,
           executable: Path, baseline: dict, options: dict, client,
           emit: Callable[[str], None], pause: Callable[[str], None] | None) -> tuple[dict, dict]:
    missing = [outcome for outcome in (1, 2)
               if str(outcome) not in branch_witnesses(baseline["observations"])]
    show_step(f"2/5 Gordian diagnosis: original replay is missing outcomes {missing}", emit, pause)
    prompt = rewrite_prompt(guard, baseline["diagnostics"], missing)
    emit("This focused demo requests one surrogate for this known guard; it does not run general triage.")
    emit(f"Exact request will be saved to {directory / 'llm/prompt.md'}")
    show_step("3/5 Request one LLM surrogate", emit, None)
    response, usage = request_rewrite(client, options["model"], prompt, directory / "llm", emit)
    surrogate, notes = surrogate_from_response(response)
    generated_driver = prepare_variant(directory / "surrogate", driver, surrogate)
    (directory / "surrogate/notes.md").write_text(notes)
    diff = source_diff(guard, surrogate)
    (directory / "surrogate.patch").write_text(diff)
    emit("GENERATED CODE DIFF\n" + diff)
    emit("MODEL EXPLANATION\n" + notes)
    show_step("4/5 KLEE on the surrogate; replay candidates on the ORIGINAL guard", emit, pause)
    assisted = observe_variant(container, root, generated_driver, directory / "assisted",
                               executable, options, emit)
    return assisted, usage


def run_demo(container, root: Path, directory: Path, driver: str, guard: str,
             options: dict, client, emit: Callable[[str], None],
             pause: Callable[[str], None] | None = None) -> dict:
    """Never overwrite a run; preserve partial evidence if any step fails."""
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(status="running", options=options, scope="reduced guard with external libm")
    save_report(directory, report)
    try:
        require_prepared_container(container)
        report["klee_version"] = container.tools.klee_version
        original_driver = prepare_variant(directory / "original", driver, guard)
        executable = build_original_replay(container, original_driver, directory / "native")
        show_step("1/5 Baseline KLEE on the original reduced guard", emit, pause)
        emit("ORIGINAL GUARD\n" + guard)
        report["baseline"] = observe_variant(container, root, original_driver,
                                             directory / "baseline", executable, options, emit)
        baseline = report["baseline"]["observations"]
        report.update(comparison(baseline, []))
        save_report(directory, report)
        if report["status"] == "baseline_already_succeeds":
            emit("Baseline already covers both outcomes. No LLM call is needed; this run does not show improvement.")
        elif options["baseline_only"]:
            report["status"] = "baseline_only"
        else:
            report["assisted"], report["llm_usage"] = assist(
                container, root, directory, driver, guard, executable,
                report["baseline"], options, client, emit, pause)
            report.update(comparison(baseline, report["assisted"]["observations"]))
        show_step("5/5 Original-code evidence", emit, None)
        emit(json.dumps({key: report[key] for key in (
            "status", "baseline_witnesses", "assisted_witnesses", "combined_witnesses")}, indent=2))
        return report
    except Exception as exc:
        report.update(status="error", error=str(exc))
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        save_report(directory, report)
        emit(f"Artifacts retained in {directory}")
