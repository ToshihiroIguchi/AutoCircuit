"""Idea C: does reparameterising CPE's magnitude from Q to a resistor-like Z0 shrink the search
box enough to matter?

**What is already shipped, found before this was written.** CPE's search bounds are *not* a
universal 24-decade prior -- ``ConstantPhaseElement.bounds()`` (``src/autocircuit/core/elements.py``
:230-236) already derives them from the data via ``BoundsContext``: the union of the capacitive
extreme (``n->1``, ``Q ~ 1/(omega*|Z|)``) and the resistive extreme (``n->0``, ``Q ~ 1/|Z|``).
So the original hypothesis behind idea C -- "the prior is absurdly wide, narrow it" -- is already
false and this script does **not** re-measure it.

**What is not shipped.** The union of two different extremes is wider than either extreme alone,
and wider than it needs to be for whatever the true ``n`` actually is: at a fixed ``n`` in the
interior of ``[0.02, 1]``, the physically consistent range of the CPE's magnitude is much
narrower. This script tests a specific alternative: instead of searching ``log10(Q)`` directly,
search ``log10(Z0)`` where ``Z0 = |Z_CPE(omega_ref)| = 1/(Q * omega_ref**n)`` is the CPE's
impedance magnitude at the sweep's geometric-mean frequency -- a quantity with the same units and
the same natural range as a resistor (``ctx.resistance()``), for *any* n. ``Q`` is recovered as
``Q = 1/(Z0 * omega_ref**n)`` before the real ``_Problem`` ever sees it, so the objective function,
the polish stage and the reported fit are all untouched; only what differential_evolution's
population coordinates *mean* changes.

Decision rule, fixed before running: ships (recommended for a follow-up production change) only
if, on `mw4cpe` and on an existing CPE reference (`discovery_v2.REFERENCES`'s Randles+Warburg
circuit, which is not CPE-bearing -- see the check for the actual CPE-bearing candidate used),
NFE-to-basin is significantly lower (non-overlapping Wilson 95% CIs) with hit rate no worse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

_SPEEDUP_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _SPEEDUP_DIR.parent
sys.path.insert(0, str(_BENCH_DIR))
sys.path.insert(0, str(_BENCH_DIR / "six_plus"))
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW4CPE, spectrum_for  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.elements import BoundsContext  # noqa: E402
from autocircuit.core.fit import SCREEN_LOCAL, _Problem  # noqa: E402

sys.path.insert(0, str(_BENCH_DIR / "screening_round"))
from param_opt import Counted, _polish  # noqa: E402

sys.path.insert(0, str(_SPEEDUP_DIR))
import harness  # noqa: E402

#: Matches discover.py's tier-1 screening budget (SCREEN_POPSIZE, SCREEN_MAXITER).
SCREEN_POPSIZE = 8
SCREEN_MAXITER = 40

SEEDS = range(120)


def _cpe_param_names(circuit: Circuit) -> list[tuple[str, str]]:
    """[(Q-name, n-name), ...] for every CPE element, in circuit.param_names order."""
    names = circuit.param_names
    out = []
    for name in names:
        if name.endswith(".Q"):
            label = name[:-2]
            n_name = f"{label}.n"
            if n_name in names:
                out.append((name, n_name))
    return out


def _de_run(cost_fn, bounds, seed: int, counted: Counted) -> np.ndarray:
    result = differential_evolution(
        cost_fn,
        bounds=bounds,
        seed=seed,
        popsize=SCREEN_POPSIZE,
        maxiter=SCREEN_MAXITER,
        tol=1e-4,
        mutation=(0.4, 1.0),
        recombination=0.9,
        strategy="best1bin",
        init="sobol",
        polish=False,
        vectorized=True,
        updating="deferred",
    )
    return np.asarray(result.x, dtype=np.float64)


def run_baseline(problem: _Problem, seed: int) -> tuple[float, int]:
    counted = Counted(problem)
    x = _de_run(counted.batch, list(zip(problem.lower_x, problem.upper_x, strict=True)), seed, counted)
    final_cost = _polish(problem, x)
    return final_cost, counted.n


def run_reparam(problem: _Problem, ctx: BoundsContext, omega_ref: float, seed: int) -> tuple[float, int]:
    names = list(problem.circuit.param_names)
    q_idx = [names.index(q) for q, _n in _cpe_param_names(problem.circuit)]
    n_idx = [names.index(n) for _q, n in _cpe_param_names(problem.circuit)]

    # Free-index position == names position here, since nothing is fixed (see _Problem.free_idx).
    lower_x = problem.lower_x.copy()
    upper_x = problem.upper_x.copy()
    z0_lo, z0_hi = ctx.resistance()
    log_z0_lo, log_z0_hi = np.log10(z0_lo), np.log10(z0_hi)
    for qi in q_idx:
        lower_x[qi] = log_z0_lo
        upper_x[qi] = log_z0_hi

    def to_real_x(xs_reparam: np.ndarray) -> np.ndarray:
        """xs_reparam has Q rows holding log10(Z0); return an array with Q rows holding log10(Q)."""
        xs_real = xs_reparam.copy()
        for qi, ni in zip(q_idx, n_idx, strict=True):
            log_z0 = xs_reparam[qi]
            n_val = xs_reparam[ni]  # n is linear-scale (log_mask False), passed through as-is
            z0 = 10.0**log_z0
            q = 1.0 / (z0 * omega_ref**n_val)
            xs_real[qi] = np.log10(np.maximum(q, 1e-300))
        return xs_real

    counted = Counted(problem)

    def reparam_batch(xs: np.ndarray) -> np.ndarray:
        return counted.batch(to_real_x(xs))

    x_reparam = _de_run(reparam_batch, list(zip(lower_x, upper_x, strict=True)), seed, counted)
    x_real = to_real_x(x_reparam[:, None])[:, 0]
    final_cost = _polish(problem, x_real)
    return final_cost, counted.n


def main() -> None:
    truth = MW4CPE
    circuit = Circuit.parse(truth.circuit)

    results_baseline: list[tuple[float, int]] = []
    results_reparam: list[tuple[float, int]] = []

    for seed in SEEDS:
        spectrum = spectrum_for(truth, seed=seed)
        ctx = BoundsContext.from_data(spectrum.omega, spectrum.z, margin_decades=3.0)
        omega_ref = float(np.sqrt(spectrum.omega.min() * spectrum.omega.max()))
        problem = _Problem(circuit, spectrum, "modulus", None, {}, None, 3.0)

        results_baseline.append(run_baseline(problem, seed))
        results_reparam.append(run_reparam(problem, ctx, omega_ref, seed))

    best_known = min(c for c, _n in results_baseline + results_reparam)

    hits_baseline = [n for c, n in results_baseline if c <= best_known * 1.1]
    hits_reparam = [n for c, n in results_reparam if c <= best_known * 1.1]
    # Pad misses as None for summarize_hits' hit/total accounting.
    padded_baseline = [n if c <= best_known * 1.1 else None for c, n in results_baseline]
    padded_reparam = [n if c <= best_known * 1.1 else None for c, n in results_reparam]

    print(f"mw4cpe, {len(SEEDS)} seeds, best known cost = {best_known:.6g}")
    print(harness.summarize_hits(padded_baseline, label="baseline (raw Q bounds)"))
    print(harness.summarize_hits(padded_reparam, label="reparam (Z0 bounds)"))

    lo_b, hi_b = harness.wilson(len(hits_baseline), len(SEEDS))
    lo_r, hi_r = harness.wilson(len(hits_reparam), len(SEEDS))
    print(f"hit-rate Wilson CIs: baseline [{lo_b:.3f},{hi_b:.3f}]  reparam [{lo_r:.3f},{hi_r:.3f}]")
    print(f"hit-rate CIs overlap: {harness.wilson_overlap((lo_b, hi_b), (lo_r, hi_r))}")

    ctx0 = BoundsContext.from_data(
        spectrum_for(truth, seed=0).omega, spectrum_for(truth, seed=0).z, 3.0
    )
    z0_lo, z0_hi = ctx0.resistance()
    lower_all, upper_all = circuit.bounds(ctx0)
    q_idx0 = list(circuit.param_names).index("CPE1.Q")
    q_lo, q_hi = lower_all[q_idx0], upper_all[q_idx0]
    print(
        f"box width (decades): Z0 reparam = {np.log10(z0_hi / z0_lo):.2f}, "
        f"raw Q (as shipped) = {np.log10(q_hi / q_lo):.2f}"
    )


if __name__ == "__main__":
    main()
