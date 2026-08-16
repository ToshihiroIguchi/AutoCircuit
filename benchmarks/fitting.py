"""Fitting-engine benchmarks: accuracy, uncertainty calibration, and restart tuning.

These are measurements, not tests. The test suite asserts that the fitter works; these
scripts say *how well*, and are the source of the **[measured]** claims in
``docs/IMPLEMENTATION_PLAN.md``. Re-run them after changing the optimizer.

Usage (needs PYTHONPATH=src)::

    python benchmarks/fitting.py accuracy      # parameter recovery, 0% and 1% noise
    python benchmarks/fitting.py calibration   # are the reported standard errors honest?
    python benchmarks/fitting.py restarts      # how many restarts are actually needed?
"""

from __future__ import annotations

import sys
import time

import numpy as np

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import fit
from autocircuit.core.simulate import log_frequencies, simulate

# (label, circuit, true parameters, f_min, f_max)
SUITE = [
    ("capacitor C-ESR-ESL", "C1-R1-L1", {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}, 1e2, 1e9),
    (
        "capacitor + skin effect",
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        1e2,
        1e9,
    ),
    (
        "Randles",
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 100.0, "W1.A": 150.0},
        1e-2,
        1e5,
    ),
    (
        "Maxwell-Wagner, 2 blocks",
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        1e-1,
        1e7,
    ),
    (
        "brick layer + CPE",
        "R1-p(R2,C1)-p(R3,CPE1)",
        {"R1.R": 50.0, "R2.R": 1e4, "C1.C": 1e-10, "R3.R": 8e4, "CPE1.Q": 3e-9, "CPE1.n": 0.8},
        1e-1,
        1e7,
    ),
]

#: The hardest case in the suite; used for the restart sweep.
HARD = SUITE[-1]


def canonical(circuit: Circuit, values: dict[str, float] | np.ndarray) -> dict[str, float]:
    """Parameters in canonical branch order, so a relabelling is not counted as an error."""
    array = circuit.values_array(values) if isinstance(values, dict) else np.asarray(values)
    return circuit.values_dict(circuit.canonicalize_values(array))


def run_accuracy() -> None:
    for noise in (0.0, 0.01):
        print(f"\n=== parameter recovery, noise = {noise:.1%} ===")
        for label, dsl, truth, f_min, f_max in SUITE:
            circuit = Circuit.parse(dsl)
            data = simulate(circuit, log_frequencies(f_min, f_max, 10), truth, noise=noise,
                            seed=0)
            started = time.perf_counter()
            result = fit(circuit, data, seed=0)
            elapsed = time.perf_counter() - started

            expected = canonical(circuit, truth)
            got = canonical(circuit, result.values)
            worst = max(abs(got[k] - v) / abs(v) for k, v in expected.items())
            print(
                f"  {label:<26}n={circuit.n_params}  worst={worst:7.2%}  "
                f"rel|Z|={result.relative_error:7.3%}  t={elapsed:5.2f}s"
            )


def run_calibration(trials: int = 25, noise: float = 0.01) -> None:
    """A z-score is (fitted - true) / reported stderr. It should look like N(0, 1)."""
    for label, dsl, truth, f_min, f_max in (SUITE[1], SUITE[4]):
        circuit = Circuit.parse(dsl)
        f = log_frequencies(f_min, f_max, 10)
        scores: dict[str, list[float]] = {name: [] for name in truth}
        for trial in range(trials):
            data = simulate(circuit, f, truth, noise=noise, seed=1000 + trial)
            result = fit(circuit, data, seed=trial)
            errors = result.stderr
            for name, true_value in truth.items():
                if errors[name] > 0:
                    scores[name].append((result.params[name] - true_value) / errors[name])

        print(f"\n{label} ({trials} noise realisations at {noise:.0%})")
        print(f"  {'parameter':<12}{'mean z':>9}{'std z':>9}{'|z|<2':>8}  (ideal 0.0, 1.0, ~95%)")
        for name, values in scores.items():
            array = np.array(values)
            print(
                f"  {name:<12}{array.mean():>9.2f}{array.std():>9.2f}"
                f"{np.mean(np.abs(array) < 2.0):>8.0%}"
            )


def run_restarts(trials: int = 25) -> None:
    label, dsl, truth, f_min, f_max = HARD
    circuit = Circuit.parse(dsl)
    f = log_frequencies(f_min, f_max, 10)
    datasets = [simulate(circuit, f, truth, noise=0.01, seed=1000 + t) for t in range(trials)]

    print(f"\n=== restart sweep on '{label}' ({trials} noise realisations) ===")
    print(f"{'restarts':>9}{'popsize':>9}{'failures':>10}{'worst err':>11}{'mean t':>9}")
    for restarts, popsize in ((3, 20), (5, 20), (8, 20), (3, 40), (5, 40)):
        failures = 0
        worst_overall = 0.0
        started = time.perf_counter()
        for trial, data in enumerate(datasets):
            result = fit(circuit, data, restarts=restarts, popsize=popsize, seed=trial)
            worst = max(abs(result.params[k] - v) / abs(v) for k, v in truth.items())
            if worst > 0.2:
                failures += 1
            else:
                worst_overall = max(worst_overall, worst)
        elapsed = (time.perf_counter() - started) / trials
        print(
            f"{restarts:>9}{popsize:>9}{failures:>4}/{trials:<5}"
            f"{worst_overall:>11.2%}{elapsed:>9.2f}s"
        )


COMMANDS = {"accuracy": run_accuracy, "calibration": run_calibration, "restarts": run_restarts}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "accuracy"
    if name not in COMMANDS:
        raise SystemExit(f"usage: fitting.py [{'|'.join(COMMANDS)}]")
    COMMANDS[name]()
