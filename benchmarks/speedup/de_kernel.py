"""Spike for docs/SEARCH_TIME_PLAN.md §8.5's unclaimed lever: a purpose-written vectorized DE
loop to replace ``scipy.optimize.differential_evolution`` on the ``workers=1, vectorized=True``
path ``core/fit.py:_global_stage`` actually takes (the only reachable path -- nothing under
``src/autocircuit`` ever calls ``fit()``/``screen()`` with ``workers > 1``).

**No production code is changed by running this.** Gates DE1 (bit-exact parity) and DE2 (speed)
from ``docs/DE_KERNEL_PLAN.md``.

Why bit-exactness is even attempted: reading scipy 1.18's own source
(``scipy/optimize/_differentialevolution.py``) shows the ``deferred``/``vectorized`` path is
already almost entirely vectorized inside one generation -- ``_mutate_many`` draws
``fill_point``/``crossovers`` in single batched calls, and the accept/promote/scale steps are
plain array ops. The only draws whose *order* forces a per-population-member Python call are the
``rng.shuffle`` calls in ``_select_samples`` (one shuffle of a persistent index array per
candidate, to pick 5 donor indices without replacement). Everything else scipy pays for on every
generation is generic machinery this project never exercises: constraint wrapping and
feasibility checks, ``integrality``, the ``maxfun`` cap, ``updating="immediate"``, and -- the
one found while reading the source rather than anticipated in the plan -- ``_global_stage``
*always* installs a ``callback`` (its own deadline check, wired unconditionally), and scipy's
main loop responds to any callback being set by rebuilding a full ``OptimizeResult`` every single
generation, including ``population=self._scale_parameters(self.population)`` -- rescaling the
*entire* population just to hand it to a callback that only reads ``time.perf_counter()``.

This prototype drives ``np.random.RandomState(seed)`` through the *same* call sequence scipy's
own driver does (dither draw, per-candidate shuffle, ``fill_point``, ``crossover``, bound
repair), so it does not reimplement any RNG -- it only removes the generic bookkeeping around
those draws. That is what makes bit-exactness and speed simultaneously achievable here, unlike
``docs/PARAM_OPTIMIZER_PLAN.md``'s L-SHADE spike, which was a *different algorithm* on a
*different* RNG stream and had to be validated by outcome quality alone.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/speedup/de_kernel.py --parity   # DE1: bit-exact vs scipy, 60 + 6 cases
    python benchmarks/speedup/de_kernel.py --speed     # DE2: per-iteration wall clock vs scipy
    python benchmarks/speedup/de_kernel.py --all       # both
"""

from __future__ import annotations

import argparse
import time
from typing import Any

import numpy as np

# Reuse the exact topology set and problem builder docs/SEARCH_TIME_PLAN.md §8's own instrument
# uses, rather than inventing a new arena -- this *is* the instrument that produced the 48-67%
# number this spike is trying to claim.
from benchmarks.speedup.where_time_goes import TOPOLOGIES, build_problem
from scipy.optimize import differential_evolution
from scipy.stats import qmc

from autocircuit.core.discover import SCREEN_MAXITER, SCREEN_POPSIZE, SCREEN_TOL
from autocircuit.core.fit import _Problem

Float = np.ndarray

#: The "publish" global-stage budget (fit.py's PUBLISH defaults: popsize=20, maxiter=400),
#: alongside the cheaper screen budget already imported above -- DE1/DE2 must hold at both,
#: since `_global_stage` is the same function under `fit()` and `screen()`.
PUBLISH_POPSIZE, PUBLISH_MAXITER, PUBLISH_TOL = 20, 400, 1e-8


# ------------------------------------------------------------------------------------------
# The prototype kernel.
# ------------------------------------------------------------------------------------------


