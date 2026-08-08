"""Exhaustive-mode discovery: the contract that makes it worth having.

The genetic search can only ever say "this is what I found". Exhaustive mode is supposed to
say something much stronger -- "this is everything there is, up to N elements" -- so these
tests are mostly about that claim being *true* and being reported honestly: every enumerated
topology really is screened, the completeness figure matches what was actually covered, and
it drops to a smaller number (never a false one) when a budget cuts the run short.
"""

from __future__ import annotations

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import (
    MIN_REFINE_PER_SIZE,
    REFINE_CEILING_FACTOR,
    _screening_aicc,
    _shortlist,
    discover,
)
from autocircuit.core.enumerate import count_topologies, enumerate_topologies
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


def test_screening_aicc_charges_for_parameters() -> None:
    """Two circuits that fit equally well are not equally good; the bigger one is worse."""
    assert _screening_aicc(1e-3, 5, 140) < _screening_aicc(1e-3, 8, 140)
    # ...and a genuinely better fit still wins despite costing more parameters.
    assert _screening_aicc(1e-6, 8, 140) < _screening_aicc(1e-3, 5, 140)
    # Degenerate inputs are ranked last rather than raising.
    assert _screening_aicc(0.0, 5, 140) == float("inf")
    assert _screening_aicc(1e-3, 200, 140) == float("inf")


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
