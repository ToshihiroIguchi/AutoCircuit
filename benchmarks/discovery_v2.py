"""Does exhaustive-first discovery actually work, and what does it cost?

Seven measurements, selected by the first command-line argument:

``gate``
    Acceptance gate **G1** of ``docs/DISCOVERY_V2_PLAN.md``: on each reference spectrum,
    ``mode="exhaustive"`` must put the true topology (or an exact equivalent of it) into the
    reported equivalence classes, for every seed, within the time budget.

``filter``
    How much the structural feasibility filter of ``core/enumerate.py`` removes, and -- the
    part that matters -- whether the truth survives it. This is the number quoted in
    ``benchmarks/README.md``; section 3.2 of the plan guessed at it, so it is measured here
    rather than assumed.

``skeleton``
    Acceptance gate **P1** of ``docs/PARTIAL_TOPOLOGY_PLAN.md``: with the *true* skeleton
    asserted, ``discover(skeleton=...)`` must still report the truth or an exact equivalent,
    on every reference and every seed. Recovery is the gate. The speed-up over the
    unconstrained run (``--compare``) is a recorded observation, not a target -- G1 records
    what happens when a time target is chased.

``wrong-skeleton``
    Acceptance gate **P2**, and the measurement section 3.2 of that plan deliberately leaves
    unwritten: with a skeleton the reference does *not* contain, what does the report look
    like? Reports the runs-test z on the residuals, whether the recommendation carries
    unresolved parameters, and how far the constrained chi2 sits from the truth's own. The
    gate's wording is written from these numbers, not before them.

``excluded``
    Section 3.3 of the same plan: with the true skeleton asserted, which same-size topologies
    did it exclude that reproduce the reported model exactly? Measures the cost (which is why
    the feature is opt-in) and the yield (which is why it exists).

``screen``
    Tuning evidence for the tier-1 screening budget: for a range of (popsize, maxiter)
    settings, how long the screen takes and whether it still ranks the truth highly enough to
    reach the tier-2 shortlist. A screen that is too cheap loses the answer; one that is too
    expensive defeats the point of screening.

``screen-rank``
    The same question asked properly, and the evidence a budget change has to rest on.
    ``screen`` samples ~60 topologies out of thousands and reports a global rank; that is not
    the quantity the pipeline uses. What decides whether the two-tier search keeps the answer
    is whether the truth -- and every known exact equivalent of it -- lands inside its
    **per-element-count quota**, ranked by screening AICc, in the *whole* filtered space. So
    this mode screens every candidate, at every budget in a grid, over several seeds, and
    records each tracked circuit's rank within its size, the quota it had to beat, and whether
    ``_shortlist`` in fact selected it. Cutting the budget on a 60-topology sample would repeat
    the mistake that cost gate G1 once already (ranking by raw cost looked fine on small cases
    and lost the truth on the real space).

Run with the package on the path (it is not pip-installed on the dev machine)::

    $env:PYTHONPATH = "C:\\Users\\toshi\\python\\AutoCircuit\\src"
    python benchmarks/discovery_v2.py filter
    python benchmarks/discovery_v2.py screen
    python benchmarks/discovery_v2.py screen-rank --workers 8
    python benchmarks/discovery_v2.py gate --workers 8
    python benchmarks/discovery_v2.py skeleton --workers 8 --compare
    python benchmarks/discovery_v2.py wrong-skeleton --workers 8
    python benchmarks/discovery_v2.py excluded --seeds 1 --workers 8

``gate`` and ``screen-rank`` are the slow ones: both fit every plausible topology up to five
elements, several times over. Use ``--seeds 1`` and ``--limit 4`` for a sanity run.
"""

from __future__ import annotations

