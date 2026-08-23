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
from scipy.optimize import differential_evolution, least_squares
from scipy.stats import qmc

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
}


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
    print(f"{'arm':20s} {'in basin':>9s} {'median NFE':>11s} {'mean NFE':>9s} "
          f"{'median excess':>14s}")
    print("-" * 70)
    for name in ARMS:
        vals = results[name]
        ok = sum(1 for (c, _), k in zip(vals, keys, strict=True)
                 if math.isfinite(c) and c <= best_known[k] * 1.01 + 1e-300)
        excess = [c / best_known[k] for (c, _), k in zip(vals, keys, strict=True)
                  if math.isfinite(c) and best_known[k] > 0]
        nfe = [n for _, n in vals]
        print(f"{name:20s} {ok:4d}/{len(vals):<4d} {np.median(nfe):11.0f} "
              f"{np.mean(nfe):9.0f} {np.median(excess):14.4f}")


if __name__ == "__main__":
    main()
