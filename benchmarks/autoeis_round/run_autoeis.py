"""Producer script: run AutoEIS's documented pipeline over one arena.

Runs under the dedicated AutoEIS virtual environment
(``C:\\Users\\toshi\\python\\autoeis-env\\Scripts\\python.exe``), never the project's own
interpreter. See ``benchmarks/autoeis_round/README.md`` for why the two environments never meet:
this script imports ``autoeis`` and must never import ``autocircuit``.

The pipeline is the four documented step-by-step calls, each at its own default arguments,
because the round compares defaults, not a tuned configuration (``perform_full_analysis()``
itself raises ``NotImplementedError`` -- see ``docs/AUTOEIS_COMPARISON.md`` section 0.1):

    1. ``utils.preprocess_impedance_data`` -- deletes points (inductive tail, Lin-KK outliers).
    2. ``generate_equivalent_circuits`` -- the genetic search over circuit topologies.
    3. ``filter_implausible_circuits`` -- heuristic post-filters.
    4. ``perform_bayesian_inference`` -- NUTS on every surviving circuit.
    5. ``compute_fitness_metrics`` -- WAIC, R^2, MAPE, and AutoEIS's own ranking rule.

The default (``parallel=True``) path of step 2 is measured to ignore its ``seed`` argument
(``docs/AUTOEIS_COMPARISON.md`` section 0.2, check 4), so passing ``seed=`` there is recorded
intent, not a reproducibility guarantee.

The Julia runtime is initialized once and reused: the first touch (installing Julia and
precompiling EquivalentCircuits.jl) costs about 147 s, and that cost must be paid once per
process, not once per spectrum -- which is why this script runs every spectrum of an arena in a
single process rather than being re-invoked per run.

Durability: the machine running this may be shut down at any moment with no operator present.
Every completed run is appended to the output ``.jsonl`` as one line, flushed and ``fsync``-ed
before the next run starts, and on start-up the script re-reads its own output to skip whatever
is already done.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

TOOL_NAME = "autoeis"

#: Budgets used only under ``--smoke``, to keep the plumbing test seconds rather than the ~35
#: minutes per spectrum the default generation budget costs (section 0.2 of
#: ``docs/AUTOEIS_COMPARISON.md``).
SMOKE_ITERS = 4
SMOKE_NUM_WARMUP = 50
SMOKE_NUM_SAMPLES = 50

#: Packages whose version is recorded as plain ``importlib.metadata.version()`` lookups. Julia
#: itself and EquivalentCircuits.jl need a running Julia runtime instead; see
#: :func:`collect_versions`.
VERSIONED_PACKAGES = (
    "autoeis",
    "jax",
    "jaxlib",
    "numpyro",
    "juliacall",
    "juliapkg",
    "pyimpspec",
    "numpy",
    "scipy",
    "arviz",
    "pandas",
)


def _json_safe(value: Any) -> Any:
    """Coerce one value into something ``json.dumps`` can always serialise.

    Mirrors ``autocircuit.core.spectrum._json_safe``: numpy scalars/arrays become plain Python
    types, and a non-finite float becomes its ``repr`` rather than the non-standard ``NaN``/
    ``Infinity`` tokens Python's ``json`` module would otherwise emit. A record that cannot be
    serialised is a lost run, so this is applied to every record before it is written.
    """
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return repr(value)


def _pkg_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def collect_versions(ae: Any) -> dict[str, Any]:
    """Everything needed to reproduce this side of the round, computed once at start-up.

    Reading the EquivalentCircuits.jl version requires a running Julia with the package already
    loaded, so this is what pays the one-time ~147 s Julia install/precompile cost (see the
    module docstring) -- the same cost the first real run would otherwise pay.
    """
    versions: dict[str, Any] = {"python": platform.python_version()}
    for pkg in VERSIONED_PACKAGES:
        versions[pkg] = _pkg_version(pkg)

    # ``ae.jl`` is a lazy proxy: touching any attribute installs Julia (if needed) and imports
    # EquivalentCircuits.jl into Main, exactly as the first real generation call would.
    versions["julia"] = str(ae.jl.seval("string(VERSION)"))
    versions["equivalent_circuits_jl_version"] = str(
        ae.jl.seval("string(pkgversion(EquivalentCircuits))")
    )
    # The pinned git revision (a branch, not a tag -- see version.py and
    # docs/AUTOEIS_COMPARISON.md section 0.1), not a resolved commit SHA.
    versions["equivalent_circuits_jl_git_revision"] = str(ae.__equivalent_circuits_jl_version__)
    return versions


def load_arena(arena_dir: Path) -> dict[str, Any]:
    with (arena_dir / "arena.json").open("r", encoding="utf-8") as handle:
        arena: dict[str, Any] = json.load(handle)
    return arena


def load_done(out_path: Path, expect_smoke: bool) -> set[tuple[str, int]]:
    """(truth_id, seed) pairs already recorded in ``out_path``.

    Tolerates a trailing partial/corrupt line (a write cut off by a power loss) by skipping it
    with a warning rather than crashing, and refuses to let smoke and non-smoke records share a
    file in either direction.
    """
    done: set[tuple[str, int]] = set()
    if not out_path.exists():
        return done

    lines = out_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            is_last = i == len(lines) - 1
            where = "trailing" if is_last else f"line {i + 1}"
            print(
                f"warning: {where} record in {out_path} is not valid JSON, skipping it "
                "(this is expected if the machine stopped mid-write)",
                flush=True,
            )
            continue

        record_smoke = bool(record.get("smoke", False))
        if record_smoke != expect_smoke:
            print(
                f"error: {out_path} already contains "
                f"{'smoke' if record_smoke else 'non-smoke'} records, "
                f"but this run is {'smoke' if expect_smoke else 'non-smoke'}. "
                "Smoke output must never mix with real results.",
                file=sys.stderr,
            )
            sys.exit(2)

        done.add((str(record["truth_id"]), int(record["seed"])))
    return done


def load_spectrum_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    freq = np.asarray(data[:, 0], dtype=np.float64)
    z = np.asarray(data[:, 1] + 1j * data[:, 2], dtype=np.complex128)
    return freq, z


def _param_stats(result: Any) -> dict[str, Any]:
    """Posterior mean and coefficient of variation of every circuit parameter.

    Guarded on its own: a circuit whose inference did not converge has an ``InferenceResult``
    whose ``mcmc`` never ran, and reading its samples raises. That failure belongs to this one
    circuit, not to the whole run.
    """
    try:
        samples = result.samples
        stats: dict[str, Any] = {}
        for var in result.variables:
            values = np.asarray(samples[var], dtype=np.float64)
            mean = float(np.mean(values))
            std = float(np.std(values))
            stats[var] = {"mean": mean, "cv": (std / mean) if mean != 0.0 else None}
        return stats
    except Exception as exc:  # noqa: BLE001 -- a per-circuit failure, recorded not raised
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_one(
    ae: Any,
    truth_id: str,
    seed: int,
    freq_in: np.ndarray,
    z_in: np.ndarray,
    *,
    smoke: bool,
    versions: dict[str, Any],
) -> dict[str, Any]:
    """Run one (truth, seed) through the AutoEIS pipeline and return one JSON-safe record.

    A raised exception anywhere in the pipeline is recorded in ``error`` rather than propagated:
    a run that fails is data about the search, not a reason to stop the loop. Stage 4 (Bayesian
    inference) gets its own inner try/except, per the round's design, so that a failure there
    does not discard what stages 1-3 already found.
    """
    record: dict[str, Any] = {
        "truth_id": truth_id,
        "seed": seed,
        "tool": TOOL_NAME,
        "smoke": smoke,
        "n_points_in": int(freq_in.size),
        "n_points_used": None,
        "versions": versions,
        "error": None,
        "wall_seconds": None,
        "linkk_rmse": None,
        "stage_wall_seconds": {},
        "n_generated": None,
        "generated_circuits": None,
        "n_filtered": None,
        "n_dropped_by_filter": None,
        "filtered_circuits": None,
        "stopped_early": None,
        "bayesian_inference_error": None,
        "circuits_converged": None,
        "circuits_num_divergences": None,
        "waic_columns": None,
        "circuits": None,
        "ranked_circuitstrings": None,
    }

    start_total = time.monotonic()
    try:
        # --- Stage 1: preprocessing (deletes points; that is the whole reason
        # n_points_used exists). ---
        t0 = time.monotonic()
        freq, z, aux = ae.utils.preprocess_impedance_data(freq_in, z_in, return_aux=True)
        record["stage_wall_seconds"]["preprocess"] = time.monotonic() - t0
        record["n_points_used"] = int(len(freq))
        record["linkk_rmse"] = float(aux.rmse)

        # --- Stage 2: generate candidate circuits. ---
        gen_kwargs: dict[str, Any] = {"seed": seed}
        if smoke:
            gen_kwargs["iters"] = SMOKE_ITERS
        t0 = time.monotonic()
        circuits = ae.generate_equivalent_circuits(freq, z, **gen_kwargs)
        record["stage_wall_seconds"]["generate"] = time.monotonic() - t0
        record["n_generated"] = int(len(circuits))
        record["generated_circuits"] = [
            {"circuitstring": row["circuitstring"], "parameters": dict(row["Parameters"])}
            for _, row in circuits.iterrows()
        ]

        if len(circuits) == 0:
            record["stopped_early"] = "generate_equivalent_circuits returned no circuits"
            record["wall_seconds"] = time.monotonic() - start_total
            return record

        # --- Stage 3: heuristic post-filters. ---
        t0 = time.monotonic()
        filtered = ae.filter_implausible_circuits(circuits).reset_index(drop=True)
        record["stage_wall_seconds"]["filter"] = time.monotonic() - t0
        record["n_filtered"] = int(len(filtered))
        record["n_dropped_by_filter"] = int(len(circuits) - len(filtered))
        record["filtered_circuits"] = [
            {"circuitstring": row["circuitstring"], "parameters": dict(row["Parameters"])}
            for _, row in filtered.iterrows()
        ]

        if len(filtered) == 0:
            record["stopped_early"] = "filter_implausible_circuits returned no circuits"
            record["wall_seconds"] = time.monotonic() - start_total
            return record

        # --- Stage 4: Bayesian inference. Its own try/except: a failure here must not lose
        # what stages 1-3 already recorded. ---
        infer_kwargs: dict[str, Any] = {"seed": seed, "progress_bar": False}
        if smoke:
            infer_kwargs["num_warmup"] = SMOKE_NUM_WARMUP
            infer_kwargs["num_samples"] = SMOKE_NUM_SAMPLES
        t0 = time.monotonic()
        try:
            results = ae.perform_bayesian_inference(filtered, freq, z, **infer_kwargs)
        except Exception as exc:  # noqa: BLE001 -- recorded, not fatal to this run
            record["stage_wall_seconds"]["bayesian_inference"] = time.monotonic() - t0
            record["bayesian_inference_error"] = f"{type(exc).__name__}: {exc}"
            record["wall_seconds"] = time.monotonic() - start_total
            return record
        record["stage_wall_seconds"]["bayesian_inference"] = time.monotonic() - t0

        record["circuits_converged"] = [bool(r.converged) for r in results]
        record["circuits_num_divergences"] = [int(r.num_divergences) for r in results]
        param_stats = [_param_stats(r) for r in results]

        # --- Stage 5: fitness metrics, including AutoEIS's own ranking rule. ---
        with_results = filtered.copy()
        with_results["InferenceResult"] = results
        t0 = time.monotonic()
        scored = ae.compute_fitness_metrics(with_results, freq, z)
        record["stage_wall_seconds"]["fitness_metrics"] = time.monotonic() - t0

        # ``compute_fitness_metrics`` names its WAIC columns after the inference ``method``:
        # "mag"/"phase" for the default "bode" method, "real"/"imag" otherwise.
        if "WAIC (mag)" in scored.columns:
            waic_cols = ("WAIC (mag)", "WAIC (phase)")
        else:
            waic_cols = ("WAIC (real)", "WAIC (imag)")
        record["waic_columns"] = list(waic_cols)
        waic_sum = scored[waic_cols[0]] + scored[waic_cols[1]]

        per_circuit = []
        for i, (_, row) in enumerate(scored.iterrows()):
            per_circuit.append(
                {
                    "circuitstring": row["circuitstring"],
                    "n_params": int(row["n_params"]),
                    "converged": bool(row["converged"]),
                    "num_divergences": int(row["divergences"]),
                    "waic": {
                        waic_cols[0]: float(row[waic_cols[0]]),
                        waic_cols[1]: float(row[waic_cols[1]]),
                        "sum": float(waic_sum.iloc[i]),
                    },
                    "r2_ravg": float(row["R^2 (ravg)"]),
                    "r2_iavg": float(row["R^2 (iavg)"]),
                    "mape_ravg": float(row["MAPE (ravg)"]),
                    "mape_iavg": float(row["MAPE (iavg)"]),
                    "parameters": param_stats[i],
                }
            )
        record["circuits"] = per_circuit

        # AutoEIS's own ranking rule (visualization.py): WAIC (sum) ascending.
        ranked = sorted(per_circuit, key=lambda c: c["waic"]["sum"])
        record["ranked_circuitstrings"] = [c["circuitstring"] for c in ranked]

    except Exception as exc:  # noqa: BLE001 -- a failed run is recorded, not fatal to the loop
        record["error"] = f"{type(exc).__name__}: {exc}"

    record["wall_seconds"] = time.monotonic() - start_total
    return record


def append_record(out_path: Path, record: dict[str, Any]) -> None:
    """Append one record and make it durable before returning.

    Once this returns, the record survives a power loss: losing power mid-run costs at most the
    run in flight, never one that already completed.
    """
    safe_record = _json_safe(record)
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True, help="arena directory")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output .jsonl (default: <arena>/results_autoeis.jsonl)",
    )
    parser.add_argument(
        "--max-seeds",
        type=int,
        default=None,
        help="use only the first N seeds from arena.json's seed list (default: all)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="TRUTH_ID",
        help="restrict to this truth_id (repeatable; default: all truths)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="plumbing test only, NOT a measurement: shrinks the budget drastically and stamps "
        "'smoke': true into every record",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    arena_dir: Path = args.arena
    out_path: Path = args.out if args.out is not None else arena_dir / "results_autoeis.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    arena = load_arena(arena_dir)
    truths: list[dict[str, Any]] = arena["truths"]
    seeds: list[int] = arena["seeds"]
    if args.max_seeds is not None:
        seeds = seeds[: args.max_seeds]
    if args.only is not None:
        wanted = set(args.only)
        truths = [t for t in truths if t["truth_id"] in wanted]
        missing = wanted - {t["truth_id"] for t in truths}
        if missing:
            names = ", ".join(sorted(missing))
            print(f"error: unknown --only truth_id(s): {names}", file=sys.stderr)
            return 2

    # Check resumability and the smoke/non-smoke split before paying any AutoEIS import cost.
    done = load_done(out_path, expect_smoke=args.smoke)

    jobs = [(t["truth_id"], s) for t in truths for s in seeds]
    total = len(jobs)
    remaining = [job for job in jobs if job not in done]
    print(
        f"{TOOL_NAME}: {len(done)} of {total} runs already done, {len(remaining)} remaining "
        f"({'SMOKE' if args.smoke else 'measurement'} mode)",
        flush=True,
    )
    if not remaining:
        print(f"{TOOL_NAME}: nothing to do", flush=True)
        return 0

    print(
        f"{TOOL_NAME}: importing autoeis (first import ~42 s, first Julia touch ~147 s, "
        "paid once for this whole process)...",
        flush=True,
    )
    import autoeis as ae

    versions = collect_versions(ae)
    print(f"{TOOL_NAME}: Julia runtime ready ({versions['julia']}), starting runs", flush=True)

    completed = len(done)
    start_all = time.monotonic()
    for truth_id, seed in remaining:
        freq_in, z_in = load_spectrum_csv(arena_dir / "spectra" / f"{truth_id}_s{seed}.csv")
        record = run_one(ae, truth_id, seed, freq_in, z_in, smoke=args.smoke, versions=versions)
        append_record(out_path, record)
        completed += 1
        status = "ok" if record["error"] is None else "ERROR"
        if record["stopped_early"]:
            status = "empty"
        elapsed_all = time.monotonic() - start_all
        print(
            f"[{completed}/{total}] {truth_id} seed={seed} {status} "
            f"run={record['wall_seconds']:.2f}s total_elapsed={elapsed_all:.1f}s",
            flush=True,
        )

    print(f"{TOOL_NAME}: done, {completed} of {total} runs recorded in {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
