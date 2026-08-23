"""KPI-0 on a pool too large to enumerate, estimated from a random sample.

The controlled max-element experiment refuted the hypothesis that the genetic search drowns in
the largest size layer, and it did so because the truth's exact-equivalence class grows with the
space at roughly constant density (0.55% at n <= 6, 0.99% at n <= 7). That leaves the element
pool as the one untested factor -- and it is the factor `POOL_FROM_SPECTRUM_PLAN.md` section 5
already has a measurement about: given enough elements the default pool builds an eight-parameter
CPE stack that reaches the noise floor. If that stack out-scores the truth under tier-1 AICc,
then the truth is not at the top of the landscape any more and **no topology-search algorithm can
recover it**, because the score it would have to climb towards points somewhere else.

Answering that does not need the whole 21,057-topology table: it needs an estimate of the
fraction of the space that out-scores the truth. A uniform sample of a few hundred per size
gives that to a couple of percent in a few minutes.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
from pathlib import Path
from typing import Any

import numpy as np
from landscape2 import reference_spectrum

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import _screening_score
from autocircuit.core.enumerate import enumerate_topologies
from autocircuit.core.fit import screen
from autocircuit.core.spectrum import Spectrum

_WORKER: dict[str, Any] = {}


def _init(f: Any, z: Any) -> None:
    _WORKER["spectrum"] = Spectrum(f, z)


def _job(task: tuple[str, int, int]) -> tuple[str, int, int, float]:
    text, n_elements, n_params = task
    try:
        cost = float(screen(text, _WORKER["spectrum"], seed=0))
    except Exception:
        cost = float("inf")
    return (text, n_elements, n_params, cost)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="R,C,L,CPE")
    ap.add_argument("--sizes", default="4,5,6")
    ap.add_argument("--per-size", type=int, default=400)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    pool = tuple(args.pool.split(","))
    spectrum = reference_spectrum(0)
    n_data = 2 * len(spectrum.f)
    truth_text = "p(R1,C1)-p(R2,C2)-p(R3,C3)"

    rng = np.random.default_rng(0)
    tasks: list[tuple[str, int, int]] = [(truth_text, 6, 6)]
    populations: dict[int, int] = {}
    for n in (int(s) for s in args.sizes.split(",")):
        level = list(enumerate_topologies(pool, n))
        populations[n] = len(level)
        idx = rng.choice(len(level), size=min(args.per_size, len(level)), replace=False)
        for i in idx:
            circuit = Circuit(level[int(i)])
            tasks.append((circuit.to_string(), n, len(circuit.param_names)))
    print(f"pool={pool} sizes={populations} sample={len(tasks) - 1}", flush=True)

    with multiprocessing.Pool(
        args.workers, initializer=_init, initargs=(spectrum.f, spectrum.z)
    ) as executor:
        rows = list(executor.imap_unordered(_job, tasks, chunksize=8))

    scored = [
        (t, n, p, c, _screening_score(c, p, n_data, "aicc")) for t, n, p, c in rows
    ]
    truth = next(r for r in scored if r[0] == truth_text)
    print(f"truth screening AICc {truth[4]:.3f}  cost {truth[3]:.5g}")
    print()
    print(f"{'n':>3s} {'level size':>11s} {'sampled':>8s} {'beat truth':>11s} "
          f"{'share':>7s} {'est. count':>11s}")
    total_better = 0.0
    for n, size in sorted(populations.items()):
        same = [r for r in scored if r[1] == n and r[0] != truth_text]
        better = sum(1 for r in same if r[4] < truth[4] - 1e-9)
        share = better / max(len(same), 1)
        est = share * size
        total_better += est
        print(f"{n:3d} {size:11,d} {len(same):8d} {better:11d} {share:7.1%} {est:11,.0f}")
    total_space = sum(populations.values())
    print(f"\nestimated topologies out-scoring the truth on tier-1 AICc: "
          f"{total_better:,.0f} of {total_space:,} ({total_better / total_space:.2%})")

    best = min(scored, key=lambda r: r[4])
    print(f"best sampled: AICc {best[4]:.3f} cost {best[3]:.5g} n={best[1]} p={best[2]}  "
          f"{best[0]}")
    if args.out:
        args.out.write_text(json.dumps([{"text": r[0], "n_elements": r[1], "n_params": r[2],
                                         "cost": r[3]} for r in scored]), encoding="utf-8")


if __name__ == "__main__":
    main()