import argparse
import itertools
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import (
    MIN_REFINE_PER_SIZE,
    REFINE_DEFAULT,
    DiscoveryResult,
    ScreenBudget,
    # ``screen-rank`` measures the ranking the two-tier search actually performs, so it calls
    # that machinery rather than re-deriving it: a reimplementation here would measure the
    # benchmark. (This is the opposite choice from ``benchmarks/topology_space.py``, which
    # keeps its own enumerator on purpose so that gate G2 checks one implementation against
    # another.) The following four imports are private:
    _screen_all,
    _screening_aicc,
    _shortlist,
    _worker_pool,
    discover,
    excluded_equivalents,
)
from autocircuit.core.enumerate import (
    EndpointBehaviour,
    contains_skeleton,
    enumerate_topologies,
    is_feasible,
)
from autocircuit.core.fit import fit, screen
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import RUNS_Z_LIMIT, _runs_z


@dataclass(frozen=True)
class Reference:
    """A synthetic spectrum whose true topology is known."""

    label: str
    circuit: str
    params: dict[str, float]
    pool: tuple[str, ...]
    f_min: float
    f_max: float
    noise: float = 0.01
    #: Same-size topologies known to fit this reference identically, measured by fitting every
    #: same-size topology to noise-free data and keeping those matching to 1e-9. The same list
    #: gate G3 uses (``tests/test_feasibility.py``): a screening budget that keeps the truth but
    #: drops its equivalents has quietly destroyed the equivalence-class report.
    equivalents: tuple[str, ...] = ()
    #: A *true* skeleton for this reference: the part of the circuit a user of this kind of
    #: sample would already know, and which the truth really does contain. Gate P1 asserts it
    #: and checks the truth still comes back. Each one is a claim someone would actually make
    #: -- a capacitor's C with its ESR and ESL, one relaxation of a two-block dielectric, the
    #: electrolyte resistance and double layer of a cell -- not a sub-circuit chosen to be easy.
    skeleton: str = ""
    #: A skeleton this reference does *not* contain, for gate P2. Each is a mistake someone
    #: would plausibly make -- a semicircle asserted for a capacitor that has none, a CPE
    #: asserted where the sample has an ideal capacitance -- rather than a circuit chosen to be
    #: obviously absurd. A wrong skeleton that is easy to spot measures nothing.
    wrong_skeleton: str = ""

    def spectrum(self, seed: int = 0, noise: float | None = None) -> Spectrum:
        return simulate(
            self.circuit,
            log_frequencies(self.f_min, self.f_max, 10),
            self.params,
            noise=self.noise if noise is None else noise,
            seed=seed,
        )

    @property
    def canonical(self) -> str:
        return Circuit.parse(self.circuit).canonical_form()

    @property
    def n_elements(self) -> int:
        return len(Circuit.parse(self.circuit).leaves)


REFERENCES = [
    Reference(
        "capacitor (C-R-L + skin effect)",
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        ("R", "C", "L", "CPE", "SKINF"),
        1e2,
        1e9,
        skeleton="C1-R1-L1",
        wrong_skeleton="R1-p(R2,C1)",
    ),
    Reference(
        "Maxwell-Wagner (two blocks)",
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        ("R", "C", "L", "CPE"),
        1e-1,
        1e7,
        equivalents=("p(R1-C1,R2,C2)", "p(p(R1,C1)-C2,R2)", "p(p(R1,C1)-R2,C2)"),
        skeleton="p(R1,C1)",
        wrong_skeleton="p(R1,CPE1)-p(R2,C1)",
    ),
    Reference(
        "Randles (with Warburg)",
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 200.0, "W1.A": 50.0},
        ("R", "C", "CPE", "W"),
        1e-2,
        1e5,
        skeleton="R1-p(C1,R2)",
        wrong_skeleton="R1-p(CPE1,R2)",
    ),
]


@dataclass(frozen=True)
class Verdict:
    """What became of the true topology in one run.

    Gate G1 as written asks only for ``reported``: the truth, or an exact equivalent of it,
    present in the reported equivalence classes. ``on_front`` and ``recommended`` are stricter
    and are tracked separately because they are not the same question. A capacitor whose ESR
    is barely resolvable at 1% noise can legitimately be *recommended* as a three-element
    model even though the four-element truth is right there on the front beside it -- that is
    the parsimony rule working, not the search failing.
    """

    reported: bool
    on_front: bool
    is_recommendation: bool
    recommendation: str


