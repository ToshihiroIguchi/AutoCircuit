"""Idea B: can the Loewner-matrix singular-value decay of Z(f) tell, before any topology is
enumerated, how many reactive elements (the McMillan degree of Z(s)) a spectrum needs?

**Why this is not the same experiment `docs/TOPOLOGY_6PLUS_PLAN.md` (d) already ran and rejected.**
That measurement (`scipy.interpolate.AAA`, a Loewner pencil, a stabilisation diagram) tried to
*reconstruct* the rational function -- recover the actual poles/zeros/residues well enough to
synthesise a circuit -- and found it "exact without noise and useless with noise" (0.04-0.20
exact-recovery at 1% noise). Order estimation is a much weaker question: not *what are the
poles*, just *how many are there*. The singular values of a Loewner matrix built from noisy data
decay to a noise floor rather than to exactly zero, and the number of singular values clearly
above that floor is a coarse, non-reconstructive read of the system order -- this script measures
whether that coarser read survives noise where full reconstruction did not.

**Method.** For each truth, split the (already-noisy) frequency samples into two interleaved
sets -- "right" points ``(lambda_k, f_k=Z(lambda_k))`` and "left" points ``(mu_j, g_j=Z(mu_j))``,
``lambda=mu=j*omega`` -- and build the Loewner matrix ``L[j,k] = (g_j - f_k)/(mu_j - lambda_k)``.
For a system of true order ``n`` and noise-free data, ``L`` has rank exactly ``n`` (Antoulas'
Loewner framework); its singular values should show ``n`` "large" values and the rest at exactly
zero. With noise, the "rest" sit at a noise floor instead of zero, and the estimated order is the
number of singular values clearly above that floor.

Two order estimators are compared, since neither is obviously better a priori:

* **gap**: the index of the largest ratio ``s[k]/s[k+1]`` (scale-free, does not need to know the
  noise level).
* **threshold**: count of singular values ``> factor * s[0] * noise`` for a fixed ``factor`` --
  needs the noise level, which this project already estimates in production (`core/noise.py`),
  but is tested here against the *true* noise level to separate "does the idea work at all" from
  "does the noise estimator feed it well".

Decision rule, fixed before running: usable as a production pre-filter only if, at the project's
standard cell (1% noise, 10 points/decade), the estimated order equals the true order on a clear
majority of the truths tried, for at least one estimator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW4CPE, MW5, MW6, SRF2, SRF2_CLOSE, SRF3, SRF3_CLOSE, spectrum_for  # noqa: E402

#: True reactive-element count (McMillan degree of Z(s)) for each truth built from ideal R/L/C.
#: mw4cpe is excluded: a CPE makes Z(s) non-rational, so "order" is not well defined for it.
TRUE_ORDER: dict[str, int] = {
    "mw5": 5,
    "mw6": 6,
    "srf2": 4,
    "srf2_close": 4,
    "srf3": 6,
    "srf3_close": 6,
}

NOISE_LEVELS = (0.0, 0.001, 0.01, 0.05)
SEEDS = range(10)
MAX_ORDER_CONSIDERED = 12


def loewner_singular_values(omega: np.ndarray, z: np.ndarray) -> np.ndarray:
    lam = 1j * omega[0::2]
    mu = 1j * omega[1::2]
    f = z[0::2]
    g = z[1::2]
    n1, n2 = len(lam), len(mu)
    n = min(n1, n2)  # use every available point -- truncating to the first n (lowest
    lam, f = lam[:n], f[:n]  # frequencies) hid every higher-frequency relaxation entirely.
    mu, g = mu[:n], g[:n]  # [measured] this was the real bug behind the first run's failure.
    L = (g[:, None] - f[None, :]) / (mu[:, None] - lam[None, :])
    return np.linalg.svd(L, compute_uv=False)


def estimate_order_gap(s: np.ndarray) -> int:
    ratios = s[:-1] / np.maximum(s[1:], 1e-300)
    return int(np.argmax(ratios)) + 1


def estimate_order_threshold(s: np.ndarray, noise: float, factor: float = 5.0) -> int:
    if noise <= 0.0:
        floor = s[-1] * 10.0  # noise-free: use the numerical floor itself, scaled up a bit
    else:
        floor = factor * s[0] * noise
    return int(np.sum(s > floor))


def run_one(truth_id: str) -> None:
    from truths import REGISTRY

    truth = REGISTRY[truth_id]
    true_order = TRUE_ORDER[truth_id]
    print(f"\n{truth_id} (true order {true_order}):")
    for noise in NOISE_LEVELS:
        gap_hits = 0
        thr_hits = 0
        for seed in SEEDS:
            spectrum = spectrum_for(truth, noise=noise, seed=(None if noise == 0.0 else seed))
            s = loewner_singular_values(spectrum.omega, spectrum.z)
            gap_order = estimate_order_gap(s)
            thr_order = estimate_order_threshold(s, noise)
            gap_hits += int(gap_order == true_order)
            thr_hits += int(thr_order == true_order)
            if noise == 0.0:
                break  # noise-free is deterministic; one draw suffices
        n = 1 if noise == 0.0 else len(SEEDS)
        print(
            f"  noise={noise:.3f}: gap estimator {gap_hits}/{n} correct, "
            f"threshold estimator {thr_hits}/{n} correct"
        )


def main() -> None:
    for truth_id in TRUE_ORDER:
        run_one(truth_id)


if __name__ == "__main__":
    main()
