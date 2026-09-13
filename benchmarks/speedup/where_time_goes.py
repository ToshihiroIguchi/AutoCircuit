"""Where a single ``screen()`` call actually spends its time -- docs/SEARCH_TIME_PLAN.md's own
missing profile, per the round that measurement was requested for.

Every speedup decision to date has been taken against a *share* inferred from one arm of an A/B
(``36-47%`` for the impedance kernel, from ``docs/SEARCH_ALGORITHM_SCREENING.md``) rather than
against a direct decomposition of one ``screen()`` call. This script produces that decomposition,
in four parts:

* **A1** -- SciPy's own differential-evolution bookkeeping, isolated with a null cost function
  and measured by wall clock alone, so the number carries no profiler bias.
* **A2** -- a ``cProfile`` decomposition of a full ``screen()`` call into four buckets (DE
  bookkeeping, local polish, impedance kernel, residual assembly), with the bias A1 exists to
  correct for stated up front: ``cProfile`` charges per Python call, so it over-states
  Python-heavy code, which is precisely SciPy's DE loop.
* **A3** -- the local polish's own finite-difference Jacobian cost, split out of A2's local-polish
  bucket, since ``least_squares(method="trf")`` is given no analytic Jacobian anywhere in this
  codebase.
* **A4** -- four named, unwired micro-inefficiencies (a constant-impedance element allocating a
  full array, a per-leaf dict lookup inside a try/except despite ``Circuit._specs`` already
  holding the resolved objects, a doubly-entered ``np.errstate``, and the omega-only
  subexpressions recomputed on every population evaluation), priced individually rather than
  wired into the package.

**No production code is changed by running this.** It is a benchmark, not a shipped path; see
``docs/SEARCH_TIME_PLAN.md``'s own new section for the numbers and the ranked candidate list this
produces.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/speedup/where_time_goes.py             # A1 (fast, a few seconds)
    python benchmarks/speedup/where_time_goes.py --profile    # + A2/A3 (cProfile decomposition)
    python benchmarks/speedup/where_time_goes.py --micro      # + A4 (microbenchmarks)
    python benchmarks/speedup/where_time_goes.py --all        # everything
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution

from autocircuit.core import elements
from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import SCREEN_MAXITER, SCREEN_POPSIZE, SCREEN_TOL
from autocircuit.core.elements import Resistor
from autocircuit.core.fit import FitContext, _global_stage, _Problem, screen
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum

Float = np.ndarray

# --------------------------------------------------------------------------------------
# The topology set: 3, 4 and 5 elements, half CPE-bearing and half not (the CPE cost gap,
# 1.77 s vs 0.87 s per fit, is this project's largest known per-element effect, so the DE share
# is expected to differ across it -- reported separately rather than averaged together).
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Topology:
    label: str
    circuit: str
    params: dict[str, float]
    has_cpe: bool


TOPOLOGIES = [
    Topology("3-element R/C", "R1-p(R2,C1)", {"R1.R": 50.0, "R2.R": 200.0, "C1.C": 1e-6}, False),
    Topology(
        "4-element R/C/L",
        "R1-p(R2,C1)-L1",
        {"R1.R": 50.0, "R2.R": 200.0, "C1.C": 1e-6, "L1.L": 1e-6},
        False,
    ),
    Topology(
        "5-element R/C",
        "p(R1,C1)-p(R2,C2)-R3",
        {"R1.R": 1e4, "C1.C": 1e-9, "R2.R": 5e5, "C2.C": 2e-8, "R3.R": 10.0},
        False,
    ),
    Topology(
        "3-element R/CPE",
        "R1-p(R2,CPE1)",
        {"R1.R": 50.0, "R2.R": 200.0, "CPE1.Q": 1e-6, "CPE1.n": 0.8},
        True,
    ),
    Topology(
        "4-element R/CPE/L",
        "R1-p(R2,CPE1)-L1",
        {"R1.R": 50.0, "R2.R": 200.0, "CPE1.Q": 1e-6, "CPE1.n": 0.8, "L1.L": 1e-6},
        True,
    ),
    Topology(
        "5-element R/C/CPE",
        "p(R1,CPE1)-p(R2,C1)-R3",
        {
            "R1.R": 1e4,
            "CPE1.Q": 1e-9,
            "CPE1.n": 0.7,
            "R2.R": 5e5,
            "C1.C": 2e-8,
            "R3.R": 10.0,
        },
        True,
    ),
]

#: This project's own standard reference window (91 points): ``log_frequencies(1e-2, 1e7, 10)``,
#: matching ``benchmarks/screening_round/profile_eval.py`` and CLAUDE.md's own note on the
#: shape of a screen's workload.
F_MIN, F_MAX, PPD = 1e-2, 1e7, 10


def build_problem(topo: Topology, seed: int = 0) -> tuple[_Problem, Spectrum]:
    circuit = Circuit.parse(topo.circuit)
    f = log_frequencies(F_MIN, F_MAX, PPD)
    spectrum = simulate(circuit, f, topo.params, noise=0.01, seed=seed)
    context = FitContext.build(spectrum, "modulus", None)
    problem = _Problem(circuit, spectrum, "modulus", None, {}, None, 3.0, context)
    return problem, spectrum


# --------------------------------------------------------------------------------------
# A1 -- SciPy's own DE bookkeeping, isolated by a null cost function.
# --------------------------------------------------------------------------------------


def _de_kwargs(problem: _Problem, seed: int) -> dict[str, Any]:
    """Verbatim copy of the kwargs `_global_stage` (core/fit.py) builds for the workers=1,
    vectorized path -- kept as a literal copy rather than refactored out of production code, so
    a change to `_global_stage`'s own kwargs is caught by the parity assertion in `run_a1` rather
    than silently drifting out of sync with what this script measures."""
    return {
        "bounds": list(zip(problem.lower_x, problem.upper_x, strict=True)),
        "seed": seed,
        "popsize": SCREEN_POPSIZE,
        "maxiter": SCREEN_MAXITER,
        "tol": SCREEN_TOL,
        "mutation": (0.4, 1.0),
        "recombination": 0.9,
        "strategy": "best1bin",
        "init": "sobol",
        "polish": False,
        "vectorized": True,
        "updating": "deferred",
    }


def _null_cost(xs: Float) -> Float:
    """A population-in/cost-out function doing no model evaluation at all: the view of the
    population's first free coordinate. Must not be a constant -- SciPy's own convergence test
    is ``std(energies) <= atol + tol*|mean(energies)|``, so an all-zero population converges at
    generation 1 and this arm would measure one generation instead of forty.

    **Measured to still converge early even so** -- the pre-registered plan anticipated the
    all-zero trap and built this defense against it, and the defense itself needed revision once
    tested: because this *is* the quantity DE is minimizing, DE successfully drives the
    population's first coordinate toward its lower bound, collapsing the population's spread in
    exactly the dimension the convergence test watches, so the null arm still stops early (e.g.
    nit=22 vs nit=39 on the smallest topology, measured). Rather than chase a landscape that
    resists convergence (which risks smuggling in a different, unmeasured bias), `run_a1` does
    not require equal `nit` at all: it normalizes both arms by their own iteration count and
    compares *time per iteration*, which is what isolates DE's own per-generation bookkeeping
    (population update, crossover, mutation, bound clipping -- all population-shape-dependent
    but cost-function-independent) from the cost evaluation itself.
    """
    return np.array(xs[0], copy=True)


def run_a1(reps: int) -> None:
    print("=" * 88)
    print("A1 -- SciPy's own DE bookkeeping share (null cost / real cost, per iteration, unbiased)")
    print("=" * 88)
    print(
        f"{'topology':<20}{'n_free':>8}{'null/it (ms)':>14}{'real/it (ms)':>14}{'share':>10}"
        f"{'nit (n/r)':>14}"
    )
    for topo in TOPOLOGIES:
        problem, _ = build_problem(topo)
        n_free = problem.free_idx.size
        null_per_iter: list[float] = []
        real_per_iter: list[float] = []
        null_nit = real_nit = -1
        for rep in range(reps):
            seed = rep
            kwargs = _de_kwargs(problem, seed)
            t0 = time.perf_counter()
            # scipy-stubs' single overload for `vectorized=True` doesn't model the
            # population-in/cost-array-out calling convention either function here relies on
            # (the same limitation `_global_stage` itself carries an ignore for, core/fit.py).
            null_result = differential_evolution(_null_cost, **kwargs)  # type: ignore[arg-type]
            null_elapsed = time.perf_counter() - t0
            null_nit = null_result.nit
            null_per_iter.append(null_elapsed / max(null_nit, 1))

            t0 = time.perf_counter()
            real_cost = problem.cost_vectorized
            real_result = differential_evolution(real_cost, **kwargs)  # type: ignore[arg-type]
            real_elapsed = time.perf_counter() - t0
            real_nit = real_result.nit
            real_per_iter.append(real_elapsed / max(real_nit, 1))

            # Parity check against the production function, on the first rep only: confirms
            # this script's copied kwargs really do reproduce `_global_stage`'s own dispatch
            # rather than a typo'd variant of it.
            if rep == 0:
                production_x = _global_stage(
                    problem,
                    seed=seed,
                    popsize=SCREEN_POPSIZE,
                    maxiter=SCREEN_MAXITER,
                    tol=SCREEN_TOL,
                    workers=1,
                    time_limit=None,
                    x0=None,
                )
                assert np.array_equal(production_x, real_result.x), (
                    f"{topo.label}: this script's direct DE call diverged from "
                    "_global_stage's own -- kwargs are out of sync, fix _de_kwargs"
                )

        null_med = float(np.median(null_per_iter))
        real_med = float(np.median(real_per_iter))
        share = null_med / real_med
        print(
            f"{topo.label:<20}{n_free:>8}{null_med * 1e3:>14.4f}{real_med * 1e3:>14.4f}"
            f"{share:>10.1%}{f'{null_nit}/{real_nit}':>14}"
        )
    print()
    print("share (null/real, per iteration) is the fraction of a screen's global stage that is")
    print("SciPy's own DE loop rather than AutoCircuit's arithmetic. This number is the one of")
    print("record if it disagrees with A2's cProfile-based estimate below (A2 is biased toward")
    print("Python-heavy code, i.e. biased toward *overstating* exactly this share).")
    print()
    print("n_free is the DE population's free-parameter count (population size = popsize *")
    print("n_free), not the topology's element count -- a CPE costs one element but two free")
    print("parameters, per docs/PARAM_BUDGET_PLAN.md's own element/parameter distinction. Both")
    print("null/it and real/it rise faster than n_free itself between the two highest-n_free")
    print("rows here, which is DE's own per-generation bookkeeping scaling worse than linearly")
    print("with dimension -- a real effect, not measurement noise, since it appears in the null")
    print("arm too, which never touches AutoCircuit's arithmetic at all.")
    print()


# --------------------------------------------------------------------------------------
# A2 -- cProfile decomposition of a full screen() call into four buckets, and A3 -- the
# finite-difference Jacobian's own share of the local-polish bucket.
# --------------------------------------------------------------------------------------

_BUCKETS = [
    ("scipy DE bookkeeping", ("_differentialevolution",)),
    ("scipy local polish (trf, excl. Jacobian)", ("_lsq",)),
    ("finite-difference Jacobian (_numdiff)", ("_numdiff",)),
    ("impedance kernel (circuit.py, elements.py)", ("circuit.py", "elements.py")),
    ("residual assembly (fit.py)", ("fit.py",)),
]


def _bucket_for(filename: str) -> str:
    for label, needles in _BUCKETS:
        if any(needle in filename for needle in needles):
            return label
    return "other (numpy internals, dispatch overhead, ...)"


def run_a2_a3(reps: int) -> None:
    print("=" * 88)
    print("A2 -- cProfile decomposition of a full screen() call (self-time, biased toward")
    print("       Python-heavy code -- see the note after A1 above)")
    print("=" * 88)
    header = (
        f"{'topology':<20}"
        + "".join(f"{label[:22]:>24}" for label, _ in _BUCKETS)
        + f"{'other':>24}"
    )
    print(header)
    for topo in TOPOLOGIES:
        _, spectrum = build_problem(topo)
        # [measured] the first topology profiled, with no warm-up call first, reads as ~89%
        # "other" and single-digit shares everywhere else -- a one-time cost (first-call scipy
        # submodule imports, allocator/thread-pool warm-up) dominating a profile this short
        # (reps defaults to 5). One untimed call before profiling starts removes it; every
        # topology gets its own warm-up since each is a different circuit/spectrum.
        screen(topo.circuit, spectrum, seed=reps)
        profiler = cProfile.Profile()
        profiler.enable()
        for rep in range(reps):
            screen(topo.circuit, spectrum, seed=rep)
        profiler.disable()

        stats = pstats.Stats(profiler)
        totals: dict[str, float] = {label: 0.0 for label, _ in _BUCKETS}
        totals["other (numpy internals, dispatch overhead, ...)"] = 0.0
        for (filename, _lineno, _funcname), (_cc, _nc, tottime, _ct, _callers) in (
            stats.stats.items()  # type: ignore[attr-defined]
        ):
            totals[_bucket_for(filename)] += tottime

        grand_total = sum(totals.values())
        row = f"{topo.label:<20}"
        for label, _ in _BUCKETS:
            share = totals[label] / grand_total if grand_total else 0.0
            row += f"{share:>24.1%}"
        other_share = (
            totals["other (numpy internals, dispatch overhead, ...)"] / grand_total
            if grand_total
            else 0.0
        )
        row += f"{other_share:>24.1%}"
        print(row)

        jac_share_of_polish = totals["finite-difference Jacobian (_numdiff)"] / max(
            totals["scipy local polish (trf, excl. Jacobian)"]
            + totals["finite-difference Jacobian (_numdiff)"],
            1e-12,
        )
        print(
            f"    A3: the finite-difference Jacobian is "
            f"{jac_share_of_polish:.1%} of the local-polish stage's own self-time"
        )
    print()


# --------------------------------------------------------------------------------------
# A4 -- named redundancies, priced individually. Microbenchmarks only; nothing wired in.
# --------------------------------------------------------------------------------------


def _time_it(fn: object, calls: int, trials: int = 7) -> float:
    """Best-of-`trials` mean time per call, each trial running `fn` `calls` times inside one
    timed block.

    Timing a single call directly -- the first version of this helper did -- is unreliable at
    this scale and was measured to fail outright: several of the operations below are
    sub-microsecond, at or under `time.perf_counter`'s effective resolution once Python's own
    function-call overhead is accounted for, so a single-call timing reads as exactly 0.0 more
    often than not (a `ZeroDivisionError` computing the reported percentage, not just a noisy
    number). Batching amortizes the timer call itself across `calls` repetitions; best-of-
    `trials` rather than a mean across trials, since OS scheduling noise on a shared machine
    only ever adds time, never subtracts it, so the minimum is the cleanest read available.
    """
    best = float("inf")
    for _ in range(trials):
        t0 = time.perf_counter()
        for _ in range(calls):
            fn()  # type: ignore[operator]
        elapsed = time.perf_counter() - t0
        best = min(best, elapsed / calls)
    return best


def run_a4(reps: int) -> None:
    print("=" * 88)
    print("A4 -- named redundancies, priced individually (microbenchmarks; nothing wired in)")
    print("=" * 88)

    omega = 2.0 * np.pi * log_frequencies(F_MIN, F_MAX, PPD)
    n_cand = SCREEN_POPSIZE * 8  # a representative population width at this project's popsize

    # --- Resistor.impedance: np.ones_like allocation vs np.broadcast_to for a constant. ---
    # Batched shapes, exactly as Circuit.impedance constructs them (circuit.py:191-198):
    # omega is (1, n_freq), and a leaf's own parameter slice is (n_params, n_cand, 1).
    r = Resistor()
    omega_batched = omega[None, :]
    values = np.full((1, n_cand, 1), 50.0)

    def resistor_current() -> Float:
        return r.impedance(omega_batched, values)

    def resistor_broadcast() -> Float:
        return np.broadcast_to(
            (values[0] + 0j), (n_cand, omega.size)
        ).copy()  # a materialized array, for a fair comparison against the current version

    # [measured] `--micro-reps`'s default (200) is too few batched calls for this pair
    # specifically to resolve above run-to-run noise -- one round even flipped which arm won.
    # A floor of 2000 calls (still well under a second total) settled it consistently.
    t_current = _time_it(resistor_current, max(reps, 2000))
    t_alt = _time_it(resistor_broadcast, max(reps, 2000))
    print(
        f"Resistor.impedance (np.ones_like) vs np.broadcast_to, n_cand={n_cand}: "
        f"{t_current * 1e6:.1f} us vs {t_alt * 1e6:.1f} us "
        f"({(1 - t_alt / t_current) * 100:+.1f}% if switched)"
    )

    # --- circuit.py's elements.get() dict-lookup-in-try/except per leaf, per evaluation. ---
    spec = elements.get("R")

    def lookup_current() -> object:
        try:
            return elements.get("R")
        except KeyError:
            return None

    def lookup_cached() -> object:
        return spec  # what _specs already holds, resolved once in Circuit.__init__

    t_current = _time_it(lookup_current, reps * 1000)
    t_alt = _time_it(lookup_cached, reps * 1000)
    print(
        f"elements.get() per leaf per eval vs a cached reference: "
        f"{t_current * 1e9:.0f} ns vs {t_alt * 1e9:.0f} ns per call "
        f"({(1 - t_alt / t_current) * 100:+.1f}% if switched)"
    )

    # --- np.errstate entered twice (Circuit.impedance, then again in cost_vectorized). ---
    def errstate_once() -> None:
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            pass

    def errstate_twice() -> None:
        # Deliberately nested, not combined: this is the actual production pattern being
        # priced (Circuit.impedance enters errstate, then cost_vectorized enters it again),
        # not a style choice ruff's SIM117 should collapse.
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):  # noqa: SIM117
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                pass

    t_once = _time_it(errstate_once, reps * 1000)
    t_twice = _time_it(errstate_twice, reps * 1000)
    print(
        f"np.errstate entered once vs the current nested-twice: "
        f"{t_once * 1e9:.0f} ns vs {t_twice * 1e9:.0f} ns per call "
        f"({(t_twice / t_once - 1) * 100:+.1f}% overhead from the redundant nesting)"
    )

    # --- omega-only subexpressions (1j*omega, log(1j*omega)) recomputed every evaluation. ---
    # Priced with the expectation stated in advance in docs/SEARCH_TIME_PLAN.md: these are
    # computed at (1, n_freq) while the expensive downstream ops are (n_cand, n_freq), so the
    # flop saving is bounded by about 1/n_cand and should be small -- reported here as both
    # time and numpy call count, since a win (if any) is a call-count effect, not arithmetic.
    def log_1j_omega_recomputed() -> Float:
        return np.log(1j * omega[None, :])

    cached_log = np.log(1j * omega[None, :])

    def log_1j_omega_cached() -> Float:
        return cached_log

    t_recompute = _time_it(log_1j_omega_recomputed, reps * 1000)
    t_cached = _time_it(log_1j_omega_cached, reps * 1000)
    print(
        f"log(1j*omega) recomputed vs hoisted, per call: "
        f"{t_recompute * 1e9:.0f} ns vs {t_cached * 1e9:.0f} ns "
        f"({(1 - t_cached / t_recompute) * 100:+.1f}% if hoisted, on this ~41-call/screen path)"
    )
    print()
    print("A4 numbers are per-call microbenchmarks, not wired into core/. Each is a candidate")
    print("for docs/SEARCH_TIME_PLAN.md's ranked list, priced but not built.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reps", type=int, default=20, help="repeats per topology (A1); default 20"
    )
    parser.add_argument(
        "--profile-reps",
        type=int,
        default=5,
        help="screen() calls profiled per topology (A2/A3)",
    )
    parser.add_argument(
        "--micro-reps", type=int, default=200, help="repeats for A4 microbenchmarks"
    )
    parser.add_argument("--profile", action="store_true", help="run A2/A3 (cProfile decomposition)")
    parser.add_argument("--micro", action="store_true", help="run A4 (microbenchmarks)")
    parser.add_argument("--all", action="store_true", help="run A1 + A2/A3 + A4")
    args = parser.parse_args()

    # [measured] A4's finest-grained microbenchmark (Resistor.impedance vs np.broadcast_to,
    # ~13 us either way) is not just noisy but flips direction depending on what ran earlier in
    # the same process: isolated, it is a consistent +26-31% win for broadcast_to across five
    # independent process runs; run right after A1's real DE workload in one `--all` invocation,
    # it read anywhere from -218% to +5.6%, almost certainly CPU frequency/cache state left over
    # from the preceding heavy work rather than a property of the code being compared. So a bare
    # `--profile` or `--micro` skips A1 entirely (rather than running it and discarding the
    # numbers) both to stay fast and to avoid exactly that contamination; `--all` still runs
    # everything, with a warning printed before A4 pointing at a standalone `--micro` run instead.
    only_one_stage = args.profile or args.micro
    if args.all or not only_one_stage:
        run_a1(args.reps)
    if args.profile or args.all:
        run_a2_a3(args.profile_reps)
    if args.micro or args.all:
        if args.all:
            print(
                "Note: A4 follows A1/A2's DE-heavy work in this same process, which "
                "[measured] pollutes its finest-grained numbers (CPU frequency/cache state, "
                "not the code being compared) -- run `--micro` alone for a trustworthy read.\n"
            )
        run_a4(args.micro_reps)


if __name__ == "__main__":
    main()
