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
from dataclasses import dataclass

import numpy as np

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import fit
from autocircuit.core.simulate import log_frequencies, simulate


@dataclass(frozen=True)
class Case:
    """One reference circuit, its true parameters, and the sweep it is measured over.

    A record rather than a tuple because two of the cases below need a sweep the others do
    not: ``points_per_decade`` was a literal ``10`` in three places until the piezoelectric
    resonator arrived, and that case is unmeasurable at 10 points per decade (see its own
    comment). The suite is also selected from *by label* rather than by index -- ``HARD`` was
    ``SUITE[-1]`` and the calibration pair was ``(SUITE[1], SUITE[4])``, so appending a case
    silently moved the restart sweep onto a different circuit while still printing the old
    circuit's heading.
    """

    label: str
    dsl: str
    truth: dict[str, float]
    f_min: float
    f_max: float
    points_per_decade: int = 10

    def frequencies(self) -> np.ndarray:
        return log_frequencies(self.f_min, self.f_max, self.points_per_decade)


SUITE = [
    Case("capacitor C-ESR-ESL", "C1-R1-L1", {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}, 1e2, 1e9),
    Case(
        "capacitor + skin effect",
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        1e2,
        1e9,
    ),
    Case(
        "Randles",
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 100.0, "W1.A": 150.0},
        1e-2,
        1e5,
    ),
    Case(
        "Maxwell-Wagner, 2 blocks",
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        1e-1,
        1e7,
    ),
    Case(
        "brick layer + CPE",
        "R1-p(R2,C1)-p(R3,CPE1)",
        {"R1.R": 50.0, "R2.R": 1e4, "C1.C": 1e-10, "R3.R": 8e4, "CPE1.Q": 3e-9, "CPE1.n": 0.8},
        1e-1,
        1e7,
    ),
    # Four parallel RC blocks in series: the Voigt (Maxwell) ladder, which is what a
    # multi-relaxation dielectric or ceramic (grain / grain boundary / two interfaces) reduces
    # to, and the same series form the linear Kramers-Kronig test fits internally. It is here
    # for *scale* rather than for degeneracy -- eight free parameters, the largest in the
    # suite -- so the time constants are placed ~2 decades apart (1e-7, 9e-6, 1e-3, 8e-2 s)
    # where every block is separately resolvable. The deliberately hard, overlapping version
    # lives in ``benchmarks/discovery_v2.py`` as ``LARGE_REFERENCES[0]``, whose last two blocks
    # are 0.6 decades apart; measuring both under one label would confuse "can the fitter carry
    # eight parameters" with "can the data separate two relaxations", which are different
    # questions with different answers.
    #
    # Swapping any two blocks' labels is the same circuit, so recovery is only meaningful
    # after ``canonicalize_values`` -- which is what ``canonical()`` below exists for.
    # [measured] 0/8 parameters unresolved at 1% noise, worst deviation 2.8% over 5 seeds.
    Case(
        "Voigt ladder, 4 blocks",
        "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)",
        {
            "R1.R": 2e3,
            "C1.C": 5e-11,
            "R2.R": 3e3,
            "C2.C": 3e-9,
            "R3.R": 5e3,
            "C3.C": 2e-7,
            "R4.R": 8e3,
            "C4.C": 1e-5,
        },
        1e-2,
        1e7,
    ),
    # A piezoelectric resonator as the Butterworth-Van Dyke model: the clamped capacitance C0
    # in parallel with a motional branch R1-L1-C1. It is the only case in the suite with a
    # *resonance* rather than a relaxation, and the only one built from R, C and L alone --
    # which is the point, because everything else here is over-damped and a resonant circuit
    # exercises the optimizer on a feature that occupies a hundredth of the sweep.
    #
    # The numbers are a soft-PZT disc: fs = 198.94 kHz, fp = 208.65 kHz, mechanical Q = 100,
    # capacitance ratio C1/C0 = 0.1.
    #
    # **The sweep is part of the reference, not a detail.** A resonance of quality factor Q is
    # only ~1/Q wide, so resolving it needs roughly ``8 * ln(10) * Q`` points per decade -- 1500
    # here, for ~8 points inside the -3 dB width. That is also why the window is 0.2 decades
    # wide rather than the several decades the other cases use: a log sweep cannot
    # simultaneously span a wide band and resolve a Q = 100 peak at any sane point count, which
    # is exactly why resonator measurement is done as a narrow sweep around fs.
    #
    # What the sweep buys is precision, and only precision. The guess this comment first
    # carried was that the case would be unmeasurable at the suite's 10 points per decade;
    # [measured] it is not. The three points left in this window at 10 per decade recover all
    # four parameters exactly from noise-free data, and leave none unresolved at 1% noise --
    # what moves is the worst deviation over 10 seeds, 0.29% at 1500 points per decade against
    # 9.9% at 10. ``tests/test_fit.py::test_the_resonator_earns_its_sweep`` pins that ratio.
    Case(
        "piezo resonator (BVD)",
        "p(C1,R1-L1-C2)",
        {"C1.C": 2e-9, "R1.R": 40.0, "L1.L": 3.2e-3, "C2.C": 2e-10},
        1.6e5,
        2.6e5,
        points_per_decade=1500,
    ),
]


