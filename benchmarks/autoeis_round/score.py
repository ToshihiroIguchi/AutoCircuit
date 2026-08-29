"""Score the AutoEIS round: one referee, applied identically to both frozen result tables.

Runs in the PROJECT environment and **never imports** ``autoeis`` -- it reads the two producers'
JSONL files, which are plain data by the time they get here. See
``docs/AUTOEIS_COMPARISON_PLAN.md`` sections 2.3 and 3 for the rules this file implements, and
``docs/AUTOEIS_COMPARISON.md`` for the measurements they rest on.

The three things this file exists to get right:

**One referee for both sides.** A hit is: the returned topology's ``canonical_form()`` equals the
truth's, *or* its response matches the truth's to within ``EQUIVALENCE_RTOL``. That is the same
rule ``benchmarks/discovery_v2.py``'s ``_large_truth_verdict`` applies to this project's own
search, and it is applied here to AutoEIS's candidates through exactly the same code path.
Applying an equivalence detector to our output and a string comparison to theirs would score the
referee rather than the searches.

**Two readings of "reported", because one of them would be a choice disguised as a measurement.**
AutoEIS's parameters come from its own optimiser. Judging its topologies on those values marks a
topology *wrong* whenever it is an exact reparameterisation of the truth that the other tool
simply fitted badly -- which is a statement about its optimiser, not about whether its search
found the right form. Refitting everything with this project's fitter answers the topology
question symmetrically, but scores the other tool on values it never reported. Both are computed
and both are printed: ``as_returned`` uses each tool's own parameters, ``refitted`` puts every
candidate from both sides through this project's fitter. Neither is designated the answer here;
the write-up quotes both, and parameter accuracy is a separate metric scored on each tool's own
values.

**A wrong answer and a refusal are not the same event.** The failure taxonomy is reported as
counts, never folded into a single "miss" -- ``filtered`` in particular, because a filter that
deletes the right answer from a search still calling itself complete is a failure mode this
project has already measured on itself twice.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from typing import Any

import numpy as np
from deviation import worst_deviation
from translate import TranslationError, to_autocircuit

from autocircuit.core.circuit import Circuit, CircuitError
from autocircuit.core.discover import EQUIVALENCE_RTOL
from autocircuit.core.fit import fit
from autocircuit.core.spectrum import Spectrum

#: Element codes AutoEIS cannot express. A truth containing one is N/A for that tool, never zero.
OUT_OF_VOCABULARY = ("W", "Ws", "Wo", "G", "CC", "HN", "SKINF", "SKINW")


@dataclass
class Outcome:
    """What one tool did on one (truth, seed) pair."""

    tool: str
    truth_id: str
    seed: int
    #: One of: ok, oov, filtered, crash, empty.
    status: str
    reported_as_returned: bool = False
    reported_refitted: bool = False
    on_front: bool = False
    recommended: bool = False
    recommended_circuit: str | None = None
    n_candidates: int = 0
    n_points_in: int = 0
    n_points_used: int = 0
    worst_param_deviation: float = math.nan
    wall_seconds: float = math.nan


@dataclass
class Census:
    """Counts that must never be collapsed into one number."""

    status: Counter[str] = field(default_factory=Counter)
    points_dropped: list[tuple[str, int, int]] = field(default_factory=list)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a producer's output, tolerating a final partial line from a power loss."""
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            where = "last" if number == len(lines) else f"line {number}"
            print(f"warning: {where} record in {path.name} is not valid JSON, skipping it")
    return records


def read_spectrum(path: Path) -> Spectrum:
    table = np.loadtxt(path, delimiter=",", skiprows=1)
    return Spectrum(f=table[:, 0], z=table[:, 1] + 1j * table[:, 2])


