"""``docs/CRITERION_SELECTION_PLAN.md``: was ``DEFAULT_CRITERION`` (``stats.py:39``), then
``"aic"``, the right default against BIC, CAIC, HQC and AICc?

**Run, and the answer moved the default: `"aic"` -> `"bic"` on 2026-09-04.** See that plan's
section 9 for the numbers this script produced and section 10 for what shipped from them. What
follows is the original scoping docstring, describing the questions this script still answers the
same way on a re-run or an extension to more of section 4's grid.

The scoping argument (that document's sections 1-2) is what makes this script narrower than "which
criterion is right": :attr:`~autocircuit.core.discover.DiscoveryResult.recommended` is built to
ignore ``criterion`` entirely, so the question is whether the *screening-stage* ranking
``criterion`` does control (``_quota_by_size``/``_screening_score``) ever changes which topologies
survive to be ``recommended``-eligible at all, and how often the separately reported
``by_criterion`` value disagrees with ``recommended`` or overfits a small truth. Three questions,
precisely (section 3):

* **Q1** -- does the criterion change whether the truth's equivalence class reaches
  ``report.pareto`` (``recovered`` below)?
* **Q2** -- does ``report.recommended`` in fact stay the same truth-equivalence verdict across
  criteria, as the property's own docstring claims by construction (``recommended_correct``)?
* **Q3** -- how often does ``report.by_criterion`` disagree with ``recommended``
  (``by_criterion_disagrees``), and on small-truth data, how often does it pick something larger
  than the truth (``by_criterion_overfits``, negative-control rows only)?

**Why element count and parameter count matter here.** ``benchmarks/six_plus/truths.py``'s nine
truths use the R, C, L pool only, where every element contributes exactly one parameter -- so
they cannot exercise the mechanism section 2(a) of the plan identifies (a CPE contributes two
parameters to one element, so same-size topologies can rank differently under different penalty
functions). ``benchmarks/discovery_v2.py``'s ``REFERENCES`` and ``LARGE_REFERENCES`` both put CPE
in the pool and are therefore the primary venue for Q1's actual hypothesis; the nine truths mainly
supply Q2's shape/size coverage and a growth-based negative control.

Three data sources, reused rather than rebuilt (section 4):

* ``benchmarks/six_plus/truths.py``'s ``TRUTHS`` (9, R/C/L only) over the same (noise,
  points-per-decade) grid ``identifiability.py`` (X2) and ``trigger.py`` (X3) already use --
  ``--only par5,par6,...``.
* ``benchmarks/discovery_v2.py``'s ``REFERENCES`` (3, <=5 elements, CPE/W in two of three pools)
  at each reference's own noise, swept over noise-realisation seeds -- ``--only ref_capacitor,...``.
* ``benchmarks/discovery_v2.py``'s ``LARGE_REFERENCES`` (3, 6-7 elements, CPE/SKINF/W in every
  pool) the same way -- ``--only large_mw3,...``.

Every cell runs one ``discover()`` call; ``recovered``/``recommended_correct``/
``by_criterion_disagrees``/``by_criterion_overfits`` all come from that one call's
``DiscoveryResult`` (``candidates``, ``recommended``, ``by_criterion``), so sweeping the four
metrics costs nothing beyond sweeping ``criterion`` itself -- there is no separate "Q3 pass".

``waic`` needs a full fit (Jacobian) to rank even the tier-1 shortlist promotion it cannot itself
perform (section 2c: it always falls back to AIC there), so it is left out of the default
``--criteria`` list; pass it explicitly to add it to the ``by_criterion`` (Q3) comparison. ``ftest``
is scored on Q3 only for the same structural reason (section 2c, section 6 penultimate paragraph).

Usage::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/criterion_selection.py --dry-run
    python benchmarks/criterion_selection.py --out benchmarks/criterion_selection.json `
        --only par5,par6 --criteria aic,bic --seeds 3 --workers 8
    python benchmarks/criterion_selection.py --out benchmarks/criterion_selection.json `
        --criteria aic,aicc,bic,caic,hqc,ftest --seeds 10 --workers 8
    python benchmarks/criterion_selection.py --summarize benchmarks/criterion_selection.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "six_plus"))

from discovery_v2 import LARGE_REFERENCES, REFERENCES, Reference  # noqa: E402
from truths import TRUTHS, Truth  # noqa: E402

from autocircuit.core.circuit import Circuit, CircuitError, count_elements  # noqa: E402
from autocircuit.core.discover import (  # noqa: E402
    EQUIVALENCE_RTOL,
    GROWTH_WIDTH,
    Candidate,
    DiscoveryResult,
    discover,
)
from autocircuit.core.fit import fit  # noqa: E402
from autocircuit.core.simulate import log_frequencies, simulate  # noqa: E402
from autocircuit.core.spectrum import Spectrum  # noqa: E402
from autocircuit.core.stats import CRITERIA, Criterion  # noqa: E402

#: Matches ``identifiability.py``/``trigger.py`` exactly, so the six_plus-truth rows are directly
#: comparable to the already-published X2/X3 figures.
NOISE_LEVELS: tuple[float, ...] = (0.001, 0.003, 0.01, 0.03)
POINTS_PER_DECADE: tuple[int, ...] = (5, 10, 20)

#: Sweeping every value in CRITERIA by default would run ``waic`` through the whole grid for no
#: benefit (section 2c: it cannot affect Q1's shortlist question, only Q3's by_criterion one) --
#: pass ``--criteria`` explicitly to add it.
DEFAULT_CRITERIA: tuple[Criterion, ...] = ("aic", "aicc", "bic", "caic", "hqc", "ftest")

#: Short ids for --only, alongside the six_plus TRUTHS' own ids (par5, ser6, ...).
REFERENCE_IDS: dict[str, Reference] = {
    "ref_capacitor": REFERENCES[0],
    "ref_mw": REFERENCES[1],
    "ref_randles": REFERENCES[2],
}
LARGE_REFERENCE_IDS: dict[str, Reference] = {
    "large_mw3": LARGE_REFERENCES[0],
    "large_cap_interfacial": LARGE_REFERENCES[1],
    "large_randles_esl": LARGE_REFERENCES[2],
}


class Referee:
    """Is this circuit the truth, or an exact reparameterisation of it?

    Canonical form first, falling back to an independent refit whose response must agree with the
    truth's own fitted response everywhere to ``EQUIVALENCE_RTOL`` -- the same referee
    ``benchmarks/six_plus/recovery.py`` and ``benchmarks/discovery_v2.py``'s
    ``_large_truth_verdict`` apply, reproduced here rather than imported so this script depends on
    neither module's own sys.path surgery.
    """

    def __init__(self, truth_circuit: str, spectrum: Spectrum) -> None:
        self.spectrum = spectrum
        self.canonical = Circuit.parse(truth_circuit).canonical_form()
        self.z_truth = fit(truth_circuit, spectrum, seed=0).z_model
        self.magnitude = np.abs(self.z_truth)
        self._cache: dict[str, bool] = {}

    def matches(self, candidate: Candidate) -> bool:
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


def _row(
    *,
    source: str,
    truth_id: str,
    shape: str | None,
    n_elements: int,
    noise: float,
    ppd: int | None,
    seed: int,
    criterion: str,
    result: DiscoveryResult,
    referee: Referee,
    elapsed: float,
    overfit_eligible: bool,
) -> dict[str, Any]:
    recovered = any(referee.matches(c) for c in result.candidates)
    recommended_correct = result.recommended is not None and referee.matches(result.recommended)
    rec = result.recommended
    by_c = result.by_criterion
    by_criterion_disagrees = (
        rec is not None
        and by_c is not None
        and by_c.circuit.canonical_form() != rec.circuit.canonical_form()
    )
    by_criterion_overfits = (
        (count_elements(by_c.circuit.root) > n_elements)
        if (overfit_eligible and by_c is not None)
        else None
    )
    return {
        "source": source,
        "truth": truth_id,
        "shape": shape,
        "n_elements": n_elements,
        "noise": noise,
        "points_per_decade": ppd,
        "seed": seed,
        "criterion": criterion,
        "n_evaluated": result.n_evaluated,
        "complete_up_to": result.complete_up_to,
        "grown_to": result.grown_to,
        "recovered": recovered,
        "recommended_correct": recommended_correct,
        "recommended_circuit": None if rec is None else rec.circuit.to_string(),
        "by_criterion_circuit": None if by_c is None else by_c.circuit.to_string(),
        "by_criterion_disagrees": by_criterion_disagrees,
        "by_criterion_overfits": by_criterion_overfits,
        "seconds": round(elapsed, 1),
        "summary": result.summary(),
    }


def run_six_plus_cell(
    truth: Truth, noise: float, ppd: int, seed: int, criterion: str, workers: int
) -> dict[str, Any]:
    freqs = log_frequencies(truth.f_min, truth.f_max, ppd)
    spectrum = simulate(truth.circuit, freqs, truth.params, noise=noise, seed=seed)
    referee = Referee(truth.circuit, spectrum)
    started = time.perf_counter()
    result = discover(
        spectrum,
        pool=truth.pool,
        mode="exhaustive",
        workers=workers,
        growth_width=GROWTH_WIDTH,
        max_elements=7,
        seed=0,
        criterion=criterion,
    )
    elapsed = time.perf_counter() - started
    return _row(
        source="six_plus",
        truth_id=truth.id,
        shape=truth.shape,
        n_elements=truth.n_elements,
        noise=noise,
        ppd=ppd,
        seed=seed,
        criterion=criterion,
        result=result,
        referee=referee,
        elapsed=elapsed,
        overfit_eligible=(truth.n_elements == 5),
    )


def run_reference_cell(
    ref: Reference, ref_id: str, seed: int, criterion: str, workers: int, *, grow: bool
) -> dict[str, Any]:
    spectrum = ref.spectrum(seed)
    referee = Referee(ref.circuit, spectrum)
    started = time.perf_counter()
    result = discover(
        spectrum,
        pool=ref.pool,
        mode="exhaustive",
        workers=workers,
        growth_width=(GROWTH_WIDTH if grow else 0),
        max_elements=7,
        seed=0,
        criterion=criterion,
    )
    elapsed = time.perf_counter() - started
    return _row(
        source="large_reference" if grow else "reference",
        truth_id=ref_id,
        shape=None,
        n_elements=ref.n_elements,
        noise=ref.noise,
        ppd=None,
        seed=seed,
        criterion=criterion,
        result=result,
        referee=referee,
        elapsed=elapsed,
        overfit_eligible=not grow,
    )


# =================================================================================================
# Planning, resuming, running
# =================================================================================================


def plan(
    only: set[str] | None,
    criteria: Sequence[str],
    n_seeds: int,
    noise_levels: Sequence[float] = NOISE_LEVELS,
    ppd_values: Sequence[int] = POINTS_PER_DECADE,
) -> list[dict[str, Any]]:
    """Every work unit to run, cheapest groups first so an interrupted run keeps the cheap half.

    ``noise_levels``/``ppd_values`` narrow the six_plus grid (e.g. to the project's own standard
    1%-noise/10-ppd cell, ``docs/TOPOLOGY_6PLUS_PLAN.md``'s recurring reference point) when the
    full 4x3 grid across every truth and criterion is not affordable -- see ``--noise``/``--ppd``.
    """
    seeds = list(range(n_seeds))
    units: list[dict[str, Any]] = []

    for ref_id in REFERENCE_IDS:
        if only is not None and ref_id not in only:
            continue
        for criterion in criteria:
            for seed in seeds:
                units.append(
                    {"group": "reference", "id": ref_id, "seed": seed, "criterion": criterion}
                )

    for truth in TRUTHS:
        if only is not None and truth.id not in only:
            continue
        for criterion in criteria:
            for noise in noise_levels:
                for ppd in ppd_values:
                    for seed in seeds:
                        units.append(
                            {
                                "group": "six_plus",
                                "id": truth.id,
                                "noise": noise,
                                "ppd": ppd,
                                "seed": seed,
                                "criterion": criterion,
                            }
                        )

    for ref_id in LARGE_REFERENCE_IDS:
        if only is not None and ref_id not in only:
            continue
        for criterion in criteria:
            for seed in seeds:
                units.append(
                    {"group": "large_reference", "id": ref_id, "seed": seed, "criterion": criterion}
                )

    return units


def _key(unit: dict[str, Any]) -> tuple[Any, ...]:
    return (
        unit["group"],
        unit["id"],
        unit.get("noise"),
        unit.get("ppd"),
        unit["seed"],
        unit["criterion"],
    )


def _row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["source"],
        row["truth"],
        row["noise"] if row["source"] == "six_plus" else None,
        row["points_per_decade"],
        row["seed"],
        row["criterion"],
    )


def run_unit(unit: dict[str, Any], workers: int) -> dict[str, Any]:
    group = unit["group"]
    if group == "six_plus":
        truth = next(t for t in TRUTHS if t.id == unit["id"])
        return run_six_plus_cell(
            truth, unit["noise"], unit["ppd"], unit["seed"], unit["criterion"], workers
        )
    if group == "reference":
        return run_reference_cell(
            REFERENCE_IDS[unit["id"]],
            unit["id"],
            unit["seed"],
            unit["criterion"],
            workers,
            grow=False,
        )
    if group == "large_reference":
        return run_reference_cell(
            LARGE_REFERENCE_IDS[unit["id"]],
            unit["id"],
            unit["seed"],
            unit["criterion"],
            workers,
            grow=True,
        )
    raise ValueError(f"unknown group {group!r}")


def summarize(rows: list[dict[str, Any]]) -> str:
    """Pooled rate per criterion, mirroring ``trigger.py --summarize``'s shape."""
    criteria_seen = sorted({r["criterion"] for r in rows}, key=lambda c: CRITERIA.index(c))
    negative_control = [r for r in rows if r["by_criterion_overfits"] is not None]
    lines = [
        "| criterion | recovered | recommended_correct | by_criterion_disagrees "
        "| by_criterion_overfits (negative controls) | n |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for criterion in criteria_seen:
        subset = [r for r in rows if r["criterion"] == criterion]
        neg_subset = [r for r in negative_control if r["criterion"] == criterion]
        n = len(subset)

        def rate(key: str, rows_: list[dict[str, Any]]) -> str:
            if not rows_:
                return "-"
            hits = sum(1 for r in rows_ if r[key])
            return f"{hits / len(rows_):.1%} ({hits}/{len(rows_)})"

        lines.append(
            f"| {criterion} | {rate('recovered', subset)} | {rate('recommended_correct', subset)} "
            f"| {rate('by_criterion_disagrees', subset)} "
            f"| {rate('by_criterion_overfits', neg_subset)} | {n} |"
        )

    lines.append("")
    lines.append("## By source")
    lines.append("")
    lines.append("| criterion | source | recovered | recommended_correct | n |")
    lines.append("|---|---|---:|---:|---:|")
    for criterion in criteria_seen:
        for source in ("reference", "six_plus", "large_reference"):
            subset = [r for r in rows if r["criterion"] == criterion and r["source"] == source]
            if not subset:
                continue
            n = len(subset)
            rec = sum(1 for r in subset if r["recovered"])
            rcc = sum(1 for r in subset if r["recommended_correct"])
            lines.append(
                f"| {criterion} | {source} | {rec / n:.1%} ({rec}/{n}) "
                f"| {rcc / n:.1%} ({rcc}/{n}) | {n} |"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--criteria", default=",".join(DEFAULT_CRITERIA), help="comma-separated criterion names"
    )
    parser.add_argument("--seeds", type=int, default=3, help="noise-realisation seeds, 0..N-1")
    parser.add_argument("--only", default=None, help="comma-separated truth/reference ids")
    parser.add_argument(
        "--noise", default=None, help="comma-separated noise levels (six_plus grid only)"
    )
    parser.add_argument(
        "--ppd", default=None, help="comma-separated points-per-decade (six_plus grid only)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--summarize", type=Path, default=None, help="print rates from an existing JSON file"
    )
    args = parser.parse_args()

    if args.summarize is not None:
        saved_rows = json.loads(args.summarize.read_text(encoding="utf-8"))
        print(summarize(saved_rows))
        return

    criteria = [c.strip() for c in args.criteria.split(",")]
    for criterion in criteria:
        if criterion not in CRITERIA:
            raise SystemExit(f"unknown criterion {criterion!r}; choose from {CRITERIA}")

    only = None if args.only is None else {s.strip() for s in args.only.split(",")}
    all_ids = {*REFERENCE_IDS, *(t.id for t in TRUTHS), *LARGE_REFERENCE_IDS}
    if only is not None and not only <= all_ids:
        raise SystemExit(f"unknown id(s): {only - all_ids}; choose from {sorted(all_ids)}")

    noise_levels = (
        NOISE_LEVELS if args.noise is None else tuple(float(x) for x in args.noise.split(","))
    )
    ppd_values = (
        POINTS_PER_DECADE if args.ppd is None else tuple(int(x) for x in args.ppd.split(","))
    )
    todo_all = plan(only, criteria, args.seeds, noise_levels, ppd_values)
    if not todo_all:
        raise SystemExit("nothing selected")

    print(f"{len(todo_all)} cells planned, criteria={criteria}, seeds=0..{args.seeds - 1}")
    if args.dry_run:
        by_group: dict[str, int] = {}
        for unit in todo_all:
            by_group[unit["group"]] = by_group.get(unit["group"], 0) + 1
        for group, count in by_group.items():
            print(f"  {group}: {count} cells")
        return
    if args.out is None:
        raise SystemExit("--out is required unless --dry-run")

    rows: list[dict[str, Any]] = []
    if args.out.exists():
        rows = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming with {len(rows)} rows already on disk", flush=True)
    done = {_row_key(r) for r in rows}
    todo = [u for u in todo_all if _key(u) not in done]
    print(f"{len(todo)} cells to go", flush=True)

    started_all = time.perf_counter()
    for index, unit in enumerate(todo, start=1):
        row = run_unit(unit, args.workers)
        rows.append(row)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(
            f"[{index}/{len(todo)}] {row['source']}/{row['truth']} noise={row['noise']:.3%} "
            f"ppd={row['points_per_decade']} seed={row['seed']} criterion={row['criterion']} "
            f"recovered={row['recovered']} recommended_correct={row['recommended_correct']} "
            f"by_criterion_disagrees={row['by_criterion_disagrees']} "
            f"{row['seconds']:.0f}s",
            flush=True,
        )
    print(f"\nall done in {(time.perf_counter() - started_all) / 60:.1f} min")
    print()
    print(summarize(rows))
    args.out.with_suffix(".md").write_text(summarize(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
