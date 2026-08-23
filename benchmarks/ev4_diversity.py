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

So this measures both arms on the same reference and the same seeds, with the control produced
by switching `_breeding_pool` off rather than by an older copy of the code:

    python benchmarks/ev4_diversity.py --reference capacitor --seeds 3

Per generation it records proposals, real fits (cache misses), the hit rate, the size of the set
bred from, and P(the best-known candidate enters a tournament) = 1 - (1 - 1/N)^3. The two arms
are interleaved seed by seed, for the reason `benchmarks/README.md` gives: the budget is
wall-clock, this machine's speed drifts by a factor of two within an hour, and an arm run after
the other one measures the drift.
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


class _Counter:
    """Per-generation proposal and cache-miss counts, taken from the evaluator itself."""

    def __init__(self) -> None:
        self.proposals: dict[int, int] = {}
        self.misses: dict[int, int] = {}
        self.pool_sizes: list[int] = []

    def install(self) -> tuple[object, object]:
        original_eval = D._Evaluator.evaluate
        original_pool = D._breeding_pool
        counter = self

        def spy_eval(self, node, generation, parent=None):  # type: ignore[no-untyped-def]
            before = len(self.cache)
            out = original_eval(self, node, generation, parent)
            counter.proposals[generation] = counter.proposals.get(generation, 0) + 1
            if len(self.cache) > before:
                counter.misses[generation] = counter.misses.get(generation, 0) + 1
            return out

        D._Evaluator.evaluate = spy_eval  # type: ignore[method-assign]
        return original_eval, original_pool


def _run(
    reference, seed: int, time_limit: float, bounded: bool, counter: _Counter
) -> tuple[D.DiscoveryResult, float]:
    """One `mode="evolve"` run, with the breeding pool bounded or not.

    The control is the shipped code with one function neutralised, not a reconstruction of the
    old code: `_breeding_pool` returning its input *is* the unbounded search, since the whole
    change is that call.
    """
    original_pool = D._breeding_pool

    def unbounded(alive, population, criterion=D.DEFAULT_CRITERION):  # type: ignore[no-untyped-def]
        counter.pool_sizes.append(len(alive))
        return list(alive)

    def bounded_spy(alive, population, criterion=D.DEFAULT_CRITERION):  # type: ignore[no-untyped-def]
        out = original_pool(alive, population, criterion)
        counter.pool_sizes.append(len(out))
        return out

    D._breeding_pool = bounded_spy if bounded else unbounded  # type: ignore[assignment]
    try:
        started = time.perf_counter()
        result = D.discover(
            reference.spectrum(seed),
            pool=reference.pool,
            mode="evolve",
            max_elements=7,
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


def _trend(values: Sequence[float]) -> str:
    """First third against last third -- the shape EV4's first clause asks about."""
    if len(values) < 6:
        return "too few generations to read"
    third = len(values) // 3
    early = statistics.mean(values[:third])
    late = statistics.mean(values[-third:])
    return f"{early:.0%} -> {late:.0%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", default="capacitor",
                    help="substring of a LARGE_REFERENCES label")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--time-limit", type=float, default=600.0)
    args = ap.parse_args()

    matches = [r for r in LARGE_REFERENCES if args.reference.lower() in r.label.lower()]
    if len(matches) != 1:
        raise SystemExit(f"--reference {args.reference!r} matched {len(matches)} references")
    reference = matches[0]
    print(f"EV4 diversity: {reference.label}  {reference.circuit}")
    print(f"pool {','.join(reference.pool)}, {args.seeds} seeds, {args.time_limit:g} s each,"
          " arms interleaved seed by seed")
    print()

    counter = _Counter()
    counter.install()
    header = (f"{'arm':10s} {'seed':>4s} {'gens':>5s} {'fits':>6s} {'evaluated':>10s} "
              f"{'hit rate':>16s} {'pool':>12s} {'P(best)':>16s} {'min':>6s}")
    print(header)
    print("-" * len(header))
    evaluated: dict[str, list[int]] = {"bounded": [], "unbounded": []}
    for seed in range(args.seeds):
        for arm, bounded in (("unbounded", False), ("bounded", True)):
            counter.proposals.clear()
            counter.misses.clear()
            counter.pool_sizes.clear()
            result, elapsed = _run(reference, seed, args.time_limit, bounded, counter)
            rates = _hit_rates(counter)
            pools = counter.pool_sizes
            pressures = [1.0 - (1.0 - 1.0 / n) ** 3 for n in pools if n]
            evaluated[arm].append(result.n_evaluated)
            print(
                f"{arm:10s} {seed:>4d} {result.generations:>5d} "
                f"{sum(counter.misses.values()):>6d} {result.n_evaluated:>10,} "
                f"{_trend(rates):>16s} "
                f"{f'{pools[0]}->{pools[-1]}' if pools else '-':>12s} "
                f"{f'{pressures[0]:.3f}->{pressures[-1]:.3f}' if pressures else '-':>16s} "
                f"{elapsed / 60:>6.1f}",
                flush=True,
            )
    print()
    for arm in ("unbounded", "bounded"):
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
