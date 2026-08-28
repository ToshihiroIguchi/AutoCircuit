"""Gate EV4: does the bounded breeding pool buy its selection pressure with diversity?

`docs/EVOLVE_SEARCH_PLAN.md` §4 states EV4 as two clauses -- the per-generation cache-hit rate
does not rise across a run, and the best-known candidate's probability of entering a tournament
does not fall with generation number -- plus "EV1 must not regress".

The second clause is what `_breeding_pool` was written for and it is answered by arithmetic once
the pool is bounded: a tournament of 3 drawn from a set that stops growing is a constant
probability. **The first clause is the one that can go the wrong way**, and it is the price the
bounded pool might be paying for the pressure it buys: a search that breeds only from the front
and the top `population` can close the neighbourhood of one attractor and spend the rest of its
budget re-proposing inside it. The cache absorbs the cost, so nothing in the report says it
happened -- the run simply stops finding anything new while still looking busy.

[measured] It went the wrong way: 26.3 points against the unbounded control's 5.7. Islands were
the remedy the plan named for exactly that, and the frozen landscape measured them out again
(section 3.4.4). What the arms compare now is the *width* of the one pool, which is what section
3.4.3 changed:

    unbounded  `_breeding_pool` neutralised: the search as it was before step 4
    bounded    the front plus the best `population` by score -- step 4 as first shipped
    front      the front alone, which is `BREEDING_EXTRA` and what ships now

Every arm is the shipped code with one argument changed, never an older copy of it.

    python benchmarks/ev4_diversity.py --reference capacitor --seeds 3 --arms bounded,front

Per generation it records proposals, real fits (cache misses), the hit rate, the size of the
set bred from, and the best-known candidate's chance of entering a tournament. The arms are
interleaved seed by seed, for the reason `benchmarks/README.md` gives: the budget is wall-clock,
this machine's speed drifts by a factor of two within an hour, and an arm run after the other one
measures the drift.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_v2 import LARGE_REFERENCES  # noqa: E402

from autocircuit.core import discover as D  # noqa: E402

#: The arms, and the `_breeding_pool` width each one runs at.
ARMS = ("unbounded", "bounded", "front")


class _Counter:
    """Per-generation proposal and cache-miss counts, taken from the evaluator itself."""

    def __init__(self) -> None:
        self.proposals: dict[int, int] = {}
        self.misses: dict[int, int] = {}
        #: One entry per `_breeding_pool` call: its size and the best score in it.
        self.pools: list[tuple[int, float]] = []

    def install(self) -> None:
        original_eval = D._Evaluator.evaluate
        counter = self

        def spy_eval(self, node, generation, parent=None):  # type: ignore[no-untyped-def]
            before = len(self.cache)
            out = original_eval(self, node, generation, parent)
            counter.proposals[generation] = counter.proposals.get(generation, 0) + 1
            if len(self.cache) > before:
                counter.misses[generation] = counter.misses.get(generation, 0) + 1
            return out

        D._Evaluator.evaluate = spy_eval  # type: ignore[method-assign]


def _best(candidates: Sequence[object]) -> float:
    scores = [c.score(D.DEFAULT_CRITERION) for c in candidates]  # type: ignore[attr-defined]
    return min(scores) if scores else float("inf")


def _run(
    reference,
    seed: int,
    time_limit: float,
    arm: str,
    population: int,
    generations: int,
    counter: _Counter,
) -> tuple[D.DiscoveryResult, float]:
    """One `mode="evolve"` run under one arm.

    Every arm is the shipped code with one function wrapped, not a reconstruction of an older
    one: `_breeding_pool` returning its input *is* the unbounded search, and the two bounded
    arms differ only in the ``extra`` they hand it. `bounded` has to state the width step 4
    first shipped -- the front plus a whole generation -- because `_evolve` no longer supplies
    it.
    """
    original_pool = D._breeding_pool

    def unbounded(alive, extra=D.BREEDING_EXTRA, criterion=D.DEFAULT_CRITERION):  # type: ignore[no-untyped-def]
        counter.pools.append((len(alive), _best(alive)))
        return list(alive)

    def spy(alive, extra=D.BREEDING_EXTRA, criterion=D.DEFAULT_CRITERION):  # type: ignore[no-untyped-def]
        out = original_pool(alive, population if arm == "bounded" else 0, criterion)
        counter.pools.append((len(out), _best(out)))
        return out

    D._breeding_pool = unbounded if arm == "unbounded" else spy  # type: ignore[assignment]
    try:
        started = time.perf_counter()
        result = D.discover(
            reference.spectrum(seed),
            pool=reference.pool,
            mode="evolve",
            max_elements=7,
            population=population,
            generations=generations,
            seed=seed,
            time_limit=time_limit,
        )
        return result, time.perf_counter() - started
    finally:
        D._breeding_pool = original_pool  # type: ignore[assignment]


def _hit_rates(counter: _Counter) -> list[float]:
    return [
        1.0 - counter.misses.get(g, 0) / counter.proposals[g]
        for g in sorted(counter.proposals)
        if counter.proposals[g]
    ]


def _pressures(counter: _Counter) -> list[float]:
    """Per generation, the chance one tournament draws the best-known candidate.

    One pool per generation, so this is the `1 - (1 - 1/N)^3` of the gate as written.
    """
    return [1.0 - (1.0 - 1.0 / n) ** 3 for n, _s in counter.pools if n]


def _trend(values: Sequence[float], fmt: str = "{:.0%}") -> str:
    """First third against last third -- the shape EV4's first clause asks about."""
    if len(values) < 6:
        return "too few generations to read"
    third = len(values) // 3
    early = statistics.mean(values[:third])
    late = statistics.mean(values[-third:])
    return f"{fmt.format(early)} -> {fmt.format(late)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", default="capacitor",
                    help="substring of a LARGE_REFERENCES label")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--time-limit", type=float, default=600.0)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--population", type=int, default=40,
                    help="`discover`'s population, and the width the `bounded` arm runs at")
    # Deliberately far above `discover`'s own default of 30. Section 4's EV3 entry measured that
    # cap binding in 5.2 of a 600 s budget, and this comparison is exactly the one it warned
    # about: the arms differ in what a generation *costs*, so a run stopped by the generation
    # count is stopped by different amounts of work per arm and the budget is not shared. The
    # wall clock has to be the thing that runs out.
    ap.add_argument("--generations", type=int, default=1000,
                    help="generation cap; the default is high enough that --time-limit binds")
    args = ap.parse_args()

    matches = [r for r in LARGE_REFERENCES if args.reference.lower() in r.label.lower()]
    if len(matches) != 1:
        raise SystemExit(f"--reference {args.reference!r} matched {len(matches)} references")
    reference = matches[0]
    arms = args.arms.split(",")
    for arm in arms:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm {arm!r}; pick from {', '.join(ARMS)}")
    print(f"EV4 diversity: {reference.label}  {reference.circuit}")
    print(f"pool {','.join(reference.pool)}, {args.seeds} seeds, {args.time_limit:g} s each,"
          f" population {args.population}, generation cap {args.generations},"
          " arms interleaved seed by seed")
    print()

    counter = _Counter()
    counter.install()
    header = (f"{'arm':10s} {'seed':>4s} {'gens':>5s} {'fits':>6s} {'evaluated':>10s} "
              f"{'hit rate':>16s} {'pool':>12s} {'P(best)':>18s} {'min':>6s}")
    print(header)
    print("-" * len(header))
    evaluated: dict[str, list[int]] = {arm: [] for arm in arms}
    for seed in range(args.seeds):
        for arm in arms:
            counter.proposals.clear()
            counter.misses.clear()
            counter.pools.clear()
            result, elapsed = _run(
                reference, seed, args.time_limit, arm, args.population, args.generations, counter
            )
            rates = _hit_rates(counter)
            pressures = _pressures(counter)
            sizes = [n for n, _s in counter.pools]
            evaluated[arm].append(result.n_evaluated)
            print(
                f"{arm:10s} {seed:>4d} {result.generations:>5d} "
                f"{sum(counter.misses.values()):>6d} {result.n_evaluated:>10,} "
                f"{_trend(rates):>16s} "
                f"{f'{sizes[0]}->{sizes[-1]}' if sizes else '-':>12s} "
                f"{_trend(pressures, '{:.4f}'):>18s} "
                f"{elapsed / 60:>6.1f}",
                flush=True,
            )
    print()
    for arm in arms:
        counts = evaluated[arm]
        distinct = len(set(counts))
        print(f"{arm:10s} topologies evaluated per seed: {counts}"
              f"  ({distinct} distinct value{'' if distinct == 1 else 's'} across"
              f" {len(counts)} seeds)")
    print()
    print("EV4 clause 1 asks whether the hit rate RISES across a run; clause 2 whether P(best)"
          " FALLS.")
    print("Evaluated counts that stop varying with the seed would say the search closed one"
          " neighbourhood and stopped exploring.")


if __name__ == "__main__":
    main()
