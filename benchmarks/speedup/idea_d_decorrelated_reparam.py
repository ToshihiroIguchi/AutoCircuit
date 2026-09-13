"""Idea D: does searching (tau, R) instead of (R, C) for each parallel-RC block shrink the
effective search box for Maxwell-Wagner-shaped truths?

**Why this might matter, precisely.** `Resistor.bounds()` and `Capacitor.bounds()`
(`src/autocircuit/core/elements.py`) already derive data-informed intervals independently --
`ctx.resistance()` for R, `ctx.capacitance()` for C -- so neither is a universal prior. But the
two are searched as an independent Cartesian product: nothing stops `differential_evolution`
from proposing an (R, C) pair whose implied relaxation time `tau = R*C` falls far outside the
measured frequency window, which is a *combination* the data cannot possibly support even though
each individual value is within its own "plausible" range. `BoundsContext.tau()`
(`elements.py:96-98`) already exists and is data-derived directly from the frequency window alone
(`1/omega_max .. 1/omega_min`), independent of R or C individually, but nothing in the shipped
code uses it for a `p(R,C)` block -- it is there for elements that are natively tau-parameterised
(Warburg-short/open, Gerischer, Cole-Cole, HN), not for a plain RC block.

This script tests searching `(log10(tau), log10(R))` instead of `(log10(R), log10(C))` per block,
with `tau` bounded by `ctx.tau()` and `R` unchanged (`ctx.resistance()`); `C` is recovered as
`log10(C) = log10(tau) - log10(R)` (both already log-scale, so this is exact arithmetic, no
re-exponentiation) before the real `_Problem` ever sees the vector.

Decision rule, fixed before running: ships only if hit rate at the production tier-1 screening
budget is significantly higher (non-overlapping Wilson 95% CIs) on `mw5` and `mw6`, with no
regression on either.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

_SPEEDUP_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _SPEEDUP_DIR.parent
sys.path.insert(0, str(_SPEEDUP_DIR))
sys.path.insert(0, str(_BENCH_DIR / "screening_round"))

import harness  # noqa: E402
from param_opt import Counted, _polish  # noqa: E402
from truths import MW5, MW6, spectrum_for  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.elements import BoundsContext  # noqa: E402
from autocircuit.core.fit import _Problem  # noqa: E402

SCREEN_POPSIZE = 8
SCREEN_MAXITER = 40
SEEDS = range(60)


def _rc_blocks(circuit_text: str) -> list[tuple[str, str]]:
    """[(R-label, C-label), ...] for every literal p(R_i,C_i) block, in circuit order."""
    return re.findall(r"R(\d+),C(\d+)", circuit_text)


def _de_run(cost_fn, bounds, seed: int) -> np.ndarray:
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
    x = _de_run(counted.batch, list(zip(problem.lower_x, problem.upper_x, strict=True)), seed)
    final_cost = _polish(problem, x)
    return final_cost, counted.n


def run_reparam(
    problem: _Problem, ctx: BoundsContext, blocks: list[tuple[str, str]], seed: int
) -> tuple[float, int]:
    names = list(problem.circuit.param_names)
    r_idx = [names.index(f"R{r}.R") for r, _c in blocks]
    c_idx = [names.index(f"C{c}.C") for _r, c in blocks]

    lower_x = problem.lower_x.copy()
    upper_x = problem.upper_x.copy()
    tau_lo, tau_hi = ctx.tau()
    log_tau_lo, log_tau_hi = np.log10(tau_lo), np.log10(tau_hi)
    for ci in c_idx:
        lower_x[ci] = log_tau_lo
        upper_x[ci] = log_tau_hi
    # c_idx rows now mean "log10(tau)"; r_idx rows are unchanged ("log10(R)").

    def to_real_x(xs: np.ndarray) -> np.ndarray:
        xs_real = xs.copy()
        for ri, ci in zip(r_idx, c_idx, strict=True):
            log_r = xs[ri]
            log_tau = xs[ci]
            xs_real[ci] = log_tau - log_r  # log10(C) = log10(tau) - log10(R)
        return xs_real

    counted = Counted(problem)

    def reparam_batch(xs: np.ndarray) -> np.ndarray:
        return counted.batch(to_real_x(xs))

    x_reparam = _de_run(reparam_batch, list(zip(lower_x, upper_x, strict=True)), seed)
    x_real = to_real_x(x_reparam[:, None])[:, 0]
    final_cost = _polish(problem, x_real)
    return final_cost, counted.n


def run_one(truth) -> None:
    circuit = Circuit.parse(truth.circuit)
    blocks = _rc_blocks(truth.circuit)

    results_baseline: list[tuple[float, int]] = []
    results_reparam: list[tuple[float, int]] = []

    for seed in SEEDS:
        spectrum = spectrum_for(truth, seed=seed)
        ctx = BoundsContext.from_data(spectrum.omega, spectrum.z, margin_decades=3.0)
        problem = _Problem(circuit, spectrum, "modulus", None, {}, None, 3.0)

        results_baseline.append(run_baseline(problem, seed))
        results_reparam.append(run_reparam(problem, ctx, blocks, seed))

    best_known = min(c for c, _n in results_baseline + results_reparam)
    padded_baseline = [n if c <= best_known * 1.1 else None for c, n in results_baseline]
    padded_reparam = [n if c <= best_known * 1.1 else None for c, n in results_reparam]
    hits_baseline = sum(1 for h in padded_baseline if h is not None)
    hits_reparam = sum(1 for h in padded_reparam if h is not None)

    print(f"\n{truth.id}, {len(SEEDS)} seeds, best known cost = {best_known:.6g}")
    print(harness.summarize_hits(padded_baseline, label="baseline (R,C bounds)"))
    print(harness.summarize_hits(padded_reparam, label="reparam (tau,R bounds)"))
    lo_b, hi_b = harness.wilson(hits_baseline, len(SEEDS))
    lo_r, hi_r = harness.wilson(hits_reparam, len(SEEDS))
    print(f"hit-rate Wilson CIs: baseline [{lo_b:.3f},{hi_b:.3f}]  reparam [{lo_r:.3f},{hi_r:.3f}]")
    print(f"hit-rate CIs overlap: {harness.wilson_overlap((lo_b, hi_b), (lo_r, hi_r))}")

    c_idx0 = list(circuit.param_names).index(f"C{blocks[0][1]}.C")
    ctx0 = BoundsContext.from_data(
        spectrum_for(truth, seed=0).omega, spectrum_for(truth, seed=0).z, 3.0
    )
    lower_all, upper_all = circuit.bounds(ctx0)
    c_lo, c_hi = lower_all[c_idx0], upper_all[c_idx0]
    tau_lo, tau_hi = ctx0.tau()
    print(
        f"per-block box width (decades), one representative block: "
        f"C (as shipped) = {np.log10(c_hi / c_lo):.2f}, "
        f"tau (reparam) = {np.log10(tau_hi / tau_lo):.2f}"
    )


def main() -> None:
    for truth in (MW5, MW6):
        run_one(truth)


if __name__ == "__main__":
    main()
