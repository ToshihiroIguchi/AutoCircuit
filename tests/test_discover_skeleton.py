"""Skeleton-constrained discovery: the *claim* a constrained search is allowed to make.

These tests are not about the search finding the right circuit -- that is what
test_discover_exhaustive.py already covers for the unconstrained case. A skeleton is the one
argument to :func:`~autocircuit.core.discover.discover` that can remove the right answer from
the candidate space while leaving a report that still looks perfectly healthy: coverage is
100%, the Pareto front is populated, nothing errors. So what has to be pinned down here is that
every candidate really does honour the constraint, that the space actually enumerated is
exactly the one the constraint defines, and that the report says, in the same sentence as the
completeness figure, which part of the space it never looked at
(docs/PARTIAL_TOPOLOGY_PLAN.md section 3).
"""

from __future__ import annotations

import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.discover import (
    DiscoveryResult,
    discover,
    excluded_equivalents,
    excluded_plan,
    excluded_target,
    exhaustive_limit_for,
    run_screen,
)
from autocircuit.core.enumerate import (
    contains_skeleton,
    count_topologies,
    grow_from_skeleton,
)
from autocircuit.core.simulate import log_frequencies, simulate

POOL = ("R", "C")

#: Values for the fixture spectrum shared by the tests that only care about the constraint
#: itself, not about recovering any particular truth.
VALUES = {"R1.R": 50.0, "R2.R": 500.0, "C1.C": 2e-7}


def _spectrum(noise: float = 0.01, seed: int = 0):
    # 9 points, 2 per decade over 4 decades -- enough to constrain a 2-3 element RC circuit
    # without paying for a real screen; see the module docstring in test_discover_exhaustive.py.
    return simulate(
        "R1-p(R2,C1)", log_frequencies(1e1, 1e5, 2), VALUES, noise=noise, seed=seed
    )


@pytest.fixture(scope="module")
def skeleton_result() -> DiscoveryResult:
    """One shared exhaustive run under skeleton="R1-C1", reused by the tests that each check a
    different facet of its report -- discover() costs real seconds, and re-running it per
    assertion would only be testing the same run three times over.
    """
    return discover(
        _spectrum(),
        pool=POOL,
        skeleton="R1-C1",
        mode="exhaustive",
        exhaustive_limit=3,
        feasibility_filter=False,
        seed=0,
    )


# =============================================================================================
# 1. Every reported candidate contains the skeleton
# =============================================================================================


def test_every_candidate_contains_the_skeleton(skeleton_result: DiscoveryResult) -> None:
    """If a single candidate slipped through without R1-C1, the search would silently be
    reporting on a different, wider space than the one it claims -- exactly the failure mode
    docs/PARTIAL_TOPOLOGY_PLAN.md section 3 warns about, just visible here instead of in a
    report the user reads.
    """
    skeleton_node = Circuit.parse("R1-C1").root
    assert skeleton_result.candidates
    for candidate in skeleton_result.candidates:
        assert contains_skeleton(candidate.circuit.root, skeleton_node)


# =============================================================================================
# 2. The constrained space is exactly the enumerated one
# =============================================================================================


def test_constrained_space_is_exactly_the_enumerated_one(
    skeleton_result: DiscoveryResult,
) -> None:
    """``n_evaluated`` and ``complete_up_to`` are the numbers the completeness sentence is built
    from; if discover() screened anything other than exactly grow_from_skeleton's output for
    each size, this would catch it independently of what completeness() happens to say about it.
    """
    skeleton_node = Circuit.parse("R1-C1").root
    expected = sum(len(list(grow_from_skeleton(skeleton_node, POOL, n))) for n in (2, 3))
    assert skeleton_result.n_evaluated == expected
    assert skeleton_result.complete_up_to == 3


# =============================================================================================
# 3. completeness() names the skeleton
# =============================================================================================


