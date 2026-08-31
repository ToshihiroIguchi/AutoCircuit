"""The growth stage: what it finds above the exhaustive limit, and what it may claim.

Above ``DEFAULT_EXHAUSTIVE_LIMIT`` the space stops being enumerable and the search grows
instead -- every one-element extension of the best ``GROWTH_WIDTH`` topologies of the last
completed level. Two things have to be true of that and they pull in opposite directions:
it has to *reach* topologies the exhaustive stage cannot, and it must not let the report
imply it enumerated them. Most of this file is about the second.

See ``docs/TOPOLOGY_6PLUS_PLAN.md`` sections 5.5 and 4.7.
"""

from __future__ import annotations

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit, count_elements
from autocircuit.core.discover import (
    GROWTH_DEFAULT,
    GROWTH_REACH,
    GROWTH_WIDTH,
    _screening_score,
    discover,
    growth_plan,
)
from autocircuit.core.simulate import log_frequencies, simulate

TWO_BLOCK = {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8, "R3.R": 2e3, "C2.C": 1e-5}


def _two_block(noise: float = 0.0, seed: int = 0, points: int = 8):
    """``R1-p(R2,C1)-p(R3,C2)``: five elements, two well-separated relaxations."""
    return simulate(
        "R1-p(R2,C1)-p(R3,C2)",
        log_frequencies(1e-1, 1e6, points),
        TWO_BLOCK,
        noise=noise,
        seed=seed,
    )


# -- growth_plan, driven by hand -------------------------------------------------------------


def _drive(plan, cost_of):
    """Run a ``growth_plan`` generator to completion with a caller-supplied cost function."""
    try:
        tasks = next(plan)
        while True:
            tasks = plan.send([cost_of(task.text) for task in tasks])
    except StopIteration as done:
        return list(done.value)


def test_growth_only_proposes_topologies_one_element_larger() -> None:
    scored = [(1.0, "R1"), (0.5, "p(R1,C1)"), (0.4, "R1-C1")]
    produced = _drive(
        growth_plan(
            scored, pool=("R", "C"), start_size=2, max_elements=3, n_data=40, width=2
        ),
        lambda text: 0.1,
    )
    assert produced
    assert {count_elements(Circuit.parse(text).root) for _cost, text in produced} == {3}


def test_growth_never_re_screens_what_the_exhaustive_stage_already_saw() -> None:
    """The two stages share one ``seen`` set, so no topology is paid for twice.

    Not a micro-optimisation: the shortlist is built from the union of both stages' costs, and
    a topology appearing twice with two different screening costs would give the per-size quota
    two different opinions of the same circuit.
    """
    scored = [(1.0, "R1"), (0.5, "C1"), (0.4, "R1-C1"), (0.3, "p(R1,C1)")]
    produced = _drive(
        growth_plan(
            scored, pool=("R", "C"), start_size=2, max_elements=3, n_data=40, width=2
        ),
        lambda text: 0.1,
    )
    already = {text for _cost, text in scored}
    assert not already & {text for _cost, text in produced}
    assert len({text for _cost, text in produced}) == len(produced)


def test_growth_extends_the_best_of_the_level_and_not_the_first() -> None:
    """The beam is ranked by the screening score, so a cheap parent is the one extended."""
    scored = [(9.0, "R1-C1"), (1e-6, "p(R1,C1)")]
    produced = _drive(
        growth_plan(
            scored, pool=("R",), start_size=2, max_elements=3, n_data=40, width=1
        ),
        lambda text: 0.1,
    )
    # Every child must contain the good parent's structure, i.e. a parallel R-C somewhere.
    assert produced
    assert all("p(" in text for _cost, text in produced)


def test_growth_stops_when_a_level_yields_nothing_new() -> None:
    """A pool of one element and a start size the insertions cannot exceed ends the stage."""
    produced = _drive(
        growth_plan(
            [(1.0, "R1")], pool=("R",), start_size=1, max_elements=2, n_data=40, width=1
        ),
        lambda text: 0.1,
    )
    # `R1-R2` and `p(R1,R2)` both simplify back to a single resistor, so there is no level 2.
    assert produced == []