class Referee:
    """The truth's own response, and the two ways of asking whether a candidate matches it.

    Constructed once per (truth, seed) so that the truth is fitted once and both tools are
    judged against the identical reference response.
    """

    def __init__(self, truth_circuit: str, spectrum: Spectrum) -> None:
        self.spectrum = spectrum
        self.canonical = Circuit.parse(truth_circuit).canonical_form()
        self.z_truth = fit(truth_circuit, spectrum, seed=0).z_model
        self.magnitude = np.abs(self.z_truth)
        self.usable = bool(np.all(self.magnitude > 0.0))
        self._refit_cache: dict[str, bool] = {}

    def _same_response(self, z_model: np.ndarray) -> bool:
        if not self.usable or z_model.shape != self.z_truth.shape:
            return False
        return bool(np.max(np.abs(z_model - self.z_truth) / self.magnitude) <= EQUIVALENCE_RTOL)

    def matches_as_returned(self, circuit: str, z_model: np.ndarray | None) -> bool:
        """Structural match, or a numeric one against the parameters the tool itself reported."""
        try:
            if Circuit.parse(circuit).canonical_form() == self.canonical:
                return True
        except (CircuitError, ValueError):
            return False
        return z_model is not None and self._same_response(z_model)

    def matches_refitted(self, circuit: str) -> bool:
        """Structural match, or a numeric one after refitting the topology with our own fitter.

        This is the symmetric reading: it asks whether the *topology* can reproduce the truth,
        rather than whether the tool that proposed it also optimised it well. Cached, because the
        same topology recurs across a tool's candidate list.
        """
        if circuit in self._refit_cache:
            return self._refit_cache[circuit]
        verdict = False
        try:
            if Circuit.parse(circuit).canonical_form() == self.canonical:
                verdict = True
            else:
                verdict = self._same_response(fit(circuit, self.spectrum, seed=0).z_model)
        except (CircuitError, ValueError, np.linalg.LinAlgError):
            verdict = False
        self._refit_cache[circuit] = verdict
        return verdict


def _autocircuit_candidates(record: dict[str, Any]) -> tuple[list[dict], list[dict], str | None]:
    """(all candidates, Pareto front, recommended circuit) from one of our reports."""
    report = record.get("report") or {}
    candidates = list(report.get("candidates") or [])
    pareto = list(report.get("pareto") or [])
    recommended = report.get("recommended")
    name = None if recommended is None else recommended.get("circuit")
    return candidates, pareto, name


def _z_from_report_entry(entry: dict[str, Any], spectrum: Spectrum) -> np.ndarray | None:
    """Rebuild a reported candidate's response from the values the report carries."""
    try:
        circuit = Circuit.parse(entry["circuit"])
        values = {k: v["value"] for k, v in entry["parameters"].items()}
        omega = 2.0 * np.pi * spectrum.f
        return circuit.impedance(omega, circuit.values_array(values))
    except (CircuitError, KeyError, ValueError):
        return None


def _z_from_autoeis(circuit: str, params: dict[str, float], spectrum: Spectrum) -> tuple[
    str | None, np.ndarray | None
]:
    """Translate one AutoEIS candidate and evaluate it at the parameters AutoEIS reported."""
    try:
        text, values = to_autocircuit(circuit, params)
    except TranslationError:
        return None, None
    try:
        parsed = Circuit.parse(text)
        omega = 2.0 * np.pi * spectrum.f
        return text, parsed.impedance(omega, parsed.values_array(values))
    except (CircuitError, KeyError, ValueError):
        return text, None


def score_autocircuit(
    record: dict[str, Any], referee: Referee, truth: dict[str, Any]
) -> Outcome:
    outcome = Outcome(
        tool="autocircuit",
        truth_id=record["truth_id"],
        seed=record["seed"],
        status="ok",
        n_points_in=record.get("n_points_in", 0),
        n_points_used=record.get("n_points_used", 0),
        wall_seconds=record.get("wall_seconds", math.nan),
    )
    if record.get("error"):
        outcome.status = "crash"
        return outcome

    candidates, pareto, recommended = _autocircuit_candidates(record)
    outcome.n_candidates = len(candidates)
    outcome.recommended_circuit = recommended
    if not candidates:
        outcome.status = "empty"
        return outcome

    outcome.reported_as_returned = any(
        referee.matches_as_returned(c["circuit"], _z_from_report_entry(c, referee.spectrum))
        for c in candidates
    )
    outcome.reported_refitted = any(referee.matches_refitted(c["circuit"]) for c in candidates)
    outcome.on_front = any(referee.matches_refitted(c["circuit"]) for c in pareto)
    outcome.recommended = recommended is not None and referee.matches_refitted(recommended)
    if outcome.recommended:
        outcome.worst_param_deviation = _worst_deviation_from_report(
            next(c for c in candidates if c["circuit"] == recommended), truth
        )
    return outcome


