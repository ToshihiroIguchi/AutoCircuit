"""Experiment X6: the parallelism the genetic fallback did not have, actually exercised.

``docs/TOPOLOGY_6PLUS_PLAN.md`` section 4.4 already carries one finding about this, made in
passing while measuring something else (commit ``1db16a2``, ``benchmarks/autoeis_round``):
``_evolve`` took no ``workers`` where ``_exhaustive`` does, so every evolve run in this repo ran
single-threaded, and all twelve of those runs stopped at ``generations = 30`` -- the library
default -- having spent 156-818 s of a 600 s allowance. **The generation cap ended every run, not
the clock.** That is why adding ``workers`` to ``_evolve`` (this repository's commit that follows
this one) is not obviously a win: a search that was stopping on iterations, not seconds, gains
nothing from finishing those iterations faster unless the freed wall clock is spent on *more*
iterations.

This script asks that question directly. ``generations`` is set far above anything either arm can
reach in the time given, so ``time_limit`` -- not the generation cap -- is what stops each run.
Two truths from the pre-registered set (``docs/TOPOLOGY_6PLUS_PLAN.md`` section 4.6,
``truths.py``), one from each side of X4's split (``par6``, which growth recovers 6/6, and
``ser6``, which it recovers 0/6, for a topology-shape reason rather than a budget one -- section
5.9). ``mode="evolve"`` is called directly, the same way gate EV1 does, rather than through
``discover(mode="auto")``'s trigger, which ``AUTOEIS_COMPARISON.md`` section 2.2 already measured
never fires on these truths' residuals.

Two readings per run: how many generations were reached, and whether the truth's equivalence
class was reported / on the front / recommended (``Referee``, lifted from ``recovery.py``
unchanged, same as X4 and X7 use).

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/x6_workers.py --out benchmarks/six_plus/x6_workers.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from recovery import Referee  # noqa: E402
from truths import BY_ID, spectrum_for  # noqa: E402

from autocircuit.core.discover import discover  # noqa: E402

TRUTH_IDS: tuple[str, ...] = ("par6", "ser6")
NOISE_SEED: int = 1
WORKER_CONFIGS: tuple[int, ...] = (1, 8)
#: Set far above what either arm can reach in TIME_LIMIT, so the generation cap never binds and
#: time_limit is the only thing that stops a run -- the whole point of this script.
GENERATIONS: int = 100_000
TIME_LIMIT: float = 300.0


def run_one(truth_id: str, workers: int) -> dict[str, Any]:
    truth = BY_ID[truth_id]
    spectrum = spectrum_for(truth, noise=0.01, seed=NOISE_SEED)
    referee = Referee(truth, spectrum)

    started = time.perf_counter()
    result = discover(
        spectrum,
        pool=truth.pool,
        mode="evolve",
        seed=0,
        workers=workers,
        generations=GENERATIONS,
        time_limit=TIME_LIMIT,
    )
    elapsed = time.perf_counter() - started

    reported = any(referee.matches(c) for c in result.candidates)
    on_front = any(referee.matches(c) for c in result.pareto)
    recommended = result.recommended is not None and referee.matches(result.recommended)
    return {
        "truth": truth_id,
        "workers": workers,
        "seconds": round(elapsed, 1),
        "generations": result.generations,
        "n_evaluated": result.n_evaluated,
        "reported": reported,
        "on_front": on_front,
        "recommended": recommended,
        "recommended_circuit": (
            None if result.recommended is None else result.recommended.circuit.to_string()
        ),
        "best_relative_error": (None if result.best is None else result.best.result.relative_error),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    if args.out.exists():
        rows = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk", flush=True)
    done = {(r["truth"], r["workers"]) for r in rows}

    plan = [(tid, w) for tid in TRUTH_IDS for w in WORKER_CONFIGS]
    todo = [key for key in plan if key not in done]
    print(
        f"{len(plan)} runs planned, {len(plan) - len(todo)} on disk, {len(todo)} to go", flush=True
    )

    for index, (truth_id, workers) in enumerate(todo, start=1):
        row = run_one(truth_id, workers)
        rows.append(row)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(
            f"[{index}/{len(todo)}] {truth_id} workers={workers}"
            f"  {row['seconds']:.0f}s  gen={row['generations']}  n={row['n_evaluated']}"
            f"  reported={row['reported']} front={row['on_front']} rec={row['recommended']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