def test_completeness_names_the_skeleton(skeleton_result: DiscoveryResult) -> None:
    """The whole point of section 3.1: the unconstrained sentence ("...from this pool was
    evaluated") is simply false once a skeleton is in play, and a reader who skims past the
    constraint has been misled by a sentence that is otherwise entirely true. The constrained
    sentence must say what was actually covered, not the unconstrained claim with a caveat
    bolted on.
    """
    text = skeleton_result.completeness()
    assert "R1-C1" in text
    assert "that contains" in text
    assert "from this pool was evaluated" not in text
    assert skeleton_result.skeleton == "R1-C1"
    assert "R1-C1" in skeleton_result.summary()


# =============================================================================================
# 4. skeleton=None is unchanged
# =============================================================================================


def test_unconstrained_completeness_sentence_is_unchanged() -> None:
    """Locks the exact old sentence down, character for character, so that adding the skeleton
    branch to completeness() could not have silently reworded the unconstrained case too.
    """
    result = discover(
        _spectrum(),
        pool=POOL,
        mode="exhaustive",
        exhaustive_limit=3,
        feasibility_filter=False,
        seed=0,
    )
    assert result.skeleton is None
    assert (
        result.completeness()
        == "Coverage: every plausible topology with up to 3 elements from this pool was "
        "evaluated."
    )


# =============================================================================================
# 5. The truth is recovered under a true skeleton
# =============================================================================================