def test_growth_ranking_uses_the_screening_score_not_the_raw_cost() -> None:
    """Raw cost always improves with parameters; ranking by it would keep only the largest.

    This is the same defect ``docs/HANDOFF.md`` section 3 records for the tier-1 shortlist,
    where ranking a whole screen by raw residual put nothing but five-element circuits on it
    and never refitted the four-element circuit that generated the data.

    The property the beam needs is that a parameter has to *earn* itself: at equal residual the
    larger model must rank worse, and it must take a real improvement to overturn that. Both
    halves are asserted, because only the second one distinguishes a penalised score from an
    unpenalised one -- a first version of this test picked two arbitrary (ssr, k) pairs and
    asserted the wrong sign of an inequality it had not worked out.
    """
    n_data = 40
    assert _screening_score(1.0e-3, 2, n_data) < _screening_score(1.0e-3, 6, n_data)
    # A residual gain small next to the penalty does not buy the extra parameters ...
    assert _screening_score(0.9e-3, 6, n_data) > _screening_score(1.0e-3, 2, n_data)
    # ... and one large next to it does.
    assert _screening_score(1.0e-6, 6, n_data) < _screening_score(1.0e-3, 2, n_data)


# -- what the report is allowed to say -------------------------------------------------------


def test_growth_is_off_unless_asked_for() -> None:
    """The default is no growth, and the test says so from the *default* rather than from 0.

    `GROWTH_DEFAULT` is the decision and `GROWTH_WIDTH` is the width to use once the decision is
    yes; asserting on a literal 0 here would pass even if the default were flipped without the
    measurement that is supposed to flip it.
    """
    assert GROWTH_DEFAULT == 0
    result = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        max_elements=5,
        seed=0,
    )
    assert result.grown_to is None
    assert "grew rather than enumerated" not in result.completeness()


def test_coverage_separates_what_was_enumerated_from_what_was_grown() -> None:
    result = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=2,
        max_elements=5,
        seed=0,
    )
    assert result.complete_up_to == 3
    assert result.grown_to is not None and result.grown_to > result.complete_up_to
    coverage = result.completeness()
    # The strong claim is still made, and only for the enumerated part.
    assert "every plausible topology with up to 3 elements" in coverage
    # The weak claim is made separately, and says in words that it is not a completeness claim.
    assert "grew rather than enumerated" in coverage
    assert "not a completeness claim" in coverage
    assert str(GROWTH_WIDTH) in coverage or "best" in coverage


def test_growth_never_raises_complete_up_to() -> None:
    """The completeness number describes the *enumeration*, and growth must not touch it.

    The failure this guards against is the one this repository has measured three times in
    other guises: a search that quietly stopped covering its space while its report went on
    looking healthy. Here it would be a single assignment.
    """
    grown = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=2,
        max_elements=5,
        seed=0,
    )
    flat = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=0,
        max_elements=5,
        seed=0,
    )
    assert grown.complete_up_to == flat.complete_up_to


def test_growth_reaches_sizes_the_exhaustive_stage_did_not() -> None:
    grown = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=2,
        max_elements=5,
        seed=0,
    )
    flat = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=0,
        max_elements=5,
        seed=0,
    )
    largest = max(count_elements(c.circuit.root) for c in grown.candidates)
    assert largest > max(count_elements(c.circuit.root) for c in flat.candidates)
    assert grown.n_evaluated > flat.n_evaluated


def test_growth_is_reproducible() -> None:
    """No seed reaches the beam: it is deterministic given the level below it."""
    kwargs = dict(
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=2,
        max_elements=5,
        seed=0,
    )
    data = _two_block(points=6)
    first = discover(data, **kwargs)
    second = discover(data, **kwargs)
    assert [c.circuit.to_string() for c in first.candidates] == [
        c.circuit.to_string() for c in second.candidates
    ]
    assert first.grown_to == second.grown_to


def test_growth_is_skipped_under_a_skeleton() -> None:
    """A skeleton run already reaches past the default limit, and mixing the two claims would
    leave the report unable to say which space it covered."""
    result = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        skeleton="R1-p(R2,C1)",
        exhaustive_limit=4,
        growth_width=4,
        max_elements=6,
        seed=0,
    )
    assert result.grown_to is None
    assert "grew rather than enumerated" not in result.completeness()


def test_grown_to_crosses_the_wire() -> None:
    result = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=2,
        max_elements=5,
        seed=0,
    )
    assert result.to_dict()["grown_to"] == result.grown_to


@pytest.mark.parametrize("width", [1, 2, 4])
def test_a_wider_beam_never_evaluates_fewer_topologies(width: int) -> None:
    """Monotonicity is what makes the width safe to raise: a wider beam cannot lose a
    candidate a narrower one keeps, so the only cost of raising it is runtime."""
    narrow = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=width,
        max_elements=5,
        seed=0,
    )
    wider = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=width + 2,
        max_elements=5,
        seed=0,
    )
    assert wider.n_evaluated >= narrow.n_evaluated