def score_autoeis(record: dict[str, Any], referee: Referee, truth: dict[str, Any]) -> Outcome:
    outcome = Outcome(
        tool="autoeis",
        truth_id=record["truth_id"],
        seed=record["seed"],
        status="ok",
        n_points_in=record.get("n_points_in", 0),
        n_points_used=record.get("n_points_used", 0),
        wall_seconds=record.get("wall_seconds", math.nan),
    )
    if any(code in truth["circuit"] for code in OUT_OF_VOCABULARY):
        outcome.status = "oov"
        return outcome
    if record.get("error"):
        outcome.status = "crash"
        return outcome

    generated = record.get("generated_circuits") or []
    surviving = record.get("filtered_circuits") or []
    if not generated:
        outcome.status = "empty"
        return outcome
    if not surviving:
        # Its own physics filters deleted everything its own search proposed. Not the same
        # event as a wrong answer, and never counted as one.
        outcome.status = "filtered"
        outcome.n_candidates = len(generated)
        return outcome

    outcome.n_candidates = len(surviving)
    as_returned = False
    refitted = False
    for entry in surviving:
        text, z_model = _z_from_autoeis(
            entry["circuitstring"], entry.get("parameters") or {}, referee.spectrum
        )
        if text is None:
            continue
        as_returned = as_returned or referee.matches_as_returned(text, z_model)
        refitted = refitted or referee.matches_refitted(text)
    outcome.reported_as_returned = as_returned
    outcome.reported_refitted = refitted
    # AutoEIS has no Pareto front; its surviving post-filter set is the nearest object, and the
    # table says so rather than pretending the two are the same thing.
    outcome.on_front = refitted

    ranked = record.get("ranked_circuitstrings") or []
    if ranked:
        top = ranked[0] if isinstance(ranked[0], str) else ranked[0].get("circuitstring")
        try:
            text, _ = to_autocircuit(top)
        except TranslationError:
            text = None
        outcome.recommended_circuit = text
        outcome.recommended = text is not None and referee.matches_refitted(text)
    return outcome


def _worst_deviation_from_report(entry: dict[str, Any], truth: dict[str, Any]) -> float:
    """Worst per-parameter relative deviation, matched by VALUE rather than by name.

    Parallel blocks in series carry a permutation symmetry, so a name-by-name comparison of a
    recovered R1 against a generating R1 is meaningless; only a value-matched comparison means
    anything. Comparable parameters are grouped by element code and matched greedily by nearest
    log-distance within the group.
    """
    try:
        recovered = {k: v["value"] for k, v in entry["parameters"].items()}
    except (KeyError, TypeError):
        return math.nan
    return worst_deviation(recovered, truth["params"])


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2.0**n)
    return min(1.0, 2.0 * tail)


