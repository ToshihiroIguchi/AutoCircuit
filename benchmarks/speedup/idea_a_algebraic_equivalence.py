"""Idea A: can a closed-form algebraic map predict a same-size equivalent topology's fitted
parameters from the first one's fit, so the second one never needs its own optimisation run?

**What "equivalent" means here, precisely -- and why it is not what a first guess assumes.**
``R1-p(R2,C1)`` (R1 in series with R2||C1) and ``p(R1,C1-R2)`` (R1 in parallel with C1-R2 in
series) do **not** compute the same impedance for the *same* (R1,R2,C1) -- direct algebra shows
their DC/HF limits and pole location are different functions of the raw parameters. What makes
this project's discovered "equivalence" (`R1-p(R2,C1)` and `p(R1,C1-R2)` fitting the same data to
1.2e-15, per `CLAUDE.md`) is that **both topologies are universal realisations of the same
3-parameter family of first-order positive-real impedances** (DC value, HF value, pole
frequency) -- so there is a one-to-one *reparameterisation* between them, derived once here by
matching those three invariants:

    R1-p(R2,C1):    DC = R1+R2,               HF = R1,                 wp = 1/(R2*C1)
    p(R1,C1-R2):    DC = R1',                 HF = R1'*R2'/(R1'+R2'),  wp = 1/(C1'*(R1'+R2'))

Solving DC=DC', HF=HF', wp=wp' for (R1',R2',C1') in terms of (R1,R2,C1):

    R1' = R1 + R2
    R2' = R1*(R1+R2)/R2
    C1' = R2**2 * C1 / (R1+R2)**2

**Test 1 (sanity):** this closed form is verified to be an exact algebraic identity -- not a
fitted coincidence -- by evaluating both impedance functions at many random complex frequencies
and random (R1,R2,C1) and checking agreement to double-precision tolerance. Two degree-(1,1)
rational functions that agree at far more points than their combined degree requires must be
identical, so this is conclusive without symbolic algebra.

**Test 2 (the actual speedup question):** fit ``R1-p(R2,C1)`` to real noisy data with the
production `fit()`, apply the closed form to its fitted (R1,R2,C1), and check whether that
*prediction* matches what an independent full `fit()` of ``p(R1,C1-R2)`` on the same data actually
finds -- if so, the second topology's entire optimisation (tier-1 screen and tier-2 refit both)
could be replaced by one closed-form evaluation.

Decision rule, fixed before running: ships only if the predicted and independently-fitted
parameters for the second topology agree to within 1% on every parameter, across multiple noise
seeds -- the same tolerance the project's own equivalence check (`EQUIVALENCE_RTOL` is far
tighter, but 1% is enough to prove the prediction is usable as a *screening* substitute, which is
the actual use case).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SPEEDUP_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _SPEEDUP_DIR.parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from autocircuit.core.fit import fit  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402


def map_series_to_parallel(r1: float, r2: float, c1: float) -> tuple[float, float, float]:
    """(R1,R2,C1) of `R1-p(R2,C1)` -> (R1',R2',C1') of the equivalent `p(R1,C1-R2)`."""
    r1p = r1 + r2
    r2p = r1 * (r1 + r2) / r2
    c1p = r2**2 * c1 / (r1 + r2) ** 2
    return r1p, r2p, c1p


def _impedance_series(omega: np.ndarray, r1: float, r2: float, c1: float) -> np.ndarray:
    return r1 + 1.0 / (1.0 / r2 + 1j * omega * c1)


def _impedance_parallel(omega: np.ndarray, r1: float, r2: float, c1: float) -> np.ndarray:
    z_branch = r2 + 1.0 / (1j * omega * c1)
    return 1.0 / (1.0 / r1 + 1.0 / z_branch)


def test1_algebraic_identity(n_trials: int = 200, seed: int = 0) -> bool:
    rng = np.random.default_rng(seed)
    worst = 0.0
    for _ in range(n_trials):
        r1, r2 = 10.0 ** rng.uniform(-1, 5, size=2)
        c1 = 10.0 ** rng.uniform(-9, -3)
        r1p, r2p, c1p = map_series_to_parallel(r1, r2, c1)
        omega = 10.0 ** rng.uniform(-3, 8, size=20)
        za = _impedance_series(omega, r1, r2, c1)
        zb = _impedance_parallel(omega, r1p, r2p, c1p)
        rel = np.max(np.abs(za - zb) / np.abs(za))
        worst = max(worst, float(rel))
    print(f"test 1 (algebraic identity): worst relative error over {n_trials} trials = {worst:.3e}")
    return worst < 1e-9


def test2_prediction_vs_independent_fit(seeds=range(10)) -> None:
    true_r1, true_r2, true_c1 = 47.0, 3300.0, 2.2e-6
    freqs = log_frequencies(1e0, 1e6, 15)

    print("\ntest 2: predicted vs independently-fitted p(R1,C1-R2) parameters")
    print(f"{'seed':>4} {'R1 pred':>12} {'R1 fit':>12} {'R2 pred':>12} {'R2 fit':>12} "
          f"{'C1 pred':>12} {'C1 fit':>12} {'max err %':>10}")
    max_errs = []
    for seed in seeds:
        spectrum = simulate(
            "R1-p(R2,C1)", freqs, {"R1.R": true_r1, "R2.R": true_r2, "C1.C": true_c1},
            noise=0.01, seed=seed,
        )
        result_a = fit("R1-p(R2,C1)", spectrum, seed=seed)
        r1a, r2a, c1a = result_a.values
        r1p, r2p, c1p = map_series_to_parallel(r1a, r2a, c1a)

        result_b = fit("p(R1,C1-R2)", spectrum, seed=seed)
        # p(R1,C1-R2) param order: R1.R, C1.C, R2.R (declaration order in the DSL string)
        names_b = list(result_b.circuit.param_names)
        r1b = result_b.values[names_b.index("R1.R")]
        c1b = result_b.values[names_b.index("C1.C")]
        r2b = result_b.values[names_b.index("R2.R")]

        err = max(
            abs(r1p - r1b) / r1b, abs(r2p - r2b) / r2b, abs(c1p - c1b) / c1b
        ) * 100
        max_errs.append(err)
        print(
            f"{seed:>4} {r1p:>12.4g} {r1b:>12.4g} {r2p:>12.4g} {r2b:>12.4g} "
            f"{c1p:>12.4g} {c1b:>12.4g} {err:>10.3f}"
        )

    print(f"\nworst max-parameter error across {len(list(seeds))} seeds: {max(max_errs):.3f}%")
    print(f"decision rule (<=1% on every parameter, every seed): "
          f"{'PASS' if max(max_errs) <= 1.0 else 'FAIL'}")


def main() -> None:
    ok = test1_algebraic_identity()
    print(f"algebraic identity confirmed: {ok}")
    if not ok:
        print("closed form is wrong -- stopping before test 2.")
        return
    test2_prediction_vs_independent_fit()


if __name__ == "__main__":
    main()
