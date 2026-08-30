"""Ask the genetic fallback the question ``mode="auto"`` never asked it.

``docs/AUTOEIS_COMPARISON.md`` section 2.2 records the defect this probe exists for:
**``generations`` is 0 on all forty runs of Arena C -- the genetic fallback never ran once.**
``mode="auto"`` hands off only when the best exhaustive fit leaves a systematic residual (a runs
test at ``z < -3.0``), and the recorded values on the six-element truths are -0.45 and +0.67. So
the round's 0/2 at six elements is a statement about the *trigger*, not about the search behind
it, and that section leaves the search's own answer unmeasured.

This script measures it, on the same spectra, with the same referee (``score.py``).

==============================================================================================
Pre-registered. Written before the first run; do not edit after it.
==============================================================================================

``TRUTH_IDS`` / ``SEEDS``
    The two six-element truths of Arena C and the first three noise realisations. Six elements is
    the only size where the question has content: at five and below the exhaustive stage is
    complete, so ``mode="auto"`` already enumerates the truth and the fallback would change
    nothing.

``ARMS``
    Three, one of which is already on disk.

    * ``auto`` -- the control, **not re-run**: ``results_autocircuit.jsonl`` already holds it.
      Its zero at six elements is *structural* rather than stochastic: ``complete_up_to`` is 5 on
      those runs, so a six-element truth cannot appear in the candidate list at all. That is why
      this probe needs no paired significance test -- any recovery at all is a strict improvement
      on an arm that could not have found it.
    * ``evolve-default`` -- ``discover(mode="evolve")`` and nothing else, which is exactly what
      ``autocircuit discover --mode evolve --time-limit 600`` runs. ``min_elements`` stays at its
      default of 2, so the population spans 2..7 elements. This is the arm that answers the
      question as a user would ask it.
    * ``evolve-min6`` -- the same call with ``min_elements=6`` and the recorded ``auto`` run's
      five best candidates passed as ``seeds``. **This reproduces the fallback call in
      ``discover.py`` argument for argument** (``min_elements=max(complete_up_to+1, ...)``,
      ``seeds=[c.circuit.to_string() for c in candidates[:5]]``), so it measures what the round
      would have produced had the trigger fired. Its seeds are read from the control's own record
      rather than re-derived, so the two cannot drift apart.

``TIME_LIMIT``
    600 s per run. The control spent 228-457 s (mean 293 s) on these ten spectra, so the evolve
    arms get roughly twice its wall clock -- and still about a third of its **core** seconds,
    because ``_exhaustive`` takes ``workers`` and ``_evolve`` does not: the genetic search is
    single-threaded whatever the machine has. Both budgets are recorded per run and neither is to
    be reported without the other.

``interleaving``
    Seed-major, arm-minor: every (truth, arm) pair sees the same stretch of machine. This machine
    has been measured drifting by a factor of two within an hour
    (``docs/EVOLVE_SEARCH_PLAN.md`` section 4), and a wall-clock budget turns that drift directly
    into a difference in topologies evaluated.

**What six runs per arm can and cannot say.** They can say whether the fallback ever reaches a
six-element truth that these spectra hide from the exhaustive stage. They cannot measure a rate,
and a zero here is a statement about this budget and these two truths, never about the search.

Durability follows ``run_autocircuit.py``: one line per completed run, flushed and fsync-ed, and
the script re-reads its own output on start-up so a re-run resumes rather than duplicates.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from autocircuit.core.discover import discover
from autocircuit.core.spectrum import Spectrum

TRUTH_IDS: tuple[str, ...] = ("c6_0", "c6_1")
SEEDS: tuple[int, ...] = (1, 2, 3)
ARMS: tuple[str, ...] = ("evolve-default", "evolve-min6")
TIME_LIMIT: float = 600.0

#: How many of the control's best candidates ``discover.py`` hands its fallback as warm seeds.
FALLBACK_SEED_COUNT: int = 5

SMOKE_TIME_LIMIT: float = 20.0


def read_spectrum(path: Path) -> Spectrum:
    table = np.loadtxt(path, delimiter=",", skiprows=1)
    return Spectrum(f=table[:, 0], z=table[:, 1] + 1j * table[:, 2])


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
    return out


def control_seeds(record: dict[str, Any]) -> list[str]:
    """The circuits ``discover.py`` would have handed the fallback, from the control's report.

    ``discover.py`` passes ``[c.circuit.to_string() for c in candidates[:5]]`` where ``candidates``
    is the exhaustive stage's list, already sorted by the criterion. The report's ``candidates``
    list is that same list in that same order, so the first five of it are the same five circuits.
    """
    report = record.get("report") or {}
    entries = list(report.get("candidates") or [])
    return [entry["circuit"] for entry in entries[:FALLBACK_SEED_COUNT]]


def run_one(
    arm: str,
    truth_id: str,
    seed: int,
    spectrum: Spectrum,
    warm_seeds: list[str],
    *,
    time_limit: float,
    versions: dict[str, Any],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"mode": "evolve", "seed": seed, "time_limit": time_limit}
    if arm == "evolve-min6":
        kwargs["min_elements"] = 6
        kwargs["seeds"] = warm_seeds

    record: dict[str, Any] = {
        "arm": arm,
        "truth_id": truth_id,
        "seed": seed,
        "tool": "autocircuit",
        "smoke": time_limit != TIME_LIMIT,
        "n_points_in": spectrum.n,
        "n_points_used": spectrum.n,
        "time_limit": time_limit,
        "warm_seeds": kwargs.get("seeds"),
        "versions": versions,
        "error": None,
        "report": None,
        "wall_seconds": None,
        "cpu_seconds": None,
    }
    start = time.monotonic()
    cpu_start = time.process_time()
    try:
        record["report"] = discover(spectrum, **kwargs).to_dict()
    except Exception as exc:  # noqa: BLE001 -- a failed run is a recorded outcome, not a crash
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["wall_seconds"] = time.monotonic() - start
    record["cpu_seconds"] = time.process_time() - cpu_start
    return record


def append_record(path: Path, record: dict[str, Any]) -> None:
    """Append one record and make it durable before returning."""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--smoke", action="store_true", help="20 s budget, plumbing only")
    parser.add_argument("--seeds", type=str, default=None, help="override, e.g. 1,2")
    args = parser.parse_args()

    out_path = args.out or (args.arena / "results_evolve_arms.jsonl")
    time_limit = SMOKE_TIME_LIMIT if args.smoke else TIME_LIMIT
    seeds = tuple(int(s) for s in args.seeds.split(",")) if args.seeds else SEEDS

    control_rows = load_jsonl(args.arena / "results_autocircuit.jsonl")
    control = {(r["truth_id"], r["seed"]): r for r in control_rows}
    done = {
        (r["arm"], r["truth_id"], r["seed"]) for r in load_jsonl(out_path) if not r.get("smoke")
    }
    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }

    plan = [(arm, tid, seed) for seed in seeds for tid in TRUTH_IDS for arm in ARMS]
    todo = [key for key in plan if args.smoke or key not in done]
    print(
        f"{len(plan)} runs planned, {len(plan) - len(todo)} already on disk, {len(todo)} to go",
        flush=True,
    )

    for index, (arm, truth_id, seed) in enumerate(todo, start=1):
        spectrum = read_spectrum(args.arena / "spectra" / f"{truth_id}_s{seed}.csv")
        warm = control_seeds(control.get((truth_id, seed), {}))
        if arm == "evolve-min6" and not warm:
            print(f"  skip {arm} {truth_id} s{seed}: no control record to take seeds from")
            continue
        record = run_one(
            arm, truth_id, seed, spectrum, warm, time_limit=time_limit, versions=versions
        )
        append_record(out_path, record)
        report = record["report"] or {}
        recommended = (report.get("recommended") or {}).get("circuit")
        print(
            f"[{index}/{len(todo)}] {arm:<15} {truth_id} s{seed}"
            f"  {record['wall_seconds']:.0f}s wall / {record['cpu_seconds']:.0f}s cpu"
            f"  gen={report.get('generations')}  n={report.get('n_evaluated')}"
            f"  rec={recommended}  {record['error'] or ''}",
            flush=True,
        )


if __name__ == "__main__":
    main()