def test_truth_is_recovered_under_a_true_skeleton() -> None:
    """The in-suite shadow of gate P1: a skeleton that genuinely is part of the generating
    circuit must not, by construction, keep the search from finding it. ``R1-p(R2,C1)`` really
    does have a series resistance, so skeleton="R1" must not exclude it.
    """
    truth_values = {"R1.R": 20.0, "R2.R": 1000.0, "C1.C": 1e-8}
    spectrum = simulate(
        "R1-p(R2,C1)", log_frequencies(1e1, 1e5, 2), truth_values, noise=0.0, seed=0
    )
    result = discover(
        spectrum, pool=POOL, skeleton="R1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    truth = Circuit.parse("R1-p(R2,C1)").canonical_form()
    assert truth in {c.circuit.canonical_form() for c in result.candidates}
    assert result.recommended is not None
    assert result.recommended.circuit.n_params == 3


# =============================================================================================
# 6. A skeleton code outside the pool survives
# =============================================================================================


def test_skeleton_code_outside_pool_survives_into_every_candidate() -> None:
    """The skeleton is an assertion, not a search result: an "L" the pool never offers must
    still show up in every generated candidate, because the search only adds R/C elements
    around it and never strips it back out.
    """
    result = discover(
        _spectrum(),
        pool=POOL,
        skeleton="L1-R1",
        mode="exhaustive",
        exhaustive_limit=3,
        feasibility_filter=False,
        seed=0,
    )
    assert result.candidates
    for candidate in result.candidates:
        leaves = candidate.circuit.leaves
        assert any(leaf.code == "L" for leaf in leaves)


# =============================================================================================
# 7. Errors are raised before any fitting
# =============================================================================================


def _tiny_spectrum():
    return simulate("R1", log_frequencies(1e3, 1e4, 1), {"R1.R": 100.0})


def test_evolve_mode_with_a_skeleton_raises_value_error() -> None:
    """mode='evolve' mutates by deleting and retyping elements, so it cannot keep a population
    confined to circuits containing a fixed skeleton -- this must fail loudly at the call, not
    quietly ignore the skeleton and run an unconstrained genetic search instead.
    """
    with pytest.raises(ValueError, match="cannot honour a skeleton"):
        discover(_tiny_spectrum(), pool=POOL, skeleton="R1-C1", mode="evolve")


def test_a_seed_circuit_outside_the_skeleton_raises_value_error() -> None:
    """A seed is a hint that *adds* to the candidate list; a skeleton is a constraint on what
    that list may hold. Asking for both when the seed violates the constraint is contradictory,
    and the harm is not hypothetical: the seed could end up as the recommendation, under a
    coverage line saying only topologies containing the skeleton were considered. Choosing
    which of the user's two instructions to drop is not the library's call to make.
    """
    with pytest.raises(ValueError, match="does not contain the skeleton"):
        discover(
            _tiny_spectrum(),
            pool=POOL,
            skeleton="R1-C1",
            mode="exhaustive",
            exhaustive_limit=3,
            seeds=("p(R1,C1)",),
        )


def test_exhaustive_limit_below_skeleton_size_raises_value_error() -> None:
    """exhaustive_limit is a *total* element count, so a limit smaller than the skeleton's own
    size describes an empty search rather than a small one; the error must fire before any
    enumeration or fitting starts.
    """
    with pytest.raises(ValueError, match="below the skeleton's own"):
        discover(
            _tiny_spectrum(),
            pool=POOL,
            skeleton="R1-C1-L1",
            mode="exhaustive",
            exhaustive_limit=2,
        )


# =============================================================================================
# 8. What the report owes the user besides the coverage sentence
# =============================================================================================


def test_placement_ambiguity_is_reported_rather_than_resolved() -> None:
    """A skeleton can sit inside one reported topology in more than one place, with the user's
    element somewhere structurally different -- and a different fitted value -- each time
    (docs/PARTIAL_TOPOLOGY_PLAN.md section 3.5). Picking one and printing it would read as a
    finding; it is not one, and the data cannot produce one. So the report says how many ways
    there are, in the summary and not only in an attribute nobody reads.
    """
    truth_values = {"R1.R": 20.0, "R2.R": 1000.0, "C1.C": 1e-8}
    spectrum = simulate(
        "R1-p(R2,C1)", log_frequencies(1e1, 1e5, 2), truth_values, noise=0.0, seed=0
    )
    result = discover(
        spectrum, pool=POOL, skeleton="R1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    # The truth has two resistors and the skeleton asserts one of them; nothing in the fit
    # says which. (Its exact equivalent p(R1-C1,R2) is the same statement about the same data.)
    ambiguous = [c for c in result.pareto if result.placements_of(c) > 1]
    assert ambiguous, "no reported candidate admitted the skeleton in more than one place"
    assert "more than one place" in result.summary()

    # Unconstrained runs have nothing to place, and must not grow a placement section.
    free = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=3, seed=0)
    assert all(free.placements_of(c) == 0 for c in free.pareto)
    assert "more than one place" not in free.summary()


def test_a_report_where_nothing_is_identifiable_says_so() -> None:
    """Section 3.4. A skeleton larger than the data can support does not fail loudly: it
    returns candidates that fit essentially perfectly and pin down nothing, with the parsimony
    rule left with nothing to prefer. Here a flat resistive spectrum is searched under a
    skeleton asserting a capacitance and an inductance it cannot see, and the fit is excellent
    -- chi2_reduced of order 1e-4 -- while two of the three parameters have standard errors
    larger than their own values. That is a finding about the measurement, and a report that
    printed only the fit quality would be inviting the reader to believe the opposite.
    """
    flat = simulate("R1", log_frequencies(1e2, 1e4, 3), {"R1.R": 100.0}, noise=0.02, seed=0)
    result = discover(
        flat, pool=POOL, skeleton="R1-C1-L1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert result.recommended is not None
    assert result.recommended.n_unresolved > 0
    assert result.unresolved_everywhere
    assert "cannot" in result.summary() and "resolve" in result.summary()


def test_an_asserted_element_the_fit_had_to_switch_off_is_named() -> None:
    """What gate P2 measured, in miniature (docs/PARTIAL_TOPOLOGY_PLAN.md section 3.2).

    [measured] Over three references and ten seeds each, a wrong skeleton left *no* trace in
    the two places a reader looks: residual structure 0/30, and a chi-squared equal to what the
    truth itself achieves on the same data. What it did leave is this. Asserting a semicircle
    `R1-p(R2,C1)` against a series `C1-R1-L1` truth returns `R1-p(R2,C1)-L1`, which becomes the
    truth exactly when R2 goes to an open -- so the fit neutralises the asserted branch, and
    the element it had to neutralise is the one whose standard error exceeds its own value.
    Naming it is the difference between a report the reader can act on and an unresolved
    parameter somewhere in a circuit they have to notice was theirs.
    """
    truth = simulate(
        "C1-R1-L1",
        log_frequencies(1e2, 1e9, 4),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.01,
        seed=0,
    )
    result = discover(
        truth,
        pool=("R", "C", "L"),
        skeleton="R1-p(R2,C1)",
        mode="exhaustive",
        exhaustive_limit=4,
        seed=0,
    )
    assert result.recommended is not None
    assert result.unsupported_assertion(result.recommended) == ("R2",)
    assert "does not test part of your skeleton" in result.summary()


def test_a_skeleton_the_data_supports_is_not_flagged() -> None:
    """The other half of the gate, and the reason this cannot simply warn whenever a skeleton
    is present: a skeleton the truth really does contain comes back with every asserted element
    resolved, and a warning there would be a false one. The measurement makes the same point
    from the other side -- two of the three "wrong" skeletons in the P2 run were strict
    generalisations of the truth (a CPE with n = 1 *is* a capacitor), fitted identically with
    nothing unresolved, and were correctly not flagged.
    """
    truth = simulate(
        "C1-R1-L1",
        log_frequencies(1e2, 1e9, 4),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.01,
        seed=0,
    )
    result = discover(
        truth,
        pool=("R", "C", "L"),
        skeleton="C1-R1-L1",
        mode="exhaustive",
        exhaustive_limit=4,
        seed=0,
    )
    assert result.recommended is not None
    assert result.unsupported_assertion(result.recommended) == ()
    assert "does not test part of your skeleton" not in result.summary()


def test_an_unconstrained_run_has_no_assertion_to_report_on() -> None:
    truth_values = {"R1.R": 20.0, "R2.R": 1000.0, "C1.C": 1e-8}
    spectrum = simulate(
        "R1-p(R2,C1)", log_frequencies(1e1, 1e5, 2), truth_values, noise=0.0, seed=0
    )
    result = discover(spectrum, pool=POOL, mode="exhaustive", exhaustive_limit=3, seed=0)
    assert result.recommended is not None
    assert result.unsupported_assertion(result.recommended) == ()


def test_a_resolved_report_carries_no_such_warning() -> None:
    """The counterpart, so the warning is a finding and not decoration: noise-free data that
    determines its circuit must not trip it.
    """
    truth_values = {"R1.R": 20.0, "R2.R": 1000.0, "C1.C": 1e-8}
    spectrum = simulate(
        "R1-p(R2,C1)", log_frequencies(1e1, 1e5, 2), truth_values, noise=0.0, seed=0
    )
    result = discover(
        spectrum, pool=POOL, skeleton="R1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert not result.unresolved_everywhere


# =============================================================================================
# 9. What the skeleton excluded that would have fitted identically
# =============================================================================================


def test_excluded_equivalents_names_what_the_assertion_chose_between() -> None:
    """Section 3.3, and the reason it cannot be read off the search: the excluded topologies
    are exactly the ones never fitted, so their equivalence has to be established here.

    The case is small but it is the real phenomenon. `C1-R1-L1` and `R1-L1-CPE1` are the same
    circuit whenever the CPE exponent is -1, because a CPE with n = -1 *is* a capacitor. A user
    who asserts a capacitor has chosen one of the two, and no measurement on this frequency
    window can support that choice -- so the report says which alternative the choice removed
    rather than letting the skeleton's survivor read as a finding. (The same pass on the
    capacitor reference at four elements screens 1,132 topologies and finds exactly one:
    `R1-L1-CPE1-SKINF1`, the same substitution.)
    """
    pool = ("R", "C", "L", "CPE")
    data = simulate(
        "C1-R1-L1",
        log_frequencies(1e2, 1e9, 4),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.0,
        seed=0,
    )
    result = discover(
        data, pool=pool, skeleton="C1-R1-L1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert result.recommended is not None
    assert result.skeleton is not None
    report = excluded_equivalents(result.recommended, result.skeleton, data, pool=pool, seed=0)

    assert report.kept + report.excluded == count_topologies(pool, 3)
    assert report.excluded > 0
    excluded_forms = {Circuit.parse(text).canonical_form() for text in report.equivalents}
    assert Circuit.parse("R1-L1-CPE1").canonical_form() in excluded_forms
    assert "choosing between them is something you did" in report.summary()


def test_the_semicircle_twin_is_reported_as_excluded() -> None:
    """The example section 3.3 opens with, and it is not hypothetical. `R1-p(R2,C1)` and
    `p(R1-C1,R2)` describe exactly the same set of Nyquist semicircles and fit any of them to
    1.2e-15; they are different topologies of the same size, so asserting either as a skeleton
    excludes the other outright. A user asserting a series electrolyte resistance is entitled
    to do that -- a physical electrode really has one -- but the report must not let the
    survivor read as something the data preferred.
    """
    pool = ("R", "C")
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e1, 1e5, 2),
        {"R1.R": 20.0, "R2.R": 1000.0, "C1.C": 1e-8},
        noise=0.0,
        seed=0,
    )
    result = discover(
        data, pool=pool, skeleton="R1-p(R2,C1)", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert result.recommended is not None
    assert result.skeleton is not None
    report = excluded_equivalents(result.recommended, result.skeleton, data, pool=pool, seed=0)
    assert Circuit.parse("p(R1-C1,R2)").canonical_form() in {
        Circuit.parse(text).canonical_form() for text in report.equivalents
    }


def test_excluded_equivalents_reports_plainly_when_nothing_was_lost() -> None:
    """The other outcome has to be sayable too, or the feature only ever produces warnings.

    `C1-R1-L1` is *unique* among the 56 three-element topologies over R, C, L -- measured
    independently by `benchmarks/topology_space.py` (b) -- so asserting it excludes 55 others
    and none of them can reproduce it. The honest report is that the assertion cost nothing the
    data could have distinguished, and saying so is what makes the warning case meaningful.
    """
    pool = ("R", "C", "L")
    data = simulate(
        "C1-R1-L1",
        log_frequencies(1e2, 1e9, 4),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.0,
        seed=0,
    )
    result = discover(
        data, pool=pool, skeleton="C1-R1-L1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert result.recommended is not None
    assert result.skeleton is not None
    report = excluded_equivalents(result.recommended, result.skeleton, data, pool=pool, seed=0)
    assert report.excluded > 0
    assert report.equivalents == ()
    assert "Nothing the data could not already distinguish was lost" in report.summary()


def test_a_driven_excluded_pass_is_the_same_pass(
) -> None:
    """The pass has two drivers now -- in-process, and a browser fanning it across workers --
    and they must be running the same one. Everything the answer is made of comes from
    :func:`excluded_plan`; a driver that decided which topologies to check, or how exact
    "exact" is, would be a second implementation of the claim this pass exists to make.
    """
    pool = ("R", "C")
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e1, 1e5, 2),
        {"R1.R": 20.0, "R2.R": 1000.0, "C1.C": 1e-8},
        noise=0.0,
        seed=0,
    )
    result = discover(
        data, pool=pool, skeleton="R1-p(R2,C1)", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert result.recommended is not None
    assert result.skeleton is not None

    target = excluded_target(result.recommended, data)
    plan = excluded_plan(result.recommended, result.skeleton, data, pool=pool, chunk=1)
    batches = 0
    driven = None
    batch = next(plan)
    while driven is None:
        batches += 1
        costs = [run_screen(task, target, weighting="modulus", seed=0) for task in batch.tasks]
        try:
            batch = plan.send(costs)
        except StopIteration as done:
            driven = done.value

    reference = excluded_equivalents(result.recommended, result.skeleton, data, pool=pool, seed=0)
    assert batches > 1  # actually batched, so the comparison means something
    assert driven.equivalents == reference.equivalents
    assert (driven.kept, driven.excluded, driven.screened) == (
        reference.kept, reference.excluded, reference.screened
    )
    assert driven.screened == driven.excluded
    assert not driven.partial


def test_a_stopped_excluded_pass_does_not_claim_the_topologies_it_never_checked() -> None:
    """The characteristic failure of this project, in its third place (docs/HANDOFF.md §3).

    "None of them reproduces your model" is a claim about every topology the skeleton excluded.
    A pass that was stopped after 8 of 55 knows nothing about the other 47, and the sentence it
    prints has to be the weaker one -- because the pass takes as long as the search it follows,
    so being stopped is the normal case rather than the exceptional one.
    """
    pool = ("R", "C", "L")
    data = simulate(
        "C1-R1-L1",
        log_frequencies(1e2, 1e9, 4),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.0,
        seed=0,
    )
    result = discover(
        data, pool=pool, skeleton="C1-R1-L1", mode="exhaustive", exhaustive_limit=3, seed=0
    )
    assert result.recommended is not None
    assert result.skeleton is not None

    target = excluded_target(result.recommended, data)
    plan = excluded_plan(result.recommended, result.skeleton, data, pool=pool, chunk=8)
    first = next(plan)
    costs = [run_screen(task, target, weighting="modulus", seed=0) for task in first.tasks]
    partial = plan.send(costs).so_far
    plan.close()

    assert partial.partial
    assert partial.screened == 8 < partial.excluded
    text = partial.summary()
    assert f"Only {partial.screened} of them have been checked" in text
    assert f"{partial.excluded - partial.screened} were never checked" in text
    # The finished pass on this same case says exactly this, and it is the claim a partial one
    # is not entitled to make.
    assert "Nothing the data could not already distinguish was lost" not in text


# =============================================================================================
# 10. A budget that bites lowers the claim instead of faking it
# =============================================================================================


def test_a_clamped_budget_lowers_the_constrained_claim_rather_than_faking_it() -> None:
    """The unconstrained version of this is already locked down in test_discover_exhaustive.py;
    the constrained path reaches the same decision through different machinery -- growth stops
    when a level cannot be afforded, and a level is taken whole or not at all -- so the honesty
    of ``complete_up_to`` has to be pinned down here too. Under a skeleton the claim is the
    *only* thing standing between a narrowed search and a report that reads like a complete
    one.
    """
    skeleton_node = Circuit.parse("R1-C1").root
    result = discover(
        _spectrum(),
        pool=POOL,
        skeleton="R1-C1",
        mode="exhaustive",
        exhaustive_limit=4,
        max_candidates=5,
        feasibility_filter=False,
        seed=0,
    )
    assert result.complete_up_to is not None
    assert result.complete_up_to < 4
    covered = sum(
        len(list(grow_from_skeleton(skeleton_node, POOL, n)))
        for n in range(2, result.complete_up_to + 1)
    )
    assert result.n_evaluated == covered
    assert str(result.complete_up_to) in result.completeness()


# =============================================================================================
# 11. exhaustive_limit_for -- the arithmetic the CLI prints before the run
# =============================================================================================


def test_exhaustive_limit_for_arithmetic() -> None:
    """The CLI prints this same arithmetic to the user before the search starts
    (``_skeleton_plan`` in autocircuit.cli.main), so it has to agree with what discover() then
    actually does -- a second copy of the default, computed separately, would be a second thing
    that could drift out of sync with this one.
    """
    assert exhaustive_limit_for(None, None) == 5
    assert exhaustive_limit_for(None, 7) == 7
    assert exhaustive_limit_for(3, None) == 8
    assert exhaustive_limit_for(10, 12) == 12
    with pytest.raises(ValueError):
        exhaustive_limit_for(10, 8)