def resolvable_discordant(n_pairs: int = 64) -> int:
    """The smallest all-in-one-direction discordant count that can reach p <= 0.05.

    **This is a property of the exact test, not of the arena.** Five discordant runs all in one
    direction reach only p = 0.0625, six reach 0.03125, so the answer is 6 for any arena with at
    least six pairs, and more seeds buy the *opportunity* for discordant runs rather than a lower
    bar. Passing a smaller ``n_pairs`` returns ``n_pairs + 1``, which is the honest way to say
    that an arena this small can resolve nothing at all -- callers must distinguish the two
    cases rather than printing the number as if it were universal.

    Declared before the result is read, per section 4 of the plan: an outcome inside it is
    reported as "indistinguishable at this seed count", and the response is more seeds or
    nothing -- never a reworded bar.
    """
    for discordant in range(1, n_pairs + 1):
        if mcnemar_exact(discordant, 0) <= 0.05:
            return discordant
    return n_pairs + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None, help="write the report as JSON here")
    args = parser.parse_args()

    arena = json.loads((args.arena / "arena.json").read_text(encoding="utf-8"))
    truths = {t["truth_id"]: t for t in arena["truths"]}
    ours = load_jsonl(args.arena / "results_autocircuit.jsonl")
    theirs = load_jsonl(args.arena / "results_autoeis.jsonl")

    smoke = [r for r in chain(ours, theirs) if r.get("smoke")]
    if smoke:
        raise SystemExit(
            f"refusing to score: {len(smoke)} smoke records present. Smoke output is a plumbing "
            "test, not a measurement."
        )

    by_key_ours = {(r["truth_id"], r["seed"]): r for r in ours}
    by_key_theirs = {(r["truth_id"], r["seed"]): r for r in theirs}
    paired = sorted(set(by_key_ours) & set(by_key_theirs))
    print(f"{len(ours)} AutoCircuit runs, {len(theirs)} AutoEIS runs, {len(paired)} paired\n")
    if not paired:
        raise SystemExit("nothing to score yet")

    outcomes: list[tuple[Outcome, Outcome]] = []
    census_ours, census_theirs = Census(), Census()
    for truth_id, seed in paired:
        truth = truths[truth_id]
        spectrum = read_spectrum(args.arena / "spectra" / f"{truth_id}_s{seed}.csv")
        referee = Referee(truth["circuit"], spectrum)
        a = score_autocircuit(by_key_ours[(truth_id, seed)], referee, truth)
        b = score_autoeis(by_key_theirs[(truth_id, seed)], referee, truth)
        outcomes.append((a, b))
        census_ours.status[a.status] += 1
        census_theirs.status[b.status] += 1
        if b.n_points_used and b.n_points_used < b.n_points_in:
            census_theirs.points_dropped.append((truth_id, b.n_points_in, b.n_points_used))
        print(
            f"  {truth_id} s{seed:<3} ours={a.status}/{int(a.reported_refitted)}"
            f"{int(a.on_front)}{int(a.recommended)}"
            f"   theirs={b.status}/{int(b.reported_refitted)}"
            f"{int(b.on_front)}{int(b.recommended)}"
            f"   pts {b.n_points_in}->{b.n_points_used}"
        )

    report = _summarise(outcomes, truths, census_ours, census_theirs)
    if args.out is not None:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")


def _rate(rows: list[Outcome], attribute: str) -> str:
    eligible = [r for r in rows if r.status != "oov"]
    if not eligible:
        return "n/a (0 eligible)"
    hits = sum(bool(getattr(r, attribute)) for r in eligible)
    return f"{hits}/{len(eligible)}"


