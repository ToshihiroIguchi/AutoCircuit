"""Exhaustive-mode discovery: the contract that makes it worth having.

The genetic search can only ever say "this is what I found". Exhaustive mode is supposed to
say something much stronger -- "this is everything there is, up to N elements" -- so these
tests are mostly about that claim being *true* and being reported honestly: every enumerated
topology really is screened, the completeness figure matches what was actually covered, and
it drops to a smaller number (never a false one) when a budget cuts the run short.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import (
    ABANDON_FACTOR,
    MIN_REFINE_PER_SIZE,
    REFINE_CEILING_FACTOR,
    SCREEN_BUDGET,
    SCREENING_FALLBACK,
    DiscoveryResult,
    Enumeration,
    ScreenTask,
    _screen_all,
    _screen_one,
    _screening_score,
    _shortlist,
    discover,
    enumerate_candidates,
    screen_plan,
)
from autocircuit.core.enumerate import (
    DEFAULT_DEGENERACY_BUDGET,
    count_topologies,
    enumerate_topologies,
)
from autocircuit.core.simulate import log_frequencies, simulate

SEMICIRCLE = {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8}


def _semicircle(noise: float = 0.005, seed: int = 0, points: int = 6):
    return simulate(
        "R1-p(R2,C1)", log_frequencies(1e0, 1e6, points), SEMICIRCLE, noise=noise, seed=seed
    )


def test_exhaustive_mode_screens_every_enumerated_topology() -> None:
    """With the feasibility filter off, the count evaluated is the enumeration count."""
    result = discover(
        _semicircle(),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        feasibility_filter=False,
        seed=0,
    )
    expected = sum(count_topologies(("R", "C"), n) for n in range(1, 4))
    assert result.n_evaluated == expected
    assert result.complete_up_to == 3
    assert result.mode == "exhaustive"


def test_feasibility_filter_reduces_the_work_without_losing_the_truth() -> None:
    data = _semicircle(noise=0.0, points=10)
    filtered = discover(
        data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=3, seed=0
    )
    unfiltered = discover(
        data,
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        feasibility_filter=False,
        seed=0,
    )
    assert filtered.n_evaluated <= unfiltered.n_evaluated
    # Whatever it removed, the true topology is still reported.
    truth = Circuit.parse("R1-p(R2,C1)").canonical_form()
    assert truth in {c.circuit.canonical_form() for c in filtered.candidates}


def test_exhaustive_mode_reports_the_true_topology_and_its_equivalent() -> None:
    """The in-suite version of gate G1, kept small enough to run in seconds.

    ``R1-p(R2,C1)`` and ``p(R1-C1,R2)`` are exact reparameterisations of each other, so the
    honest outcome is both of them in one equivalence class -- not a choice between them.
    """
    result = discover(
        _semicircle(noise=0.0, points=10),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        seed=0,
    )
    forms = {c.circuit.canonical_form(): c for c in result.candidates}
    truth = forms[Circuit.parse("R1-p(R2,C1)").canonical_form()]
    twin = forms[Circuit.parse("p(R1-C1,R2)").canonical_form()]
    np.testing.assert_allclose(truth.result.z_model, twin.result.z_model, rtol=1e-6)
    assert twin in result.equivalents_of(truth)
    assert result.recommended is not None
    assert result.recommended.circuit.n_params == 3


def test_completeness_is_lowered_rather_than_faked_when_the_budget_bites() -> None:
    """A candidate ceiling must cut the claim, not the honesty of the claim."""
    result = discover(
        _semicircle(),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=5,
        max_candidates=5,
        feasibility_filter=False,
        seed=0,
    )
    assert result.complete_up_to is not None
    assert result.complete_up_to < 5
    covered = sum(count_topologies(("R", "C"), n) for n in range(1, result.complete_up_to + 1))
    assert result.n_evaluated == covered
    assert str(result.complete_up_to) in result.completeness()


def test_a_search_that_evaluated_nothing_says_so_instead_of_claiming_coverage() -> None:
    """An empty report has two causes, and the coverage line has to tell them apart.

    A pool that cannot build anything structurally consistent with the data evaluates nothing,
    and "every plausible topology up to N elements was evaluated" is then true of an empty set
    -- which reads as an assurance. Here R and C alone meet a spectrum that is inductive above
    its resonance, and the feasibility screen rejects every candidate.
    """
    inductive = simulate(
        "C1-R1-L1",
        log_frequencies(1e2, 1e9, 10),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.01,
        seed=0,
    )
    result = discover(
        inductive, pool=("R", "C"), mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert result.n_evaluated == 0
    assert result.candidates == []
    assert "no topology was evaluated at all" in result.completeness()
    assert "every plausible topology" not in result.completeness()


def test_a_second_stage_that_was_stopped_says_the_front_is_partial() -> None:
    """A complete screen does not make a half-refitted shortlist look like a finished report."""
    finished = DiscoveryResult(
        candidates=[], pareto=[], n_evaluated=41, generations=0, elapsed_s=1.0,
        pool=("R", "C"), mode="exhaustive", complete_up_to=3,
    )
    stopped = replace(finished, refit_progress=(8, 37))

    assert "partial" not in finished.completeness()
    sentence = stopped.completeness()
    # The screen's claim survives -- it is about the screen -- and the qualification lands on
    # the same line rather than in a footnote a reader can skim past.
    assert "up to 3 elements" in sentence
    assert "8 of the 37 shortlisted" in sentence
    assert "partial" in sentence


def test_evolve_mode_never_claims_completeness() -> None:
    result = discover(
        _semicircle(),
        pool=("R", "C"),
        mode="evolve",
        generations=3,
        population=8,
        max_elements=3,
        search_maxiter=20,
        n_refine=2,
        final_restarts=1,
        seed=0,
    )
    assert result.mode == "evolve"
    assert result.complete_up_to is None
    assert "sampled, not exhaustive" in result.completeness()


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown discovery mode"):
        discover(_semicircle(), pool=("R", "C"), mode="sideways")  # type: ignore[arg-type]


def test_progress_callback_counts_up_to_the_total() -> None:
    calls: list[tuple[int, int, str | None]] = []
    result = discover(
        _semicircle(),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        seed=0,
        on_progress=lambda done, total, best: calls.append((done, total, best)),
    )
    assert calls, "the progress callback was never invoked"
    assert [done for done, _, _ in calls] == sorted(done for done, _, _ in calls)
    assert calls[-1][0] == calls[-1][1] == result.n_evaluated
    assert calls[-1][2] is not None


def test_exhaustive_mode_is_reproducible() -> None:
    data = _semicircle()
    first = discover(data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=3, seed=1)
    second = discover(data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=3, seed=1)
    assert [c.circuit.canonical_form() for c in first.pareto] == [
        c.circuit.canonical_form() for c in second.pareto
    ]


def test_worker_processes_do_not_change_the_answer() -> None:
    """The parallel screen is an optimisation; it must not be a different search."""
    data = _semicircle()
    serial = discover(
        data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=3, workers=1, seed=0
    )
    parallel = discover(
        data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=3, workers=2, seed=0
    )
    assert serial.n_evaluated == parallel.n_evaluated
    assert sorted(c.circuit.canonical_form() for c in serial.candidates) == sorted(
        c.circuit.canonical_form() for c in parallel.candidates
    )


def test_auto_mode_covers_what_it_can_and_says_so() -> None:
    result = discover(
        _semicircle(),
        pool=("R", "C"),
        mode="auto",
        exhaustive_limit=3,
        max_elements=3,
        generations=2,
        population=6,
        search_maxiter=20,
        seed=0,
    )
    assert result.mode == "auto"
    assert result.complete_up_to == 3
    assert "up to 3 elements" in result.completeness()


def _forms(pool: tuple[str, ...], n: int) -> list[str]:
    return [Circuit(node).to_string() for node in enumerate_topologies(pool, n)]


def test_shortlist_gives_every_element_count_its_own_quota() -> None:
    """The bug this locks down cost gate G1 an entire benchmark run.

    Raw residual cost always improves with parameters, so ranking the whole screen by it hands
    the shortlist to the biggest circuits: on the capacitor reference all 60 shortlisted
    candidates had five elements and the four-element circuit that generated the data was
    never refitted at all. Small test spaces hide this completely, because there the shortlist
    covers every size anyway -- hence this deliberately lopsided synthetic screen.
    """
    small = _forms(("R", "C"), 2)
    large = _forms(("R", "C"), 5)
    assert len(large) > 30, "fixture assumes the large size dominates by count"
    scored = [(1e-6, text) for text in large] + [(1e-3, text) for text in small]

    keep = set(_shortlist(scored, n_refine=10, n_data=140))
    assert keep & set(small), "every two-element candidate was crowded out by the big circuits"
    assert keep & set(large)


def test_shortlist_stays_bounded_when_everything_is_a_near_tie() -> None:
    """The near-tie rule must not be able to nominate the whole space for a full refit."""
    texts = _forms(("R", "C"), 5)
    scored = [(1e-6, text) for text in texts]
    keep = _shortlist(scored, n_refine=10, n_data=140)
    assert len(keep) < len(texts)
    assert len(keep) <= max(MIN_REFINE_PER_SIZE, 10) * REFINE_CEILING_FACTOR


def test_screening_score_charges_for_parameters() -> None:
    """Two circuits that fit equally well are not equally good; the bigger one is worse."""
    for name in ("aic", "aicc", "bic", "caic", "hqc"):
        assert _screening_score(1e-3, 5, 140, name) < _screening_score(1e-3, 8, 140, name)
        # ...and a genuinely better fit still wins despite costing more parameters.
        assert _screening_score(1e-6, 8, 140, name) < _screening_score(1e-3, 5, 140, name)
        # Degenerate inputs are ranked last rather than raising.
        assert _screening_score(0.0, 5, 140, name) == float("inf")
        assert _screening_score(1e-3, 200, 140, name) == float("inf")


def test_screening_falls_back_where_a_cost_is_not_enough() -> None:
    """WAIC needs a Jacobian and an F-test needs two models; tier 1 has neither.

    The screen decides who is refitted, not who wins, so falling back is a cost in shortlist
    ordering and never in a reported number -- but it has to be the *stated* fallback rather
    than whatever the attribute lookup happens to return.
    """
    for name in ("waic", "ftest"):
        assert _screening_score(1e-3, 5, 140, name) == _screening_score(
            1e-3, 5, 140, SCREENING_FALLBACK
        )


def test_seed_circuits_are_evaluated_in_exhaustive_mode() -> None:
    """A user-supplied circuit outside the enumerated size range still gets fitted."""
    result = discover(
        _semicircle(noise=0.0, points=10),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=2,
        seed=0,
        seeds=("R1-p(R2,C1)",),
    )
    target = Circuit.parse("R1-p(R2,C1)").canonical_form()
    assert target in {c.circuit.canonical_form() for c in result.candidates}
    # ...without inflating the completeness claim, which only covers the enumerated sizes.
    assert result.complete_up_to == 2


# =============================================================================================
# screen_plan -- the tier-1 stage with its transport removed
# =============================================================================================
#
# This is the seam the web UI screens through (docs/WEB_UI_PLAN.md): the browser cannot use
# multiprocessing, so JavaScript fans batches across Web Workers -- but the decisions between
# batches, which are the ones gate G1 depends on, must stay in exactly one place. These tests
# pin that contract down, because a second implementation of it in another language is a second
# thing that can be wrong.


def _drive(plan, cost_of):
    """Run a screen plan to completion with a caller-supplied cost function."""
    seen = []
    try:
        tasks = next(plan)
        while True:
            seen.append(list(tasks))
            tasks = plan.send([cost_of(task.text) for task in tasks])
    except StopIteration as done:
        return done.value, seen


def test_screen_plan_yields_every_text_exactly_once() -> None:
    texts = [f"R{i}" for i in range(1, 10)]
    scored, batches = _drive(screen_plan(texts, chunk=4), lambda text: 1.0)
    assert [text for _, text in scored] == texts
    assert [len(batch) for batch in batches] == [4, 4, 1]


def test_screen_plan_chunk_size_does_not_change_what_is_scored() -> None:
    texts = [f"R{i}" for i in range(1, 20)]
    costs = {text: float(i) for i, text in enumerate(texts)}
    one, _ = _drive(screen_plan(texts, chunk=1), costs.__getitem__)
    many, _ = _drive(screen_plan(texts, chunk=7), costs.__getitem__)
    assert one == many


def test_screen_plan_tightens_the_abandon_threshold_as_costs_arrive() -> None:
    """Within a complexity class, a cheap result makes the next batch's threshold stricter."""
    texts = ["R1-C1", "R2-C2", "R3-C3", "R4-C4"]
    costs = {"R1-C1": 10.0, "R2-C2": 1.0, "R3-C3": 5.0, "R4-C4": 5.0}
    _, batches = _drive(screen_plan(texts, chunk=1), costs.__getitem__)
    thresholds = [batch[0].abandon_above for batch in batches]
    # Nothing to compare the first candidate against, then 10x100, then 1x100 and no looser.
    assert thresholds[0] == math.inf
    assert thresholds[1] == pytest.approx(10.0 * ABANDON_FACTOR)
    assert thresholds[2] == pytest.approx(1.0 * ABANDON_FACTOR)
    assert thresholds[3] == pytest.approx(1.0 * ABANDON_FACTOR)


