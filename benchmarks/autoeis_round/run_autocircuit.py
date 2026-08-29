"""Producer script: run AutoCircuit's ``discover()`` over one arena, in the PROJECT environment.

See ``benchmarks/autoeis_round/README.md`` for why there are two producer scripts and why they
never share a process, and ``benchmarks/autoeis_round/arena.py`` for what an arena directory
contains. This script imports ``autocircuit`` and must never import ``autoeis``.

The machine running this may be shut down without warning and without an operator present, so
the whole script is built around one rule: **a result is durable the instant it is written**.
Every completed run is appended to the output ``.jsonl`` as one line, flushed and ``fsync``-ed
before the next run starts, and on start-up the script re-reads its own output to skip whatever
is already done. Re-running the exact same command after a crash costs at most the run that was
in flight, never a restart from zero and never a duplicate.

``discover(spectrum)`` is called at its defaults -- no ``pool``, ``mode``, or ``criterion`` -- so
that this round measures the software's out-of-the-box behaviour rather than a tuned one. Only
``workers`` (a machine resource, not a search setting) and ``seed`` (the spectrum's own seed, for
reproducibility) are passed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from autocircuit.core.discover import discover
from autocircuit.core.spectrum import Spectrum

#: Budget used only under ``--smoke``, to keep the plumbing test seconds rather than minutes.
SMOKE_MAX_ELEMENTS = 3
SMOKE_TIME_LIMIT = 30.0

TOOL_NAME = "autocircuit"


def _git_sha(repo_root: Path) -> str | None:
    """This repository's current commit, or ``None`` if it cannot be determined.

    Tolerated rather than fatal: a benchmark run should not fail because ``git`` is unavailable
    or the tree is not a checkout.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def collect_versions() -> dict[str, Any]:
    """Everything needed to reproduce this side of the round, computed once at start-up."""
    repo_root = Path(__file__).resolve().parents[2]
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "git_sha": _git_sha(repo_root),
    }


def load_arena(arena_dir: Path) -> dict[str, Any]:
    with (arena_dir / "arena.json").open("r", encoding="utf-8") as handle:
        arena: dict[str, Any] = json.load(handle)
    return arena


def load_done(out_path: Path, expect_smoke: bool) -> set[tuple[str, int]]:
    """(truth_id, seed) pairs already recorded in ``out_path``.

    Tolerates a trailing partial/corrupt line (e.g. a write cut off by a power loss) by skipping
    it with a warning rather than crashing. Also enforces that a smoke output file is never mixed
    with a non-smoke one, in either direction.
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


def load_spectrum(arena_dir: Path, truth_id: str, seed: int) -> Spectrum:
    path = arena_dir / "spectra" / f"{truth_id}_s{seed}.csv"
    data = np.loadtxt(path, delimiter=",", skiprows=1)
    return Spectrum.from_parts(f=data[:, 0], real=data[:, 1], imag=data[:, 2])


def run_one(
    truth_id: str,
    seed: int,
    spectrum: Spectrum,
    *,
    workers: int,
    smoke: bool,
    versions: dict[str, Any],
) -> dict[str, Any]:
    """Run one (truth, seed) through ``discover()`` and return one JSON-serialisable record.

    A raised exception here is recorded in the ``error`` field rather than propagated: a run
    that fails is data about the search, not a reason to stop the loop.
    """
    record: dict[str, Any] = {
        "truth_id": truth_id,
        "seed": seed,
        "tool": TOOL_NAME,
        "smoke": smoke,
        "n_points_in": spectrum.n,
        "n_points_used": spectrum.n,
        "versions": versions,
        "error": None,
        "report": None,
        "wall_seconds": None,
    }

    kwargs: dict[str, Any] = {"workers": workers, "seed": seed}
    if smoke:
        kwargs["max_elements"] = SMOKE_MAX_ELEMENTS
        kwargs["time_limit"] = SMOKE_TIME_LIMIT

    start = time.monotonic()
    try:
        result = discover(spectrum, **kwargs)
        record["report"] = result.to_dict()
    except Exception as exc:  # noqa: BLE001 -- a failed run is a recorded outcome, not a crash
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["wall_seconds"] = time.monotonic() - start
    return record


def append_record(out_path: Path, record: dict[str, Any]) -> None:
    """Append one record and make it durable before returning.

    This is the whole point of the resumability design: once this function returns, the record
    survives a power loss. Losing power mid-run costs at most the run in flight, never one that
    already completed.
    """
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True, help="arena directory")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output .jsonl (default: <arena>/results_autocircuit.jsonl)",
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
        "--workers",
        type=int,
        default=1,
        help="worker processes passed to discover() (a machine resource, not a search setting)",
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
    out_path: Path = args.out if args.out is not None else arena_dir / "results_autocircuit.jsonl"
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

    done = load_done(out_path, expect_smoke=args.smoke)
    versions = collect_versions()

    jobs = [(t["truth_id"], s) for t in truths for s in seeds]
    total = len(jobs)
    remaining = [job for job in jobs if job not in done]
    print(
        f"{TOOL_NAME}: {len(done)} of {total} runs already done, {len(remaining)} remaining "
        f"({'SMOKE' if args.smoke else 'measurement'} mode)",
        flush=True,
    )

    completed = len(done)
    start_all = time.monotonic()
    for truth_id, seed in remaining:
        spectrum = load_spectrum(arena_dir, truth_id, seed)
        record = run_one(
            truth_id, seed, spectrum, workers=args.workers, smoke=args.smoke, versions=versions
        )
        append_record(out_path, record)
        completed += 1
        status = "ok" if record["error"] is None else "ERROR"
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
