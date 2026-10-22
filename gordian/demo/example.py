"""Pure transformations for the reduced trigonometric example."""
from __future__ import annotations

import difflib
import math
import re
import struct

from ..llm.base import parse_file_blocks


def surrogate_from_response(response: str) -> tuple[str, str]:
    """Accept only the two requested artifacts; never use model-supplied paths."""
    files = parse_file_blocks(response)
    if set(files) != {"guard.inc", "notes.md"}:
        raise ValueError("model must return exactly guard.inc and notes.md file blocks")
    guard = files["guard.inc"]
    if not re.search(r"\btrig_branch\s*\(\s*double\s+\w+\s*\)", guard):
        raise ValueError("surrogate must define trig_branch(double)")
    if re.search(r"\b(main|klee_make_symbolic|klee_range)\s*\(", guard):
        raise ValueError("surrogate cannot replace main or add symbolic inputs")
    return guard, files["notes.md"]


def source_diff(original: str, surrogate: str) -> str:
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True), surrogate.splitlines(keepends=True),
        fromfile="original/guard.inc", tofile="surrogate/guard.inc"))


def input_value(objects: list[dict]) -> float:
    """Require the original one-double interface, ignoring KLEE runtime metadata."""
    inputs = [obj for obj in objects if obj["name"] != "model_version"]
    if len(inputs) != 1 or inputs[0]["name"] != "a0" or len(inputs[0]["bytes"]) != 8:
        raise ValueError("test does not have the original eight-byte a0 input")
    value, = struct.unpack("<d", inputs[0]["bytes"])
    if not math.isfinite(value) or not 2 <= value <= 6:
        raise ValueError("test input is outside [2, 6]")
    return value


def replay_outcome(stdout: str, expected: float) -> int:
    matches = re.findall(r"^GORDIAN_TRIG x=(\S+) outcome=([012])$", stdout, re.M)
    if len(matches) != 1:
        raise ValueError("replay did not emit exactly one branch observation")
    value, outcome = matches[0]
    if float(value) != expected or int(outcome) not in (1, 2):
        raise ValueError("replay input or branch observation is invalid")
    return int(outcome)


def branch_witnesses(observations: list[dict]) -> dict[str, dict]:
    """Choose one successful original-code replay per outcome."""
    return {str(outcome): next(row for row in observations if row.get("outcome") == outcome)
            for outcome in (1, 2) if any(row.get("outcome") == outcome for row in observations)}


def comparison(baseline: list[dict], assisted: list[dict]) -> dict:
    before, after = branch_witnesses(baseline), branch_witnesses(assisted)
    combined = {**before, **after}
    status = ("baseline_already_succeeds" if len(before) == 2 else
              "improved" if len(combined) == 2 else "incomplete")
    return dict(status=status, baseline_witnesses=before, assisted_witnesses=after,
                combined_witnesses=combined)