def test_screen_plan_never_abandons_against_an_exact_reference() -> None:
    """The rule that keeps exact equivalents alive on noise-free data (see PERFECT_COST)."""
    texts = ["R1-C1", "R2-C2"]
    _, batches = _drive(screen_plan(texts, chunk=1), lambda text: 1e-30)
    assert all(batch[0].abandon_above == math.inf for batch in batches)


def test_screen_plan_matches_the_in_process_screen() -> None:
    """Driving the plan by hand reproduces what discover's own sequential driver produces."""
    spectrum = _semicircle(noise=0.0, points=8)
    texts = [
        Circuit(node).to_string()
        for n in (1, 2, 3)
        for node in enumerate_topologies(("R", "C"), n)
    ]

    def cost_of(text: str) -> float:
        return _screen_one(
            ScreenTask(text, math.inf), spectrum, weighting="modulus", seed=0,
            budget=SCREEN_BUDGET,
        )

    driven, _ = _drive(screen_plan(texts, chunk=1), cost_of)
    reference = _screen_all(
        texts, spectrum, weighting="modulus", seed=0, executor=None,
        on_progress=None, time_limit=None, started=0.0,
    )
    assert [text for _, text in driven] == [text for _, text in reference]


# -- The enumeration, and the coverage claim that comes out of it -----------------------------
#
# These stand between discover() and any other driver of the two tiers -- the browser is one --
# because the completeness claim is derived here and nowhere else.


