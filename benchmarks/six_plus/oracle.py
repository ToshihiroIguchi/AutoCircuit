"""Experiment X8 of ``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5.1: with the true topology handed to
the fitter directly -- no topology search at all -- does the no-initial-values global search
reach the global optimum?

On noise-free data the truth's own parameter vector gives cost exactly zero, so "did it get
there" is decidable rather than a judgement call: :func:`autocircuit.core.fit.fit`'s
``relative_error`` is either at machine precision or it is not.

A pilot already found the headline on one seven-element, nine-parameter reference
(``R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)``, 71 points, noise 0): the shipped default
``restarts=5, popsize=20, maxiter=400`` reaches 0.228% relative error instead of 0, while
``restarts=50`` (default ``popsize``/``maxiter``) or ``popsize=60, maxiter=1500`` (default
``restarts``) each independently reach exactly 0. That single point cannot say whether the
defect is indexed on the **element count** or the **parameter count** -- a circuit can grow
either without growing the other. This file turns it into a 2-D measurement: eight fixed cases
spanning 4-8 elements and 4-9 parameters, crossed with the full ``restarts`` x
``(popsize, maxiter)`` budget grid, on both noise-free data (a strict zero/nonzero verdict) and
1% noise (a chi-squared ratio against the truth's own parameters, since the noisy optimum is not
zero).

*Decision this feeds:* if convergence tracks element count rather than parameter count (or vice
versa), the shipped default budget should scale on that axis specifically rather than on total
element count as it does today; if it tracks neither cleanly, the current single flat default is
already about as good as a flat default can be and the fix has to be adaptive (e.g. from
``n_free`` at the call site) rather than a bigger constant.

Cases (see ``CASES`` below for values and windows; four reuse fixtures already vetted in
``benchmarks/discovery_v2.py``, four are new and pass ``benchmarks/autoeis_round/arena.py``'s
identifiability screen at their own window before being used -- see ``_check_identifiable``)::

    label       circuit                                       n_el  n_par
    4el/4par    p(R1,C1)-p(R2,C2)                                4      4
    5el/5par    C1-R1-L1-p(R2,C2)                                5      5
    6el/6par    p(R1,C1)-p(R2,C2)-p(R3,C3)                       6      6
    7el/7par    R4-p(R1,C1)-p(R2,C2)-p(R3,C3)                    7      7
    8el/8par    p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)              8      8
    6el/8par    C1-R1-L1-SKINF1-p(R2,CPE1)                       6      8
    6el/9par    p(R1,CPE1)-p(R2,CPE2)-p(R3,CPE3)                 6      9
    7el/9par    R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)                    7      9

The budget grid is ``restarts in {1, 5, 10, 20, 50}`` crossed with ``(popsize, maxiter) in
{(8, 40), (20, 400), (40, 800), (60, 1500)}`` -- 20 combinations per case. The global stage's
cost grows with ``restarts * popsize * n_free * maxiter`` (``popsize`` is scipy's own
per-parameter population multiplier, so the free-parameter count belongs in the estimate), and
at the high end that is minutes per single fit; ``--max-nfe`` bounds the sweep by skipping
combinations whose estimate exceeds it, and the default is chosen so the full grid over all
eight cases finishes well under an hour on 8 cores. Raise it explicitly to reproduce the pilot's
two named reference points on the hardest (9-parameter) cases -- both are in-budget only above
roughly 4e6.

Run with the package on the path (it is not pip-installed on the dev machine)::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/oracle.py --out results/x8_oracle.json --workers 8
    python benchmarks/six_plus/oracle.py --out results/x8_oracle.json --cases 9par --max-nfe 5000000
    python benchmarks/six_plus/oracle.py --out /tmp/smoke.json --quick
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

_BENCH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BENCH_DIR))
sys.path.insert(0, str(_BENCH_DIR / "autoeis_round"))

import arena  # noqa: E402  (module import: its constants are overridden per-case, see below)
from deviation import worst_deviation  # noqa: E402
from discovery_v2 import LARGE_REFERENCES, REFERENCES  # noqa: E402

from autocircuit.core.circuit import Circuit  # noqa: E402
from autocircuit.core.fit import fit, screen  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402

#: Relative error at or below this counts as "reached the global optimum" on noise-free data,
#: where the truth's own parameters give exactly zero cost.
CONVERGENCE_RTOL: float = 1e-6

#: Proportional noise level for the second half of each row, matching every reference in
#: ``benchmarks/discovery_v2.py``.
NOISE_LEVEL: float = 0.01

#: Fixed noise realisations for the noisy half, per ``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5.1.
NOISE_SEEDS: tuple[int, ...] = (1, 2, 3)


class Budget(NamedTuple):
    """One point of the global-search budget grid."""

    restarts: int
    popsize: int
    maxiter: int

    @property
    def label(self) -> str:
        return f"r{self.restarts}/p{self.popsize}/m{self.maxiter}"


#: restarts x (popsize, maxiter), per the plan: (8, 40) is the tier-1 screening budget,
#: (20, 400) is the shipped default, (40, 800) and (60, 1500) are the pilot's larger alternatives.
RESTARTS: tuple[int, ...] = (1, 5, 10, 20, 50)
POP_MAXITER: tuple[tuple[int, int], ...] = ((8, 40), (20, 400), (40, 800), (60, 1500))
BUDGETS: tuple[Budget, ...] = tuple(Budget(r, p, m) for r in RESTARTS for p, m in POP_MAXITER)

#: [measured] A single fit of the hardest (9-parameter) case at restarts=50, popsize=20,
#: maxiter=400 -- nfe estimate 3.6e6 -- took 50.3s on this machine; the same case at
#: restarts=50, popsize=60, maxiter=1500 (nfe 4.05e7) did not finish in two minutes. The default
#: below keeps the sweep well under an hour across all eight cases and four noise conditions
#: (1 noise-free + 3 noisy seeds) per budget; raise it via --max-nfe for a slower, more complete
#: run.
DEFAULT_MAX_NFE: int = 2_000_000


def _nfe_estimate(budget: Budget, n_free: int) -> int:
    """A cheap upper-bound proxy for one fit's global-stage cost.

    Not the exact number of objective evaluations differential evolution performs -- ``tol``
    can stop a restart well short of ``maxiter`` -- but ``restarts`` independent runs of a
    population sized ``popsize * n_free`` (scipy's own convention) over up to ``maxiter``
    generations is the right order of magnitude, and it costs nothing to compute before running
    anything.
    """
    return budget.restarts * budget.popsize * n_free * budget.maxiter


@dataclass(frozen=True)
class Case:
    """One (topology, parameter set, frequency window) fixture for the oracle sweep."""

    label: str
    circuit: str
    params: dict[str, float]
    f_min: float
    f_max: float
    points_per_decade: int = 10
    noise: float = 0.01
    #: Whether ``params``/window were reused from an existing, already-vetted reference in
    #: ``benchmarks/discovery_v2.py``. Only cases with ``reused=False`` go through the
    #: identifiability screen here -- see ``_check_identifiable``.
    reused: bool = True

    def spectrum(self, *, noise: float, seed: int) -> Spectrum:
        frequencies = log_frequencies(self.f_min, self.f_max, self.points_per_decade)
        return simulate(self.circuit, frequencies, self.params, noise=noise, seed=seed)

    @property
    def n_elements(self) -> int:
        return len(Circuit.parse(self.circuit).leaves)

    @property
    def n_parameters(self) -> int:
        return len(Circuit.parse(self.circuit).param_names)


def _lookup(references: Sequence[Any], circuit: str) -> Any:
    """Find a ``Reference`` by its circuit string, so values are imported rather than retyped."""
    for reference in references:
        if reference.circuit == circuit:
            return reference
    raise KeyError(f"no reference with circuit {circuit!r}")


_MW2 = _lookup(REFERENCES, "p(R1,C1)-p(R2,C2)")
_MW3 = _lookup(LARGE_REFERENCES, "p(R1,C1)-p(R2,C2)-p(R3,C3)")
_CAP_INTERFACIAL = _lookup(LARGE_REFERENCES, "C1-R1-L1-SKINF1-p(R2,CPE1)")
_RANDLES_ESL = _lookup(LARGE_REFERENCES, "R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)")

#: [measured, discovery_v2.py LARGE_REFERENCES comment] at the reference's own R2.R = 5000 the
#: interfacial block leaves 3 of 8 parameters unresolved at 1% noise; at R2.R = 5 it is 0/8.
#: This case uses the identifiable variant.
_CAP_INTERFACIAL_PARAMS = dict(_CAP_INTERFACIAL.params)
_CAP_INTERFACIAL_PARAMS["R2.R"] = 5.0

CASES: tuple[Case, ...] = (
    Case("4el/4par", _MW2.circuit, dict(_MW2.params), _MW2.f_min, _MW2.f_max, noise=_MW2.noise),
    Case(
        # New: a capacitor-shaped series ladder (C-R-L) plus one parallel RC block, well
        # separated by roughly two decades at each corner -- the identifiability screen requires
        # this explicitly, see main().
        "5el/5par",
        "C1-R1-L1-p(R2,C2)",
        {"C1.C": 3.183e-3, "R1.R": 50.0, "L1.L": 7.96e-4, "R2.R": 500.0, "C2.C": 3.183e-6},
        1e-2,
        1e6,
        reused=False,
    ),
    Case("6el/6par", _MW3.circuit, dict(_MW3.params), _MW3.f_min, _MW3.f_max, noise=_MW3.noise),
    Case(
        # New: the six-element three-block reference's own shape does not clear the leverage
        # screen at a size-matched separation (its blocks 2 and 3 are deliberately only 0.6
        # decades apart, see LARGE_REFERENCES), so this is a fresh three-block ladder with equal
        # plateau resistances and two-decade corner spacing, plus a series R4 -- identifiable
        # because R4 sets the high-frequency real asymptote once every block's capacitor has
        # shorted it out.
        "7el/7par",
        "R4-p(R1,C1)-p(R2,C2)-p(R3,C3)",
        {
            "R4.R": 300.0,
            "R1.R": 1000.0,
            "C1.C": 1.5915494309189533e-6,
            "R2.R": 1000.0,
            "C2.C": 1.5915494309189534e-8,
            "R3.R": 1000.0,
            "C3.C": 1.5915494309189535e-10,
        },
        1.0,
        1e8,
        reused=False,
    ),
    Case(
        # New: the same equal-resistance, two-decade-spaced ladder as 7el/7par with a fourth
        # block appended instead of a series resistor, adding an element and a parameter
        # together (the parameter-count control for the element-count-matched 6el/9par case).
        "8el/8par",
        "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)",
        {
            "R1.R": 1000.0,
            "C1.C": 1.5915494309189533e-6,
            "R2.R": 1000.0,
            "C2.C": 1.5915494309189534e-8,
            "R3.R": 1000.0,
            "C3.C": 1.5915494309189535e-10,
            "R4.R": 1000.0,
            "C4.C": 1.5915494309189534e-12,
        },
        1.0,
        1e10,
        reused=False,
    ),
    Case(
        "6el/8par",
        _CAP_INTERFACIAL.circuit,
        _CAP_INTERFACIAL_PARAMS,
        _CAP_INTERFACIAL.f_min,
        _CAP_INTERFACIAL.f_max,
        noise=_CAP_INTERFACIAL.noise,
    ),
    Case(
        # New: same three-block, two-decade-spaced shape as 6el/6par/7el/7par/8el/8par, but with
        # CPE elements instead of ideal capacitors -- the parameter-count control that adds
        # parameters (three CPE.n exponents) without adding elements over 6el/6par.
        "6el/9par",
        "p(R1,CPE1)-p(R2,CPE2)-p(R3,CPE3)",
        {
            "R1.R": 1000.0,
            "CPE1.Q": 3.0313642078925785e-6,
            "CPE1.n": 0.9,
            "R2.R": 1000.0,
            "CPE2.Q": 4.8043884969592235e-8,
            "CPE2.n": 0.9,
            "R3.R": 1000.0,
            "CPE3.Q": 7.614442622769154e-10,
            "CPE3.n": 0.9,
        },
        1.0,
        1e8,
        reused=False,
    ),
    Case(
        "7el/9par",
        _RANDLES_ESL.circuit,
        dict(_RANDLES_ESL.params),
        _RANDLES_ESL.f_min,
        _RANDLES_ESL.f_max,
        noise=_RANDLES_ESL.noise,
    ),
)


def _parse_label(label: str) -> tuple[int, int]:
    el_part, par_part = label.split("/")
    return int(el_part.removesuffix("el")), int(par_part.removesuffix("par"))


for _case in CASES:
    _n_el, _n_par = _parse_label(_case.label)
    if (_case.n_elements, _case.n_parameters) != (_n_el, _n_par):
        raise AssertionError(
            f"case {_case.label!r}: circuit {_case.circuit!r} parses to {_case.n_elements} "
            f"elements and {_case.n_parameters} parameters, not {_n_el}/{_n_par} as labelled"
        )
del _case, _n_el, _n_par


def _check_identifiable(case: Case) -> None:
    """Verify a newly authored case's parameters are identifiable, at the case's own window.

    ``arena.parameter_leverage``/``arena.is_identifiable`` (``benchmarks/autoeis_round/arena.py``)
    read their sampling window and noise level from module-level constants rather than taking
    them as arguments, so this overrides those constants to match the case's own window and
    restores them afterwards.

    Only cases with ``reused=False`` are checked here. A case reused from
    ``benchmarks/discovery_v2.py`` is an existing, already-vetted reference and is not re-run
    through this screen: [measured] even the shipped six-element "three-block Maxwell-Wagner"
    reference (``LARGE_REFERENCES``) fails this leverage check at its own window -- its weakest
    parameter, C3.C, has 0.698% leverage against the 1% noise floor -- because two of its three
    blocks are deliberately only 0.6 decades apart (see that file's own comment); it is already
    known to be recoverable via the weaker unresolved-parameter and value-matched-deviation
    checks that ``is_identifiable`` also performs, at the reference's own noise realisation. That
    is a property of an existing fixture, not something a new case should reproduce.
    """
    saved = (arena.F_MIN, arena.F_MAX, arena.POINTS_PER_DECADE, arena.NOISE)
    arena.F_MIN, arena.F_MAX, arena.POINTS_PER_DECADE, arena.NOISE = (
        case.f_min,
        case.f_max,
        case.points_per_decade,
        case.noise,
    )
    try:
        leverage = arena.parameter_leverage(case.circuit, case.params)
        worst_name = min(leverage, key=lambda name: leverage[name])
        if leverage[worst_name] < arena.NOISE:
            raise SystemExit(
                f"error: case {case.label!r} ({case.circuit}) fails the identifiability screen: "
                f"parameter {worst_name!r} has leverage {leverage[worst_name]:.4%}, below the "
                f"{arena.NOISE:.2%} noise floor at window ({case.f_min:g}, {case.f_max:g}) Hz. "
                "Choose different parameter values or a different window -- this is not a case "
                "the data actually contains."
            )
        if not arena.is_identifiable(case.circuit, case.params):
            raise SystemExit(
                f"error: case {case.label!r} ({case.circuit}) fails the identifiability screen: "
                "a fit of the truth to its own noisy data left an unresolved parameter, or a "
                "value-matched deviation beyond the bar. Choose different parameter values."
            )
    finally:
        arena.F_MIN, arena.F_MAX, arena.POINTS_PER_DECADE, arena.NOISE = saved


def _run_case(
    case: Case,
    budgets: Sequence[Budget],
    max_nfe: int,
    workers: int,
    fit_seeds: int,
) -> list[dict[str, Any]]:
    """Sweep every in-budget point of the grid for one case, streaming a row per point."""
    n_free = case.n_parameters
    noise_free_spectrum = case.spectrum(noise=0.0, seed=0)
    screen_cost = screen(case.circuit, noise_free_spectrum)

    noisy_spectra = {seed: case.spectrum(noise=NOISE_LEVEL, seed=seed) for seed in NOISE_SEEDS}
    #: The reference each noisy chi2 is scored against: the truth's own parameters, refined
    #: locally with no global search, per docs/TOPOLOGY_6PLUS_PLAN.md section 5.1.
    truth_own_chi2 = {
        seed: fit(
            case.circuit, spectrum, initial=case.params, global_search=False, restarts=1
        ).chi2_reduced
        for seed, spectrum in noisy_spectra.items()
    }

    rows: list[dict[str, Any]] = []
    for budget in budgets:
        nfe = _nfe_estimate(budget, n_free)
        if nfe > max_nfe:
            continue

        # The noise-free fit is repeated over independent fitter seeds, because a single draw
        # cannot tell a budget that is too small from a basin the search reaches only sometimes.
        # [measured] The first version of this file ran one seed per cell and reported "1/1" or
        # "0/1"; on the nine-parameter case the same budget then converged or failed depending on
        # the seed, so every cell of that table was a one-sample Bernoulli draw. `converged` and
        # the timing below stay on seed 0 so the streamed row keeps its original meaning; the
        # rate is what the table reports.
        started = time.perf_counter()
        attempts = [
            fit(
                case.circuit,
                noise_free_spectrum,
                restarts=budget.restarts,
                popsize=budget.popsize,
                maxiter=budget.maxiter,
                seed=fit_seed,
                workers=workers,
            )
            for fit_seed in range(fit_seeds)
        ]
        seconds = (time.perf_counter() - started) / max(len(attempts), 1)
        result = attempts[0]
        n_converged = sum(1 for a in attempts if a.relative_error <= CONVERGENCE_RTOL)

        row: dict[str, Any] = {
            "fit_seeds": fit_seeds,
            "n_converged": n_converged,
            "relative_error_pct_all": [a.relative_error * 100.0 for a in attempts],
            "case": case.label,
            "circuit": case.circuit,
            "n_elements": case.n_elements,
            "n_parameters": case.n_parameters,
            "restarts": budget.restarts,
            "popsize": budget.popsize,
            "maxiter": budget.maxiter,
            "nfe_estimate": nfe,
            "screen_cost": screen_cost,
            "converged": bool(result.relative_error <= CONVERGENCE_RTOL),
            "relative_error_pct": result.relative_error * 100.0,
            "chi2_reduced": result.chi2_reduced,
            "worst_deviation_pct": worst_deviation(result.params, case.params) * 100.0,
            "seconds": seconds,
            "noisy": [],
        }

        for seed, spectrum in noisy_spectra.items():
            n_started = time.perf_counter()
            n_result = fit(
                case.circuit,
                spectrum,
                restarts=budget.restarts,
                popsize=budget.popsize,
                maxiter=budget.maxiter,
                seed=seed,
                workers=workers,
            )
            n_seconds = time.perf_counter() - n_started
            row["noisy"].append(
                {
                    "seed": seed,
                    "seconds": n_seconds,
                    "relative_error_pct": n_result.relative_error * 100.0,
                    "chi2_reduced": n_result.chi2_reduced,
                    "truth_own_chi2_reduced": truth_own_chi2[seed],
                    "chi2_ratio": n_result.chi2_reduced / truth_own_chi2[seed],
                    "worst_deviation_pct": worst_deviation(n_result.params, case.params) * 100.0,
                }
            )

        rows.append(row)
        print(json.dumps(row), flush=True)

    return rows


def _markdown_table(
    cases: Sequence[Case],
    budgets: Sequence[Budget],
    max_nfe: int,
    rows: Sequence[dict[str, Any]],
) -> str:
    """Rows = cases, columns = budgets, cells = noise-free convergence over the fitter seeds."""
    by_key = {(row["case"], (row["restarts"], row["popsize"], row["maxiter"])): row for row in rows}
    header = "| case | " + " | ".join(b.label for b in budgets) + " |"
    separator = "|" + "---|" * (len(budgets) + 1)
    lines = [header, separator]
    for case in cases:
        cells = []
        for budget in budgets:
            row = by_key.get((case.label, (budget.restarts, budget.popsize, budget.maxiter)))
            if row is None:
                over_budget = _nfe_estimate(budget, case.n_parameters) > max_nfe
                cells.append("skip" if over_budget else "-")
            else:
                attempts = int(row.get("fit_seeds", 1))
                hits = int(row.get("n_converged", 1 if row["converged"] else 0))
                cells.append(f"{hits}/{attempts}")
        lines.append(f"| {case.label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="X8: does the no-initial-values fitter reach the global optimum on a known "
        "topology, as a function of element count vs. parameter count?"
    )
    parser.add_argument("--out", required=True, type=Path, help="path to write the full JSON list")
    parser.add_argument(
        "--cases", default=None, help="only run cases whose label contains this substring"
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="process count forwarded to fit()'s global stage"
    )
    parser.add_argument(
        "--max-nfe",
        type=int,
        default=DEFAULT_MAX_NFE,
        help="skip budgets whose estimated global-stage cost (restarts*popsize*n_free*maxiter) "
        "exceeds this",
    )
    parser.add_argument(
        "--budgets",
        default=None,
        help=(
            "comma-separated budget labels to keep, e.g. 'r1/p8/m40,r5/p20/m400'. The full grid "
            "answers which budgets converge at all; a seeded rate only needs the ones that "
            "decide something -- the tier-1 screen and the shipped default."
        ),
    )
    parser.add_argument(
        "--fit-seeds",
        type=int,
        default=1,
        help=(
            "independent fitter seeds per noise-free cell. One draw cannot separate a budget "
            "that is too small from a basin the search reaches only sometimes, so any claim "
            "about convergence needs more than one."
        ),
    )
    parser.add_argument(
        "--quick", action="store_true", help="tiny grid, one case, for a plumbing smoke test"
    )
    args = parser.parse_args()

    cases = [case for case in CASES if args.cases is None or args.cases in case.label]
    if not cases:
        raise SystemExit(f"error: no case label contains {args.cases!r}")

    for case in cases:
        if not case.reused:
            _check_identifiable(case)

    budgets: Sequence[Budget] = BUDGETS
    max_nfe = args.max_nfe
    if args.quick:
        cases = cases[:1]
        budgets = (Budget(1, 8, 40), Budget(5, 20, 400))
        max_nfe = 10**12
    if args.budgets is not None:
        keep = {label.strip() for label in args.budgets.split(",")}
        budgets = [b for b in budgets if b.label in keep]
        if not budgets:
            raise SystemExit(f"no budget matched {args.budgets!r}")

    all_rows: list[dict[str, Any]] = []
    for case in cases:
        print(
            f"# {case.label}: {case.circuit}  "
            f"({case.n_elements} elements, {case.n_parameters} parameters)",
            file=sys.stderr,
            flush=True,
        )
        all_rows.extend(_run_case(case, budgets, max_nfe, args.workers, args.fit_seeds))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(all_rows, indent=2), encoding="utf-8")

    print()
    print("Noise-free convergence (relative error <= 1e-6), by case and budget:")
    print(_markdown_table(cases, budgets, max_nfe, all_rows))


if __name__ == "__main__":
    main()
