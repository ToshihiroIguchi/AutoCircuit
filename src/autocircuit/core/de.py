"""A purpose-written vectorized differential evolution loop, replacing
``scipy.optimize.differential_evolution`` on the ``workers=1`` path :func:`fit._global_stage`
takes -- the only path any caller in this codebase reaches (nothing under ``src/autocircuit``
ever calls ``fit()``/``screen()`` with ``workers > 1``; ``discover()``'s own ``workers`` fans out
across *candidates* through a process pool, and each pool worker calls ``fit``/``screen`` at
``workers=1``).

Why this exists: ``docs/SEARCH_TIME_PLAN.md`` section 8 measured that SciPy's own DE bookkeeping
is 48-67% of the global stage's per-iteration cost, unbiased and confirmed two independent ways,
and named it "the only place this round found real, uncommitted headroom." Reading scipy 1.18's
own source (``scipy/optimize/_differentialevolution.py``) explains why: the ``deferred``/
``vectorized`` path is already almost entirely vectorized inside one generation, and most of the
remaining cost is generic machinery this project never exercises -- constraint wrapping and
feasibility checks, ``integrality``, the ``maxfun`` cap, ``updating="immediate"``, and (found
while reading the source, not anticipated) an ``OptimizeResult`` rebuilt every single generation
-- including rescaling the *entire* population -- purely to hand to a callback that only reads
``time.perf_counter()``, because :func:`fit._global_stage` always installs one.

This loop removes that machinery. It drives ``np.random.RandomState(seed)`` through nearly the
same call sequence scipy's own driver does (Sobol init, a dither draw, donor sampling, crossover,
bound repair), so it is not a reimplementation of DE as an algorithm -- one deliberate departure
keeps it fast: scipy draws each candidate's 5 donor indices with its own sequential
``rng.shuffle`` call per candidate (unavoidably a per-member Python loop, kept in the bit-exact
prototype this module started as), and this version instead draws the whole generation's donor
sets in one batched call, ``rng.random((N, N)).argsort(axis=1)``. That trades bit-exact
reproduction of scipy's RNG stream for a different, statistically equally valid one.

**Measured, not assumed, to cost nothing in search quality** -- ``docs/DE_KERNEL_PLAN.md``'s
DE5 battery, all four clauses: two frozen-landscape arenas at Wilson-CI scale (750 and 375
paired samples) found the in-basin rate statistically indistinguishable from the incumbent on
both; a 120-optimizer-seed sweep of the hardest known multi-modal landscape in this repository
(the same one that took ``docs/PARAM_OPTIMIZER_PLAN.md``'s L-SHADE from 5/12 to 0/12) found no
significant difference by exact McNemar (p=0.84) once the sample was large enough to say
anything at all -- the original n=12 draw's apparent 5/12-vs-2/12 gap was small-sample noise,
not a reproducible effect; and end-to-end pipeline and recovery comparisons across this
project's own reference spectra agreed on every reported number except which member of an
already-documented exact-equivalence tie a restart search happens to land on, the same
basin-lottery relabeling this project's own CPE-kernel change already produced
(``SEARCH_TIME_PLAN.md`` section 3.3). Real end-to-end wall-clock fell throughout that
comparison, consistent with the per-iteration measurement below.

**Per-iteration speed, measured** (``benchmarks/speedup/de_kernel.py``, six topologies spanning
3-6 free parameters, half CPE-bearing, each topology timed in its own subprocess to avoid a
same-process contamination artifact this round found and worked around): 35-46% faster than
scipy per DE generation on the real cost function (ratio 0.54-0.65x scipy's own time), shrinking
somewhat as the cost function itself gets more expensive relative to the fixed bookkeeping this
loop removes.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.stats import qmc

Float = NDArray[np.float64]


def de_best1bin(
    cost_vectorized: Callable[[Float], Float],
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
    """``strategy="best1bin"``, ``init="sobol"``, ``updating="deferred"``, ``vectorized=True``
    differential evolution -- the exact configuration :func:`fit._global_stage` has always
    passed to ``scipy.optimize.differential_evolution`` on its ``workers=1`` branch.

    Args:
        cost_vectorized: Scores a whole population in one call. Takes ``(n_params, S)``, returns
            ``(S,)`` -- the same contract ``fit._Problem.cost_vectorized`` has always had.
        bounds: ``(lower, upper)`` per free parameter, in the same (possibly log10) search space
            the caller already uses.
        seed: Seeds an ``np.random.RandomState`` -- legacy semantics, matching what scipy itself
            uses when given an integer ``seed=`` (as opposed to ``rng=``, which would be
            ``default_rng`` semantics scipy 1.18 also supports but this project's callers do not
            pass).
        popsize: Population size before the sobol-power-of-2 rounding below is ``popsize *
            n_free`` (or 5, whichever is larger) -- scipy's own formula.
        maxiter: Generation cap.
        tol, atol: Convergence test, scipy's own: ``std(energies) <= atol + tol *
            |mean(energies)|``.
        mutation: A ``(lo, hi)`` pair dithers the mutation constant once per generation
            (``rng.uniform(lo, hi)``); a single float holds it fixed.
        recombination: Crossover probability.
        x0: Optional starting point, scattered into population slot 0 after scaling into the
            unit cube. Raises if it lies outside ``bounds``, matching scipy.
        deadline: A ``time.perf_counter()`` value; the loop stops cleanly at the next generation
            boundary once passed. ``None`` means no deadline.

    Returns:
        The best point found, in the same units as ``bounds``.
    """
    rng = np.random.RandomState(seed)
    lower = np.array([b[0] for b in bounds], dtype=np.float64)
    upper = np.array([b[1] for b in bounds], dtype=np.float64)
    n = lower.size

    # scipy's own sobol-specific bump: population size must be a power of 2 for the QMC engine,
    # and equal-bounds parameters (fixed, not free -- never happens through this module's only
    # caller, but kept for parity with scipy's own formula) don't count toward it.
    eb_count = int(np.count_nonzero(lower == upper))
    num_pop = max(5, popsize * max(1, n - eb_count))
    num_pop = int(2 ** np.ceil(np.log2(num_pop)))

    scale_arg1 = 0.5 * (lower + upper)
    scale_arg2 = np.fabs(lower - upper)

    def scale_params(trial: Float) -> Float:
        return scale_arg1 + (trial - 0.5) * scale_arg2

    def unscale_params(params: Float) -> Float:
        return (params - scale_arg1) / scale_arg2 + 0.5

    # Same call scipy's own `init_population_qmc` makes: passing `rng` as `seed` means the
    # Sobol engine's scrambling draws come from, and advance, this exact RandomState stream.
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

        # The one deliberate departure from scipy's own RNG stream (see module docstring):
        # every candidate's 5 donor indices, drawn in one batched call rather than scipy's own
        # per-candidate sequential `rng.shuffle`. `argsort` of one random row per candidate is
        # an independent random permutation of `0..num_pop-1` for that candidate.
        perms = rng.random((num_pop, num_pop)).argsort(axis=1)
        # Drop each row's own index, keep the first 5 of what remains. Every row has exactly
        # num_pop-1 True entries (its own index removed), so this reshape needs no per-row loop.
        self_mask = perms != row[:, None]
        samples = perms[self_mask].reshape(num_pop, num_pop - 1)[:, :5]

        r0, r1 = samples[:, 0], samples[:, 1]
        bprime = population[0] + scale * (population[r0] - population[r1])

        # dtype="int64" matches scipy's own `rng_integers(rng, n, size=S)` exactly; the
        # platform-default `randint` dtype (C `long`) is 32-bit on Windows and 64-bit on Linux,
        # which would otherwise make this loop's RNG consumption diverge by platform.
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

        # scipy's own accept rule (`_accept_trial`, both sides always feasible here): "<=", not
        # "<".
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
