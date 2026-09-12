"""Live-instrumented test of the archive-diversity-collapse stopping rule against real
``discover(mode="evolve")``-style runs -- docs/EVOLVE_SEARCH_PLAN.md section 3.6(a).

That section's pilot (``benchmarks/screening_round/stopping_rule_probe.py``) measured the rule
against a *frozen-table simulation*, not a live search, and said so explicitly: "this answers
'does the signal work as a rule' cheaply; it is not the live-truth evidence base the section's
own decision rule asks for, and nothing here ships as a default on its strength alone." This
script is that live-truth check, run against the nine pre-registered ``benchmarks/six_plus/
truths.py`` truths the section's own pre-registered experiment names.

The decision rule, restated from section 3.6(a) rather than re-derived: the rule ships only if
(i) the false-stop rate is at or indistinguishable from zero -- no run where stopping at the
fired generation would have missed a truth-or-equivalent that continuing to the existing budget
found -- and (ii) it produces a reported, non-trivial wall-clock or fit-count saving on the runs
it correctly cuts short. Either clause failing alone is enough not to ship it.

This drives ``evolve_plan`` -- the same generator :func:`autocircuit.core.discover._evolve` uses
-- with the exact dispatch loop ``_evolve`` itself runs (single-process ``_evolve_one`` calls, or
an ``executor.map`` over ``_evolve_polish_then_search_worker`` behind a real
:class:`multiprocessing.pool.Pool`), so ``run`` measures the real search's genuine cache-hit
signal rather than a re-implementation of it. What is added is bookkeeping the generator does not
expose on its own: the cumulative *charged* (actually fitted) count per generation, and the first
charged-fit count at which any produced candidate is the truth or an exact reparameterisation of
it (:class:`recovery.Referee`, reused verbatim rather than re-derived).

``diversity_stop_generation`` below is copied verbatim from ``stopping_rule_probe.py`` -- the same
13-line function, not a reimplementation -- because no existing ``benchmarks/six_plus`` script
imports Python objects across a sibling benchmark subdirectory (only ``build_arenas.py`` reaches
into ``screening_round``, and only via ``subprocess``), and one small pure function is cheaper to
copy than to wire a new cross-directory import path for.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/stopping_live.py run --out benchmarks/six_plus/x_stopping.json \\
        --workers 8
    python benchmarks/six_plus/stopping_live.py analyse --in benchmarks/six_plus/x_stopping.json

Resumable exactly as ``recovery.py`` is: a ``(truth, seed)`` pair already on disk is skipped, and
the whole accumulated list is rewritten after every completed run, so an interrupted run keeps
its hours.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from recovery import Referee  # noqa: E402
from truths import TRUTHS, Truth, spectrum_for  # noqa: E402

from autocircuit.core.discover import (  # noqa: E402
    Candidate,
    _evolve_one,
    _evolve_polish_then_search_worker,
    _worker_pool,
    evolve_plan,
)
from autocircuit.core.fit import FitContext, Weighting  # noqa: E402
from autocircuit.core.stats import DEFAULT_CRITERION, Criterion  # noqa: E402

#: ``discover()``'s own tier-1 defaults (``search_restarts``/``search_popsize``/
#: ``search_maxiter``/``search_tol``), unchanged here so this measures the search that ships,
#: not a differently-tuned one.
SEARCH_RESTARTS = 1
SEARCH_POPSIZE = 12
SEARCH_MAXITER = 60
SEARCH_TOL = 1e-5

#: ``discover()``'s own default weighting and minimum random-topology size.
WEIGHTING: Weighting = "modulus"
MIN_ELEMENTS = 2

#: Proportional noise, matching ``benchmarks/six_plus/recovery.py``'s own ``NOISE``.
NOISE = 0.01

WINDOWS: tuple[int, ...] = (2, 3, 5)
THRESHOLDS: tuple[float, ...] = (0.50, 0.65, 0.80, 0.90)


def diversity_stop_generation(
    fits_hist: list[int], population: int, window: int, threshold: float
) -> int | None:
    """First generation count ``g`` (1-indexed: "after ``g`` generations have completed") at
    which the cache-hit rate over the last ``window`` generations meets or exceeds ``threshold``.

    The same function as ``benchmarks/screening_round/stopping_rule_probe.py``'s
    ``diversity_stop_generation`` -- copied, not reimplemented; see the module docstring for why.
    """
    new_per_gen = [fits_hist[0]] + [
        fits_hist[i] - fits_hist[i - 1] for i in range(1, len(fits_hist))
    ]
    for g in range(window, len(new_per_gen) + 1):
        recent = new_per_gen[g - window : g]
        hit_rate = 1.0 - (sum(recent) / (population * window))
        if hit_rate >= threshold:
            return g
    return None


def _best_score(scored: list[Candidate], criterion: Criterion) -> float:
    """Lowest (best) score in ``scored``, or +inf when nothing has been scored yet."""
    if not scored:
        return math.inf
    return min(c.score(criterion) for c in scored)


def run_live(
    truth: Truth,
    seed: int,
    *,
    workers: int,
    generations: int,
    population: int,
    max_elements: int,
    time_limit: float,
    pool: tuple[str, ...] | None,
    criterion: Criterion = DEFAULT_CRITERION,
) -> dict[str, Any]:
    """Drive one real ``evolve_plan`` run, instrumenting it exactly the way
    :func:`autocircuit.core.discover._evolve` drives it, plus:

    * ``fits_hist`` -- cumulative *charged* (actually fitted, i.e. ``len(batch.tasks)``) count
      recorded at every generation boundary;
    * ``best_hist`` -- the best (lowest) score across everything scored so far, at the same
      boundaries;
    * ``hit_at`` -- the cumulative charged-fit count at which a truth-equivalent candidate was
      first produced, or ``None`` if it never was within this run's budget.

    ``pool`` overrides ``truth.pool`` when given; otherwise the truth's own pool is used, so a
    run does not silently narrow or widen the vocabulary the truth was built to be found in.
    """
    used_pool = pool if pool is not None else truth.pool
    spectrum = spectrum_for(truth, noise=NOISE, seed=seed)
    referee = Referee(truth, spectrum)
    context = FitContext.build(spectrum, WEIGHTING, None, 3.0)

    total_fits = 0
    seen_scored = 0
    hit_at: int | None = None
    fits_hist: list[int] = []
    best_hist: list[float] = []

    def check_new(scored: list[Candidate]) -> None:
        """Referee-check every candidate appended to ``scored`` since the last check.

        Called with the *current* ``total_fits`` still holding the count charged before the
        window that produced these candidates, so a first match is attributed to the charged-fit
        count at which it became available -- the same convention
        ``benchmarks/screening_round/arms.py``'s ``Table.evaluate`` uses (``self.fits += 1``,
        then check, so ``hit_at`` already includes the fit that produced the hit).
        """
        nonlocal hit_at, seen_scored
        for candidate in scored[seen_scored:]:
            if hit_at is None and referee.matches(candidate):
                hit_at = total_fits
        seen_scored = len(scored)

    started = time.perf_counter()
    stopped_early = False
    generations_run = 0
    with _worker_pool(workers, spectrum, WEIGHTING) as executor:
        item_chunk = population if executor is not None else 1
        plan = evolve_plan(
            pool=used_pool,
            generations=generations,
            population=population,
            max_elements=max_elements,
            min_elements=MIN_ELEMENTS,
            seed=seed,
            search_restarts=SEARCH_RESTARTS,
            search_popsize=SEARCH_POPSIZE,
            search_maxiter=SEARCH_MAXITER,
            search_tol=SEARCH_TOL,
            seeds=None,
            criterion=criterion,
            item_chunk=item_chunk,
        )
        try:
            batch = next(plan)
            current_generation = batch.generation
            while True:
                # Mirrors `_evolve`'s own driving loop exactly (discover.py, `_evolve`): a
                # generation boundary is where `batch.generation` first differs from what was
                # seen before, and it is the only place `batch.scored` is a *complete* snapshot
                # of a just-finished generation rather than a partial one.
                if batch.generation != current_generation:
                    current_generation = batch.generation
                    check_new(batch.scored)
                    fits_hist.append(total_fits)
                    best_hist.append(_best_score(batch.scored, criterion))
                    generations_run = current_generation
                    if time.perf_counter() - started > time_limit:
                        plan.close()
                        stopped_early = True
                        break
                else:
                    check_new(batch.scored)
                if executor is not None:
                    outcomes = list(
                        executor.map(_evolve_polish_then_search_worker, batch.tasks)
                    )
                else:
                    outcomes = [
                        _evolve_one(task, spectrum, weighting=WEIGHTING, context=context)
                        for task in batch.tasks
                    ]
                total_fits += len(batch.tasks)
                batch = plan.send(outcomes)
        except StopIteration as done:
            result = done.value
            check_new(result.scored)
            fits_hist.append(total_fits)
            best_hist.append(_best_score(result.scored, criterion))
            generations_run = result.generations_run
    wall_clock = time.perf_counter() - started

    return {
        "truth": truth.id,
        "shape": truth.shape,
        "seed": seed,
        "pool": list(used_pool),
        "population": population,
        "max_elements": max_elements,
        "criterion": criterion,
        "fits_hist": fits_hist,
        "best_hist": best_hist,
        "hit_at": hit_at,
        "generations_run": generations_run,
        "stopped_early": stopped_early,
        "wall_clock_s": round(wall_clock, 1),
    }


def _run(args: argparse.Namespace) -> None:
    truths = [t for t in TRUTHS if args.truths is None or t.id in args.truths.split(",")]
    seeds = tuple(int(s) for s in args.seeds.split(","))
    pool = tuple(args.pool.split(",")) if args.pool else None
    if not truths:
        raise SystemExit("no truths selected")

    rows: list[dict[str, Any]] = []
    if args.out.exists():
        rows = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk", flush=True)
    done = {(r["truth"], r["seed"]) for r in rows}

    for truth in truths:
        for seed in seeds:
            if (truth.id, seed) in done:
                continue
            row = run_live(
                truth,
                seed,
                workers=args.workers,
                generations=args.generations,
                population=args.population,
                max_elements=args.max_elements,
                time_limit=args.time_limit,
                pool=pool,
            )
            rows.append(row)
            print(
                f"{row['truth']:8s} seed={row['seed']} "
                f"generations_run={row['generations_run']:3d} hit_at={row['hit_at']} "
                f"wall_clock_s={row['wall_clock_s']:.1f}",
                flush=True,
            )
            args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _analyse(args: argparse.Namespace) -> None:
    rows: list[dict[str, Any]] = json.loads(args.in_path.read_text(encoding="utf-8"))
    if not rows:
        print("no runs in input")
        return

    n_hit = sum(1 for r in rows if r["hit_at"] is not None)
    print(f"{len(rows)} runs, baseline hit rate {n_hit}/{len(rows)} = {n_hit / len(rows):.1%}")
    print()
    header = (
        f"{'window':>6s} {'thresh':>7s} {'fired':>6s} {'false_stop':>16s} "
        f"{'safe_stop':>10s} {'no_hit':>7s} {'never':>6s} {'mean saved':>11s} "
        f"{'median saved':>13s}"
    )
    print(header)
    print("-" * len(header))
    for window in WINDOWS:
        for threshold in THRESHOLDS:
            false_stop = 0
            safe_stop = 0
            no_hit_fired = 0
            never_fired = 0
            saved: list[float] = []
            for row in rows:
                fits_hist: list[int] = row["fits_hist"]
                population: int = row["population"]
                hit_at: int | None = row["hit_at"]
                stop_g = diversity_stop_generation(fits_hist, population, window, threshold)
                if stop_g is None:
                    never_fired += 1
                    continue
                stop_index = stop_g - 1
                if stop_index < 0 or stop_index >= len(fits_hist):
                    never_fired += 1
                    continue
                stop_fits = fits_hist[stop_index]
                if hit_at is None:
                    # Nothing was there to miss: firing here is never a false stop, and it is
                    # not a measured saving either, since the run never reached the truth even
                    # at its full budget. Counted separately rather than folded into either.
                    no_hit_fired += 1
                elif hit_at > stop_fits:
                    false_stop += 1
                else:
                    safe_stop += 1
                    saved.append(float(fits_hist[-1] - stop_fits))
            total_stopped = false_stop + safe_stop
            rate = false_stop / total_stopped if total_stopped else float("nan")
            mean_saved = float(np.mean(saved)) if saved else float("nan")
            median_saved = float(np.median(saved)) if saved else float("nan")
            fired = false_stop + safe_stop + no_hit_fired
            print(
                f"{window:6d} {threshold:7.2f} {fired:6d} "
                f"{false_stop:5d} ({rate:6.1%}) {safe_stop:10d} {no_hit_fired:7d} "
                f"{never_fired:6d} {mean_saved:11.1f} {median_saved:13.1f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser(
        "run", help="drive real evolve_plan runs and record per-generation stopping-rule stats"
    )
    run_p.add_argument("--out", type=Path, required=True)
    run_p.add_argument("--workers", type=int, default=8)
    run_p.add_argument("--truths", default=None, help="comma-separated truth ids")
    run_p.add_argument("--seeds", default="1,2,3", help="comma-separated noise seeds")
    run_p.add_argument("--generations", type=int, default=60, help="safety cap on generations")
    run_p.add_argument(
        "--time-limit", type=float, default=600.0, help="per-run wall-clock safety cap, seconds"
    )
    run_p.add_argument("--population", type=int, default=40)
    run_p.add_argument("--max-elements", type=int, default=7)
    run_p.add_argument(
        "--pool",
        default=None,
        help="comma-separated element codes; default is each truth's own pool",
    )

    analyse_p = sub.add_parser(
        "analyse", help="score the diversity-collapse rule at a (window, threshold) grid"
    )
    analyse_p.add_argument("--in", dest="in_path", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "run":
        _run(args)
    else:
        _analyse(args)


if __name__ == "__main__":
    main()
