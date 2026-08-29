"""Worst per-parameter relative deviation, matched by value rather than by name.

Shared by ``arena.py`` (which uses it to decide whether a sampled truth is recoverable at all)
and ``score.py`` (which uses it to score parameter accuracy), so the two cannot drift apart.

**Matching by value is not a refinement, it is the only thing that means anything here.** Parallel
blocks in series carry a permutation symmetry: swapping the labels of two blocks is the same
circuit, so comparing a recovered ``R1`` against a generating ``R1`` by name compares two things
that were never the same object. ``benchmarks/discovery_v2.py``'s three-block reference says so in
its own comment, and the deviation it records there is the value-matched one.
"""

from __future__ import annotations

import math


def worst_deviation(recovered: dict[str, float], generating: dict[str, float]) -> float:
    """Worst relative deviation over all parameters, or NaN if the two do not correspond.

    Both dictionaries are keyed ``"<label>.<param>"``. Parameters are grouped by element code and
    parameter name -- every ``R.R`` together, every ``CPE.n`` together -- and within each group
    matched greedily to the nearest value in log distance, which is the metric these quantities
    live on. A mismatch in the groups themselves returns NaN rather than a number, because a
    deviation between differently-shaped parameter sets is not a deviation.
    """

    def group(values: dict[str, float]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for name, value in values.items():
            label, _, param = name.partition(".")
            code = label.rstrip("0123456789")
            out.setdefault(f"{code}.{param}", []).append(value)
        return out

    got, want = group(recovered), group(generating)
    if set(got) != set(want) or any(len(got[k]) != len(want[k]) for k in got):
        return math.nan

    def log_distance(value: float, target: float) -> float:
        return abs(math.log(abs(value) + 1e-300) - math.log(abs(target) + 1e-300))

    worst = 0.0
    for key, targets in want.items():
        pool = list(got[key])
        for target in sorted(targets):
            if not pool:
                return math.nan
            best = min(pool, key=lambda value: log_distance(value, target))
            pool.remove(best)
            if target != 0.0:
                worst = max(worst, abs(best - target) / abs(target))
    return worst
