"""Idea G: does per-block, per-frequency-band local fitting produce a warm start good enough to
replace the global DE stage entirely with a cheap local polish?

**Method.** For a truth with N series `p(R,C)` blocks whose relaxation frequencies are spread
across the sweep (`mw5`, `mw6`), split the frequency axis into N equal log-decade sub-bands (one
per block, in the same order the blocks appear -- their tuned time constants are monotonic by
construction of the leverage-maximising tuner, which tends to spread them out). Fit a *lone*
`p(R,C)` block to the data restricted to each sub-band alone (a cheap 2-parameter local
least-squares, no global search needed for a single relaxation), assemble the N per-band
estimates into one initial guess for the *full* circuit, and run only a **local polish** from
that guess -- no `differential_evolution` at all. Compare its final cost against the production
pipeline's full global-DE-plus-polish, at the same total budget class (one local polish vs one
full screen).

Decision rule, fixed before running: worth prototyping into `discover.py` only if the
band-warm-start route reaches within the same basin (`cost <= best_known * 1.1`) at least as
often as the production screen, since its whole appeal is replacing an expensive global search
with N cheap local ones.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

_SPEEDUP_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _SPEEDUP_DIR.parent
sys.path.insert(0, str(_SPEEDUP_DIR))
sys.path.insert(0, str(_BENCH_DIR / "screening_round"))

import harness  # noqa: E402
from param_opt import _polish  # noqa: E402
from truths import MW5, MW6, spectrum_for  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.fit import _Problem, screen  # noqa: E402

SEEDS = range(120)
SCREEN_POPSIZE, SCREEN_MAXITER = 8, 40  # matches discover.py's tier-1 budget


def band_warm_start(omega: np.ndarray, z: np.ndarray, n_blocks: int) -> list[tuple[float, float]]:
    """Fit a lone R||C block to each of n_blocks equal log-decade sub-bands.

    Returns [(R,C), ...].
    """
    log_omega = np.log10(omega)
    edges = np.linspace(log_omega.min(), log_omega.max(), n_blocks + 1)
    out: list[tuple[float, float]] = []
    for i in range(n_blocks):
        mask = (log_omega >= edges[i]) & (log_omega <= edges[i + 1])
        if mask.sum() < 3:
            mask = np.ones_like(log_omega, dtype=bool)  # degenerate band: fall back to everything
        w, zw = omega[mask], z[mask]

        def residuals(x, w=w, zw=zw):
            r, c = 10.0 ** x[0], 10.0 ** x[1]
            model = r / (1 + 1j * w * r * c)
            return np.concatenate([(model.real - zw.real), (model.imag - zw.imag)])

        r0 = float(np.median(np.abs(zw)))
        c0 = 1.0 / (float(np.median(w)) * max(r0, 1e-9))
        try:
            result = least_squares(
                residuals, x0=[np.log10(max(r0, 1e-9)), np.log10(max(c0, 1e-15))],
                method="lm", max_nfev=500,
            )
            r_fit, c_fit = 10.0 ** result.x[0], 10.0 ** result.x[1]
        except Exception:
            r_fit, c_fit = r0, c0
        out.append((r_fit, c_fit))
    return out


def run_one(truth) -> None:
    circuit = Circuit.parse(truth.circuit)
    n_blocks = len(truth.circuit.split("-p("))  # "p(R1,C1)-p(R2,C2)-..." -> count of blocks
    names = list(circuit.param_names)

    band_costs = []
    screen_costs = []
    for seed in SEEDS:
        spectrum = spectrum_for(truth, seed=seed)
        problem = _Problem(circuit, spectrum, "modulus", None, {}, None, 3.0)

        blocks = band_warm_start(spectrum.omega, spectrum.z, n_blocks)
        x0 = np.zeros(len(names))
        for i, (r, c) in enumerate(blocks, start=1):
            x0[names.index(f"R{i}.R")] = np.log10(max(r, 1e-9))
            x0[names.index(f"C{i}.C")] = np.log10(max(c, 1e-15))
        x0 = np.clip(x0, problem.lower_x, problem.upper_x)
        band_cost = _polish(problem, x0)
        band_costs.append(band_cost)

        screen_costs.append(
            screen(
                truth.circuit,
                spectrum,
                seed=seed,
                popsize=SCREEN_POPSIZE,
                maxiter=SCREEN_MAXITER,
            )
        )

    best_known = min(band_costs + screen_costs)
    band_hits = sum(1 for c in band_costs if c <= best_known * 1.1)
    screen_hits = sum(1 for c in screen_costs if c <= best_known * 1.1)

    print(f"\n{truth.id}, {len(SEEDS)} seeds, best known cost = {best_known:.6g}")
    lo_b, hi_b = harness.wilson(band_hits, len(SEEDS))
    lo_s, hi_s = harness.wilson(screen_hits, len(SEEDS))
    print(
        f"  band warm-start + local polish only: {band_hits}/{len(SEEDS)} "
        f"in basin [{lo_b:.3f},{hi_b:.3f}]"
    )
    print(
        f"  production tier-1 screen (global DE): {screen_hits}/{len(SEEDS)} "
        f"in basin [{lo_s:.3f},{hi_s:.3f}]"
    )
    print(f"  CIs overlap: {harness.wilson_overlap((lo_b, hi_b), (lo_s, hi_s))}")


def main() -> None:
    run_one(MW5)
    run_one(MW6)


if __name__ == "__main__":
    main()