def case(label: str) -> Case:
    """The suite entry with this label. By name, never by index: see :class:`Case`."""
    for entry in SUITE:
        if entry.label == label:
            return entry
    raise KeyError(label)


#: The hardest case in the suite; used for the restart sweep. Six parameters, three of which
#: trade against each other. Pinned by label so that appending to ``SUITE`` cannot move it --
#: the numbers in ``benchmarks/README.md`` are this circuit's.
HARD = case("brick layer + CPE")

#: The calibration pair, also pinned by label. Two relaxation cases plus the two additions --
#: eight parameters, and a resonance, both of which are new shapes for the covariance estimate
#: rather than more of the same.
CALIBRATION = [
    case("capacitor + skin effect"),
    case("brick layer + CPE"),
    case("Voigt ladder, 4 blocks"),
    case("piezo resonator (BVD)"),
]


def canonical(circuit: Circuit, values: dict[str, float] | np.ndarray) -> dict[str, float]:
    """Parameters in canonical branch order, so a relabelling is not counted as an error."""
    array = circuit.values_array(values) if isinstance(values, dict) else np.asarray(values)
    return circuit.values_dict(circuit.canonicalize_values(array))


def run_accuracy() -> None:
    for noise in (0.0, 0.01):
        print(f"\n=== parameter recovery, noise = {noise:.1%} ===")
        for entry in SUITE:
            circuit = Circuit.parse(entry.dsl)
            data = simulate(circuit, entry.frequencies(), entry.truth, noise=noise, seed=0)
            started = time.perf_counter()
            result = fit(circuit, data, seed=0)
            elapsed = time.perf_counter() - started

            expected = canonical(circuit, entry.truth)
            got = canonical(circuit, result.values)
            worst = max(abs(got[k] - v) / abs(v) for k, v in expected.items())
            print(
                f"  {entry.label:<26}n={circuit.n_params}  worst={worst:7.2%}  "
                f"rel|Z|={result.relative_error:7.3%}  t={elapsed:5.2f}s"
            )


def run_calibration(trials: int = 25, noise: float = 0.01) -> None:
    """A z-score is (fitted - true) / reported stderr. It should look like N(0, 1)."""
    for entry in CALIBRATION:
        circuit = Circuit.parse(entry.dsl)
        f = entry.frequencies()
        scores: dict[str, list[float]] = {name: [] for name in entry.truth}
        for trial in range(trials):
            data = simulate(circuit, f, entry.truth, noise=noise, seed=1000 + trial)
            result = fit(circuit, data, seed=trial)
            errors = result.stderr
            for name, true_value in entry.truth.items():
                if errors[name] > 0:
                    scores[name].append((result.params[name] - true_value) / errors[name])

        print(f"\n{entry.label} ({trials} noise realisations at {noise:.0%})")
        print(f"  {'parameter':<12}{'mean z':>9}{'std z':>9}{'|z|<2':>8}  (ideal 0.0, 1.0, ~95%)")
        for name, values in scores.items():
            array = np.array(values)
            print(
                f"  {name:<12}{array.mean():>9.2f}{array.std():>9.2f}"
                f"{np.mean(np.abs(array) < 2.0):>8.0%}"
            )


def run_restarts(trials: int = 25) -> None:
    circuit = Circuit.parse(HARD.dsl)
    truth = HARD.truth
    f = HARD.frequencies()
    datasets = [simulate(circuit, f, truth, noise=0.01, seed=1000 + t) for t in range(trials)]

    print(f"\n=== restart sweep on '{HARD.label}' ({trials} noise realisations) ===")
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