def de_best1bin(
    cost_vectorized: Any,
    bounds: list[tuple[float, float]],
    *,
    seed: int,
    popsize: int,
    maxiter: int,
    tol: float,
    mutation: tuple[float, float] | float = (0.4, 1.0),
    recombination: float = 0.9,
    x0: Float | None = None,
    deadline: float | None = None,
    atol: float = 0.0,
) -> Float:
    """A from-scratch ``strategy="best1bin"``, ``init="sobol"``, ``updating="deferred"``,
    ``vectorized=True`` differential evolution loop, built to reproduce
    ``scipy.optimize.differential_evolution``'s own RNG call sequence exactly (same
    ``np.random.RandomState(seed)``, same order of draws) while skipping every piece of
    generic machinery (constraints, ``integrality``, ``maxfun``, the callback/``OptimizeResult``
    rebuild every generation) this project never uses.

    ``cost_vectorized`` must accept an ``(n_params, S)`` array and return an ``(S,)`` array of
    costs -- ``_Problem.cost_vectorized``'s own contract, unchanged.
    """
    rng = np.random.RandomState(seed)
    lower = np.array([b[0] for b in bounds], dtype=np.float64)
    upper = np.array([b[1] for b in bounds], dtype=np.float64)
    n = lower.size

    eb_count = int(np.count_nonzero(lower == upper))
    num_pop = max(5, popsize * max(1, n - eb_count))
    # scipy's own sobol-specific bump: population size must be a power of 2 for the QMC engine.
    num_pop = int(2 ** np.ceil(np.log2(num_pop)))

    scale_arg1 = 0.5 * (lower + upper)
    scale_arg2 = np.fabs(lower - upper)

    def scale_params(trial: Float) -> Float:
        return scale_arg1 + (trial - 0.5) * scale_arg2

    def unscale_params(params: Float) -> Float:
        return (params - scale_arg1) / scale_arg2 + 0.5

    # Same call as scipy's own `init_population_qmc`: passing `rng` as `seed` means the Sobol
    # engine's scrambling draws come from -- and advance -- this exact RandomState stream, so
    # nothing here is a reimplementation of Sobol; it is the same call scipy makes.
    sampler = qmc.Sobol(d=n, seed=rng)
    population = sampler.random(n=num_pop)

    if x0 is not None:
        x0_scaled = unscale_params(np.asarray(x0, dtype=np.float64))
        if np.any((x0_scaled > 1.0) | (x0_scaled < 0.0)):
            raise ValueError("x0 lies outside the specified bounds")
        population[0] = x0_scaled

    pool_idx = np.arange(num_pop)

    params_pop = scale_params(population)
    energies = np.atleast_1d(np.asarray(cost_vectorized(params_pop.T), dtype=np.float64))
    best = int(np.argmin(energies))
    energies[[0, best]] = energies[[best, 0]]
    population[[0, best]] = population[[best, 0]]

    if isinstance(mutation, tuple):
        dither_lo, dither_hi = sorted(mutation)
        dither = True
        scale_const = 0.0
    else:
        dither = False
        scale_const = float(mutation)

    row = np.arange(num_pop)
    for _nit in range(1, maxiter + 1):
        scale = float(rng.uniform(dither_lo, dither_hi)) if dither else scale_const

        # The one loop that cannot be vectorized away: each candidate's donor set is drawn by
        # shuffling one persistent index array, and the shuffle order must stay per-candidate
        # sequential to reproduce scipy's own RNG stream bit-for-bit (see module docstring).
        samples = np.empty((num_pop, 5), dtype=np.intp)
        for c in range(num_pop):
            rng.shuffle(pool_idx)
            picked = pool_idx[:6]
            samples[c] = picked[picked != c][:5]

        r0, r1 = samples[:, 0], samples[:, 1]
        bprime = population[0] + scale * (population[r0] - population[r1])

        # dtype='int64' matches scipy's own `rng_integers(rng, n, size=S)` call exactly; the
        # platform-default `randint` dtype (C `long`) is 32-bit on Windows and 64-bit on Linux,
        # and differs enough internally to desync the RNG stream if left unspecified here.
        fill_point = rng.randint(n, size=num_pop, dtype="int64")
        crossovers = rng.uniform(size=(num_pop, n)) < recombination
        crossovers[row, fill_point] = True
        trial = np.where(crossovers, bprime, population)

        mask = (trial > 1.0) | (trial < 0.0)
        oob = int(np.count_nonzero(mask))
        if oob:
            trial[mask] = rng.uniform(size=oob)

        trial_params = scale_params(trial)
        trial_energies = np.atleast_1d(
            np.asarray(cost_vectorized(trial_params.T), dtype=np.float64)
        )

        # scipy's _accept_trial: "energy_trial <= energy_orig" when both sides are feasible
        # (always true here, no constraints) -- <=, not <.
        improved = trial_energies <= energies
        population = np.where(improved[:, None], trial, population)
        energies = np.where(improved, trial_energies, energies)

        best = int(np.argmin(energies))
        energies[[0, best]] = energies[[best, 0]]
        population[[0, best]] = population[[best, 0]]

        if deadline is not None and time.perf_counter() > deadline:
            break
        if not np.any(np.isinf(energies)) and np.std(energies) <= atol + tol * np.abs(
            np.mean(energies)
        ):
            break

    return scale_params(population[0])


