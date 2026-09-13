"""Monkeypatch used to run the *real* `fit()`/`screen()`/`discover()` production code through
docs/DE_KERNEL_PLAN.md's relaxed vectorized DE kernel for Step 4's pipeline-level measurements
(the T5-style ``.summary()`` comparison, the known-trap noise sweep, and the recovery-gate
comparison), each done by patching ``autocircuit.core.fit._global_stage`` -- the one function
every entry point calls -- for the duration of a ``with use_relaxed_de():`` block.

**Shipped, 2026-09-13**: DE5 passed (two Wilson-CI arenas, a 120-seed reliability sweep, and the
pipeline/recovery comparisons all found no significant quality difference), so
``_global_stage``'s own ``workers=1`` branch now calls ``core.de.de_best1bin`` directly --
:func:`use_relaxed_de` is a no-op against today's code (it patches ``_global_stage`` to
something it already is). It is kept, alongside the new :func:`use_scipy_de`, so a *future*
measurement can still force either kernel for comparison without touching ``core/fit.py``: pass
neither for "whatever production does today," or wrap a block in :func:`use_scipy_de` to
reconstruct the historical scipy-only baseline this project's own DE5 battery was measured
against.

The ``workers != 1`` branch is left on scipy in both patches, unconditionally: verified during
planning that nothing under ``src/autocircuit`` ever calls ``fit()``/``screen()`` with
``workers > 1`` (the process-pool fan-out in ``discover()`` calls each worker at ``workers=1``),
so this branch is kept only so a future caller that *did* pass ``workers>1`` gets scipy's own
behaviour rather than a silently different one -- true of production itself, not just this
patch.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import numpy as np
from benchmarks.speedup.de_kernel import de_best1bin_relaxed
from scipy.optimize import differential_evolution

import autocircuit.core.fit as fit_module

Float = np.ndarray


def _scipy_global_stage(
    problem: Any,
    *,
    seed: int,
    popsize: int,
    maxiter: int,
    tol: float,
    workers: int,
    time_limit: float | None,
    x0: Float | None,
) -> Float:
    """The historical scipy-only global stage, reconstructed for comparison against whatever
    kernel production uses today -- production itself no longer contains this code path."""
    deadline = None if time_limit is None else time.perf_counter() + time_limit

    def callback(xk: Float, convergence: float = 0.0) -> bool:
        return deadline is not None and time.perf_counter() > deadline

    kwargs: dict[str, Any] = {
        "bounds": list(zip(problem.lower_x, problem.upper_x, strict=True)),
        "seed": seed,
        "popsize": popsize,
        "maxiter": maxiter,
        "tol": tol,
        "mutation": (0.4, 1.0),
        "recombination": 0.9,
        "strategy": "best1bin",
        "init": "sobol",
        "polish": False,
        "callback": callback,
    }
    if x0 is not None:
        kwargs["x0"] = x0
    if workers and workers != 1:
        kwargs["workers"] = workers
        kwargs["updating"] = "deferred"
        result = differential_evolution(problem.cost, **kwargs)
    else:
        kwargs["vectorized"] = True
        kwargs["updating"] = "deferred"
        result = differential_evolution(problem.cost_vectorized, **kwargs)  # type: ignore[arg-type]
    return np.asarray(result.x, dtype=np.float64)


@contextmanager
def use_scipy_de() -> Iterator[None]:
    """Force the historical scipy-only global stage, for a future comparison against whatever
    kernel production uses by then."""
    original = fit_module._global_stage
    fit_module._global_stage = _scipy_global_stage  # type: ignore[assignment]
    try:
        yield
    finally:
        fit_module._global_stage = original  # type: ignore[assignment]


def _patched_global_stage(
    problem: Any,
    *,
    seed: int,
    popsize: int,
    maxiter: int,
    tol: float,
    workers: int,
    time_limit: float | None,
    x0: Float | None,
) -> Float:
    if workers and workers != 1:
        deadline = None if time_limit is None else time.perf_counter() + time_limit

        def callback(xk: Float, convergence: float = 0.0) -> bool:
            return deadline is not None and time.perf_counter() > deadline

        kwargs: dict[str, Any] = {
            "bounds": list(zip(problem.lower_x, problem.upper_x, strict=True)),
            "seed": seed,
            "popsize": popsize,
            "maxiter": maxiter,
            "tol": tol,
            "mutation": (0.4, 1.0),
            "recombination": 0.9,
            "strategy": "best1bin",
            "init": "sobol",
            "polish": False,
            "callback": callback,
            "workers": workers,
            "updating": "deferred",
        }
        if x0 is not None:
            kwargs["x0"] = x0
        result = differential_evolution(problem.cost, **kwargs)
        return np.asarray(result.x, dtype=np.float64)

    deadline = None if time_limit is None else time.perf_counter() + time_limit
    bounds = list(zip(problem.lower_x, problem.upper_x, strict=True))
    return de_best1bin_relaxed(
        problem.cost_vectorized,
        bounds,
        seed=seed,
        popsize=popsize,
        maxiter=maxiter,
        tol=tol,
        x0=x0,
        deadline=deadline,
    )


@contextmanager
def use_relaxed_de() -> Iterator[None]:
    original = fit_module._global_stage
    fit_module._global_stage = _patched_global_stage  # type: ignore[assignment]
    try:
        yield
    finally:
        fit_module._global_stage = original  # type: ignore[assignment]
