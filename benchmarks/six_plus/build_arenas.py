"""Freeze one landscape and one target set per pre-registered truth (experiment X4).

``benchmarks/screening_round`` compares topology searches against a frozen table of
pre-screened topologies, which is what makes the comparison immune to machine load. Every table
it has ever held freezes the **same** truth, and ``docs/SEARCH_ALGORITHM_SCREENING.md`` section
3.5.2 records the reading that cost: an operator weighting that wins on three parallel blocks
loses by the same margin on a series-shaped truth. This driver builds the nine tables that let a
result be stated across shapes instead of on one.

It is resumable and idempotent: a landscape or target file that already exists is skipped, so a
run interrupted after four hours resumes where it stopped. Nothing here is quick --
``--n-max 7`` on the R,C,L pool is 11,033 screening fits, about 15 minutes on 8 workers, and the
target pass refits every candidate inside the truth's cost band.

Element caps, and why they differ by truth size:

* the five-element truths get ``--n-max 6``. They are the negative control of
  ``docs/TOPOLOGY_6PLUS_PLAN.md`` section 4.7, and what has to be visible there is whether a
  method wrongly prefers a **six**-element circuit; a seventh element answers no question that
  the sixth has not already answered, and costs 5x the build.
* the six- and seven-element truths get ``--n-max 7``, so a search can overshoot the truth by one
  element and be seen doing it.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/build_arenas.py --workers 8
    python benchmarks/six_plus/build_arenas.py --workers 8 --only par6,ser6,mix6
    python benchmarks/six_plus/build_arenas.py --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCREENING = _HERE.parent / "screening_round"
sys.path.insert(0, str(_HERE))

from truths import TRUTHS  # noqa: E402

#: Element cap per truth size. See the module docstring for why five gets six and not seven.
CAP_FOR_SIZE: dict[int, int] = {5: 6, 6: 7, 7: 7}

#: Raised well above ``targets.py``'s own default because that default silently truncates: its
#: own comment records a five-element series truth whose cost band held 761 rows against a cap of
#: 400, so 361 possible equivalents went uncounted. A target set that is missing members
#: understates every arm equally, but it also makes "the truth's class" mean something different
#: per arena, which is exactly what this round is trying to compare across.
MAX_CHECKS = 1200


@dataclass(frozen=True)
class Job:
    truth_id: str
    n_max: int
    pool: str

    @property
    def landscape(self) -> Path:
        return _SCREENING / f"land_{self.truth_id}_n{self.n_max}.json"

    @property
    def targets(self) -> Path:
        return _SCREENING / f"targets_{self.truth_id}_n{self.n_max}.json"


def jobs(only: set[str] | None) -> list[Job]:
    out: list[Job] = []
    for truth in TRUTHS:
        if only is not None and truth.id not in only:
            continue
        out.append(
            Job(truth.id, CAP_FOR_SIZE[truth.n_elements], ",".join(truth.pool))
        )
    return out


def run(command: list[str], *, cwd: Path) -> None:
    print("  $ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"command failed with {completed.returncode}: {' '.join(command)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--only", default=None, help="comma-separated truth ids")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter to run the two screening_round scripts with",
    )
    args = parser.parse_args()

    only = None if args.only is None else {s.strip() for s in args.only.split(",")}
    planned = jobs(only)
    if not planned:
        raise SystemExit("no truth selected")

    print(f"{len(planned)} arenas to consider, in {_SCREENING}")
    for job in planned:
        have_land = job.landscape.exists()
        have_targets = job.targets.exists()
        print(
            f"  {job.truth_id:6s} pool={job.pool:8s} n<={job.n_max}  "
            f"landscape={'have' if have_land else 'BUILD'}  "
            f"targets={'have' if have_targets else 'BUILD'}"
        )
    if args.dry_run:
        return

    started = time.perf_counter()
    for job in planned:
        print(f"\n== {job.truth_id} ==", flush=True)
        if job.landscape.exists():
            print("  landscape exists, skipping", flush=True)
        else:
            run(
                [
                    args.python,
                    "landscape.py",
                    "--pool",
                    job.pool,
                    "--n-max",
                    str(job.n_max),
                    "--truth",
                    job.truth_id,
                    "--workers",
                    str(args.workers),
                    "--out",
                    job.landscape.name,
                ],
                cwd=_SCREENING,
            )
        if job.targets.exists():
            print("  targets exist, skipping", flush=True)
        else:
            run(
                [
                    args.python,
                    "targets.py",
                    job.landscape.name,
                    "--max-checks",
                    str(MAX_CHECKS),
                    "--out",
                    job.targets.name,
                ],
                cwd=_SCREENING,
            )
    print(f"\nall done in {(time.perf_counter() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