def _enumeration(**kwargs: object) -> Enumeration:
    defaults: dict[str, object] = dict(
        pool=("R", "C"),
        skeleton=None,
        limit=3,
        floor=1,
        max_candidates=20_000,
        feasibility_filter=False,
        feasibility_budget=DEFAULT_DEGENERACY_BUDGET,
    )
    defaults.update(kwargs)
    return enumerate_candidates(_semicircle(), **defaults)  # type: ignore[arg-type]


def test_enumeration_holds_every_topology_in_size_order() -> None:
    plan = _enumeration()
    assert len(plan.texts) == sum(count_topologies(("R", "C"), n) for n in range(1, 4))
    sizes = [len(Circuit.parse(text).leaves) for text in plan.texts]
    assert sizes == sorted(sizes)
    assert [n for n, _ in plan.boundaries] == [1, 2, 3]
    assert plan.boundaries[-1][1] == len(plan.texts)


def test_coverage_counts_whole_levels_only() -> None:
    """A screen cut short mid-level claims the level below it, never the one it is inside."""
    plan = _enumeration()
    assert plan.coverage(len(plan.texts)) == 3
    for n, end in plan.boundaries:
        assert plan.coverage(end) == n
        assert plan.coverage(end - 1) == (None if n == 1 else n - 1)
    assert plan.coverage(0) is None


def test_coverage_is_forfeited_when_the_smallest_sizes_were_skipped() -> None:
    plan = _enumeration(floor=2)
    assert plan.coverage(len(plan.texts)) is None


def test_enumeration_drops_a_level_it_cannot_afford_whole() -> None:
    plan = _enumeration(limit=5, max_candidates=5)
    assert plan.coverage(len(plan.texts)) == plan.boundaries[-1][0] < 5


def test_seed_circuits_are_appended_after_the_levels() -> None:
    """A seed adds a candidate; it does not add to what any level claims to have covered."""
    plain = _enumeration()
    seeded = _enumeration(extra=["R1-p(R2,C1)-C2-R3"])
    assert seeded.texts[: len(plain.texts)] == plain.texts
    assert len(seeded.texts) == len(plain.texts) + 1
    assert seeded.boundaries == plain.boundaries
