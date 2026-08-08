"""AutoCircuit command line.

Built on argparse rather than a CLI framework so that the package keeps numpy and scipy as
its only runtime dependencies, which is what lets the same wheel run under Pyodide.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from autocircuit import __version__
from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import discover
from autocircuit.core.drt import DRTResult, drt
from autocircuit.core.elements import (
    COMPONENT_POOL,
    DEFAULT_POOL,
    ELECTROCHEMICAL_POOL,
    REGISTRY,
)
from autocircuit.core.fit import FitResult, fit
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.spice import to_netlist
from autocircuit.core.validate import lin_kk
from autocircuit.io import read as read_spectrum
from autocircuit.io import write_csv, write_zview

POOLS = {
    "default": DEFAULT_POOL,
    "component": COMPONENT_POOL,
    "electrochemical": ELECTROCHEMICAL_POOL,
}


def _parse_assignments(items: Sequence[str] | None, what: str) -> dict[str, float]:
    """Parse repeated ``NAME=VALUE`` options."""
    out: dict[str, float] = {}
    for item in items or ():
        if "=" not in item:
            raise SystemExit(f"error: {what} must be given as NAME=VALUE, got {item!r}")
        name, _, text = item.partition("=")
        try:
            out[name.strip()] = float(text)
        except ValueError:
            raise SystemExit(
                f"error: {what} value for {name!r} is not a number: {text!r}"
            ) from None
    return out


def _parse_bounds(items: Sequence[str] | None) -> dict[str, tuple[float, float]]:
    """Parse repeated ``NAME=LO:HI`` options."""
    out: dict[str, tuple[float, float]] = {}
    for item in items or ():
        name, _, span = item.partition("=")
        lo_text, _, hi_text = span.partition(":")
        try:
            out[name.strip()] = (float(lo_text), float(hi_text))
        except ValueError:
            raise SystemExit(f"error: bounds must be NAME=LO:HI, got {item!r}") from None
    return out


def _load(args: argparse.Namespace) -> Spectrum:
    hints: dict[str, Any] = {}
    if getattr(args, "port_config", None):
        hints["port_config"] = args.port_config
    if getattr(args, "negate_imag", False):
        hints["negate_imag"] = True
    spectrum = read_spectrum(args.data, format=args.format, **hints)
    if getattr(args, "fmin", None) or getattr(args, "fmax", None):
        spectrum = spectrum.select(args.fmin, args.fmax)
    return spectrum


def _describe(spectrum: Spectrum) -> str:
    lines = [
        f"Data          : {spectrum.metadata.get('source_path', '<memory>')}",
        f"Format        : {spectrum.metadata.get('format', 'unknown')}",
        f"Points        : {spectrum.n}",
        f"Frequency     : {spectrum.f[0]:.6g} Hz .. {spectrum.f[-1]:.6g} Hz",
        f"|Z|           : {np.abs(spectrum.z).min():.6g} .. {np.abs(spectrum.z).max():.6g} ohm",
    ]
    convention = spectrum.metadata.get("imag_sign_convention")
    if convention:
        lines.append(f"Im(Z) handling: {convention}")
    for warning in spectrum.metadata.get("warnings", []) or []:
        lines.append(f"! {warning}")
    return "\n".join(lines)


def _preflight(spectrum: Spectrum, skip: bool) -> None:
    """Warn before fitting if the data is not Kramers-Kronig consistent."""
    if skip:
        return
    try:
        result = lin_kk(spectrum)
    except (ValueError, np.linalg.LinAlgError) as exc:  # pragma: no cover - defensive
        print(f"! Lin-KK pre-check could not run: {exc}", file=sys.stderr)
        return
    if not result.passed:
        print(result.summary(spectrum), file=sys.stderr)
        print(
            "\n! Continuing anyway, but treat the fitted parameters with suspicion.\n",
            file=sys.stderr,
        )


def _write_outputs(
    args: argparse.Namespace, spectrum: Spectrum, circuit: Circuit, result: FitResult
) -> None:
    if getattr(args, "json", None):
        payload = result.to_dict()
        payload["data"] = {
            "source": str(spectrum.metadata.get("source_path", "")),
            "n_points": spectrum.n,
            "f_min": float(spectrum.f[0]),
            "f_max": float(spectrum.f[-1]),
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote fit report to {args.json}")
    if getattr(args, "spice", None):
        netlist = to_netlist(
            circuit,
            result.values,
            f_min=float(spectrum.f[0]),
            f_max=float(spectrum.f[-1]),
            name=args.subckt,
            error_target=args.spice_error,
            header=f"Fitted to {spectrum.metadata.get('source_path', 'data')}",
        )
        Path(args.spice).write_text(netlist, encoding="utf-8")
        print(f"Wrote SPICE subcircuit to {args.spice}")
    if getattr(args, "model_csv", None):
        write_csv(Spectrum(spectrum.f, result.z_model), args.model_csv)
        print(f"Wrote model spectrum to {args.model_csv}")


# -- Commands --------------------------------------------------------------------------------


def cmd_fit(args: argparse.Namespace) -> int:
    spectrum = _load(args)
    print(_describe(spectrum))
    print()
    _preflight(spectrum, args.no_validate)

    circuit = Circuit.parse(args.circuit)
    result = fit(
        circuit,
        spectrum,
        weighting=args.weighting,
        fixed=_parse_assignments(args.fix, "--fix"),
        bounds=_parse_bounds(args.bound),
        initial=_parse_assignments(args.initial, "--initial") or None,
        restarts=args.restarts,
        seed=args.seed,
        popsize=args.popsize,
        maxiter=args.maxiter,
        time_limit=args.time_limit,
    )
    print(result.summary(spectrum))
    _write_outputs(args, spectrum, circuit, result)
    return 0 if result.success else 1


def _progress_reporter() -> Callable[[int, int, str | None], None]:
    """Build an ``on_progress`` callback that writes a self-overwriting line to stderr.

    Throttled to roughly 20 updates per second or every 25 candidates, whichever comes first,
    so that a screen firing the callback thousands of times cannot dominate the run time.
    It writes to stderr on purpose: stdout carries the report, which must stay pipeable.
    """
    last_time = 0.0
    last_done = -1

    def on_progress(done: int, total: int, best: str | None) -> None:
        nonlocal last_time, last_done
        now = time.perf_counter()
        finished = done >= total
        if not finished and now - last_time < 0.05 and done - last_done < 25:
            return
        last_time, last_done = now, done
        sys.stderr.write(f"\r  screening {done}/{total}  best so far: {best or '-'}")
        sys.stderr.flush()
        if finished:
            sys.stderr.write("\n")
            sys.stderr.flush()

    return on_progress


def cmd_discover(args: argparse.Namespace) -> int:
    spectrum = _load(args)
    print(_describe(spectrum))
    print()
    _preflight(spectrum, args.no_validate)

    pool = POOLS[args.pool] if args.pool in POOLS else tuple(args.pool.split(","))
    unknown = [code for code in pool if code not in REGISTRY]
    if unknown:
        raise SystemExit(f"error: unknown element codes in pool: {', '.join(unknown)}")

    result = discover(
        spectrum,
        pool=pool,
        mode=args.mode,
        exhaustive_limit=args.exhaustive_limit,
        max_candidates=args.max_candidates,
        workers=args.workers,
        feasibility_filter=not args.no_feasibility_filter,
        on_progress=_progress_reporter() if args.progress else None,
        generations=args.generations,
        population=args.population,
        max_elements=args.max_elements,
        seed=args.seed,
        weighting=args.weighting,
        time_limit=args.time_limit,
        seeds=args.seed_circuit or None,
    )
    print(result.summary(spectrum, limit=args.top))

    # DRT is printed beside the search, never fed into it. Raising the enumeration floor on a
    # DRT relaxation count would save under 1% of the screen and cost the completeness claim
    # (docs/DISCOVERY_V2_PLAN.md section 3.4), so the two analyses stay independent and the
    # reader compares them.
    probe = None if args.no_drt else _probe_structure(spectrum)
    if probe is not None:
        print("\nStructure probe (independent of the search above):")
        for line in probe.hints():
            print(f"  {line}")

    if args.json:
        payload = {
            "pool": list(result.pool),
            "mode": result.mode,
            "complete_up_to": result.complete_up_to,
            "n_evaluated": result.n_evaluated,
            "generations": result.generations,
            "elapsed_s": result.elapsed_s,
            "recommended": (
                result.recommended.to_dict() if result.recommended is not None else None
            ),
            "pareto": [c.to_dict() for c in result.pareto],
            "candidates": [c.to_dict() for c in result.candidates[: args.top]],
            "equivalence_classes": [
                [c.circuit.to_string() for c in group]
                for group in result.equivalence_classes()
                if len(group) > 1
            ],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote discovery report to {args.json}")

    best = result.recommended
    if best is not None and args.spice:
        netlist = to_netlist(
            best.circuit,
            best.result.values,
            f_min=float(spectrum.f[0]),
            f_max=float(spectrum.f[-1]),
            name=args.subckt,
            error_target=args.spice_error,
            header="Topology discovered automatically by AutoCircuit",
        )
        Path(args.spice).write_text(netlist, encoding="utf-8")
        print(f"Wrote SPICE subcircuit for the recommended candidate to {args.spice}")
    return 0 if best is not None else 1


def cmd_validate(args: argparse.Namespace) -> int:
    spectrum = _load(args)
    print(_describe(spectrum))
    print()
    result = lin_kk(spectrum, mu_criterion=args.mu, residual_limit=args.limit)
    print(result.summary(spectrum))
    if args.residuals:
        rows = np.column_stack([spectrum.f, result.residual_real, result.residual_imag])
        header = "frequency_hz,residual_real,residual_imag"
        np.savetxt(args.residuals, rows, delimiter=",", header=header, comments="")
        print(f"\nWrote residuals to {args.residuals}")
    return 0 if result.passed else 1


def _probe_structure(spectrum: Spectrum) -> DRTResult | None:
    """DRT alongside a discovery run, as advice. Never allowed to break the search."""
    try:
        return drt(spectrum)
    except (ValueError, np.linalg.LinAlgError):
        return None


def cmd_drt(args: argparse.Namespace) -> int:
    spectrum = _load(args)
    print(_describe(spectrum))
    print()
    result = drt(
        spectrum,
        points_per_decade=args.points_per_decade,
        series_inductance=args.series_l,
        series_capacitance=args.series_c,
        lam=args.regularisation,
    )
    print(result.summary())
    if args.json:
        Path(args.json).write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"\nWrote distribution to {args.json}")
    if args.distribution:
        rows = np.column_stack([result.tau, result.gamma])
        np.savetxt(
            args.distribution,
            rows,
            delimiter=",",
            header="tau_s,gamma_ohm",
            comments="",
        )
        print(f"Wrote gamma(tau) to {args.distribution}")
    # A spectrum the Debye model cannot represent is a failed analysis, not a zero-peak one.
    return 0 if result.well_described else 1


def cmd_simulate(args: argparse.Namespace) -> int:
    circuit = Circuit.parse(args.circuit)
    values = _parse_assignments(args.param, "--param")
    missing = [name for name in circuit.param_names if name not in values]
    if missing:
        raise SystemExit(
            "error: missing --param values for: "
            + ", ".join(missing)
            + f"\n  circuit {circuit.to_string()} needs: {', '.join(circuit.param_names)}"
        )
    f = log_frequencies(args.fmin, args.fmax, args.points_per_decade)
    spectrum = simulate(
        circuit, f, values, noise=args.noise, seed=args.seed, noise_model=args.noise_model
    )
    if args.output.lower().endswith(".z"):
        write_zview(spectrum, args.output)
    else:
        write_csv(spectrum, args.output)
    print(f"Wrote {spectrum.n} points ({circuit.to_string()}) to {args.output}")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    spectrum = _load(args)
    print(_describe(spectrum))
    if args.output.lower().endswith(".z"):
        write_zview(spectrum, args.output)
    else:
        write_csv(spectrum, args.output)
    print(f"\nWrote {spectrum.n} points to {args.output}")
    return 0


def cmd_elements(args: argparse.Namespace) -> int:
    print(f"{'code':<8}{'parameters':<40}{'SPICE':<12}name")
    for code in sorted(REGISTRY):
        element = REGISTRY[code]
        params = ", ".join(f"{p.name} [{p.unit}]" for p in element.params)
        form = {
            "primitive": "native",
            "rc": "RC ladder",
            "rl": "RL ladder",
        }[element.spice_form]
        print(f"{code:<8}{params:<40}{form:<12}{element.name}")
    print()
    print("Pools:")
    for name, pool in POOLS.items():
        print(f"  {name:<16}{', '.join(pool)}")
    print()
    print("Circuit syntax: '-' is series, 'p(a,b)' is parallel, e.g. R1-p(C1,R2-W1)")
    return 0


# -- Argument parsing ------------------------------------------------------------------------


def _add_data_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("data", help="impedance data file")
    parser.add_argument("--format", help="force a reader instead of sniffing the format")
    parser.add_argument("--fmin", type=float, help="discard points below this frequency (Hz)")
    parser.add_argument("--fmax", type=float, help="discard points above this frequency (Hz)")
    parser.add_argument(
        "--port-config",
        choices=["series_thru", "shunt_thru"],
        help="Touchstone 2-port fixture; shunt_thru is correct for low-ESR capacitors",
    )
    parser.add_argument(
        "--negate-imag",
        action="store_true",
        help="flip the sign of the imaginary column (for -Im(Z) 'positive up' files)",
    )


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", help="write a machine-readable report here")
    parser.add_argument("--spice", help="write a SPICE .subckt here")
    parser.add_argument("--subckt", default="AUTOCIRCUIT", help="SPICE subcircuit name")
    parser.add_argument(
        "--spice-error",
        type=float,
        default=0.01,
        help="accuracy target for ladder synthesis of fractional elements (default 0.01)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autocircuit",
        description=(
            "Equivalent circuit analysis of passive-component frequency characteristics. "
            "Parameters are found by global optimization, so no initial values are needed."
        ),
    )
    parser.add_argument("--version", action="version", version=f"autocircuit {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # fit
    p_fit = subparsers.add_parser(
        "fit", help="fit a given circuit to data (no initial values required)"
    )
    _add_data_arguments(p_fit)
    p_fit.add_argument(
        "-c", "--circuit", required=True, help="circuit string, e.g. 'C1-R1-L1-SKINF1'"
    )
    p_fit.add_argument(
        "-w", "--weighting", default="modulus",
        choices=["modulus", "unit", "proportional"],
        help="residual weighting (default modulus, i.e. relative error)",
    )
    p_fit.add_argument("--fix", action="append", metavar="NAME=VALUE", help="hold a parameter")
    p_fit.add_argument(
        "--bound", action="append", metavar="NAME=LO:HI", help="override a search interval"
    )
    p_fit.add_argument(
        "--initial", action="append", metavar="NAME=VALUE",
        help="optional starting guess; never required",
    )
    p_fit.add_argument("--restarts", type=int, default=5, help="independent global searches")
    p_fit.add_argument("--popsize", type=int, default=20, help="global search population")
    p_fit.add_argument("--maxiter", type=int, default=400, help="global search generations")
    p_fit.add_argument("--seed", type=int, default=0, help="random seed (results reproduce)")
    p_fit.add_argument("--time-limit", type=float, help="seconds per global search stage")
    p_fit.add_argument("--model-csv", help="write the fitted model spectrum here")
    p_fit.add_argument("--no-validate", action="store_true", help="skip the Lin-KK pre-check")
    _add_output_arguments(p_fit)
    p_fit.set_defaults(func=cmd_fit)

    # discover
    p_disc = subparsers.add_parser(
        "discover", help="search for the circuit topology as well as its parameters"
    )
    _add_data_arguments(p_disc)
    p_disc.add_argument(
        "--pool", default="default",
        help="element pool: 'default', 'component', 'electrochemical', or a comma list",
    )
    p_disc.add_argument(
        "--mode", choices=["auto", "exhaustive", "evolve"], default="auto",
        help=(
            "which search to use; auto enumerates exhaustively then falls back to the "
            "genetic search only if the residuals still look systematic"
        ),
    )
    p_disc.add_argument(
        "--exhaustive-limit", type=int, default=5,
        help="largest element count to enumerate",
    )
    p_disc.add_argument(
        "--max-candidates", type=int, default=20000,
        help="ceiling on topologies screened before the exhaustive limit is clamped down",
    )
    p_disc.add_argument(
        "--workers", type=int, default=1,
        help="processes for the screening pass; 1 keeps the run single-process (required "
        "under Pyodide)",
    )
    p_disc.add_argument(
        "--no-feasibility-filter", action="store_true",
        help="keep every enumerated topology, skipping the endpoint-behaviour screen",
    )
    p_disc.add_argument(
        "--progress", action="store_true",
        help="print a progress line to stderr during screening",
    )
    p_disc.add_argument(
        "--no-drt", action="store_true",
        help="skip the DRT structure probe printed beside the report (it never affects the"
        " search either way)",
    )
    p_disc.add_argument("--generations", type=int, default=30)
    p_disc.add_argument("--population", type=int, default=40)
    p_disc.add_argument("--max-elements", type=int, default=7)
    p_disc.add_argument("--top", type=int, default=10, help="how many candidates to report")
    p_disc.add_argument(
        "-w", "--weighting", default="modulus", choices=["modulus", "unit", "proportional"]
    )
    p_disc.add_argument(
        "--seed-circuit", action="append", metavar="CIRCUIT",
        help="inject a known circuit into the initial population; repeatable",
    )
    p_disc.add_argument("--seed", type=int, default=0)
    p_disc.add_argument("--time-limit", type=float, help="wall-clock budget in seconds")
    p_disc.add_argument("--no-validate", action="store_true")
    _add_output_arguments(p_disc)
    p_disc.set_defaults(func=cmd_discover)

    # validate
    p_val = subparsers.add_parser(
        "validate", help="Kramers-Kronig consistency check (run this before trusting a fit)"
    )
    _add_data_arguments(p_val)
    p_val.add_argument("--mu", type=float, default=0.85, help="model-order criterion")
    p_val.add_argument("--limit", type=float, default=0.01, help="residual pass threshold")
    p_val.add_argument("--residuals", help="write per-point residuals to this CSV")
    p_val.set_defaults(func=cmd_validate)

    # drt
    p_drt = subparsers.add_parser(
        "drt",
        help="distribution of relaxation times: how many relaxations does this data show?",
        description=(
            "Invert a spectrum into a distribution of relaxation times. Answers how many "
            "distinct relaxations the sample shows and whether any of them is broadened "
            "enough to want a CPE rather than a C. Advisory: it constrains nothing, and "
            "'discover' does not use it to narrow the search."
        ),
    )
    _add_data_arguments(p_drt)
    p_drt.add_argument(
        "--points-per-decade", type=int, default=10, help="density of the tau grid"
    )
    p_drt.add_argument(
        "--regularisation",
        type=float,
        help="fix the smoothing strength instead of choosing it by GCV",
    )
    p_drt.add_argument(
        "--series-l",
        dest="series_l",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include a series inductance (default: decided from the data)",
    )
    p_drt.add_argument(
        "--series-c",
        dest="series_c",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include a series capacitance, for blocking data (default: decided from the data)",
    )
    p_drt.add_argument("--json", help="write a machine-readable report here")
    p_drt.add_argument("--distribution", help="write gamma(tau) to this CSV")
    p_drt.set_defaults(func=cmd_drt)

    # simulate
    p_sim = subparsers.add_parser("simulate", help="generate a synthetic spectrum")
    p_sim.add_argument("-c", "--circuit", required=True)
    p_sim.add_argument(
        "-p", "--param", action="append", metavar="NAME=VALUE", required=True
    )
    p_sim.add_argument("-o", "--output", required=True, help="output .csv or .z file")
    p_sim.add_argument("--fmin", type=float, default=1.0)
    p_sim.add_argument("--fmax", type=float, default=1e6)
    p_sim.add_argument("--points-per-decade", type=int, default=10)
    p_sim.add_argument("--noise", type=float, default=0.0, help="relative noise level")
    p_sim.add_argument(
        "--noise-model", default="proportional", choices=["proportional", "absolute"]
    )
    p_sim.add_argument("--seed", type=int, default=0)
    p_sim.set_defaults(func=cmd_simulate)

    # convert
    p_conv = subparsers.add_parser("convert", help="convert between impedance data formats")
    _add_data_arguments(p_conv)
    p_conv.add_argument("-o", "--output", required=True, help="output .csv or .z file")
    p_conv.set_defaults(func=cmd_convert)

    # elements
    p_el = subparsers.add_parser("elements", help="list the available circuit elements")
    p_el.set_defaults(func=cmd_elements)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