def de_best1bin_relaxed(
    cost_vectorized: Any,
    bounds: list[tuple[float, float]],
    *,
    seed: int,
    popsize: int,
    maxiter: int,
    tol: float,
    mutation: tuple[float, float] | float = (0.4, 1.0),
    recombination: float = 0.9,
    x0: Float | None = None,
    deadline: float | None = None,
    atol: float = 0.0,
) -> Float:
    """Same algorithm as :func:`de_best1bin`, but the one part of the loop that could not be
    vectorized while staying bit-exact -- ``N`` sequential ``rng.shuffle`` calls, one per
    candidate, to draw 5 donor indices each -- is replaced by a single batched draw for the
    whole generation: ``rng.random((N, N)).argsort(axis=1)`` gives every candidate an
    independent random permutation of ``0..N-1`` in one C-level call, and the first 5 entries
    (after dropping the candidate's own index) are its donors.

    This produces a **different, but equally valid, RNG stream** -- not bit-identical to scipy,
    per docs/DE_KERNEL_PLAN.md Step 4. It exists only to measure whether removing the last
    per-candidate Python loop closes DE2's gap enough to justify the full quality battery
    (DE5) that must follow before this variant could ever ship.
    """
    rng = np.random.RandomState(seed)
    lower = np.array([b[0] for b in bounds], dtype=np.float64)
    upper = np.array([b[1] for b in bounds], dtype=np.float64)
    n = lower.size

    eb_count = int(np.count_nonzero(lower == upper))
    num_pop = max(5, popsize * max(1, n - eb_count))
    num_pop = int(2 ** np.ceil(np.log2(num_pop)))

    scale_arg1 = 0.5 * (lower + upper)
    scale_arg2 = np.fabs(lower - upper)

    def scale_params(trial: Float) -> Float:
        return scale_arg1 + (trial - 0.5) * scale_arg2

    def unscale_params(params: Float) -> Float:
        return (params - scale_arg1) / scale_arg2 + 0.5

    sampler = qmc.Sobol(d=n, seed=rng)
    population = sampler.random(n=num_pop)

    if x0 is not None:
        x0_scaled = unscale_params(np.asarray(x0, dtype=np.float64))
        if np.any((x0_scaled > 1.0) | (x0_scaled < 0.0)):
            raise ValueError("x0 lies outside the specified bounds")
        population[0] = x0_scaled

    params_pop = scale_params(population)
    energies = np.atleast_1d(np.asarray(cost_vectorized(params_pop.T), dtype=np.float64))
    best = int(np.argmin(energies))
    energies[[0, best]] = energies[[best, 0]]
    population[[0, best]] = population[[best, 0]]

    if isinstance(mutation, tuple):
        dither_lo, dither_hi = sorted(mutation)
        dither = True
        scale_const = 0.0
    else:
        dither = False
        scale_const = float(mutation)

    row = np.arange(num_pop)
    for _nit in range(1, maxiter + 1):
        scale = float(rng.uniform(dither_lo, dither_hi)) if dither else scale_const

        # One batched draw for the whole generation instead of N sequential shuffles.
        perms = rng.random((num_pop, num_pop)).argsort(axis=1)
        # Drop each row's own index, keep the first 5 of what remains.
        self_mask = perms != row[:, None]
        # Every row has exactly num_pop-1 True entries in self_mask (its own index removed);
        # reshape keeps this a fixed-width array without a per-row Python loop.
        samples = perms[self_mask].reshape(num_pop, num_pop - 1)[:, :5]

        r0, r1 = samples[:, 0], samples[:, 1]
        bprime = population[0] + scale * (population[r0] - population[r1])

        fill_point = rng.randint(n, size=num_pop, dtype="int64")
        crossovers = rng.uniform(size=(num_pop, n)) < recombination
        crossovers[row, fill_point] = True
        trial = np.where(crossovers, bprime, population)

        mask = (trial > 1.0) | (trial < 0.0)
        oob = int(np.count_nonzero(mask))
        if oob:
            trial[mask] = rng.uniform(size=oob)

        trial_params = scale_params(trial)
        trial_energies = np.atleast_1d(
            np.asarray(cost_vectorized(trial_params.T), dtype=np.float64)
        )

        improved = trial_energies <= energies
        population = np.where(improved[:, None], trial, population)
        energies = np.where(improved, trial_energies, energies)

        best = int(np.argmin(energies))
        energies[[0, best]] = energies[[best, 0]]
        population[[0, best]] = population[[best, 0]]

        if deadline is not None and time.perf_counter() > deadline:
            break
        if not np.any(np.isinf(energies)) and np.std(energies) <= atol + tol * np.abs(
            np.mean(energies)
        ):
            break

    return scale_params(population[0])