def _summarise(
    outcomes: list[tuple[Outcome, Outcome]],
    truths: dict[str, dict[str, Any]],
    census_ours: Census,
    census_theirs: Census,
) -> dict[str, Any]:
    ours = [a for a, _ in outcomes]
    theirs = [b for _, b in outcomes]

    print("\n" + "=" * 88)
    print("Recovery. 'oov' truths are excluded from that tool's denominator, never scored zero.")
    print("=" * 88)
    for label, attribute in (
        ("reported (refitted referee)", "reported_refitted"),
        ("reported (tool's own values)", "reported_as_returned"),
        ("on front / post-filter set", "on_front"),
        ("recommended", "recommended"),
    ):
        print(f"  {label:<30} AutoCircuit {_rate(ours, attribute):>10}"
              f"    AutoEIS {_rate(theirs, attribute):>10}")
    print("\n  The two 'reported' rows are two readings, not a headline and a footnote; see this")
    print("  module's docstring. 'on front' compares different objects on the two sides: a Pareto")
    print("  front here, the surviving post-filter set there.")

    print("\n" + "=" * 88)
    print("Split by element count, and by whether the truth contains an inductor")
    print("=" * 88)
    for size in sorted({truths[o.truth_id]["n_elements"] for o in ours}):
        a = [o for o in ours if truths[o.truth_id]["n_elements"] == size]
        b = [o for o in theirs if truths[o.truth_id]["n_elements"] == size]
        print(f"  {size} elements   AutoCircuit {_rate(a, 'reported_refitted'):>10}"
              f"    AutoEIS {_rate(b, 'reported_refitted'):>10}")
    for has_l in (True, False):
        a = [o for o in ours if truths[o.truth_id]["has_inductor"] is has_l]
        b = [o for o in theirs if truths[o.truth_id]["has_inductor"] is has_l]
        tag = "with L" if has_l else "without L"
        print(f"  {tag:<12} AutoCircuit {_rate(a, 'reported_refitted'):>10}"
              f"    AutoEIS {_rate(b, 'reported_refitted'):>10}")

    # The `L` split is the pre-registered proxy and it is coarse: what AutoEIS's preprocessing
    # responds to is whether the spectrum has an inductive tail, not whether the circuit has an
    # inductor, and one L-carrying truth in this arena loses no points at all (section 0.5). So
    # the same rates are also split by how much of the sweep that run's search actually got.
    print("\n  ...and by how much of the sweep AutoEIS's search actually received:")
    buckets = (("kept < 75%", 0.0, 0.75), ("75-95%", 0.75, 0.95), ("kept >= 95%", 0.95, 1.01))
    for label, low, high in buckets:
        pairs = [
            (a, b)
            for a, b in zip(ours, theirs, strict=True)
            if b.n_points_in and low <= b.n_points_used / b.n_points_in < high
        ]
        if not pairs:
            continue
        print(f"  {label:<12} AutoCircuit {_rate([a for a, _ in pairs], 'reported_refitted'):>10}"
              f"    AutoEIS {_rate([b for _, b in pairs], 'reported_refitted'):>10}"
              f"   ({len(pairs)} pairs)")

    print("\n" + "=" * 88)
    print("Failure taxonomy -- a wrong answer and a refusal are different events")
    print("=" * 88)
    print(f"  AutoCircuit  {dict(census_ours.status)}")
    print(f"  AutoEIS      {dict(census_theirs.status)}")
    if census_theirs.points_dropped:
        dropped = census_theirs.points_dropped
        print(f"\n  AutoEIS's preprocessing removed points on {len(dropped)} of {len(theirs)} runs")
        print("  (its search never saw them; this is not the same event as `filtered`):")
        for truth_id, before, after in dropped[:10]:
            print(f"    {truth_id}: {before} -> {after}")

    eligible = [(a, b) for a, b in outcomes if b.status != "oov"]
    only_ours = sum(1 for a, b in eligible if a.reported_refitted and not b.reported_refitted)
    only_theirs = sum(1 for a, b in eligible if b.reported_refitted and not a.reported_refitted)
    p_value = mcnemar_exact(only_ours, only_theirs)
    d = resolvable_discordant()  # the test's own bar, independent of this arena
    reachable = len(eligible) >= d

    print("\n" + "=" * 88)
    print("Paired comparison (McNemar exact, on `reported` with the refitted referee)")
    print("=" * 88)
    print(f"  pairs {len(eligible)},  AutoCircuit only {only_ours},  AutoEIS only {only_theirs}")
    print(f"  p = {p_value:.4f}")
    print(f"  d = {d}: fewer than {d} discordant runs all in one direction cannot reach")
    print("      p <= 0.05. This is a property of the exact test, not of the arena -- more")
    print("      seeds buy the opportunity for discordant runs, never a lower bar.")
    if not reachable:
        print(f"  This arena cannot resolve ANY difference: {len(eligible)} pairs is fewer than")
        print(f"      the {d} discordant runs the bar needs, so no outcome here could be called.")
    elif max(only_ours, only_theirs) < d:
        print("  VERDICT: indistinguishable at this seed count. The response is more seeds or")
        print("           nothing -- not a reworded bar.")

    return {
        "n_pairs": len(eligible),
        "only_autocircuit": only_ours,
        "only_autoeis": only_theirs,
        "p_value": p_value,
        "resolvable_discordant": d,
        "bar_reachable_at_this_arena_size": reachable,
        "census_autocircuit": dict(census_ours.status),
        "census_autoeis": dict(census_theirs.status),
        "outcomes": [
            {"autocircuit": vars(a), "autoeis": vars(b)} for a, b in outcomes
        ],
    }


if __name__ == "__main__":
    main()
