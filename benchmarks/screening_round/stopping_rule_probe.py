"""docs/EVOLVE_SEARCH_PLAN.md section 3.6 Step 7, run: false-stop rate of two candidate stopping
rules for the genetic fallback, against the same frozen-landscape tables and 480-seed discipline
`arms.py` already uses.

Method: run the *unstopped* `current` simulation (reusing `arms.Table`/`_unique_best`/
`_next_generation`/`random_topology` exactly as `arms.arm_current` does) for every seed,
recording each generation's cumulative fit count and best score. Post-hoc, for each candidate
rule, find the generation at which it would have fired and mark a **false stop** iff the run's
`hit_at` (already tracked, in fits) occurred strictly after that generation's fit count -- the
run would have found the truth had it kept going.

This is a controlled simulation against a frozen table, not a live `discover(mode="evolve")` run,
so it answers "does the signal even work as a rule" cheaply; a positive result here is a pilot
that still needs the live nine-truth `benchmarks/six_plus/recovery.py` check before shipping,
exactly as this script's own write-up in the plan document says.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from arms import CRITERION, Table

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import _next_generation, _unique_best, random_topology


def run_one(
    table: Table,
    rng: np.random.Generator,
    pool: tuple[str, ...],
    max_elements: int,
    population: int,
) -> tuple[int | None, list[int], list[float]]:
    """Runs `arm_current`'s exact loop, additionally recording per-generation fits/best."""
    trees: list[tuple[object, object]] = [
        (random_topology(rng, pool, int(rng.integers(2, max_elements + 1))), None)
        for _ in range(population)
    ]
    scored: list[object] = []
    fits_hist: list[int] = []
    best_hist: list[float] = []
    generation = 0
    while not table.exhausted:
        for tree, _parent in trees:
            ind = table.evaluate(tree, generation)
            if ind is not None:
                scored.append(ind)
            if table.exhausted:
                break
        alive = _unique_best(scored, CRITERION)
        fits_hist.append(table.fits)
        best_hist.append(table.best)
        if not alive:
            trees = [
                (random_topology(rng, pool, int(rng.integers(2, max_elements + 1))), None)
                for _ in range(population)
            ]
            continue
        trees = _next_generation(alive, rng, pool, max_elements, population, CRITERION)
        generation += 1
    return table.hit_at, fits_hist, best_hist


def plateau_stop_generation(best_hist: list[float], k: int) -> int | None:
    """First generation index g (0-based) with no real improvement over the k generations before it.

    `best_hist` is monotonically non-increasing (a running best), so "no improvement over the
    last k generations" is exactly `best_hist[g] >= best_hist[g - k] - eps`.
    """
    eps = 1e-9
    for g in range(k, len(best_hist)):
        if best_hist[g] >= best_hist[g - k] - eps:
            return g
    return None


def diversity_stop_generation(
    fits_hist: list[int], population: int, window: int, threshold: float
) -> int | None:
    """First generation g where the cache-hit rate over the last `window` generations exceeds it."""
    new_per_gen = [fits_hist[0]] + [
        fits_hist[i] - fits_hist[i - 1] for i in range(1, len(fits_hist))
    ]
    for g in range(window, len(new_per_gen) + 1):
        recent = new_per_gen[g - window : g]
        hit_rate = 1.0 - (sum(recent) / (population * window))
        if hit_rate >= threshold:
            return g
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("landscape", type=Path)
    ap.add_argument("targets", type=Path)
    ap.add_argument("--budget", type=int, default=150)
    ap.add_argument("--seeds", type=int, default=480)
    ap.add_argument("--population", type=int, default=40)
    ap.add_argument("--max-elements", type=int, default=6)
    args = ap.parse_args()

    data = json.loads(args.landscape.read_text(encoding="utf-8"))
    targets = frozenset(json.loads(args.targets.read_text(encoding="utf-8"))["targets"])
    pool = tuple(data["pool"])
    rows = {
        Circuit.parse(r["text"]).canonical_form(): (r["n_elements"], r["n_params"], r["cost"])
        for r in data["rows"]
    }

    print(
        f"arena: {args.landscape.name}  {len(rows)} topologies, {len(targets)} targets, "
        f"budget {args.budget}, {args.seeds} seeds"
    )

    rules = {
        "plateau_k3": lambda fh, bh: plateau_stop_generation(bh, 3),
        "plateau_k5": lambda fh, bh: plateau_stop_generation(bh, 5),
        "plateau_k8": lambda fh, bh: plateau_stop_generation(bh, 8),
        "diversity_w3_t90": lambda fh, bh: diversity_stop_generation(fh, args.population, 3, 0.90),
    }
    counts = {
        name: {"false_stop": 0, "safe_stop": 0, "never_stopped": 0, "fits_saved": []}
        for name in rules
    }
    n_hit = 0

    for seed in range(args.seeds):
        table = Table(rows, data["n_data"], targets, args.budget)
        rng = np.random.default_rng(seed)
        hit_at, fits_hist, best_hist = run_one(table, rng, pool, args.max_elements, args.population)
        if hit_at is not None:
            n_hit += 1
        for name, rule in rules.items():
            stop_gen = rule(fits_hist, best_hist)
            if stop_gen is None or stop_gen >= len(fits_hist):
                counts[name]["never_stopped"] += 1
                continue
            stop_fits = fits_hist[stop_gen]
            if hit_at is not None and hit_at > stop_fits:
                counts[name]["false_stop"] += 1
            else:
                counts[name]["safe_stop"] += 1
            counts[name]["fits_saved"].append(fits_hist[-1] - stop_fits)

    print(f"baseline hit rate (unstopped): {n_hit}/{args.seeds} = {n_hit / args.seeds:.1%}")
    print()
    header = (
        f"{'rule':18s} {'false_stop':>14s} {'safe_stop':>10s} {'never':>7s} "
        f"{'mean fits saved':>16s}"
    )
    print(header)
    print("-" * len(header))
    for name, c in counts.items():
        total_stopped = c["false_stop"] + c["safe_stop"]
        rate = c["false_stop"] / total_stopped if total_stopped else float("nan")
        mean_saved = float(np.mean(c["fits_saved"])) if c["fits_saved"] else float("nan")
        print(
            f"{name:18s} {c['false_stop']:5d} ({rate:6.1%}) {c['safe_stop']:10d} "
            f"{c['never_stopped']:7d} {mean_saved:16.1f}"
        )


if __name__ == "__main__":
    main()