def de_best1bin_from_problem(
    problem: _Problem,
    *,
    seed: int,
    popsize: int,
    maxiter: int,
    tol: float,
    x0: Float | None = None,
    deadline: float | None = None,
) -> Float:
    """The same call `_global_stage` makes, wired to this prototype instead of scipy."""
    bounds = list(zip(problem.lower_x, problem.upper_x, strict=True))
    return de_best1bin(
        problem.cost_vectorized,
        bounds,
        seed=seed,
        popsize=popsize,
        maxiter=maxiter,
        tol=tol,
        mutation=(0.4, 1.0),
        recombination=0.9,
        x0=x0,
        deadline=deadline,
    )


# ------------------------------------------------------------------------------------------
# DE1 -- bit-exact parity against scipy and against `_global_stage` itself.
# ------------------------------------------------------------------------------------------


def _scipy_kwargs(problem: _Problem, seed: int, popsize: int, maxiter: int, tol: float) -> dict[
    str, Any
]:
    return {
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
        "vectorized": True,
        "updating": "deferred",
    }


def run_parity() -> bool:
    print("=" * 88)
    print("DE1 -- bit-exact parity: de_best1bin vs scipy.optimize.differential_evolution")
    print("=" * 88)
    budgets = [
        ("screen (8x40)", SCREEN_POPSIZE, SCREEN_MAXITER, SCREEN_TOL),
        ("publish (20x400)", PUBLISH_POPSIZE, PUBLISH_MAXITER, PUBLISH_TOL),
    ]
    seeds = [0, 1, 2, 3, 4]
    total = 0
    passed = 0
    for topo in TOPOLOGIES:
        problem, _ = build_problem(topo)
        for label, popsize, maxiter, tol in budgets:
            for seed in seeds:
                total += 1
                kwargs = _scipy_kwargs(problem, seed, popsize, maxiter, tol)
                scipy_result = differential_evolution(  # type: ignore[arg-type]
                    problem.cost_vectorized, **kwargs
                )
                mine = de_best1bin_from_problem(
                    problem, seed=seed, popsize=popsize, maxiter=maxiter, tol=tol
                )
                ok = np.array_equal(mine, scipy_result.x)
                passed += ok
                if not ok:
                    print(
                        f"  MISMATCH {topo.label} / {label} / seed={seed}: "
                        f"max abs diff = {np.max(np.abs(mine - scipy_result.x)):.3e}"
                    )

    print(f"exact match (no x0): {passed}/{total}")

    # Six more cases with x0 supplied, one per topology, at the screen budget -- exercises the
    # `population[0] = x0_scaled` branch, which none of the above cases touch.
    x0_total = 0
    x0_passed = 0
    for topo in TOPOLOGIES:
        problem, _ = build_problem(topo)
        x0 = 0.5 * (problem.lower_x + problem.upper_x)
        x0_total += 1
        kwargs = _scipy_kwargs(problem, seed=0, popsize=SCREEN_POPSIZE, maxiter=SCREEN_MAXITER,
                               tol=SCREEN_TOL)
        kwargs["x0"] = x0
        scipy_result = differential_evolution(problem.cost_vectorized, **kwargs)  # type: ignore[arg-type]
        mine = de_best1bin_from_problem(
            problem, seed=0, popsize=SCREEN_POPSIZE, maxiter=SCREEN_MAXITER, tol=SCREEN_TOL, x0=x0
        )
        ok = np.array_equal(mine, scipy_result.x)
        x0_passed += ok
        if not ok:
            print(
                f"  MISMATCH (x0) {topo.label}: "
                f"max abs diff = {np.max(np.abs(mine - scipy_result.x)):.3e}"
            )
    print(f"exact match (with x0): {x0_passed}/{x0_total}")

    # A third check used to live here: parity between this file's bit-exact prototype and
    # `_global_stage` itself. **That comparison no longer applies as a pass/fail check.**
    # docs/DE_KERNEL_PLAN.md's DE2 gate found this bit-exact route not fast enough to ship
    # (only 1/6 topologies cleared the 0.75x bar); what shipped instead is the *relaxed*
    # variant (`de_best1bin_relaxed` below, ported into `src/autocircuit/core/de.py`), which is
    # a different, not bit-exact, RNG stream by design. `_global_stage` now calls that, so a
    # byte comparison against this file's bit-exact prototype would correctly report a mismatch
    # on every topology -- expected, not a regression. See `run_speed_relaxed` below for the
    # check that actually applies to what shipped.

    all_ok = passed == total and x0_passed == x0_total
    print()
    print(f"DE1 {'PASSED' if all_ok else 'FAILED'}")
    print()
    return all_ok


