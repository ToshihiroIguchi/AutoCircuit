"""Shared measurement instruments for the non-hardware speedup experiments, reused rather than
re-implemented from ``benchmarks/screening_round/param_opt.py`` (:class:`Counted`, Wilson CI),
``benchmarks/autoeis_round/score.py`` (McNemar exact), and ``benchmarks/ev5_fingerprint.py`` /
``benchmarks/o1_objective.py`` (``_stable`` byte-identical fingerprinting).

Every idea in ``docs/SEARCH_SPEEDUP_PLAN.md`` uses one of these three kinds of verdict:

* **NFE comparison** (:class:`Counted` + :func:`wilson`) -- does a change reach the same basin in
  fewer cost-function evaluations, with a confidence interval around the hit rate.
* **byte-identical fingerprint** (:func:`stable`, :func:`fingerprint`) -- for a change that must
  not alter any reported number (memoization, dedup): the JSON payload before and after must
  match exactly once clocks are stripped.
* **paired hit-rate significance** (:func:`mcnemar_exact`) -- for a change with a real trade-off
  (budget reallocation, early stopping): the two arms' hit/miss pairs on the same seeds are
  compared with the exact two-sided McNemar test, never a bare difference in percentages.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from autocircuit.core.fit import _Problem

Float = np.ndarray


class Counted:
    """Wraps a ``_Problem`` and counts individual cost evaluations, however they arrive.

    Identical to ``benchmarks/screening_round/param_opt.py``'s class of the same name; kept here
    verbatim so every idea's NFE count is comparable against that round's own numbers.
    """

    def __init__(self, problem: _Problem) -> None:
        self.p = problem
        self.n = 0

    def scalar(self, x: Float) -> float:
        self.n += 1
        return self.p.cost(x)

    def batch(self, xs: Float) -> Float:
        self.n += xs.shape[1]
        return self.p.cost_vectorized(xs)


def wilson(ok: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a hit rate ``ok / total``.

    ``z=1.959964`` is the two-sided 95% normal quantile, matching
    ``benchmarks/screening_round/param_opt.py:_wilson``.
    """
    if total == 0:
        return 0.0, 1.0
    p = ok / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - spread) / denom, (centre + spread) / denom


def wilson_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True iff the two Wilson intervals overlap.

    That is "not significant" under this repo's convention.
    """
    return a[0] <= b[1] and b[0] <= a[1]


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts.

    Identical to ``benchmarks/autoeis_round/score.py:mcnemar_exact``.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2.0**n)
    return min(1.0, 2.0 * tail)


#: Keys whose value is a measurement of this machine rather than of the answer.
VOLATILE = frozenset({"elapsed_s", "duration_s", "seconds", "n"})


def stable(value: Any) -> Any:
    """The report with every clock removed and every float in a lossless, sortable form.

    Identical convention to ``benchmarks/ev5_fingerprint.py:_stable`` /
    ``benchmarks/o1_objective.py:_stable``: floats become ``repr()`` (lossless, sortable text),
    dict keys are sorted, and ``VOLATILE`` keys are dropped so wall-clock noise never shows up
    as a "the result changed" false positive.
    """
    if isinstance(value, dict):
        return {k: stable(v) for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, (list, tuple)):
        return [stable(v) for v in value]
    if isinstance(value, float):
        return repr(value)
    return value


def fingerprint(value: Any) -> str:
    """A single deterministic string for :func:`stable`'s output, for a quick equality check."""
    import json

    return json.dumps(stable(value), sort_keys=True)


def nfe_to_basin(
    counted: Counted,
    x_final: Float,
    best_known_cost: float,
    *,
    basin_factor: float = 1.1,
) -> int | None:
    """``counted.n`` if the run's final cost is within ``basin_factor`` of the best known cost
    across all compared arms on this case, else ``None`` (missed the basin -- an NFE count from a
    miss is not comparable to one from a hit, exactly the distinction
    ``benchmarks/screening_round/param_opt.py``'s module docstring insists on).
    """
    final_cost = float(counted.p.cost(x_final))
    if final_cost <= best_known_cost * basin_factor:
        return counted.n
    return None


def summarize_hits(hits: Sequence[int | None], *, label: str) -> str:
    """One printable line: hit rate, Wilson CI, median/mean NFE among hits."""
    n = len(hits)
    ok_values = [h for h in hits if h is not None]
    lo, hi = wilson(len(ok_values), n)
    if ok_values:
        median_nfe = float(np.median(ok_values))
        mean_nfe = float(np.mean(ok_values))
        nfe_text = f"median NFE {median_nfe:.0f}, mean NFE {mean_nfe:.0f}"
    else:
        nfe_text = "no hits"
    return (
        f"{label}: {len(ok_values)}/{n} in basin "
        f"(95% CI [{lo * 100:.1f}%, {hi * 100:.1f}%]), {nfe_text}"
    )
