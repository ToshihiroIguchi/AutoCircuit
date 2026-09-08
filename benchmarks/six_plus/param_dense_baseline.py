"""Baseline the E.1 parameter-dense truths on today's element axis (``docs/PARAM_BUDGET_PLAN.md``
Phase 2), before anything is wired to a parameter budget.

Every truth in :mod:`param_dense_truths` is exactly 5 elements, so today's exhaustive stage
(``exhaustive_limit`` / ``complete_up_to`` = 5) enumerates each one's own topology directly --
this is expected to recover cleanly, and the point of running it is to record that as the "before"
picture rather than assume it. The two readings the plan asks Phase 3 to repeat under a parameter
budget are recorded here on the element axis first:

* ``reported``/``on_front``/``recommended`` -- recovery, via the same :class:`Referee` used by
  ``recovery.py``'s X4;
* the coverage sentence's own text -- the honesty reading has no way to fail yet (there is no
  parameter budget to be dishonest about), but its wording is captured now as the "before" string
  so a Phase 3 diff has something to diff against.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/param_dense_baseline.py --out param_dense_baseline.json
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

from param_dense_truths import TRUTHS, ratio  # noqa: E402
from recovery import Referee  # noqa: E402
from truths import Truth, spectrum_for  # noqa: E402

from autocircuit.core.circuit import count_elements  # noqa: E402
from autocircuit.core.discover import discover  # noqa: E402

SEEDS: tuple[int, ...] = (1, 2, 3)
NOISE = 0.01


def run_one(truth: Truth, seed: int, workers: int) -> dict[str, Any]:
    spectrum = spectrum_for(truth, noise=NOISE, seed=seed)
    referee = Referee(truth, spectrum)

    started = time.perf_counter()
    result = discover(spectrum, pool=truth.pool, mode="exhaustive", workers=workers, seed=0)
    elapsed = time.perf_counter() - started

    reported = any(referee.matches(c) for c in result.candidates)
    on_front = any(referee.matches(c) for c in result.pareto)
    recommended = result.recommended is not None and referee.matches(result.recommended)
    rec_size = (
        None if result.recommended is None else count_elements(result.recommended.circuit.root)
    )
    return {
        "truth": truth.id,
        "n_elements": truth.n_elements,
        "ratio": round(ratio(truth), 2),
        "seed": seed,
        "seconds": round(elapsed, 1),
        "n_evaluated": result.n_evaluated,
        "complete_up_to": result.complete_up_to,
        "reported": reported,
        "on_front": on_front,
        "recommended": recommended,
        "recommended_circuit": (
            None if result.recommended is None else result.recommended.circuit.to_string()
        ),
        "recommended_n_elements": rec_size,
        "coverage_sentence": result.summary().splitlines()[
            next(
                i
                for i, line in enumerate(result.summary().splitlines())
                if line.startswith("Coverage:")
            )
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=str, default=None, help="comma-separated seed list")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    seeds = SEEDS if args.seeds is None else tuple(int(s) for s in args.seeds.split(","))

    rows: list[dict[str, Any]] = []
    for truth in TRUTHS:
        for seed in seeds:
            row = run_one(truth, seed, args.workers)
            rows.append(row)
            print(
                f"{row['truth']:12s} seed={seed} reported={row['reported']} "
                f"on_front={row['on_front']} recommended={row['recommended']} "
                f"({row['seconds']}s, complete_up_to={row['complete_up_to']})"
            )
            print(f"    {row['coverage_sentence']}")

    print()
    for truth in TRUTHS:
        subset = [r for r in rows if r["truth"] == truth.id]
        total = len(subset)
        print(
            f"{truth.id:12s} (ratio {ratio(truth):.2f})  "
            f"reported {sum(r['reported'] for r in subset)}/{total}  "
            f"on_front {sum(r['on_front'] for r in subset)}/{total}  "
            f"recommended {sum(r['recommended'] for r in subset)}/{total}"
        )

    if args.out is not None:
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