# ------------------------------------------------------------------------------------------
# DE2 -- per-iteration wall clock vs scipy, real cost only (the null-cost mechanism check from
# where_time_goes.py's A1 is reported alongside, reusing that script's own null cost function).
# ------------------------------------------------------------------------------------------


def _speed_one_topology(topo_idx: int, reps: int) -> dict[str, float]:
    """Measure one topology's scipy-vs-mine per-iteration wall clock, real and null cost.

    Called from a fresh subprocess (one per topology) rather than in a loop inside one process:
    **[measured]** running all six topologies' comparisons back to back in a single process
    produces a large, non-monotonic, order-dependent inflation of scipy's own measured time (a
    topology that reads 0.36 ms/it in isolation read 1.27-2.22 ms/it as the 4th-6th topology
    measured in one process, and reversing the topology order moved the inflation to whichever
    topologies were measured later, not to the same physical topologies) -- the same kind of
    same-process contamination `where_time_goes.py`'s own A4 note already documents for a
    different pair of arms. Per-topology subprocess isolation is the fix used there (run the
    polluting stage standalone) applied automatically here instead of left as a documented
    caveat, since DE2's verdict depends on getting this right.
    """
    from benchmarks.speedup.where_time_goes import _null_cost

    topo = TOPOLOGIES[topo_idx]
    problem, _ = build_problem(topo)
    n_free = int(problem.free_idx.size)
    scipy_real: list[float] = []
    mine_real: list[float] = []
    scipy_null: list[float] = []
    mine_null: list[float] = []
    for rep in range(reps):
        seed = rep
        kwargs = _scipy_kwargs(problem, seed, SCREEN_POPSIZE, SCREEN_MAXITER, SCREEN_TOL)

        t0 = time.perf_counter()
        r = differential_evolution(problem.cost_vectorized, **kwargs)  # type: ignore[arg-type]
        scipy_real.append((time.perf_counter() - t0) / max(r.nit, 1))

        t0 = time.perf_counter()
        de_best1bin_from_problem(
            problem, seed=seed, popsize=SCREEN_POPSIZE, maxiter=SCREEN_MAXITER, tol=SCREEN_TOL,
        )
        # de_best1bin doesn't report nit; DE1's bit-exact parity already proved the same seed
        # produces the same trajectory, so scipy's own nit is the correct shared denominator,
        # not an approximation.
        mine_real.append((time.perf_counter() - t0) / max(r.nit, 1))

        t0 = time.perf_counter()
        rn = differential_evolution(_null_cost, **kwargs)  # type: ignore[arg-type]
        scipy_null.append((time.perf_counter() - t0) / max(rn.nit, 1))

        t0 = time.perf_counter()
        de_best1bin(
            _null_cost, list(zip(problem.lower_x, problem.upper_x, strict=True)),
            seed=seed, popsize=SCREEN_POPSIZE, maxiter=SCREEN_MAXITER, tol=SCREEN_TOL,
        )
        mine_null.append((time.perf_counter() - t0) / max(rn.nit, 1))

    return {
        "label": topo.label,  # type: ignore[dict-item]
        "n_free": n_free,
        "scipy_real": float(np.median(scipy_real)) * 1e3,
        "mine_real": float(np.median(mine_real)) * 1e3,
        "scipy_null": float(np.median(scipy_null)) * 1e3,
        "mine_null": float(np.median(mine_null)) * 1e3,
    }


