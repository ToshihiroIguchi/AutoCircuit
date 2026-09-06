"""KPI-3: does another global optimiser reach the same basin in fewer function evaluations?

Survey candidate (i). The budget here is **cost-function evaluations**, not seconds, for the
same reason the topology arms count fits: the machine is not the thing being measured. Every
arm searches the identical `_Problem` -- same log-space bounds, same weighting, same data --
and every arm is followed by the identical trust-region polish, so the only difference is which
points in the box got looked at.

Success is defined against the best cost *any* arm reached on that topology, not against the
truth's parameters: a screening fit's job is to rank a topology, and it has done that job when
it lands in the basin the other arms agree on.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
from landscape import reference_spectrum
from scipy.optimize import (
    basinhopping,
    differential_evolution,
    dual_annealing,
    least_squares,
    shgo,
)
from scipy.stats import norm, qmc

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import SCREEN_LOCAL, _Problem

Float = np.ndarray


class Counted:
    """Wraps a `_Problem` and counts individual cost evaluations, however they arrive."""

    def __init__(self, problem: _Problem) -> None:
        self.p = problem
        self.n = 0

    def scalar(self, x: Float) -> float:
        self.n += 1
        return self.p.cost(x)

    def batch(self, xs: Float) -> Float:
        self.n += xs.shape[1]
        return self.p.cost_vectorized(xs)


def _polish(problem: _Problem, x: Float) -> float:
    try:
        out = least_squares(
            problem.residuals,
            x,
            bounds=(problem.lower_x, problem.upper_x),
            method="trf",
            xtol=SCREEN_LOCAL.xtol,
            ftol=SCREEN_LOCAL.ftol,
            gtol=SCREEN_LOCAL.gtol,
            max_nfev=SCREEN_LOCAL.max_nfev,
        )
        return float(problem.cost(out.x))
    except Exception:
        return float(problem.cost(x))


def de(popsize: int, maxiter: int) -> Callable[[Counted, int], Float]:
    def run(c: Counted, seed: int) -> Float:
        result = differential_evolution(
            c.batch,
            bounds=list(zip(c.p.lower_x, c.p.upper_x, strict=True)),
            seed=seed,
            popsize=popsize,
            maxiter=maxiter,
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

    return run


def de_strategy(name: str) -> Callable[[Counted, int], Float]:
    def run(c: Counted, seed: int) -> Float:
        result = differential_evolution(
            c.batch,
            bounds=list(zip(c.p.lower_x, c.p.upper_x, strict=True)),
            seed=seed, popsize=8, maxiter=40, tol=1e-4,
            mutation=(0.4, 1.0), recombination=0.9, strategy=name,
            init="sobol", polish=False, vectorized=True, updating="deferred",
        )
        return np.asarray(result.x, dtype=np.float64)

    return run


def cmaes(budget_factor: float = 1.0) -> Callable[[Counted, int], Float]:
    """Textbook (mu/mu_w, lambda)-CMA-ES, numpy only, box handled by clipping.

    Hansen & Ostermeier (2001). Restarted from a fresh uniform point whenever the step size
    collapses, so that the arm is a *global* search and not one local one dressed up as one --
    which is the comparison survey candidate (i) actually proposes.
    """

    def run(c: Counted, seed: int) -> Float:
        rng = np.random.default_rng(seed)
        lo, hi = c.p.lower_x, c.p.upper_x
        n = lo.size
        lam = 4 + int(3 * math.log(n))
        mu = lam // 2
        w = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
        w /= w.sum()
        mueff = 1.0 / np.sum(w**2)
        cc = (4 + mueff / n) / (n + 4 + 2 * mueff / n)
        cs = (mueff + 2) / (n + mueff + 5)
        c1 = 2 / ((n + 1.3) ** 2 + mueff)
        cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((n + 2) ** 2 + mueff))
        damps = 1 + 2 * max(0.0, math.sqrt((mueff - 1) / (n + 1)) - 1) + cs
        chin = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
        cap = int(budget_factor * 8 * n * 41)  # match the incumbent's own ceiling

        best_x, best_f = None, math.inf
        while c.n < cap:
            m = rng.uniform(lo, hi)
            sigma = 0.3 * float(np.mean(hi - lo))
            C = np.eye(n)
            pc = np.zeros(n)
            ps = np.zeros(n)
            for gen in range(1, 10_000):
                if c.n >= cap:
                    break
                d, B = np.linalg.eigh(C)
                d = np.sqrt(np.maximum(d, 1e-20))
                zs = rng.standard_normal((n, lam))
                ys = B @ (d[:, None] * zs)
                xs = np.clip(m[:, None] + sigma * ys, lo[:, None], hi[:, None])
                fs = c.batch(xs)
                order = np.argsort(fs)
                if fs[order[0]] < best_f:
                    best_f, best_x = float(fs[order[0]]), xs[:, order[0]].copy()
                sel = order[:mu]
                m_old = m
                m = xs[:, sel] @ w
                y = (m - m_old) / max(sigma, 1e-300)
                invsqrt = B @ np.diag(1.0 / d) @ B.T
                ps = (1 - cs) * ps + math.sqrt(cs * (2 - cs) * mueff) * (invsqrt @ y)
                hsig = float(
                    np.linalg.norm(ps) / math.sqrt(1 - (1 - cs) ** (2 * gen)) / chin
                ) < 1.4 + 2 / (n + 1)
                pc = (1 - cc) * pc + (1.0 if hsig else 0.0) * math.sqrt(
                    cc * (2 - cc) * mueff
                ) * y
                ys_sel = (xs[:, sel] - m_old[:, None]) / max(sigma, 1e-300)
                C = (
                    (1 - c1 - cmu) * C
                    + c1 * (np.outer(pc, pc) + (0.0 if hsig else cc * (2 - cc)) * C)
                    + cmu * (ys_sel * w) @ ys_sel.T
                )
                C = np.triu(C) + np.triu(C, 1).T
                sigma *= math.exp((cs / damps) * (np.linalg.norm(ps) / chin - 1))
                if sigma < 1e-9 or not np.all(np.isfinite(C)):
                    break
        return best_x if best_x is not None else rng.uniform(lo, hi)

    return run


def lshade(
    np_init_mult: float = 18.0, np_min: int = 4, h: int = 6, use_lpsr: bool = True
) -> Callable[[Counted, int], Float]:
    """L-SHADE (Tanabe & Fukunaga, CEC 2014), or plain SHADE when ``use_lpsr=False``.

    Success-history memory of size `h` for (F, CR), Lehmer-weighted by the fitness improvement
    each successful trial bought; `current-to-pbest/1` mutation against the union of the
    population and a bounded archive of recently-replaced parents; binomial crossover; linear
    population-size reduction from `np_init_mult * n` down to `np_min` over the budget when
    `use_lpsr` is set (SHADE keeps the population fixed at its initial size). Hyperparameters
    (`np_init_mult=18`, `h=6`, `arc_rate=2.6`, `p_min_frac=0.11`) are the commonly cited L-SHADE
    defaults, not tuned against this project's own benchmarks -- see
    `docs/PARAM_OPTIMIZER_PLAN.md`. As with `cmaes()` above, this is a textbook implementation
    with box bounds handled by clipping, not a claim of matching a reference implementation
    bit-for-bit.
    """

    def run(c: Counted, seed: int) -> Float:
        rng = np.random.default_rng(seed)
        lo, hi = c.p.lower_x, c.p.upper_x
        n = lo.size
        cap = 8 * n * 41  # same NFE ceiling as cmaes(), for an equal-budget comparison
        np_init = max(np_min, int(round(np_init_mult * n)))
        arc_rate, p_min_frac = 2.6, 0.11
        m_f = np.full(h, 0.5)
        m_cr = np.full(h, 0.5)
        mem_i = 0

        pop_size = np_init
        pop = rng.uniform(lo[:, None], hi[:, None], size=(n, pop_size))
        fitness = c.batch(pop)
        best_x = pop[:, int(np.argmin(fitness))].copy()
        best_f = float(fitness.min())
        archive: list[Float] = []

        while c.n < cap and pop_size > 1:
            r = rng.integers(0, h, size=pop_size)
            cr = np.clip(rng.normal(m_cr[r], 0.1), 0.0, 1.0)
            f_i = np.empty(pop_size)
            for i in range(pop_size):
                fi = -1.0
                while fi <= 0.0:
                    fi = rng.standard_cauchy() * 0.1 + m_f[r[i]]
                f_i[i] = min(fi, 1.0)

            p_num = max(2, int(round(p_min_frac * pop_size)))
            order = np.argsort(fitness)
            pbest_idx = order[rng.integers(0, p_num, size=pop_size)]
            r1 = rng.integers(0, pop_size, size=pop_size)
            union = pop if not archive else np.concatenate([pop, np.array(archive).T], axis=1)
            r2 = rng.integers(0, union.shape[1], size=pop_size)

            mutants = (
                pop
                + f_i[None, :] * (pop[:, pbest_idx] - pop)
                + f_i[None, :] * (pop[:, r1] - union[:, r2])
            )
            mutants = np.clip(mutants, lo[:, None], hi[:, None])

            trial = pop.copy()
            j_rand = rng.integers(0, n, size=pop_size)
            cross_mask = rng.uniform(size=(n, pop_size)) < cr[None, :]
            cross_mask[j_rand, np.arange(pop_size)] = True
            trial[cross_mask] = mutants[cross_mask]

            trial_fitness = c.batch(trial)
            improved = trial_fitness < fitness

            if np.any(improved):
                for col in np.nonzero(improved)[0]:
                    archive.append(pop[:, col].copy())
                max_arc = int(round(arc_rate * pop_size))
                if len(archive) > max_arc:
                    keep_idx = rng.choice(len(archive), size=max_arc, replace=False)
                    archive = [archive[i] for i in keep_idx]

                s_f, s_cr = f_i[improved], cr[improved]
                delta = fitness[improved] - trial_fitness[improved]
                w = delta / (delta.sum() + 1e-300)
                m_f[mem_i] = np.sum(w * s_f**2) / (np.sum(w * s_f) + 1e-300)
                m_cr[mem_i] = np.sum(w * s_cr)
                mem_i = (mem_i + 1) % h

            pop = np.where(improved[None, :], trial, pop)
            fitness = np.where(improved, trial_fitness, fitness)
            gen_best_i = int(np.argmin(fitness))
            if fitness[gen_best_i] < best_f:
                best_f, best_x = float(fitness[gen_best_i]), pop[:, gen_best_i].copy()

            if use_lpsr:
                new_size = max(
                    np_min, int(round(np_init + (np_min - np_init) * c.n / cap))
                )
                if new_size < pop_size:
                    keep = np.argsort(fitness)[:new_size]
                    pop, fitness, pop_size = pop[:, keep], fitness[keep], new_size

        return best_x

    return run


def jade(np_mult: float = 18.0, p_min_frac: float = 0.05, c: float = 0.1) -> Callable[[Counted, int], Float]:
    """JADE (Zhang & Sanderson, 2009): SHADE's ancestor.

    Same `current-to-pbest/1` mutation and archive as `lshade()`, but adaptation is a single
    exponentially-decayed scalar (`mu_F`, `mu_CR`) rather than a success-history memory, and the
    population size is fixed. Kept as its own arm rather than folded into `lshade(use_lpsr=...)`
    because the adaptation mechanism, not just the population schedule, differs.
    """

    def run(c_: Counted, seed: int) -> Float:
        rng = np.random.default_rng(seed)
        lo, hi = c_.p.lower_x, c_.p.upper_x
        n = lo.size
        cap = 8 * n * 41
        pop_size = max(4, int(round(np_mult * n)))
        mu_f, mu_cr = 0.5, 0.5

        pop = rng.uniform(lo[:, None], hi[:, None], size=(n, pop_size))
        fitness = c_.batch(pop)
        best_i = int(np.argmin(fitness))
        best_x, best_f = pop[:, best_i].copy(), float(fitness[best_i])
        archive: list[Float] = []

        while c_.n < cap:
            cr = np.clip(rng.normal(mu_cr, 0.1, size=pop_size), 0.0, 1.0)
            f_i = np.empty(pop_size)
            for i in range(pop_size):
                fi = -1.0
                while fi <= 0.0:
                    fi = rng.standard_cauchy() * 0.1 + mu_f
                f_i[i] = min(fi, 1.0)

            p_num = max(2, int(round(p_min_frac * pop_size)))
            order = np.argsort(fitness)
            pbest_idx = order[rng.integers(0, p_num, size=pop_size)]
            r1 = rng.integers(0, pop_size, size=pop_size)
            union = pop if not archive else np.concatenate([pop, np.array(archive).T], axis=1)
            r2 = rng.integers(0, union.shape[1], size=pop_size)

            mutants = (
                pop
                + f_i[None, :] * (pop[:, pbest_idx] - pop)
                + f_i[None, :] * (pop[:, r1] - union[:, r2])
            )
            mutants = np.clip(mutants, lo[:, None], hi[:, None])

            trial = pop.copy()
            j_rand = rng.integers(0, n, size=pop_size)
            cross_mask = rng.uniform(size=(n, pop_size)) < cr[None, :]
            cross_mask[j_rand, np.arange(pop_size)] = True
            trial[cross_mask] = mutants[cross_mask]

            trial_fitness = c_.batch(trial)
            improved = trial_fitness < fitness

            if np.any(improved):
                for col in np.nonzero(improved)[0]:
                    archive.append(pop[:, col].copy())
                max_arc = pop_size
                if len(archive) > max_arc:
                    keep_idx = rng.choice(len(archive), size=max_arc, replace=False)
                    archive = [archive[i] for i in keep_idx]

                s_f, s_cr = f_i[improved], cr[improved]
                mu_cr = (1 - c) * mu_cr + c * float(np.mean(s_cr))
                mu_f = (1 - c) * mu_f + c * float(np.sum(s_f**2) / (np.sum(s_f) + 1e-300))

            pop = np.where(improved[None, :], trial, pop)
            fitness = np.where(improved, trial_fitness, fitness)
            gi = int(np.argmin(fitness))
            if fitness[gi] < best_f:
                best_f, best_x = float(fitness[gi]), pop[:, gi].copy()

        return best_x

    return run


def shgo_arm() -> Callable[[Counted, int], Float]:
    """`scipy.optimize.shgo`, Sobol sampling. Deterministic: ignores `seed`."""

    def run(c: Counted, seed: int) -> Float:
        n = c.p.lower_x.size
        bounds = list(zip(c.p.lower_x, c.p.upper_x, strict=True))
        cap = 8 * n * 41
        result = shgo(c.scalar, bounds, sampling_method="sobol", options={"maxfev": cap})
        return np.asarray(result.x, dtype=np.float64)

    return run


def dual_annealing_arm() -> Callable[[Counted, int], Float]:
    """`scipy.optimize.dual_annealing`, capped at the same NFE ceiling as the other arms."""

    def run(c: Counted, seed: int) -> Float:
        n = c.p.lower_x.size
        bounds = list(zip(c.p.lower_x, c.p.upper_x, strict=True))
        cap = 8 * n * 41
        result = dual_annealing(c.scalar, bounds, seed=seed, maxfun=cap, no_local_search=True)
        return np.asarray(result.x, dtype=np.float64)

    return run


def basinhopping_arm(niter: int = 30) -> Callable[[Counted, int], Float]:
    """`scipy.optimize.basinhopping` with an L-BFGS-B local step, from a random start."""

    def run(c: Counted, seed: int) -> Float:
        rng = np.random.default_rng(seed)
        lo, hi = c.p.lower_x, c.p.upper_x
        x0 = rng.uniform(lo, hi)
        minimizer_kwargs = {"method": "L-BFGS-B", "bounds": list(zip(lo, hi, strict=True))}
        result = basinhopping(
            c.scalar, x0, niter=niter, minimizer_kwargs=minimizer_kwargs, seed=seed
        )
        return np.asarray(result.x, dtype=np.float64)

    return run


def ga_sbx(
    pop_mult: float = 8.0, eta_c: float = 15.0, eta_m: float = 20.0, pc: float = 0.9
) -> Callable[[Counted, int], Float]:
    """Real-coded genetic algorithm: SBX crossover (Deb & Agrawal, 1995), polynomial mutation
    (Deb & Goyal, 1996), binary tournament selection, one-slot elitism.

    Included because it is a genuinely different recombination mechanism from DE's
    difference-vector mutation and CMA-ES's covariance adaptation -- which is what the no-free-
    lunch theorem actually argues for testing (distinct search mechanisms), not more variants of
    the same one. `eta_c=15`, `eta_m=20`, `pc=0.9` are the standard textbook defaults from Deb's
    own papers, not tuned against this project's benchmarks.
    """

    def run(c: Counted, seed: int) -> Float:
        rng = np.random.default_rng(seed)
        lo, hi = c.p.lower_x, c.p.upper_x
        n = lo.size
        cap = 8 * n * 41
        pop_size = max(4, int(round(pop_mult * n)))
        pm = 1.0 / n
        span = (hi - lo)[:, None]

        pop = rng.uniform(lo[:, None], hi[:, None], size=(n, pop_size))
        fitness = c.batch(pop)
        best_i = int(np.argmin(fitness))
        best_x, best_f = pop[:, best_i].copy(), float(fitness[best_i])

        while c.n < cap:
            i1, i2 = rng.integers(0, pop_size, size=pop_size), rng.integers(0, pop_size, size=pop_size)
            sel1 = np.where(fitness[i1] < fitness[i2], i1, i2)
            i3, i4 = rng.integers(0, pop_size, size=pop_size), rng.integers(0, pop_size, size=pop_size)
            sel2 = np.where(fitness[i3] < fitness[i4], i3, i4)
            p1, p2 = pop[:, sel1], pop[:, sel2]

            u = rng.uniform(size=(n, pop_size))
            beta = np.where(
                u <= 0.5,
                (2 * u) ** (1.0 / (eta_c + 1)),
                (1.0 / (2 * (1 - u))) ** (1.0 / (eta_c + 1)),
            )
            do_cx = rng.uniform(size=pop_size) < pc
            child = np.where(do_cx[None, :], 0.5 * ((1 + beta) * p1 + (1 - beta) * p2), p1)

            do_mut = rng.uniform(size=(n, pop_size)) < pm
            u2 = rng.uniform(size=(n, pop_size))
            delta = np.where(
                u2 < 0.5,
                (2 * u2) ** (1.0 / (eta_m + 1)) - 1.0,
                1.0 - (2 * (1 - u2)) ** (1.0 / (eta_m + 1)),
            )
            child = np.where(do_mut, child + delta * span, child)
            child = np.clip(child, lo[:, None], hi[:, None])

            child_fitness = c.batch(child)
            worst = int(np.argmax(child_fitness))
            if best_f < child_fitness[worst]:
                child[:, worst], child_fitness[worst] = best_x, best_f

            pop, fitness = child, child_fitness
            gi = int(np.argmin(fitness))
            if fitness[gi] < best_f:
                best_f, best_x = float(fitness[gi]), pop[:, gi].copy()

        return best_x

    return run


def pso(
    w_start: float = 0.9, w_end: float = 0.4, c1: float = 2.0, c2: float = 2.0
) -> Callable[[Counted, int], Float]:
    """Particle swarm optimisation, inertia-weight variant (Shi & Eberhart, 1998).

    Linearly decaying inertia from `w_start` to `w_end` over the budget; standard cognitive/
    social coefficients `c1=c2=2.0`. Velocity clamped to 20% of the box range per dimension,
    position clipped to bounds. Swarm size matches the incumbent DE's own population convention
    (`popsize * n_free`) for a like-for-like comparison. As with `cmaes()`/`lshade()` above,
    hyperparameters are the commonly cited textbook defaults, not tuned against this project's
    benchmarks -- see `docs/PARAM_OPTIMIZER_PLAN.md`.
    """

    def run(c: Counted, seed: int) -> Float:
        rng = np.random.default_rng(seed)
        lo, hi = c.p.lower_x, c.p.upper_x
        n = lo.size
        cap = 8 * n * 41
        swarm = 8 * n
        vmax = 0.2 * (hi - lo)

        pos = rng.uniform(lo[:, None], hi[:, None], size=(n, swarm))
        vel = rng.uniform(-vmax[:, None], vmax[:, None], size=(n, swarm))
        fitness = c.batch(pos)
        pbest_pos, pbest_fit = pos.copy(), fitness.copy()
        g = int(np.argmin(fitness))
        gbest_pos, gbest_fit = pos[:, g].copy(), float(fitness[g])

        while c.n < cap:
            frac = min(1.0, c.n / cap)
            w = w_start + (w_end - w_start) * frac
            r1 = rng.uniform(size=(n, swarm))
            r2 = rng.uniform(size=(n, swarm))
            vel = (
                w * vel
                + c1 * r1 * (pbest_pos - pos)
                + c2 * r2 * (gbest_pos[:, None] - pos)
            )
            vel = np.clip(vel, -vmax[:, None], vmax[:, None])
            pos = np.clip(pos + vel, lo[:, None], hi[:, None])
            fitness = c.batch(pos)
            improved = fitness < pbest_fit
            pbest_pos[:, improved] = pos[:, improved]
            pbest_fit[improved] = fitness[improved]
            g = int(np.argmin(pbest_fit))
            if pbest_fit[g] < gbest_fit:
                gbest_fit, gbest_pos = float(pbest_fit[g]), pbest_pos[:, g].copy()
        return gbest_pos

    return run


def bayes_opt(xi: float = 0.01) -> Callable[[Counted, int], Float]:
    """A from-scratch GP-EI Bayesian optimiser: numpy + scipy.stats.norm only, no new dependency.

    The fourth distinct search paradigm alongside DE-family, evolution strategies and swarm
    intelligence: model-based rather than population-based. Fixed RBF length scale (`0.2` of the
    box range per dimension, not fit by marginal likelihood -- keeping this simple), standardised
    targets, exact Cholesky GP (no sparsification), Expected Improvement scored on a random
    5,000-point candidate pool each iteration.

    **Budget is `min(cap, 30n + 50)`, not the shared NFE cap every other arm uses.** Refitting a
    Gaussian process from scratch is `O(N^3)` in the number of observations so far, so pushing it
    through the same ~2,000-evaluation budget the other arms get is computationally prohibitive
    and outside where Bayesian optimisation is normally used at all (expensive-per-call
    objectives -- hyperparameter tuning, physical experiments -- with budgets of tens to a few
    hundred calls). This measures it in its own natural regime instead: the question is whether
    it reaches a comparable basin *when given the kind of budget it is designed for*, not whether
    it wins a comparison it was never built to enter. Read this arm's NFE column as "what BO
    actually used", not as a like-for-like figure against the other arms.
    """

    def run(c: Counted, seed: int) -> Float:
        rng = np.random.default_rng(seed)
        lo, hi = c.p.lower_x, c.p.upper_x
        n = lo.size
        cap = 8 * n * 41
        budget = min(cap, 30 * n + 50)
        ls = 0.2 * (hi - lo)
        n_init = max(2 * n, 8)

        def kernel(a: Float, b: Float) -> Float:
            d = (a[:, :, None] - b[:, None, :]) / ls[:, None, None]
            return np.exp(-0.5 * np.sum(d**2, axis=0))

        x_obs = rng.uniform(lo[:, None], hi[:, None], size=(n, n_init))
        y_obs = np.array([c.scalar(x_obs[:, i]) for i in range(n_init)])
        best_i = int(np.argmin(y_obs))
        best_x, best_f = x_obs[:, best_i].copy(), float(y_obs[best_i])

        while c.n < budget:
            mu_y, sigma_y = y_obs.mean(), y_obs.std() + 1e-300
            y_norm = (y_obs - mu_y) / sigma_y
            kmat = kernel(x_obs, x_obs) + 1e-6 * np.eye(x_obs.shape[1])
            chol = np.linalg.cholesky(kmat)
            alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y_norm))

            cand = rng.uniform(lo[:, None], hi[:, None], size=(n, 5000))
            k_star = kernel(x_obs, cand)
            mu = k_star.T @ alpha
            v = np.linalg.solve(chol, k_star)
            var = np.clip(1.0 - np.sum(v**2, axis=0), 1e-12, None)
            sigma = np.sqrt(var)

            imp = y_norm.min() - mu - xi
            z = imp / sigma
            ei = imp * norm.cdf(z) + sigma * norm.pdf(z)
            ei = np.where(sigma < 1e-9, 0.0, ei)

            x_next = cand[:, int(np.argmax(ei))]
            f_next = c.scalar(x_next)
            x_obs = np.concatenate([x_obs, x_next[:, None]], axis=1)
            y_obs = np.concatenate([y_obs, [f_next]])
            if f_next < best_f:
                best_f, best_x = float(f_next), x_next.copy()

        return best_x

    return run


def sobol_lm(n_starts: int = 12) -> Callable[[Counted, int], Float]:
    """Multi-start trust-region from a Sobol design: no population method at all."""

    def run(c: Counted, seed: int) -> Float:
        lo, hi = c.p.lower_x, c.p.upper_x
        pts = qmc.Sobol(len(lo), scramble=True, seed=seed).random(n_starts)
        starts = lo + pts * (hi - lo)
        best_x, best_f = starts[0], math.inf
        for s in starts:
            try:
                out = least_squares(
                    lambda x: (c.scalar(x), c.p.residuals(x))[1],
                    s, bounds=(lo, hi), method="trf",
                    xtol=SCREEN_LOCAL.xtol, ftol=SCREEN_LOCAL.ftol,
                    gtol=SCREEN_LOCAL.gtol, max_nfev=SCREEN_LOCAL.max_nfev,
                )
            except Exception:
                continue
            f = float(c.p.cost(out.x))
            if f < best_f:
                best_f, best_x = f, out.x
        return np.asarray(best_x, dtype=np.float64)

    return run


ARMS: dict[str, Callable[[Counted, int], Float]] = {
    "de_8x40 (current)": de(8, 40),
    "de_8x20": de(8, 20),
    "de_4x40": de(4, 40),
    "de_rand1bin": de_strategy("rand1bin"),
    "cmaes": cmaes(1.0),
    "cmaes_half": cmaes(0.5),
    "sobol_lm": sobol_lm(12),
    "lshade": lshade(use_lpsr=True),
    "shade": lshade(use_lpsr=False),
    "jade": jade(),
    "pso": pso(),
    "ga_sbx": ga_sbx(),
    "dual_annealing": dual_annealing_arm(),
    "basinhopping": basinhopping_arm(),
    "bayesopt": bayes_opt(),
}

#: `shgo_arm()` is defined above but deliberately excluded from `ARMS`: a single-topology sanity
#: check measured 361.7 s per call (against <1 s for every other arm), which would cost hours
#: across 25 topologies x several seeds. It reached cost 0.0451 against a best-known 0.0166 on
#: that same check -- the same basin failure as CMA-ES/PSO -- so there is no reason to pay for a
#: wider run of it.


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("landscape", type=Path)
    ap.add_argument("--cases", type=int, default=24)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()

    data = json.loads(args.landscape.read_text(encoding="utf-8"))
    spectrum = reference_spectrum(data["data_seed"])
    rows = data["rows"]
    rng = np.random.default_rng(0)
    # Stratify by element count: a screening optimiser's job gets harder with dimension, and an
    # average over whatever the top of the list happens to contain would hide that.
    picked: list[dict] = []
    for n in (4, 5, 6):
        same = [r for r in rows if r["n_elements"] == n]
        idx = rng.choice(len(same), size=min(args.cases // 3, len(same)), replace=False)
        picked.extend(same[int(i)] for i in idx)
    picked.append(next(r for r in rows if Circuit.parse(r["text"]).canonical_form()
                       == data["truth_canonical"]))
    print(f"{len(picked)} topologies x {args.seeds} seeds, arena {args.landscape.name}")

    results: dict[str, list[tuple[float, int]]] = {k: [] for k in ARMS}
    best_known: dict[tuple[str, int], float] = {}
    for row in picked:
        problem = _Problem(Circuit.parse(row["text"]), spectrum, "modulus", None, {}, None, 3.0)
        for seed in range(args.seeds):
            for name, arm in ARMS.items():
                counted = Counted(problem)
                try:
                    x = arm(counted, seed)
                    cost = _polish(problem, x)
                except Exception:
                    cost, counted.n = math.inf, counted.n
                results[name].append((cost, counted.n))
                key = (row["text"], seed)
                if cost < best_known.get(key, math.inf):
                    best_known[key] = cost

    keys = [(row["text"], seed) for row in picked for seed in range(args.seeds)]
    print()
    print(f"{'arm':20s} {'in basin':>9s} {'95% Wilson CI':>15s} {'median NFE':>11s} "
          f"{'mean NFE':>9s} {'median excess':>14s}")
    print("-" * 90)
    for name in ARMS:
        vals = results[name]
        ok = sum(1 for (c, _), k in zip(vals, keys, strict=True)
                 if math.isfinite(c) and c <= best_known[k] * 1.01 + 1e-300)
        excess = [c / best_known[k] for (c, _), k in zip(vals, keys, strict=True)
                  if math.isfinite(c) and best_known[k] > 0]
        nfe = [n for _, n in vals]
        lo_ci, hi_ci = _wilson(ok, len(vals))
        print(f"{name:20s} {ok:4d}/{len(vals):<4d} "
              f"[{lo_ci:.2f},{hi_ci:.2f}]{'':>4s} {np.median(nfe):11.0f} "
              f"{np.mean(nfe):9.0f} {np.median(excess):14.4f}")


def _wilson(ok: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a hit rate ``ok / total``.

    Every other round in `docs/SEARCH_ALGORITHM_SCREENING.md` insists on this before reading a
    difference between two arms as real; this script never carried one, so a hand run of it would
    have to be redone by hand each time. ``z=1.959964`` is the two-sided 95% normal quantile.
    """
    if total == 0:
        return 0.0, 1.0
    p = ok / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - spread) / denom, (centre + spread) / denom


if __name__ == "__main__":
    main()