def test_growth_finds_a_truth_the_exhaustive_limit_excludes() -> None:
    """The point of the stage, on a five-element truth with the limit set to four.

    Deliberately a *small* instance: the arena-scale version of this claim is X4 of
    ``docs/TOPOLOGY_6PLUS_PLAN.md`` and takes hours. What this pins is that the mechanism
    works end to end -- the beam reaches the size, the candidate is refitted at full budget,
    and it arrives in the report through the same shortlist as everything else.
    """
    data = _two_block(noise=0.0, points=10)
    truth = Circuit.parse("R1-p(R2,C1)-p(R3,C2)").canonical_form()

    flat = discover(
        data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=4,
        growth_width=0, max_elements=6, seed=0,
    )
    assert truth not in {c.circuit.canonical_form() for c in flat.candidates}

    grown = discover(
        data, pool=("R", "C"), mode="exhaustive", exhaustive_limit=4,
        growth_width=GROWTH_WIDTH, max_elements=6, seed=0,
    )
    found = {c.circuit.canonical_form() for c in grown.candidates}
    assert truth in found, "the growth stage did not reach the five-element truth"

    match = next(c for c in grown.candidates if c.circuit.canonical_form() == truth)
    np.testing.assert_allclose(match.result.z_model, data.z, rtol=1e-4)


# -- the browser runs the same search --------------------------------------------------------


def test_the_browser_grows_the_same_way_the_command_line_does() -> None:
    """Parity for the growth stage, the way gate W2 asks for it for the two tiers.

    The browser does not call ``discover``: it drives ``screen_plan`` and ``refit_plan`` itself
    so it can fan batches across Web Workers, and growth had to be added to that driver as well
    or the two front ends would run different searches. The failure this pins is specific and
    was made once while writing it -- ``DiscoveryJob`` derives ``complete_up_to`` from the
    length of its screened list, and the growth stage appends to that list, so the first
    version reported a *higher* completeness than it had earned.
    """
    from autocircuit.core.discover import (
        SCREEN_BUDGET,
        ScreenTask,
        _full_fit,
        _screen_one,
    )
    from autocircuit.web.job import DiscoveryJob

    data = _two_block(points=6)
    driven = DiscoveryJob(
        data,
        pool=("R", "C"),
        exhaustive_limit=3,
        max_elements=5,
        growth_width=GROWTH_WIDTH,
        seed=0,
        screen_chunk=1,
    )
    while True:
        batch = driven.next_screen()
        if batch is None:
            break
        driven.submit_screen(
            [
                _screen_one(
                    ScreenTask(text, abandon),
                    data,
                    weighting="modulus",
                    seed=0,
                    budget=SCREEN_BUDGET,
                )
                for text, abandon in batch
            ]
        )
    while True:
        tasks = driven.next_refit()
        if tasks is None:
            break
        driven.submit_refit(
            [
                _full_fit(text, data, "modulus", restarts, seed)
                for text, restarts, seed in tasks
            ]
        )
    report = driven.report()

    reference = discover(
        data,
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        max_elements=5,
        growth_width=GROWTH_WIDTH,
        seed=0,
    )
    assert report.complete_up_to == reference.complete_up_to
    assert report.grown_to == reference.grown_to
    assert report.completeness() == reference.completeness()
    assert [c.circuit.to_string() for c in report.candidates] == [
        c.circuit.to_string() for c in reference.candidates
    ]


def test_growth_reaches_a_bounded_distance_past_the_complete_level() -> None:
    """Growth is a *reach*, not a walk to ``max_elements``.

    A level's survivors are chosen from the level below, so four levels grown from a complete
    level 3 is a weaker claim than two grown from a complete level 5 -- and the coverage sentence
    cannot tell those apart. Bounding the distance is what keeps that sentence honest whatever
    ``exhaustive_limit`` the caller chose, and it is what stops a small space from growing for
    minutes.
    """
    result = discover(
        _two_block(points=6),
        pool=("R", "C"),
        mode="exhaustive",
        exhaustive_limit=3,
        growth_width=2,
        max_elements=7,
        seed=0,
    )
    assert result.complete_up_to == 3
    assert result.grown_to == 3 + GROWTH_REACH
