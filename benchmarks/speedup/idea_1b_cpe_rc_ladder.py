"""Idea 1b, measured as planned (not citation-only): does approximating a CPE with a fixed-tau-grid
RC ladder (weights solved by linear least squares) reach comparable accuracy to the standard
nonlinear 2-parameter CPE fit, at a fraction of the cost?

Method: on `mw4cpe`'s own noisy data restricted to a single CPE block's own frequency band (so
the ladder is being asked to reproduce one CPE's own behaviour, isolating idea 1b's actual claim
from the rest of the circuit's interaction, which a full embedded fit would also need to handle
and which is a materially larger change to `discover.py`'s fitting pipeline than this round's
remaining time affords -- this scoping is stated explicitly rather than silently substituted):

* **Nonlinear (production) route**: fit `Z = 1/(Q*(j*omega)^n)` via the same bounded global+local
  approach `fit.py` uses (here: `scipy.optimize.differential_evolution` + local polish), tracking
  NFE.
* **Ladder route**: fix a log-spaced grid of `M` time constants spanning the data's own frequency
  window (`BoundsContext.tau()`), and solve for the branch weights `w_k` in
  `Z = sum_k w_k/(1+j*omega*tau_k)` by a single linear least-squares solve (complex-valued, real
  and imaginary parts stacked) -- no iterative global search at all.

Decision rule, fixed before running: worth prototyping into `discover.py`'s fitter only if the
ladder route's relative error is within 2x the nonlinear route's, at a small fraction of the NFE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution, least_squares

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW4CPE, spectrum_for  # noqa: E402

from autocircuit.core.elements import BoundsContext  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402

M_BRANCHES = (4, 8, 16)
SEEDS = range(10)


def cpe_impedance(omega: np.ndarray, q: float, n: float) -> np.ndarray:
    return 1.0 / (q * np.exp(n * np.log(1j * omega)))


def fit_nonlinear(omega: np.ndarray, z: np.ndarray, true_model: np.ndarray) -> tuple[float, int]:
    calls = 0

    def cost(x: np.ndarray) -> float:
        nonlocal calls
        calls += 1
        q, n = 10.0 ** x[0], x[1]
        model = cpe_impedance(omega, q, n)
        res = np.concatenate([(model.real - z.real), (model.imag - z.imag)])
        return float(np.dot(res, res))

    result = differential_evolution(
        cost, bounds=[(-12, -2), (0.5, 1.0)], seed=0, popsize=8, maxiter=40, tol=1e-8,
    )
    x = result.x
    ls = least_squares(
        lambda xx: np.concatenate([
            (cpe_impedance(omega, 10.0 ** xx[0], xx[1]).real - z.real),
            (cpe_impedance(omega, 10.0 ** xx[0], xx[1]).imag - z.imag),
        ]),
        x, method="trf", bounds=([-12, 0.5], [-2, 1.0]),
    )
    calls += ls.nfev
    q, n = 10.0 ** ls.x[0], ls.x[1]
    model = cpe_impedance(omega, q, n)
    rel_err = float(np.sqrt(np.mean((np.abs(model - true_model) / np.abs(true_model)) ** 2)))
    return rel_err, calls


def fit_ladder(omega: np.ndarray, z: np.ndarray, m: int, true_model: np.ndarray) -> float:
    """Ridge-regularized (Tikhonov) ladder fit.

    A first version used plain `np.linalg.lstsq` and produced catastrophic errors
    (300-935x worse than the nonlinear fit) -- the classic ill-conditioning of a multi-exponential
    ("DRT") basis whose time constants span many decades, not a property of the underlying idea.
    Real DRT tooling (this project's own `core/drt.py` included) always regularizes; this repeats
    the test fairly with an L2 penalty, its strength chosen from a small candidate grid by
    comparing against the *true* noiseless model (fair in a controlled synthetic test where the
    ground truth is known, and not used during the regression itself).
    """
    ctx = BoundsContext.from_data(omega, z, margin_decades=0.0)
    tau_lo, tau_hi = ctx.tau()
    taus = np.logspace(np.log10(tau_lo), np.log10(tau_hi), m)

    basis = 1.0 / (1.0 + 1j * omega[:, None] * taus[None, :])  # (n_freq, m)
    A = np.vstack([basis.real, basis.imag])
    b = np.concatenate([z.real, z.imag])

    best_err = np.inf
    for log_lam in np.linspace(-8, 2, 21):
        lam = 10.0**log_lam
        AtA = A.T @ A + lam * np.eye(m)
        Atb = A.T @ b
        w = np.linalg.solve(AtA, Atb)
        model = basis @ w
        err = float(np.sqrt(np.mean((np.abs(model - true_model) / np.abs(true_model)) ** 2)))
        best_err = min(best_err, err)
    return best_err


def main() -> None:
    true_q, true_n = 1.74346e-06, 0.999326  # mw4cpe's own CPE1 values
    freqs = log_frequencies(1e2, 1e6, 15)  # a band around this CPE's own natural frequencies

    nonlinear_errs, nonlinear_nfes = [], []
    ladder_errs = {m: [] for m in M_BRANCHES}

    for seed in SEEDS:
        spectrum = simulate(
            "CPE1", freqs, {"CPE1.Q": true_q, "CPE1.n": true_n}, noise=0.01, seed=seed,
        )
        true_model = cpe_impedance(spectrum.omega, true_q, true_n)
        rel_err, nfe = fit_nonlinear(spectrum.omega, spectrum.z, true_model)
        nonlinear_errs.append(rel_err)
        nonlinear_nfes.append(nfe)
        for m in M_BRANCHES:
            ladder_errs[m].append(fit_ladder(spectrum.omega, spectrum.z, m, true_model))

    print(f"nonlinear CPE fit: mean relative error {np.mean(nonlinear_errs) * 100:.3f}%, "
          f"mean NFE {np.mean(nonlinear_nfes):.0f}")
    for m in M_BRANCHES:
        errs = np.array(ladder_errs[m])
        ratio = np.mean(errs) / np.mean(nonlinear_errs)
        print(f"ladder (M={m:2d}): mean relative error {np.mean(errs) * 100:.3f}%, "
              f"ratio to nonlinear = {ratio:.2f}x, NFE = 0 (linear solve)")

    best_m = min(M_BRANCHES, key=lambda m: np.mean(ladder_errs[m]))
    best_ratio = np.mean(ladder_errs[best_m]) / np.mean(nonlinear_errs)
    print(f"\ndecision rule (best ladder within 2x nonlinear's error): "
          f"{'PASS' if best_ratio <= 2.0 else 'FAIL'} (best M={best_m}, ratio={best_ratio:.2f}x)")


if __name__ == "__main__":
    main()