def run_speed(reps: int) -> bool:
    import json
    import subprocess
    import sys

    print("=" * 88)
    print("DE2 -- per-iteration wall clock: de_best1bin vs scipy, real cost and null cost")
    print("(each topology measured in its own subprocess -- see _speed_one_topology's docstring)")
    print("=" * 88)
    print(
        f"{'topology':<20}{'n_free':>8}{'scipy real/it (ms)':>20}{'mine real/it (ms)':>20}"
        f"{'ratio':>10}{'scipy null/it (ms)':>20}{'mine null/it (ms)':>20}"
    )
    ratios = []
    for idx, topo in enumerate(TOPOLOGIES):
        proc = subprocess.run(
            [sys.executable, __file__, "--speed-one", str(idx), "--reps", str(reps)],
            capture_output=True,
            text=True,
            check=True,
        )
        row = json.loads(proc.stdout.strip().splitlines()[-1])
        ratio = row["mine_real"] / row["scipy_real"]
        ratios.append(ratio)
        print(
            f"{topo.label:<20}{row['n_free']:>8}{row['scipy_real']:>20.4f}"
            f"{row['mine_real']:>20.4f}{ratio:>10.2f}{row['scipy_null']:>20.4f}"
            f"{row['mine_null']:>20.4f}"
        )

    n_pass = sum(1 for r in ratios if r <= 0.75)
    print()
    print(f"topologies at or under 0.75x scipy's real-cost per-iteration time: {n_pass}/6")
    ok = n_pass >= 5
    print(f"DE2 {'PASSED' if ok else 'FAILED'} (bar: >=5/6 at <=0.75x)")
    print()
    return ok


def _speed_relaxed_one_topology(topo_idx: int, reps: int) -> dict[str, float]:
    """Same subprocess-isolation rationale as `_speed_one_topology`."""
    topo = TOPOLOGIES[topo_idx]
    problem, _ = build_problem(topo)
    n_free = int(problem.free_idx.size)
    scipy_real: list[float] = []
    relaxed_real: list[float] = []
    for rep in range(reps):
        seed = rep
        kwargs = _scipy_kwargs(problem, seed, SCREEN_POPSIZE, SCREEN_MAXITER, SCREEN_TOL)
        t0 = time.perf_counter()
        r = differential_evolution(problem.cost_vectorized, **kwargs)  # type: ignore[arg-type]
        scipy_real.append((time.perf_counter() - t0) / max(r.nit, 1))

        bounds = list(zip(problem.lower_x, problem.upper_x, strict=True))
        t0 = time.perf_counter()
        de_best1bin_relaxed(
            problem.cost_vectorized, bounds, seed=seed, popsize=SCREEN_POPSIZE,
            maxiter=SCREEN_MAXITER, tol=SCREEN_TOL,
        )
        relaxed_real.append((time.perf_counter() - t0) / max(r.nit, 1))

    return {
        "label": topo.label,  # type: ignore[dict-item]
        "n_free": n_free,
        "scipy_real": float(np.median(scipy_real)) * 1e3,
        "relaxed_real": float(np.median(relaxed_real)) * 1e3,
    }


