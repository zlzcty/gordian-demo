#!/usr/bin/env python3
"""Summarise <runs_dir>/*/report.json into <out_dir>/SUMMARY.md and <out_dir>/summary.json.

    python scripts/summarise_results.py [out_dir] [--runs runs_dir]    (defaults: runs/summary, runs/)

Tables: LogicBombs (bombs triggered / critical paths per backend), FDLibM and structured-input
line coverage per target and backend, LLM token usage.  Only batch runs are counted (names
starting with abl_/e2e_/test_/explore_ are ablations or smoke tests and are skipped).
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
SKIP = ("abl_", "e2e_", "test_", "explore_")


def bomb_status(run_dir: Path) -> tuple[bool, bool]:
    st = run_dir / "state.json"
    if not st.exists():
        return False, False
    cov = (json.loads(st.read_text()).get("coverage") or {}).get("files") or {}
    for path, f in cov.items():
        src = Path(path) if Path(path).is_absolute() else ROOT / path
        if not src.exists() or "logic_bombs" not in str(src):
            continue
        covered = set(f["covered"])
        bomb_lines, benign_lines = bomb_and_benign_lines(src.read_text(errors="replace").splitlines())
        return bool(bomb_lines & covered), bool(benign_lines & covered)
    return False, False


def bomb_and_benign_lines(lines: list[str]) -> tuple[set[int], set[int]]:
    """Same rule as gordian.cli: named endings, else plain ``return 1`` / ``return 0`` (file_posix_cp_l1)."""
    bomb = {i for i, l in enumerate(lines, 1) if ("BOMB_ENDING" in l and "return" in l and "#define" not in l) or "klee_assert(0" in l}
    benign = {i for i, l in enumerate(lines, 1) if "NORMAL_ENDING" in l and "return" in l and "#define" not in l}
    if not bomb and not benign:
        bomb = {i for i, l in enumerate(lines, 1) if re.match(r"\s*return\s+1\s*;", l)}
        benign = {i for i, l in enumerate(lines, 1) if re.match(r"\s*return\s+0\s*;", l)}
    return bomb, benign


def main(out_dir: Path, runs: Path = RUNS):
    if not runs.is_dir():
        sys.exit(f"no runs directory {runs}")
    bombs = defaultdict(dict); fd = defaultdict(dict); st = defaultdict(dict); usage = defaultdict(lambda: [0, 0, 0])
    for rp in sorted(runs.glob("*/report.json")):
        rd = rp.parent
        if rd.name.startswith(SKIP):
            continue
        r = json.loads(rp.read_text()); b = r.get("backend", "?"); t = r.get("target", "?"); c = r.get("coverage", {})
        u = r.get("llm_usage") or {}
        usage[b][0] += u.get("input_tokens", 0); usage[b][1] += u.get("output_tokens", 0); usage[b][2] += 1
        if t.startswith("lb_"):
            bombs[b][t] = bomb_status(rd) + (c.get("covered"), c.get("total"))
        elif t.startswith("fdlibm_"):
            fd[b][t] = (c.get("covered"), c.get("total"))
        else:
            st[b][t] = (c.get("covered"), c.get("total"))
    lines = ["# Gordian results (this artifact's runs)", "",
             "Budgets: 600 s per logic bomb, 900 s per FDLibM function, 1500 s per structured-input target; "
             "all three ghost-code stages (partition -> surrogate model -> inversion); every test case replayed on the "
             "original program.", "",
             "## LogicBombs: bombs triggered and critical paths (max 53 bombs / 106 paths)", "",
             "| backend | bombs run | triggered | critical paths | not triggered |", "|---|---|---|---|---|"]
    for b, d in sorted(bombs.items()):
        trig = sum(1 for v in d.values() if v[0]); cps = sum(int(v[0]) + int(v[1]) for v in d.values())
        miss = ", ".join(sorted(k[3:] for k, v in d.items() if not v[0]))
        lines.append(f"| {b} | {len(d)} | {trig} | {cps} / {2 * len(d)} | {miss} |")
    for title, data in (("FDLibM line coverage", fd), ("Structured-input line coverage", st)):
        backends = sorted(data)
        targets = sorted({t for d in data.values() for t in d})
        if not targets:
            continue
        lines += ["", f"## {title}", "", "| target | " + " | ".join(backends) + " |", "|---|" + "---|" * len(backends)]
        for t in targets:
            cells = []
            for b in backends:
                v = data[b].get(t)
                cells.append(f"{v[0]}/{v[1]} ({100 * v[0] / v[1]:.0f}%)" if v and v[1] else "-")
            lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines += ["", "## LLM usage (sum over runs; agent backends count cached context reads as input)", "",
              "| backend | runs | input tokens | output tokens |", "|---|---|---|---|"]
    for b, (i, o, n) in sorted(usage.items()):
        lines.append(f"| {b} | {n} | {i:,} | {o:,} |")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    (out_dir / "summary.json").write_text(json.dumps({"bombs": bombs, "fdlibm": fd, "structured": st, "usage": usage}, indent=1, default=str))
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="summarise Gordian runs")
    ap.add_argument("out_dir", nargs="?", type=Path, default=None, help="where SUMMARY.md / summary.json go (default: <runs>/summary)")
    ap.add_argument("--runs", type=Path, default=RUNS, help="directory holding one sub-directory per run (default: runs/)")
    a = ap.parse_args()
    main(a.out_dir or a.runs / "summary", a.runs)
