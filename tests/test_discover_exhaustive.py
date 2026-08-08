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
from autocircuit.core.discover import discover
from autocircuit.core.enumerate import count_topologies
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
