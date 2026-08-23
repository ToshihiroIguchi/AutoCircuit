"""Where does one tier-1 topology evaluation actually spend its time?

This is the measurement that decides whether "rewrite it in C++" is even on the table. The
genetic search's problem is `cost per topology x topologies needed`; the arms experiment
addresses the second factor, and this addresses the first. Two outcomes point in opposite
directions:

* if most of the time is inside the impedance/residual kernel, a compiled kernel (or a batched
  numpy rewrite) buys a proportional speed-up and nothing else has to change;
* if most of it is scipy's own differential-evolution bookkeeping, then only replacing the
  optimiser helps, and a compiled kernel would be work spent on 20% of the clock.

Reported as *fractions of one process's own time*, which is what makes the reading survive a
loaded machine -- everything slows together.
"""

from __future__ import annotations

import cProfile
import pstats
import time
from io import StringIO

import numpy as np

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import _Problem, screen
from autocircuit.core.simulate import log_frequencies, simulate

TRUTH = "p(R1,C1)-p(R2,C2)-p(R3,C3)"
PARAMS = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 8e4, "C3.C": 5e-7}
CASES = ["p(R1,C1)-p(R2,C2)-p(R3,C3)", "R1-p(CPE1,R2)-p(R3,C1)-L1", "p(R1,C1)-p(R2,CPE1)-C2"]


def main() -> None:
    spectrum = simulate(TRUTH, log_frequencies(1e-2, 1e7, 10), PARAMS, noise=0.01, seed=0)
    print(f"spectrum: {len(spectrum.f)} points ({2 * len(spectrum.f)} real residuals)")

    # 1. How much of one screen is the cost function, and how much is scipy's own loop?
    for text in CASES:
        screen(text, spectrum, seed=0)  # warm the caches
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(3):
            screen(text, spectrum, seed=0)
        pr.disable()
        stream = StringIO()
        stats = pstats.Stats(pr, stream=stream)
        total = stats.total_tt
        buckets = {"kernel": 0.0, "scipy_de": 0.0, "least_squares": 0.0, "setup": 0.0}
        for (fname, _line, func), (_cc, _nc, tt, _ct, _cal) in stats.stats.items():
            if "elements.py" in fname or "circuit.py" in fname or func in (
                "cost_vectorized", "cost", "residuals", "to_values_batch"
            ):
                buckets["kernel"] += tt
            elif "_differentialevolution" in fname:
                buckets["scipy_de"] += tt
            elif "_lsq" in fname or "least_squares" in func or "trf" in fname:
                buckets["least_squares"] += tt
            else:
                buckets["setup"] += tt
        share = {k: v / total for k, v in buckets.items()}
        print(f"\n{text}")
        print(f"  {total / 3 * 1000:.0f} ms per screen (profiled, ~2x real)")
        for k, v in sorted(share.items(), key=lambda kv: -kv[1]):
            print(f"    {k:15s} {v:6.1%}")

    # 2. The raw cost of one population evaluation, against the arithmetic it contains.
    print("\ncost_vectorized throughput (the thing a compiled kernel would replace):")
    for text in CASES:
        circuit = Circuit.parse(text)
        problem = _Problem(circuit, spectrum, "modulus", None, {}, None, 3.0)
        n_free = len(problem.free_idx)
        for popsize in (1, 8, 120):
            xs = np.random.default_rng(0).uniform(
                problem.lower_x[:, None], problem.upper_x[:, None], size=(n_free, popsize)
            )
            problem.cost_vectorized(xs)
            t = time.perf_counter()
            reps = 200
            for _ in range(reps):
                problem.cost_vectorized(xs)
            dt = (time.perf_counter() - t) / reps
            print(f"  {text[:34]:34s} n_free={n_free} pop={popsize:4d} "
                  f"{dt * 1e6:8.1f} us/call  {dt / popsize * 1e6:7.2f} us/individual")


if __name__ == "__main__":
    main()