def _truth_verdict(result: DiscoveryResult, reference: Reference) -> Verdict:
    truth = next(
        (c for c in result.candidates if c.circuit.canonical_form() == reference.canonical),
        None,
    )
    recommended = result.recommended
    name = "-" if recommended is None else recommended.circuit.to_string()
    if truth is None:
        return Verdict(False, False, False, name)
    equivalents = result.equivalents_of(truth)
    on_front = any(c is truth or c in equivalents for c in result.pareto)
    is_recommendation = recommended is not None and (
        truth is recommended or recommended in equivalents
    )
    return Verdict(True, on_front, is_recommendation, name)


def report_gate(seeds: int, limit: int, workers: int) -> None:
    print("=" * 92)
    print("G1: does exhaustive mode report the true topology (or an exact equivalent)?")
    print("=" * 92)
    for reference in REFERENCES:
        print(f"\n{reference.label}: {reference.circuit}   pool {','.join(reference.pool)}")
        passes = on_front = recommended_count = 0
        elapsed_total = 0.0
        for seed in range(seeds):
            data = reference.spectrum(seed)
            started = time.perf_counter()
            result = discover(
                data,
                pool=reference.pool,
                mode="exhaustive",
                exhaustive_limit=limit,
                workers=workers,
                seed=seed,
            )
            elapsed = time.perf_counter() - started
            elapsed_total += elapsed
            verdict = _truth_verdict(result, reference)
            passes += int(verdict.reported)
            on_front += int(verdict.on_front)
            recommended_count += int(verdict.is_recommendation)
            print(
                f"  seed {seed}: {'PASS' if verdict.reported else 'FAIL'}"
                f"  reported={verdict.reported} on-front={verdict.on_front}"
                f" recommended={verdict.is_recommendation}"
                f"  complete<={result.complete_up_to}"
                f"  screened={result.n_evaluated:,}  {elapsed / 60:.1f} min"
                f"  -> {verdict.recommendation}",
                flush=True,
            )
        print(
            f"  ==> G1 (truth reported): {passes}/{seeds};"
            f" on the Pareto front: {on_front}/{seeds};"
            f" it is the recommendation: {recommended_count}/{seeds};"
            f" mean {elapsed_total / max(seeds, 1) / 60:.1f} min"
        )


