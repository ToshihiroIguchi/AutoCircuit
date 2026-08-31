"""Experiment X4: does the whole pipeline recover the truth, across shapes and sizes?

This is the end-to-end gate the two new levers have to pass before either default moves:

* ``growth_width`` -- above the exhaustive limit, grow instead of enumerating
  (``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5.8);
* ``screen_restarts`` -- more than one draw per topology in the tier-1 screen, because that
  screen's verdict is measurably a lottery for a minority of topologies (section 5.7.2).

Unlike ``benchmarks/screening_round``, which compares *searches* against a frozen table in units
of fits, this runs the real pipeline in wall clock and scores what the **report** says. Those are
different questions and this repository has confused them before: a search that reaches the
truth's class and a report that recommends it are two stages, and
``docs/AUTOEIS_COMPARISON.md`` section 2.2 records a run where the first happened and the second
did not.

Three readings per run, never pooled (section 4.7):

* ``reported`` -- a truth-equivalent is anywhere in the candidate list;
* ``on_front`` -- one is on the Pareto front;
* ``recommended`` -- one *is* the recommendation.

Truth-equivalence is decided by canonical form or, failing that, by the fitted response agreeing
to ``EQUIVALENCE_RTOL`` -- the same referee ``benchmarks/autoeis_round/score.py`` applies, because
at these sizes an exact reparameterisation of the truth is the expected outcome of a correct
search rather than a bug in it.

**The five-element truths are the negative control and are scored separately.** A method that
always grows to six elements would score perfectly on recovery and be worthless; what is asked of
``par5``, ``ser5`` and ``mix5`` is that the report does *not* prefer something larger. That
number is reported beside the recovery rate and never averaged into it.

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/six_plus/recovery.py --out benchmarks/six_plus/x4_recovery.json --workers 8
    python benchmarks/six_plus/recovery.py --out ... --arms base,grow --seeds 1,2,3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from truths import TRUTHS, Truth, spectrum_for  # noqa: E402

from autocircuit.core.circuit import Circuit, CircuitError, count_elements  # noqa: E402
from autocircuit.core.discover import (  # noqa: E402
    EQUIVALENCE_RTOL,
    Candidate,
    discover,
)
from autocircuit.core.fit import fit  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402


@dataclass(frozen=True)
class Arm:
    """One pipeline configuration. ``base`` is the shipped one and is never omitted."""

    name: str
    growth_width: int
    screen_restarts: int


ARMS: tuple[Arm, ...] = (
    Arm("base", growth_width=0, screen_restarts=1),
    Arm("grow", growth_width=4, screen_restarts=1),
    Arm("seeds2", growth_width=0, screen_restarts=2),
    Arm("grow+seeds2", growth_width=4, screen_restarts=2),
)

#: Noise realisations. Fixed here rather than passed, so that a run cannot be extended until it
#: says what someone hoped -- the departure rule of ``docs/AUTOEIS_COMPARISON.md`` section 2.1.
SEEDS: tuple[int, ...] = (1, 2, 3)

NOISE = 0.01


class Referee:
    """Is this circuit the truth, or an exact reparameterisation of it?

    Lifted from ``benchmarks/autoeis_round/score.py`` rather than re-invented: canonical form
    first, and failing that an independent refit whose response must agree with the truth's own
    fitted response everywhere to ``EQUIVALENCE_RTOL``. The refit is what makes the comparison
    fair to a candidate the search fitted badly -- the question is whether the *topology* is
    right, not whether one run of the optimiser was lucky.
    """

    def __init__(self, truth: Truth, spectrum: Spectrum) -> None:
        self.spectrum = spectrum
        self.canonical = Circuit.parse(truth.circuit).canonical_form()
        self.z_truth = fit(truth.circuit, spectrum, seed=0).z_model
        self.magnitude = np.abs(self.z_truth)
        self._cache: dict[str, bool] = {}

    def matches(self, candidate: Candidate) -> bool:
        """Is this candidate the truth or an exact reparameterisation of it?

        Three tests, cheapest first, and the middle one is why this does not take hours. The
        candidate arrives having *already* been refitted at full budget by the tier-2 stage, so
        its own ``z_model`` is the same quantity an independent refit would produce -- asking it
        first turns the common case into an array comparison. The independent refit stays as the
        third test rather than being dropped: a candidate the search happened to fit badly should
        still be judged on its topology, which is the whole point of the referee.
        """
        text = candidate.circuit.to_string()
        if text in self._cache:
            return self._cache[text]
        verdict = self._decide(text, candidate.result.z_model)
        self._cache[text] = verdict
        return verdict

    def _decide(self, circuit: str, z_reported: np.ndarray | None) -> bool:
        try:
            if Circuit.parse(circuit).canonical_form() == self.canonical:
                return True
            if z_reported is not None and self._same(z_reported):
                return True
            z = fit(circuit, self.spectrum, seed=0).z_model
        except (CircuitError, ValueError, np.linalg.LinAlgError):
            return False
        return self._same(z)

    def _same(self, z: np.ndarray) -> bool:
        if z.shape != self.z_truth.shape:
            return False
        return bool(np.max(np.abs(z - self.z_truth) / self.magnitude) <= EQUIVALENCE_RTOL)


def run_one(truth: Truth, arm: Arm, seed: int, workers: int) -> dict[str, Any]:
    spectrum = spectrum_for(truth, noise=NOISE, seed=seed)
    referee = Referee(truth, spectrum)

    started = time.perf_counter()
    result = discover(
        spectrum,
        pool=truth.pool,
        mode="exhaustive",
        workers=workers,
        growth_width=arm.growth_width,
        screen_restarts=arm.screen_restarts,
        max_elements=7,
        seed=0,
    )
    elapsed = time.perf_counter() - started

    reported = any(referee.matches(c) for c in result.candidates)
    on_front = any(referee.matches(c) for c in result.pareto)
    recommended = result.recommended is not None and referee.matches(result.recommended)
    rec_size = (
        None
        if result.recommended is None
        else count_elements(result.recommended.circuit.root)
    )
    return {
        "truth": truth.id,
        "shape": truth.shape,
        "n_elements": truth.n_elements,
        "arm": arm.name,
        "growth_width": arm.growth_width,
        "screen_restarts": arm.screen_restarts,
        "seed": seed,
        "seconds": round(elapsed, 1),
        "n_evaluated": result.n_evaluated,
        "complete_up_to": result.complete_up_to,
        "grown_to": result.grown_to,
        "reported": reported,
        "on_front": on_front,
        "recommended": recommended,
        "recommended_circuit": (
            None if result.recommended is None else result.recommended.circuit.to_string()
        ),
        "recommended_n_elements": rec_size,
        # The negative control's actual question: did the report prefer something *larger* than
        # the truth? Meaningless for the six- and seven-element rows and computed anyway, so the
        # two are read from the same field rather than from two code paths.
        "over_grown": None if rec_size is None else rec_size > truth.n_elements,
        "best_relative_error": (
            None if result.best is None else result.best.result.relative_error
        ),
    }


def summarise(rows: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    arms = [a.name for a in ARMS if any(r["arm"] == a.name for r in rows)]

    lines.append("## Recovery on the six- and seven-element truths")
    lines.append("")
    lines.append("| arm | reported | on the front | recommended | median seconds |")
    lines.append("|---|---:|---:|---:|---:|")
    for name in arms:
        subset = [r for r in rows if r["arm"] == name and r["n_elements"] >= 6]
        if not subset:
            continue
        total = len(subset)
        secs = float(np.median([r["seconds"] for r in subset]))
        lines.append(
            f"| {name} | {sum(r['reported'] for r in subset)}/{total} "
            f"| {sum(r['on_front'] for r in subset)}/{total} "
            f"| {sum(r['recommended'] for r in subset)}/{total} | {secs:.0f} |"
        )

    lines.append("")
    lines.append("## The negative control: five-element truths")
    lines.append("")
    lines.append(
        "A method that always grows would score perfectly above and be worthless. "
        "`over-grown` counts the runs whose recommendation has **more** elements than the truth."
    )
    lines.append("")
    lines.append("| arm | recommended correctly | over-grown | median seconds |")
    lines.append("|---|---:|---:|---:|")
    for name in arms:
        subset = [r for r in rows if r["arm"] == name and r["n_elements"] == 5]
        if not subset:
            continue
        total = len(subset)
        secs = float(np.median([r["seconds"] for r in subset]))
        lines.append(
            f"| {name} | {sum(r['recommended'] for r in subset)}/{total} "
            f"| {sum(bool(r['over_grown']) for r in subset)}/{total} | {secs:.0f} |"
        )

    lines.append("")
    lines.append("## By shape, `reported` only")
    lines.append("")
    shapes = ["parallel", "series", "mixed"]
    lines.append("| arm | " + " | ".join(shapes) + " |")
    lines.append("|---|" + "---:|" * len(shapes))
    for name in arms:
        cells = []
        for shape in shapes:
            subset = [
                r for r in rows if r["arm"] == name and r["shape"] == shape
            ]
            cells.append(
                "-" if not subset
                else f"{sum(r['reported'] for r in subset)}/{len(subset)}"
            )
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--arms", default=None, help="comma-separated arm names")
    parser.add_argument("--truths", default=None, help="comma-separated truth ids")
    parser.add_argument("--seeds", default=None, help="comma-separated noise seeds")
    args = parser.parse_args()

    arms = [a for a in ARMS if args.arms is None or a.name in args.arms.split(",")]
    truths = [t for t in TRUTHS if args.truths is None or t.id in args.truths.split(",")]
    seeds = SEEDS if args.seeds is None else tuple(int(s) for s in args.seeds.split(","))
    if not arms or not truths:
        raise SystemExit("nothing selected")

    # Resume: a run interrupted after two hours keeps what it had.
    rows: list[dict[str, Any]] = []
    if args.out.exists():
        rows = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk", flush=True)
    done = {(r["truth"], r["arm"], r["seed"]) for r in rows}

    for truth in truths:
        for arm in arms:
            for seed in seeds:
                if (truth.id, arm.name, seed) in done:
                    continue
                row = run_one(truth, arm, seed, args.workers)
                rows.append(row)
                print(json.dumps(row), flush=True)
                args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print()
    print(summarise(rows))
    args.out.with_suffix(".md").write_text(summarise(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