def run_speed_relaxed(reps: int) -> bool:
    """Cheap pre-check before committing to DE5's multi-day battery: does dropping bit-exactness
    (batched sample-index draws instead of N sequential shuffles) close DE2's gap enough to be
    worth measuring for quality at all? Same 0.75x/5-of-6 bar as DE2, informational only -- DE5
    is the real gate for this variant."""
    import json
    import subprocess
    import sys

    print("=" * 88)
    print("Relaxed-variant pre-check -- per-iteration wall clock, batched sample draw")
    print("(each topology measured in its own subprocess, per DE2's own finding)")
    print("=" * 88)
    print(
        f"{'topology':<20}{'n_free':>8}{'scipy real/it (ms)':>20}"
        f"{'relaxed real/it (ms)':>22}{'ratio':>10}"
    )
    ratios = []
    for idx, topo in enumerate(TOPOLOGIES):
        proc = subprocess.run(
            [sys.executable, __file__, "--speed-relaxed-one", str(idx), "--reps", str(reps)],
            capture_output=True,
            text=True,
            check=True,
        )
        row = json.loads(proc.stdout.strip().splitlines()[-1])
        ratio = row["relaxed_real"] / row["scipy_real"]
        ratios.append(ratio)
        print(
            f"{topo.label:<20}{row['n_free']:>8}{row['scipy_real']:>20.4f}"
            f"{row['relaxed_real']:>22.4f}{ratio:>10.2f}"
        )

    n_pass = sum(1 for r in ratios if r <= 0.75)
    print()
    print(f"topologies at or under 0.75x scipy's real-cost per-iteration time: {n_pass}/6")
    print()
    return n_pass >= 5


def main() -> None:
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parity", action="store_true", help="run DE1 (bit-exact parity)")
    parser.add_argument("--speed", action="store_true", help="run DE2 (per-iteration wall clock)")
    parser.add_argument(
        "--relaxed", action="store_true", help="run the relaxed-variant speed pre-check"
    )
    parser.add_argument("--all", action="store_true", help="run DE1 + DE2")
    parser.add_argument("--reps", type=int, default=20, help="repeats per topology for DE2")
    parser.add_argument(
        "--speed-one", type=int, default=None, metavar="IDX",
        help="internal: measure one topology's DE2 numbers in an isolated subprocess",
    )
    parser.add_argument(
        "--speed-relaxed-one", type=int, default=None, metavar="IDX",
        help="internal: measure one topology's relaxed-variant numbers in an isolated subprocess",
    )
    args = parser.parse_args()

    if args.speed_one is not None:
        print(json.dumps(_speed_one_topology(args.speed_one, args.reps)))
        return
    if args.speed_relaxed_one is not None:
        print(json.dumps(_speed_relaxed_one_topology(args.speed_relaxed_one, args.reps)))
        return

    if not (args.parity or args.speed or args.relaxed or args.all):
        args.all = True

    de1_ok = True
    if args.parity or args.all:
        de1_ok = run_parity()
    if args.speed or args.all:
        run_speed(args.reps)
    if args.relaxed:
        run_speed_relaxed(args.reps)
        if args.all and not de1_ok:
            print("NOTE: DE1 failed above -- DE2's numbers are for a kernel not yet proven")
            print("bit-exact; per docs/DE_KERNEL_PLAN.md, DE1 failing routes to the relaxed")
            print("variant (Step 4), not to shipping this kernel as-is.")


if __name__ == "__main__":
    main()