def report_skeleton(seeds: int, limit: int, workers: int, compare: bool) -> None:
    """Gate P1: assert the true skeleton and check the truth survives the constraint.

    The failure this is watching for is not "the search got slower answers". It is that a
    skeleton *removes* topologies from the space, so an asserted skeleton that the truth does
    contain must leave the truth reachable -- and if the enumeration or the growth had a hole
    in it, the report would still come back looking healthy, ranked front and all, exactly the
    shape of every trap this project has already measured.
    """
    print("=" * 92)
    print("P1: with the TRUE skeleton asserted, is the truth still reported?")
    print("=" * 92)
    for reference in REFERENCES:
        if not reference.skeleton:
            continue
        # A skeleton the truth does not contain would make the gate vacuous, so the fixture is
        # checked against the same predicate that defines the space.
        if not contains_skeleton(
            Circuit.parse(reference.circuit).root, Circuit.parse(reference.skeleton).root
        ):
            raise SystemExit(
                f"error: {reference.label}: {reference.circuit} does not contain the skeleton"
                f" {reference.skeleton}; the fixture, not the search, is wrong"
            )
        print(
            f"\n{reference.label}: {reference.circuit}   pool {','.join(reference.pool)}"
            f"\n  skeleton {reference.skeleton}"
        )
        passes = on_front = 0
        constrained_s = free_s = 0.0
        constrained_n = free_n = 0
        for seed in range(seeds):
            data = reference.spectrum(seed)
            started = time.perf_counter()
            result = discover(
                data,
                pool=reference.pool,
                skeleton=reference.skeleton,
                mode="exhaustive",
                exhaustive_limit=limit,
                workers=workers,
                seed=seed,
            )
            elapsed = time.perf_counter() - started
            constrained_s += elapsed
            constrained_n += result.n_evaluated
            verdict = _truth_verdict(result, reference)
            passes += int(verdict.reported)
            on_front += int(verdict.on_front)
            line = (
                f"  seed {seed}: {'PASS' if verdict.reported else 'FAIL'}"
                f"  on-front={verdict.on_front} recommended={verdict.is_recommendation}"
                f"  complete<={result.complete_up_to}"
                f"  screened={result.n_evaluated:,}  {elapsed / 60:.1f} min"
                f"  -> {verdict.recommendation}"
            )
            if compare:
                started = time.perf_counter()
                free = discover(
                    data,
                    pool=reference.pool,
                    mode="exhaustive",
                    exhaustive_limit=limit,
                    workers=workers,
                    seed=seed,
                )
                free_s += time.perf_counter() - started
                free_n += free.n_evaluated
                line += f"  (unconstrained {free.n_evaluated:,} in {free_s / 60:.1f} min)"
            print(line, flush=True)
        summary = (
            f"  ==> P1 (truth reported): {passes}/{seeds};"
            f" on the Pareto front: {on_front}/{seeds};"
            f" mean {constrained_s / max(seeds, 1) / 60:.1f} min"
            f" over {constrained_n // max(seeds, 1):,} candidates"
        )
        if compare and constrained_s > 0.0 and constrained_n > 0:
            summary += (
                f"; {free_n / constrained_n:.1f}x fewer candidates and"
                f" {free_s / constrained_s:.1f}x faster than unconstrained"
            )
        print(summary)
    print(
        "\nRecovery is the gate. The speed-up is an observation: tuning towards it is how the\n"
        "screening budget nearly lost the Maxwell-Wagner truth (docs/HANDOFF.md section 3)."
    )


def _structure_z(result: DiscoveryResult) -> float:
    """Runs-test z on the best-fitting candidate's residuals; below the limit means structure.

    The same statistic ``mode="auto"`` uses to decide whether to keep searching, computed here
    on its own so the number can be looked at rather than only acted on. Real and imaginary
    residuals are separate halves of the vector, so each is tested and the worse one reported.
    """
    if not result.candidates:
        return math.nan
    best = min(result.candidates, key=lambda c: c.result.chi2_reduced)
    residuals = best.result.residuals
    if residuals.size < 4:
        return math.nan
    half = residuals.size // 2
    return min(_runs_z(residuals[:half]), _runs_z(residuals[half:]))


