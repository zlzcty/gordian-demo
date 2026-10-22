"""Stage 0: exploratory KLEE run on the unmodified program.

Short budget, solver timeout reduced by 90 %: the goal is to
learn which lines are easy, and which remain uncovered and therefore are
candidates for ghost code.
"""
from __future__ import annotations

import json

from .common import Context, group_uncovered, rank_regions
from ..log import get_logger

log = get_logger(__name__)


def run(ctx: Context, budget_s: float) -> dict:
    solver = ctx.settings.explore_solver_timeout_s
    ktests, rep = ctx.run_variant("00_explore", budget_s=budget_s, solver_timeout_s=solver)
    unc = ctx.uncovered()
    summary = {}
    for path, lines in unc.items():
        regions = rank_regions(group_uncovered(lines), {ln for ln, _ in lines})
        summary[path] = dict(uncovered=len(lines), regions=regions[:50])
    (ctx.run_dir / "explore.json").write_text(json.dumps(dict(ktests=len(ktests), uncovered=summary), indent=2))
    return summary
