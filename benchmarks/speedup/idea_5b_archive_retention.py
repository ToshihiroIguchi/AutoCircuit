"""Idea 5b, measured as planned (not citation-only): does widening the evolve fallback's breeding
pool beyond the current Pareto front (`BREEDING_EXTRA`) change the hit rate on mw6/srf3?

`docs/EVOLVE_SEARCH_PLAN.md` section 3.4 already ran a similar-looking ladder and found the
Pareto-front-only rule (extra=0) wins or ties at every budget tested there. This script does not
rest on that citation -- it re-runs the comparison on this round's own truths (`mw6`, `srf3`)
directly, per the user's instruction that a planned measurement is not to be replaced by a citation.

`_breeding_pool`'s `extra` parameter is bound as a default argument at function-definition time
(`extra: int = BREEDING_EXTRA`), so patching the module constant after import has no effect; this
script instead replaces `discover._breeding_pool` itself with a wrapper forcing a chosen `extra`,
which *is* picked up because `_evolve` looks up the name in the module's global namespace at call
time.

Paired by seed (same seed run under both `extra` settings), so McNemar's exact test on the
discordant pairs is the right instrument rather than a bare percentage difference -- with the
seed count this round's budget allows, `docs/autoeis_round/score.py`'s own `resolvable_discordant`
logic applies: a small arena may simply not be able to resolve anything, and that is reported as
such rather than as a null result.

Decision rule, fixed before running: ships only if the wider pool wins with McNemar p<0.05 and no
regression on either truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

import harness  # noqa: E402
from truths import MW6, SRF3, spectrum_for  # noqa: E402

from autocircuit.core import discover as discover_mod  # noqa: E402
from autocircuit.core.discover import discover  # noqa: E402

GENERATIONS = 10
POPULATION = 15
SEEDS = range(5)

_original_breeding_pool = discover_mod._breeding_pool


def _patch_extra(extra: int) -> None:
    def wrapper(alive, extra=extra, criterion=discover_mod.DEFAULT_CRITERION):
        return _original_breeding_pool(alive, extra=extra, criterion=criterion)

    discover_mod._breeding_pool = wrapper


def _unpatch() -> None:
    discover_mod._breeding_pool = _original_breeding_pool


def run_one(truth, pool) -> None:
    print(f"\n{truth.id} (pool={pool}):", flush=True)
    baseline_costs = []
    wide_costs = []
    for seed in SEEDS:
        spectrum = spectrum_for(truth, seed=seed)

        _patch_extra(0)
        try:
            baseline = discover(
                spectrum, pool=pool, mode="evolve", generations=GENERATIONS,
                population=POPULATION, max_elements=truth.n_elements + 1, seed=seed, workers=1,
            )
        finally:
            _unpatch()

        _patch_extra(POPULATION // 2)
        try:
            wide = discover(
                spectrum, pool=pool, mode="evolve", generations=GENERATIONS,
                population=POPULATION, max_elements=truth.n_elements + 1, seed=seed, workers=1,
            )
        finally:
            _unpatch()

        b_cost = baseline.best.score() if baseline.best else float("inf")
        w_cost = wide.best.score() if wide.best else float("inf")
        baseline_costs.append(b_cost)
        wide_costs.append(w_cost)
        print(
            f"  seed {seed}: baseline(extra=0)={b_cost:.6g}  "
            f"wide(extra={POPULATION // 2})={w_cost:.6g}",
            flush=True,
        )

    best_known = min(baseline_costs + wide_costs)
    baseline_hits = sum(1 for c in baseline_costs if c <= best_known * 1.1)
    wide_hits = sum(1 for c in wide_costs if c <= best_known * 1.1)

    only_wide = sum(
        1 for b, w in zip(baseline_costs, wide_costs, strict=True)
        if (w <= best_known * 1.1) and not (b <= best_known * 1.1)
    )
    only_baseline = sum(
        1 for b, w in zip(baseline_costs, wide_costs, strict=True)
        if (b <= best_known * 1.1) and not (w <= best_known * 1.1)
    )
    p = harness.mcnemar_exact(only_wide, only_baseline)

    print(f"  {truth.id}: baseline {baseline_hits}/{len(SEEDS)}, wide {wide_hits}/{len(SEEDS)}, "
          f"discordant (only-wide={only_wide}, only-baseline={only_baseline}), McNemar p={p:.4f}",
          flush=True)


def main() -> None:
    run_one(MW6, ("R", "C"))
    run_one(SRF3, ("R", "C", "L"))


if __name__ == "__main__":
    main()