def report_wrong_skeleton(seeds: int, limit: int, workers: int) -> None:
    """Gate P2: what does the report look like when the asserted skeleton is wrong?

    This is the measurement section 3.2 of docs/PARTIAL_TOPOLOGY_PLAN.md refuses to guess at,
    for a reason with three precedents in this project: every trap here so far has been a
    report that stayed healthy-looking while the answer was gone. So the questions are asked
    as numbers, not as a verdict --

    * does the constrained fit leave residuals the runs test can see as structure?
    * does the recommendation come with unresolved parameters, or does it look clean?
    * how far is the constrained chi2 from what the truth itself achieves on the same data?

    -- and the wording of gate P2 is written afterwards, from what comes out. Note the truth's
    own chi2 is the right reference, not the unconstrained search's: it is what the data can be
    fitted to at all, and it costs one fit instead of a second whole search.
    """
    print("=" * 92)
    print("P2: what does a WRONG skeleton look like in the report?")
    print("=" * 92)
    for reference in REFERENCES:
        if not reference.wrong_skeleton:
            continue
        if contains_skeleton(
            Circuit.parse(reference.circuit).root,
            Circuit.parse(reference.wrong_skeleton).root,
        ):
            raise SystemExit(
                f"error: {reference.label}: {reference.circuit} does contain"
                f" {reference.wrong_skeleton}, so it is not a wrong skeleton at all"
            )
        print(
            f"\n{reference.label}: truth {reference.circuit}   pool {','.join(reference.pool)}"
            f"\n  wrong skeleton {reference.wrong_skeleton}"
        )
        structure = unresolved = all_unresolved = 0
        ratios: list[float] = []
        for seed in range(seeds):
            data = reference.spectrum(seed)
            truth_fit = fit(Circuit.parse(reference.circuit), data, weighting="modulus", seed=seed)
            result = discover(
                data,
                pool=reference.pool,
                skeleton=reference.wrong_skeleton,
                mode="exhaustive",
                exhaustive_limit=limit,
                workers=workers,
                seed=seed,
            )
            if not result.candidates:
                print(f"  seed {seed}: no candidate could be fitted at all", flush=True)
                continue
            best_chi2 = min(c.result.chi2_reduced for c in result.candidates)
            ratio = best_chi2 / truth_fit.chi2_reduced if truth_fit.chi2_reduced > 0 else math.inf
            ratios.append(ratio)
            z = _structure_z(result)
            has_structure = z < RUNS_Z_LIMIT
            structure += int(has_structure)
            recommended = result.recommended
            n_bad = 0 if recommended is None else recommended.n_unresolved
            unresolved += int(n_bad > 0)
            all_unresolved += int(result.unresolved_everywhere)
            name = "-" if recommended is None else recommended.circuit.to_string()
            print(
                f"  seed {seed}: chi2 {best_chi2:.3g} vs {truth_fit.chi2_reduced:.3g} for the"
                f" truth ({ratio:.1f}x)  runs z={z:+.1f}"
                f" (structure: {'yes' if has_structure else 'NO'})"
                f"  -> {name} with {n_bad} unresolved"
                f"{', nothing identifiable' if result.unresolved_everywhere else ''}",
                flush=True,
            )
        if ratios:
            ordered = sorted(ratios)
            median = ordered[len(ordered) // 2]
            print(
                f"  ==> residual structure seen {structure}/{len(ratios)};"
                f" recommendation carried unresolved parameters {unresolved}/{len(ratios)};"
                f" nothing identifiable at all {all_unresolved}/{len(ratios)};"
                f" chi2 ratio median {median:.1f}x (min {ordered[0]:.1f}x,"
                f" max {ordered[-1]:.1f}x)"
            )
    print(
        "\nP2 passes only if a wrong skeleton is visible in the report *without* knowing the\n"
        "truth. A large chi2 ratio is not by itself enough -- the reader does not have the\n"
        "truth's chi2 to compare against -- so the runs test and the unresolved counts are the\n"
        "signals that have to carry it."
    )


def report_excluded(seeds: int, limit: int, workers: int) -> None:
    """What a *true* skeleton removed that would have fitted identically, and what it costs.

    Section 3.3 of docs/PARTIAL_TOPOLOGY_PLAN.md, whose first draft called this cheap. It is
    not: the excluded topologies are by definition the ones the search never fitted, so each
    needs a screen of its own. This measures both halves of the decision -- the cost, which
    made it opt-in, and the yield, which is what makes it worth having at all.
    """
    print("=" * 92)
    print("Section 3.3: which indistinguishable topologies did the skeleton exclude?")
    print("=" * 92)
    for reference in REFERENCES:
        if not reference.skeleton:
            continue
        print(
            f"\n{reference.label}: truth {reference.circuit}"
            f"\n  skeleton {reference.skeleton}"
        )
        for seed in range(seeds):
            data = reference.spectrum(seed)
            result = discover(
                data,
                pool=reference.pool,
                skeleton=reference.skeleton,
                mode="exhaustive",
                exhaustive_limit=limit,
                workers=workers,
                seed=seed,
            )
            recommended = result.recommended
            if recommended is None or result.skeleton is None:
                print(f"  seed {seed}: nothing was fitted", flush=True)
                continue
            report = excluded_equivalents(
                recommended,
                result.skeleton,
                data,
                pool=reference.pool,
                seed=seed,
                workers=workers,
            )
            names = ", ".join(report.equivalents) if report.equivalents else "-"
            print(
                f"  seed {seed}: {recommended.circuit.to_string()}"
                f"  {report.excluded} excluded of {report.kept + report.excluded}"
                f" at {report.size} elements, screened in {report.elapsed_s:.0f} s"
                f"  -> {len(report.equivalents)} exact: {names}",
                flush=True,
            )
    print(
        "\nThe list is what the tier-1 screen found: a budget that misses an exact equivalent\n"
        "makes this a floor, never a proof that nothing else was excluded."
    )


def report_filter() -> None:
    print("=" * 92)
    print("Feasibility filter: how much is removed, and does the truth survive?")
    print("=" * 92)
    print(f"{'reference':<40}{'n<=5':>10}{'kept':>10}{'reduction':>12}{'truth kept':>12}")
    for reference in REFERENCES:
        for noise in (0.0, reference.noise):
            data = reference.spectrum(0, noise=noise)
            behaviour = EndpointBehaviour.from_spectrum(data)
            total = kept = 0
            for n in range(1, 6):
                level = list(enumerate_topologies(reference.pool, n))
                total += len(level)
                kept += sum(1 for node in level if is_feasible(node, behaviour))
            survives = is_feasible(Circuit.parse(reference.circuit).root, behaviour)
            label = f"{reference.label} @ {noise:.0%}"
            print(
                f"{label:<40}{total:>10,}{kept:>10,}"
                f"{total / max(kept, 1):>11.2f}x{str(survives):>12}"
            )


def report_screen(sample: int) -> None:
    print("=" * 92)
    print("Tier-1 screening budget: cost per topology, and does the truth stay in the ranking?")
    print("=" * 92)
    reference = REFERENCES[0]
    data = reference.spectrum(0)
    behaviour = EndpointBehaviour.from_spectrum(data)
    nodes = [
        node
        for n in range(1, reference.n_elements + 1)
        for node in enumerate_topologies(reference.pool, n)
        if is_feasible(node, behaviour)
    ]
    step = max(len(nodes) // sample, 1)
    circuits = [Circuit(node) for node in itertools.islice(nodes, 0, len(nodes), step)]
    truth = Circuit.parse(reference.circuit)
    if all(c.canonical_form() != truth.canonical_form() for c in circuits):
        circuits.append(truth)

    print(f"{'popsize':>9}{'maxiter':>9}{'ms/topology':>14}{'truth rank':>12}  of sample")
    for popsize, maxiter in ((4, 20), (8, 40), (12, 60), (20, 100)):
        started = time.perf_counter()
        scored: list[tuple[float, str]] = []
        for circuit in circuits:
            try:
                cost = screen(circuit, data, seed=0, popsize=popsize, maxiter=maxiter)
            except Exception:  # noqa: BLE001 - an unfittable candidate is simply hopeless
                cost = float("inf")
            scored.append((cost, circuit.canonical_form()))
        elapsed = time.perf_counter() - started
        scored.sort()
        rank = next(
            i for i, (_, key) in enumerate(scored, start=1) if key == truth.canonical_form()
        )
        print(
            f"{popsize:>9}{maxiter:>9}{elapsed / len(circuits) * 1000:>14.1f}"
            f"{rank:>12}  of {len(circuits)}",
            flush=True,
        )


DEFAULT_BUDGETS = (
    ScreenBudget(8, 40),  # current default
    ScreenBudget(8, 20),
    ScreenBudget(4, 40),
    ScreenBudget(4, 20),
)


@dataclass(frozen=True)
class RankRow:
    """Where one tracked circuit landed in the screen it has to survive."""

    text: str
    size: int
    rank: int  #: position within its own element count, ranked by screening AICc
    of: int  #: how many candidates that element count held
    quota: int  #: how many of them ``_shortlist`` takes before the near-tie rule
    cost_ratio: float  #: its screening cost over the best cost at its size
    shortlisted: bool  #: what ``_shortlist`` actually did -- the only hard verdict here

    @property
    def margin(self) -> float:
        """Rank as a fraction of the quota. Below 1 is inside; well below 1 is safe."""
        return self.rank / self.quota


def _feasible_texts(reference: Reference, data: Spectrum, limit: int) -> list[str]:
    """The candidate list the exhaustive stage would build for this spectrum."""
    behaviour = EndpointBehaviour.from_spectrum(data)
    return [
        Circuit(node).to_string()
        for n in range(1, limit + 1)
        for node in enumerate_topologies(reference.pool, n)
        if is_feasible(node, behaviour)
    ]


def _rank_rows(
    scored: list[tuple[float, str]], tracked: dict[str, str], n_data: int, n_refine: int
) -> list[RankRow]:
    """Rank every screened candidate the way :func:`_shortlist` does, then find the tracked ones.

    Ranking is per element count and by screening AICc, because that is what the shortlist
    does; a global rank by raw cost -- what the ``screen`` mode reports -- answers a question
    the pipeline never asks.
    """
    by_size: dict[int, list[tuple[float, float, str]]] = {}
    for cost, text in scored:
        if not math.isfinite(cost):
            continue
        circuit = Circuit.parse(text)
        aicc = _screening_aicc(cost, circuit.n_params, n_data)
        by_size.setdefault(len(circuit.leaves), []).append((aicc, cost, text))
    for group in by_size.values():
        group.sort()

    quota = max(MIN_REFINE_PER_SIZE, n_refine // max(len(by_size), 1))
    chosen = {Circuit.parse(text).canonical_form() for text in _shortlist(scored, n_refine, n_data)}

    rows: list[RankRow] = []
    for canonical, label in tracked.items():
        for size, group in by_size.items():
            position = next(
                (
                    i
                    for i, (_, _, text) in enumerate(group, start=1)
                    if Circuit.parse(text).canonical_form() == canonical
                ),
                None,
            )
            if position is None:
                continue
            best_cost = min(cost for _, cost, _ in group)
            cost = group[position - 1][1]
            rows.append(
                RankRow(
                    label,
                    size,
                    position,
                    len(group),
                    quota,
                    cost / best_cost if best_cost > 0.0 else math.inf,
                    canonical in chosen,
                )
            )
            break
        else:
            # Screened but unfittable at every budget, or removed by the feasibility filter --
            # either way it never reached the ranking, which is a failure of this budget.
            rows.append(RankRow(label, 0, 0, 0, 1, math.inf, False))
    return rows


def report_screen_rank(
    seeds: int, limit: int, workers: int, budgets: Sequence[ScreenBudget]
) -> None:
    print("=" * 108)
    print("Tier-1 budget vs. the tier-2 shortlist: does the truth still make its per-size quota?")
    print("=" * 108)
    print(
        "rank/of = position within the same element count by screening AICc; quota = how many\n"
        "_shortlist takes per size before the near-tie rule; margin = rank/quota (< 1 is in).\n"
        "'kept' is the verdict that counts: _shortlist actually selected it.\n"
    )
    n_refine = REFINE_DEFAULT["exhaustive"]
    # budget -> (worst margin seen anywhere, tracked circuits kept, tracked circuits tested)
    overall: dict[ScreenBudget, list[float]] = {b: [0.0, 0.0, 0.0] for b in budgets}
    seconds: dict[ScreenBudget, float] = dict.fromkeys(budgets, 0.0)

    for reference in REFERENCES:
        print("-" * 108)
        print(f"{reference.label}: {reference.circuit}   pool {','.join(reference.pool)}")
        tracked = {
            Circuit.parse(text).canonical_form(): text
            for text in (reference.circuit, *reference.equivalents)
        }
        for seed in range(seeds):
            data = reference.spectrum(seed)
            texts = _feasible_texts(reference, data, limit)
            print(f"  seed {seed}: {len(texts):,} feasible candidates", flush=True)
            with _worker_pool(workers, data, "modulus") as executor:
                for budget in budgets:
                    started = time.perf_counter()
                    scored = _screen_all(
                        texts,
                        data,
                        weighting="modulus",
                        seed=seed,
                        executor=executor,
                        on_progress=None,
                        time_limit=None,
                        started=started,
                        budget=budget,
                    )
                    elapsed = time.perf_counter() - started
                    seconds[budget] += elapsed
                    rows = _rank_rows(scored, tracked, 2 * data.n, n_refine)
                    for row in rows:
                        overall[budget][1] += float(row.shortlisted)
                        overall[budget][2] += 1.0
                        overall[budget][0] = max(overall[budget][0], row.margin)
                        print(
                            f"    {budget.popsize:>2}x{budget.maxiter:<3}"
                            f" {elapsed / 60:>5.1f} min  {row.text:<26}"
                            f" n={row.size}  {row.rank:>4}/{row.of:<5}"
                            f" quota {row.quota:>2}  margin {row.margin:>5.2f}"
                            f"  cost/best {row.cost_ratio:>8.2f}"
                            f"  kept {'yes' if row.shortlisted else 'NO'}",
                            flush=True,
                        )

    print("-" * 108)
    print("summary (all references, all seeds, all tracked circuits):")
    print(f"{'budget':>10}{'total screen':>15}{'vs 8x40':>10}{'worst margin':>15}{'kept':>10}")
    baseline = seconds.get(budgets[0], 0.0)
    for budget in budgets:
        worst, kept, total = overall[budget]
        print(
            f"{f'{budget.popsize}x{budget.maxiter}':>10}{seconds[budget] / 60:>13.1f} m"
            f"{seconds[budget] / baseline if baseline else float('nan'):>9.2f}x"
            f"{worst:>15.2f}{f'{int(kept)}/{int(total)}':>10}"
        )
    print(
        "\nA budget is safe to adopt only if every tracked circuit is kept and the worst margin\n"
        "stays clear of 1 -- a margin at 0.9 means the next seed can push it out."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "what",
        choices=[
            "gate", "skeleton", "wrong-skeleton", "excluded", "filter", "screen", "screen-rank"
        ],
    )
    parser.add_argument(
        "--seeds", type=int, default=10,
        help="seeds per reference (gate, skeleton, screen-rank)",
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="exhaustive element limit (gate, skeleton, screen-rank)",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="screening processes (gate, skeleton, screen-rank)",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="skeleton: also run each reference unconstrained, to record the speed-up",
    )
    parser.add_argument("--sample", type=int, default=60, help="topologies sampled (screen)")
    parser.add_argument(
        "--only",
        help="run just the reference spectra whose label contains one of these comma-separated"
        " strings, e.g. 'Maxwell,Randles'. These runs are long enough that resuming one after"
        " an interruption beats repeating it.",
    )
    parser.add_argument(
        "--budgets",
        default=",".join(f"{b.popsize}x{b.maxiter}" for b in DEFAULT_BUDGETS),
        help="screen-rank budget grid as popsize x maxiter, e.g. 8x40,4x20. The first entry is"
        " the baseline the others are timed against.",
    )
    args = parser.parse_args()

    if args.only:
        wanted = [text.strip().lower() for text in args.only.split(",") if text.strip()]
        selected = [r for r in REFERENCES if any(w in r.label.lower() for w in wanted)]
        if not selected:
            raise SystemExit(f"error: --only {args.only!r} matched no reference spectrum")
        REFERENCES[:] = selected

    if args.what == "gate":
        report_gate(args.seeds, args.limit, args.workers)
    elif args.what == "skeleton":
        report_skeleton(args.seeds, args.limit, args.workers, args.compare)
    elif args.what == "wrong-skeleton":
        report_wrong_skeleton(args.seeds, args.limit, args.workers)
    elif args.what == "excluded":
        report_excluded(args.seeds, args.limit, args.workers)
    elif args.what == "filter":
        report_filter()
    elif args.what == "screen":
        report_screen(args.sample)
    else:
        budgets = [
            ScreenBudget(*(int(part) for part in text.split("x")))
            for text in args.budgets.split(",")
        ]
        report_screen_rank(args.seeds, args.limit, args.workers, budgets)


if __name__ == "__main__":
    main()
