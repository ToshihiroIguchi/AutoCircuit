"""Idea E: does an early-stopping rule on the genetic fallback's per-generation improvement rate
change the final answer, or only the time spent reaching it?

**Method, as originally planned (restored after an unapproved mid-run substitution was reverted
on the user's instruction -- see docs/SEARCH_SPEEDUP_PLAN.md's idea E section for that note).**
Run `discover(mode="evolve")` at a *reduced* generation budget and at the *full* default budget,
same seed, same everything else, on `mw6` and `srf3` -- the truths this round's plan actually
named -- and compare the recommended candidate. If a plateauing truth reaches the *same* answer at
a fraction of the generations, an early-stopping rule has something real to detect; if even the
answer on these truths is unchanged, generations beyond the reduced budget are not buying
anything on these truths at all, at any seed tried.

This is known from direct measurement to be slow: a single `discover(mode="evolve")` call on
`mw6` (12 elements) at generations=8, population=20 did not finish in 45+ minutes of CPU time
during this round's first attempt. It is run anyway, at the originally planned scope, because the
user explicitly instructed that a planned measurement is not to be silently descoped for
convenience.

Decision rule, fixed before running: worth building an actual SPRT rule only if the reduced-budget
run matches the full-budget run's recommended circuit (by canonical form) on a clear majority of
(truth, seed) pairs.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW6, SRF3, spectrum_for  # noqa: E402

from autocircuit.core.discover import discover  # noqa: E402

REDUCED_GENERATIONS = 8
FULL_GENERATIONS = 24
POPULATION = 20
SEEDS = range(3)


def run_one(truth, pool) -> None:
    print(f"\n{truth.id} (pool={pool})):", flush=True)
    matches = 0
    total = 0
    for seed in SEEDS:
        spectrum = spectrum_for(truth, seed=seed)
        t0 = time.time()
        reduced = discover(
            spectrum, pool=pool, mode="evolve", generations=REDUCED_GENERATIONS,
            population=POPULATION, max_elements=truth.n_elements + 1, seed=seed, workers=1,
        )
        t1 = time.time()
        print(f"  seed {seed}: reduced ({REDUCED_GENERATIONS}gen) done in {t1 - t0:.1f}s", flush=True)
        full = discover(
            spectrum, pool=pool, mode="evolve", generations=FULL_GENERATIONS,
            population=POPULATION, max_elements=truth.n_elements + 1, seed=seed, workers=1,
        )
        t2 = time.time()
        print(f"  seed {seed}: full ({FULL_GENERATIONS}gen) done in {t2 - t1:.1f}s", flush=True)

        rec_reduced = reduced.recommended.circuit.canonical_form() if reduced.recommended else None
        rec_full = full.recommended.circuit.canonical_form() if full.recommended else None
        match = rec_reduced == rec_full
        matches += int(match)
        total += 1
        print(
            f"  seed {seed}: recommended match: {match} "
            f"(reduced best={reduced.best.score():.6g}, full best={full.best.score():.6g})",
            flush=True,
        )
    print(f"  {truth.id}: {matches}/{total} seeds matched", flush=True)


def main() -> None:
    run_one(MW6, ("R", "C"))
    run_one(SRF3, ("R", "C", "L"))


if __name__ == "__main__":
    main()
