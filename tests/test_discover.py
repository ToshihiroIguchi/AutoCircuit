"""Topology-discovery tests.

Discovery is stochastic, so these tests avoid asserting that one particular circuit wins.
What they do assert is the contract the feature actually makes: the genetic operators always
produce valid circuits, structurally redundant topologies are filtered out, the Pareto front
really is non-dominated, a run is reproducible from its seed, and on easy data the true
topology does appear on the front.

Tests that exercise the genetic search itself -- seeds, generations, the time limit -- pass
``mode="evolve"`` explicitly. The default is now ``"auto"``, which starts with exhaustive
enumeration, and on the wider pools that means fitting several hundred topologies: correct,
but not what these particular tests are about, and far too slow to run for each of them.
Exhaustive and auto mode have their own file, ``test_discover_exhaustive.py``.
"""

from __future__ import annotations

import math
import time

import numpy as np

# Private, and deliberately so: parameter inheritance is an internal of the genetic search
# (step 3 of docs/EVOLVE_SEARCH_PLAN.md), and the tests below assert its rules directly
# because nothing a caller can see distinguishes a warm-started tier-1 fit from a cold one --
# by design, since neither is ever published. The module itself is imported as well, so that a
# test can spy on one internal call without reaching through the package each time.
from autocircuit.core import discover as discover_module
from autocircuit.core.circuit import Circuit, count_elements, simplify
from autocircuit.core.discover import (
    Candidate,
    DiscoveryResult,
    _breeding_pool,
    _Evaluator,
    _fit_cost,
    _inherited_values,
    _refine,
    _refit_order,
    crossover,
    discover,
    is_plausible,
    mutate,
    pareto_front,
    random_topology,
)
from autocircuit.core.fit import FitResult, fit
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.stats import Statistics

FAST = {
    "generations": 8,
    "population": 16,
    "max_elements": 4,
    "search_maxiter": 30,
    "n_refine": 3,
    "final_restarts": 2,
}

#: The same reduced budget, pinned to the genetic search.
FAST_EVOLVE = {**FAST, "mode": "evolve"}


def test_random_topology_has_the_requested_element_count() -> None:
    rng = np.random.default_rng(0)
    for n in range(1, 8):
        tree = random_topology(rng, ("R", "C", "L"), n)
        assert count_elements(tree) == n
        Circuit(tree)  # must be constructible


def test_mutation_always_yields_a_valid_circuit() -> None:
    rng = np.random.default_rng(1)
    pool = ("R", "C", "L", "CPE", "W")
    tree = random_topology(rng, pool, 4)
    for _ in range(300):
        tree = mutate(tree, rng, pool, max_elements=6)
        circuit = Circuit(tree)
        assert circuit.n_params >= 1
        assert 1 <= count_elements(tree) <= 6
        # A valid circuit must be evaluable.
        values = np.full(circuit.n_params, 1e-3)
        z = circuit.impedance(np.array([1.0, 1e3]), values)
        assert z.shape == (2,)


def test_crossover_always_yields_a_valid_circuit() -> None:
    rng = np.random.default_rng(2)
    pool = ("R", "C", "CPE")
    for _ in range(200):
        a = random_topology(rng, pool, int(rng.integers(1, 5)))
        b = random_topology(rng, pool, int(rng.integers(1, 5)))
        child = crossover(a, b, rng)
        assert count_elements(child) >= 1
        Circuit(child)


def test_simplify_removes_exact_redundancy() -> None:
    assert Circuit(simplify(Circuit.parse("R1-R2").root)).canonical_form() == "R"
    assert Circuit(simplify(Circuit.parse("p(R1,R2)").root)).canonical_form() == "R"
    assert Circuit(simplify(Circuit.parse("C1-C2-C3").root)).canonical_form() == "C"
    assert Circuit(simplify(Circuit.parse("p(L1,L2)").root)).canonical_form() == "L"
    # Genuinely different elements must survive untouched.
    assert count_elements(simplify(Circuit.parse("R1-C1").root)) == 2
    assert count_elements(simplify(Circuit.parse("p(R1,C1)").root)) == 2
    assert count_elements(simplify(Circuit.parse("CPE1-CPE2").root)) == 2


def test_implausible_topologies_are_rejected() -> None:
    # A capacitor in parallel with a CPE is degenerate: a CPE with n = 1 is a capacitor.
    assert not is_plausible(Circuit.parse("p(C1,CPE1)"))
    # A bare LC tank cannot describe a lossy measured spectrum.
    assert not is_plausible(Circuit.parse("p(L1,C1)"))
    assert not is_plausible(Circuit.parse("R1-p(L1,C1)"))
    # Ordinary topologies pass.
    assert is_plausible(Circuit.parse("R1-p(R2,C1)"))
    assert is_plausible(Circuit.parse("C1-R1-L1"))
    assert is_plausible(Circuit.parse("p(C1,R1-L1)"))


def test_pareto_front_is_non_dominated() -> None:
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e0, 1e6, 8),
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    result = discover(data, pool=("R", "C"), seed=0, **FAST)
    assert result.pareto, "discovery produced no Pareto front at all"

    for candidate in result.pareto:
        for other in result.candidates:
            if other is candidate:
                continue
            strictly_better = (
                other.complexity <= candidate.complexity
                and other.aicc <= candidate.aicc
                and (other.complexity < candidate.complexity or other.aicc < candidate.aicc)
            )
            assert not strictly_better, (
                f"{candidate.circuit} is on the front but dominated by {other.circuit}"
            )
    # The front must be sorted by increasing complexity.
    complexities = [c.complexity for c in result.pareto]
    assert complexities == sorted(complexities)


def test_pareto_front_helper_on_hand_built_candidates() -> None:
    class Fake:
        def __init__(self, complexity: float, value: float) -> None:
            self.complexity = complexity
            self.value = value
            self.circuit = complexity

        def score(self, criterion: str) -> float:
            return self.value

    points = [Fake(1.0, 10.0), Fake(2.0, 5.0), Fake(3.0, 6.0), Fake(2.0, 8.0)]
    front = pareto_front(points)  # type: ignore[arg-type]
    assert [(p.complexity, p.value) for p in front] == [(1.0, 10.0), (2.0, 5.0)]


def test_discovery_is_reproducible_from_its_seed() -> None:
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e0, 1e6, 8),
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    first = discover(data, pool=("R", "C"), seed=3, **FAST_EVOLVE)
    second = discover(data, pool=("R", "C"), seed=3, **FAST_EVOLVE)
    assert [c.circuit.canonical_form() for c in first.pareto] == [
        c.circuit.canonical_form() for c in second.pareto
    ]


def test_discovery_recovers_a_simple_topology() -> None:
    """On clean single-relaxation data the front must reach a model equivalent to the truth.

    Insisting on the exact string ``R1-p(R2,C1)`` would be testing the wrong thing.
    ``p(R1,C1-R2)`` describes exactly the same family of Nyquist semicircles -- fitted to
    this data the two agree to machine precision -- so the honest requirement is that the
    front contains a topology of the right size whose response matches the truth.
    """
    truth = {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8}
    f = log_frequencies(1e0, 1e7, 10)
    data = simulate("R1-p(R2,C1)", f, truth, noise=0.002, seed=1)
    exact = simulate("R1-p(R2,C1)", f, truth, seed=1)

    result = discover(
        data,
        pool=("R", "C"),
        generations=12,
        population=20,
        max_elements=4,
        search_maxiter=40,
        n_refine=4,
        final_restarts=3,
        seed=0,
    )

    matches = [
        c
        for c in result.pareto
        if c.circuit.n_params == 3
        and np.max(np.abs(c.result.z_model - exact.z) / np.abs(exact.z)) < 0.02
    ]
    assert matches, (
        "no three-parameter model on the front reproduces the true response; front is "
        f"{[c.circuit.to_string() for c in result.pareto]}"
    )


def test_reparameterised_topologies_are_reported_as_indistinguishable() -> None:
    """R1-p(R2,C1) and p(R1,C1-R2) fit identically; the tool must say so, not pick one."""
    truth = {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8}
    data = simulate("R1-p(R2,C1)", log_frequencies(1e0, 1e7, 10), truth, seed=1)
    result = discover(
        data,
        pool=("R", "C"),
        generations=10,
        population=20,
        max_elements=4,
        search_maxiter=40,
        n_refine=6,
        final_restarts=3,
        seed=0,
        seeds=("R1-p(R2,C1)", "p(R1,C1-R2)"),
    )

    forms = {c.circuit.canonical_form(): c for c in result.candidates}
    a = forms[Circuit.parse("R1-p(R2,C1)").canonical_form()]
    b = forms[Circuit.parse("p(R1,C1-R2)").canonical_form()]

    # They really are the same model: identical response from different parameters.
    np.testing.assert_allclose(a.result.z_model, b.result.z_model, rtol=1e-6)
    assert b in result.equivalents_of(a)
    assert a in result.equivalents_of(b)

    classes = result.equivalence_classes()
    together = [group for group in classes if a in group and b in group]
    assert together, "equivalent topologies were not grouped into one class"


def test_seed_circuits_are_evaluated() -> None:
    """A circuit injected by the user must appear among the evaluated candidates."""
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e0, 1e6, 8),
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    result = discover(
        data, pool=("R", "C"), seed=0, seeds=("R1-p(R2,C1)",), **FAST_EVOLVE
    )
    target = Circuit.parse("R1-p(R2,C1)").canonical_form()
    assert target in [c.circuit.canonical_form() for c in result.candidates]


def test_element_pool_is_respected() -> None:
    data = simulate(
        "p(R1,C1)", log_frequencies(1e0, 1e6, 8), {"R1.R": 1e3, "C1.C": 1e-8}, seed=0
    )
    result = discover(data, pool=("R", "C"), seed=0, **FAST)
    for candidate in result.candidates:
        for leaf in candidate.circuit.leaves:
            assert leaf.code in ("R", "C")


def test_recommendation_prefers_parsimony_over_raw_score() -> None:
    """The headline model must not be an over-parameterised one full of unresolved terms."""
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e0, 1e7, 10),
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=6,
    )
    result = discover(
        data,
        pool=("R", "C", "CPE"),
        mode="evolve",
        generations=10,
        population=20,
        max_elements=6,
        search_maxiter=40,
        n_refine=6,
        final_restarts=3,
        seed=0,
    )
    recommended = result.recommended
    assert recommended is not None
    # Whatever it picks, it must be a model whose parameters the data actually resolves...
    assert recommended.n_unresolved == 0
    # ...and it must never be more complex than the raw AICc winner.
    assert result.best is not None
    assert recommended.complexity <= result.best.complexity
    # ...while still fitting essentially as well.
    best_chi2 = min(c.result.chi2_reduced for c in result.candidates)
    assert recommended.result.chi2_reduced <= best_chi2 * 2.0


def _candidate(
    circuit_str: str,
    *,
    chi2_reduced: float,
    aicc: float,
    bic: float,
    unresolved_index: int | None = None,
) -> Candidate:
    """A candidate with hand-picked scores, built rather than fitted.

    Driving a real search into the exact chi-squared-band tie-break of
    docs/TOPOLOGY_6PLUS_PLAN.md section 5.10 costs minutes for something these three numbers
    already determine. Every parameter gets a 10% standard error, well inside
    :data:`~autocircuit.core.stats.UNRESOLVED_STDERR`, so ``n_unresolved`` is 0 unless
    ``unresolved_index`` names one parameter to blow up past its own value instead.
    """
    circuit = Circuit.parse(circuit_str)
    n = circuit.n_params
    values = np.linspace(10.0, 10.0 * n, n)
    stderr = 0.1 * values
    if unresolved_index is not None:
        stderr[unresolved_index] = abs(values[unresolved_index]) * 2.0
    stats = Statistics(
        n_data=2 * n + 10,
        n_params=n,
        ssr=1.0,
        chi2_reduced=chi2_reduced,
        stderr=stderr,
        correlation=np.eye(n),
        aic=aicc,
        aicc=aicc,
        bic=bic,
    )
    result = FitResult(
        circuit=circuit,
        values=values,
        z_model=np.zeros(n + 5, dtype=complex),
        residuals=np.zeros(2 * n + 10),
        statistics=stats,
        weighting="modulus",
        success=True,
        message="ok",
        n_restarts=1,
        relative_error=0.01,
    )
    return Candidate(circuit, result, 0)


def test_by_criterion_decline_reason_distinguishes_unresolved_from_inside_band() -> None:
    """docs/TOPOLOGY_6PLUS_PLAN.md section 5.10: the printed reason must match the real one.

    The report used to print "the extra elements are not supported by the data" whenever
    :attr:`DiscoveryResult.by_criterion` was declined, regardless of *why*. This builds the
    measured case -- the criterion's pick has every parameter resolved and is declined only for
    being more complex, inside the same chi-squared band as the simpler recommendation -- and
    checks that both the machine-readable reason and the printed sentence say so rather than
    naming an unresolved parameter that does not exist.
    """
    recommended = _candidate("R1-p(R2,C1)", chi2_reduced=1.0, aicc=-30.0, bic=-25.0)
    chosen = _candidate("R1-p(R2,C1)-p(R3,C2)", chi2_reduced=1.5, aicc=-60.0, bic=-50.0)
    assert chosen.n_unresolved == 0
    assert recommended.complexity < chosen.complexity

    result = DiscoveryResult(
        candidates=[chosen, recommended],
        pareto=[recommended, chosen],
        n_evaluated=2,
        generations=0,
        elapsed_s=1.0,
        pool=("R", "C"),
        mode="exhaustive",
        complete_up_to=5,
        criterion="aicc",
    )

    assert result.best is chosen
    assert result.by_criterion is chosen
    assert result.recommended is recommended
    assert result._decline_reason(chosen) == "inside_band"
    assert result.by_criterion_decline_reason == "inside_band"

    summary = result.summary()
    assert "not supported by the data" not in summary
    assert "all resolved" in summary
    assert "the same band" in summary


def test_by_criterion_decline_reason_is_unresolved_when_it_really_is() -> None:
    """The other branch: an unresolved parameter still gets the original sentence, unchanged."""
    recommended = _candidate("R1-p(R2,C1)", chi2_reduced=1.0, aicc=-30.0, bic=-25.0)
    chosen = _candidate(
        "R1-p(R2,C1)-p(R3,C2)", chi2_reduced=1.5, aicc=-60.0, bic=-50.0, unresolved_index=-1
    )
    assert chosen.n_unresolved == 1

    result = DiscoveryResult(
        candidates=[chosen, recommended],
        pareto=[recommended, chosen],
        n_evaluated=2,
        generations=0,
        elapsed_s=1.0,
        pool=("R", "C"),
        mode="exhaustive",
        complete_up_to=5,
        criterion="aicc",
    )

    assert result.by_criterion is chosen
    assert result.recommended is recommended
    assert result.by_criterion_decline_reason == "unresolved"
    assert "the extra elements are not supported by the data" in result.summary()


def test_recommendation_is_on_the_pareto_front() -> None:
    data = simulate(
        "p(R1,C1)", log_frequencies(1e0, 1e6, 8), {"R1.R": 1e3, "C1.C": 1e-8}, seed=0
    )
    result = discover(data, pool=("R", "C"), seed=0, **FAST)
    assert result.recommended in result.pareto


def test_summary_reports_the_degeneracy_caveat() -> None:
    data = simulate(
        "p(R1,C1)", log_frequencies(1e0, 1e6, 8), {"R1.R": 1e3, "C1.C": 1e-8}, seed=0
    )
    text = discover(data, pool=("R", "C"), seed=0, **FAST).summary()
    assert "Pareto front" in text
    assert "degenerate" in text
    assert "Recommended" in text


def test_candidate_serialises() -> None:
    import json

    data = simulate(
        "p(R1,C1)", log_frequencies(1e0, 1e6, 8), {"R1.R": 1e3, "C1.C": 1e-8}, seed=0
    )
    result = discover(data, pool=("R", "C"), seed=0, **FAST)
    assert result.best is not None
    payload: Candidate = result.best
    restored = json.loads(json.dumps(payload.to_dict()))
    assert "complexity" in restored
    assert "n_unresolved" in restored


def test_time_limit_stops_the_search() -> None:
    import time

    data = simulate(
        "R1-p(R2,C1)-p(R3,C2)",
        log_frequencies(1e-1, 1e7, 10),
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8, "R3.R": 1e5, "C2.C": 1e-10},
        noise=0.005,
        seed=0,
    )
    started = time.perf_counter()
    result = discover(
        data,
        pool=("R", "C", "CPE"),
        mode="evolve",
        generations=1000,
        population=20,
        seed=0,
        time_limit=5.0,
    )
    elapsed = time.perf_counter() - started
    # The limit governs the evolutionary loop; the final refit runs afterwards, so allow slack.
    assert elapsed < 60.0
    assert result.generations < 1000


def test_every_reported_candidate_was_refitted_at_full_budget() -> None:
    """Gate EV2 of ``docs/EVOLVE_SEARCH_PLAN.md``: the genetic search publishes tier-2 only.

    ``_evolve`` used to merge its unrefitted archive back into the reported list, so a Pareto
    row's chi-squared, standard errors and therefore its ``free?`` mark could come from the
    reduced search budget while the report said nothing about it. [measured, section 1.4 of that
    plan] 82% of the rows it reported on the three-block Maxwell-Wagner reference were of that
    kind. The defect is invisible in the numbers, which is why this asserts on the returned
    object rather than on anything a reader could be expected to notice.

    ``n_restarts`` is the provenance marker: the search budget uses ``search_restarts`` and the
    refit uses ``final_restarts``, so the two are distinguishable exactly when they differ --
    which is why they are set apart here rather than left at the shared FAST value.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.01,
        seed=0,
    )
    result = discover(
        data,
        pool=("R", "C"),
        mode="evolve",
        generations=6,
        population=16,
        max_elements=4,
        search_restarts=1,
        search_maxiter=30,
        final_restarts=3,
        seed=0,
    )
    assert result.candidates, "the search reported nothing at all"
    assert all(c.result.n_restarts == 3 for c in result.candidates)
    # The front is drawn from the candidates, so this cannot fail independently -- it is
    # asserted anyway because the front is what a reader actually looks at.
    assert all(c.result.n_restarts == 3 for c in result.pareto)
    recommended = result.recommended
    assert recommended is not None and recommended.result.n_restarts == 3
    # The archive is still counted rather than discarded with the rows it no longer supplies.
    # Not a strict inequality: on a pool this small the whole reachable space fits inside the
    # per-size quota, so every topology evaluated is legitimately also refitted.
    assert result.n_evaluated >= len(result.candidates)


def test_the_genetic_shortlist_reaches_every_element_count() -> None:
    """The per-size quota applies to the genetic search too, which is what EV2 rests on.

    Reporting tier-2 only is worth nothing if the shortlist is chosen the way the plan's
    section 5.1 records as wrong -- globally by score, which puts nothing but the largest
    circuits on it. The Pareto front is the deliverable, and a front with one complexity on it
    is not a trade-off curve.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.01,
        seed=0,
    )
    result = discover(
        data,
        pool=("R", "C"),
        mode="evolve",
        generations=6,
        population=16,
        max_elements=4,
        search_maxiter=30,
        final_restarts=2,
        seed=0,
    )
    sizes = {len(c.circuit.leaves) for c in result.candidates}
    assert len(sizes) >= 3, f"only these element counts were refitted: {sorted(sizes)}"


def _fitted(circuit: str, data: Spectrum) -> Candidate:
    """One full-budget fit of ``circuit``, wrapped as a candidate to inherit from."""
    result = fit(circuit, data, restarts=2, seed=0)
    return Candidate(result.circuit, result, 0)


def test_inherited_values_follow_the_structure_and_not_the_labels() -> None:
    """Step 3 of ``docs/EVOLVE_SEARCH_PLAN.md``: a child starts from its parent's parameters.

    The correspondence has to be structural. ``simplify`` drops every label before a child is
    fitted, so the parent's ``R2`` and the child's ``R2`` are related by nothing but a counter
    -- and a label-keyed lookup would still *appear* to work in the search, because the
    relabelling happens to be canonical there. This parent is labelled ``R7``/``R3``/``C5`` for
    exactly that reason: under a label-keyed rule it would carry nothing at all.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    parent = _fitted("R7-p(R3,C5)", data)
    child = Circuit(simplify(Circuit.parse("R1-p(R2,C1)").root))

    warm = _inherited_values(parent, child)

    assert warm == {
        "R1.R": parent.result.params["R7.R"],
        "R2.R": parent.result.params["R3.R"],
        "C1.C": parent.result.params["C5.C"],
    }


def test_inheritance_is_partial_where_the_child_has_elements_the_parent_lacks() -> None:
    """An inserted element keeps the template default; ``fit`` accepts a partial dict.

    This is the ordinary case -- a mutation inserts one element -- and the point of carrying
    values at all: the other five parameters do not have to be rediscovered because one is new.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    parent = _fitted("R1-p(R2,C1)", data)
    child = Circuit(simplify(Circuit.parse("R1-p(R2,C1)-L1-CPE1").root))

    warm = _inherited_values(parent, child)

    assert set(warm) == {"R1.R", "R2.R", "C1.C"}
    # The starting point is usable as it stands: a partial dict is what ``fit`` takes.
    polished = fit(child, data, initial=warm, global_search=False, seed=0)
    assert math.isfinite(polished.statistics.aicc)
    assert polished.params["R1.R"] > 0.0


def test_the_evaluator_keeps_the_better_of_two_fits_of_one_topology() -> None:
    """The cache is best-wins, which is what makes a warm start safe to re-propose into.

    [measured, section 1.3 of the plan] Over half of each late generation re-proposes a
    topology already evaluated. First-wins would freeze whichever fit arrived first and make a
    candidate's score depend on which parent happened to propose it; best-wins turns those
    hits into cheap refinement instead. The bad fit here is planted rather than hoped for, so
    the assertion is about the rule and not about a global stage happening to land badly.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    tree = Circuit.parse("R1-p(R2,C1)").root
    circuit = Circuit(simplify(tree))
    evaluator = _Evaluator(data, "modulus", 1, 12, 30, 1e-5, 0)

    # A fit of the right topology with the capacitance pinned five decades away: it converges,
    # it is finite, and it is wrong. (Starting a *free* fit from bad values does not work as a
    # planted failure here -- the local stage finds the optimum from anywhere on a problem this
    # small, which is itself worth knowing before writing a test around a bad fit.)
    far_off = fit(circuit, data, fixed={"C1.C": 1e-3}, restarts=1, popsize=8, maxiter=20, seed=0)
    planted = Candidate(circuit, far_off, 0)
    evaluator.cache[circuit.canonical_form()] = planted

    improved = evaluator.evaluate(tree, 1, _fitted("R1-p(R2,C1)", data))

    assert improved is not None
    assert _fit_cost(improved.result) < _fit_cost(planted.result)
    assert evaluator.cache[circuit.canonical_form()] is improved


def test_warm_accept_zero_switches_inheritance_off() -> None:
    """The control arm the benchmark's sweep needs, asserted as a contract rather than a flag.

    With inheritance off the evaluator must not polish, so a cache hit returns the fit it
    already had -- the same object, not merely an equal one.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    tree = Circuit.parse("R1-p(R2,C1)").root
    parent = _fitted("R1-p(R2,C1)", data)

    cold = _Evaluator(data, "modulus", 1, 12, 30, 1e-5, 0, 0.0)
    first = cold.evaluate(tree, 0)
    assert first is not None
    assert cold.evaluate(tree, 1, parent) is first

    warm = _Evaluator(data, "modulus", 1, 12, 30, 1e-5, 0)
    seeded = warm.evaluate(tree, 0)
    assert seeded is not None
    revisited = warm.evaluate(tree, 1, parent)
    assert revisited is not None
    assert _fit_cost(revisited.result) <= _fit_cost(seeded.result)


# -- The bounded tier 2 ---------------------------------------------------------------------
#
# docs/SEARCH_ALGORITHM_SCREENING.md section 4.6 measured the genetic search finding the truth's
# equivalence class, scoring it 1 of 270, and reporting none of it: the shortlist arrives grouped
# by element count and `_refine`'s deadline fell in the middle of the groups. These two assert
# the order that fixes it, on the return values rather than on a run's luck -- gate EV2's shape.


def _archive(data: Spectrum) -> list[Candidate]:
    """Two fitted candidates at each of three element counts, worst group first.

    The order is adversarial on purpose: it is what `_quota_by_size` hands over -- grouped by
    size, the groups in whatever order the archive first mentioned them -- and the group holding
    the best candidate is last, which is the case that lost the answer.
    """
    return [
        _fitted(text, data)
        for text in (
            "R1-C1-L1",
            "p(R1,C1)-p(R2,C2)",
            "R1-p(R2,C1)-C2",
            "R1-C1",
            "p(R1,C1)",
            "R1-p(R2,C1)",
        )
    ]


def test_the_refit_order_takes_the_best_of_every_size_before_any_size_twice() -> None:
    """A round robin over the element counts, best first within each round.

    Both halves matter and they are the two things the per-size quota exists for. The archive's
    best-scoring candidate has to be refitted first, because a tier that stops early must not
    stop before the answer; and one refit per size has to come before any size's second, because
    a front cut down to the sizes that fitted inside the clock is not a trade-off curve.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    archive = _archive(data)
    best = min(archive, key=lambda c: c.score("aicc"))

    order = _refit_order(archive, "aicc")

    assert order[0] is best, "the best-scoring candidate is not refitted first"
    first_round = [len(c.circuit.leaves) for c in order[:3]]
    assert sorted(first_round) == [2, 3, 4], f"a size was refitted twice first: {first_round}"
    assert len(order) == len(archive)
    assert {id(c) for c in order} == {id(c) for c in archive}


def test_a_refit_stopped_by_its_deadline_still_reports_the_best_candidate() -> None:
    """The defect itself, reduced to one fit: an expired deadline must keep the answer.

    `_refine` always attempts its first candidate -- a report with no rows cannot be read -- so
    a deadline already in the past makes the tier exactly one fit long, and which topology that
    is is the whole question. Before the fix it was whichever element count the caller's list
    happened to start with.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    archive = _archive(data)
    best = min(archive, key=lambda c: c.score("aicc"))

    refined, attempted = _refine(
        archive,
        data,
        "modulus",
        restarts=1,
        seed=0,
        deadline=time.perf_counter() - 1.0,
        criterion="aicc",
    )

    assert attempted == 1
    assert [c.circuit.canonical_form() for c in refined] == [best.circuit.canonical_form()]


# -- The bounded breeding pool --------------------------------------------------------------
#
# docs/EVOLVE_SEARCH_PLAN.md §1.2: breeding from the whole history makes `_tournament` draw 3 of
# N with N growing every generation, so the best-known candidate's chance of being picked falls
# 8.2x over twelve generations. §3.4's first half bounds the set; the frozen-landscape round
# measured that arm at 120/120 against 87/120 (docs/SEARCH_ALGORITHM_SCREENING.md §5).


def test_the_breeding_pool_is_the_front_plus_the_best_and_nothing_else() -> None:
    """The rule itself, on an archive small enough to check by hand."""
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    archive = _archive(data)
    front = pareto_front(archive, "aicc")
    ranked = sorted(archive, key=lambda c: c.score("aicc"))

    pool = _breeding_pool(archive, 2, "aicc")

    assert {id(c) for c in front} <= {id(c) for c in pool}
    assert {id(c) for c in ranked[:2]} <= {id(c) for c in pool}
    assert len(pool) <= len(front) + 2
    assert len(pool) == len({id(c) for c in pool})
    # The order the archive arrives in must not choose between two equal candidates.
    assert [c.circuit.canonical_form() for c in _breeding_pool(archive[::-1], 2, "aicc")] == [
        c.circuit.canonical_form() for c in pool
    ]


def test_the_search_breeds_from_a_bounded_pool_however_long_it_runs(
    monkeypatch: object,
) -> None:
    """The wiring, not just the helper: what `_next_generation` is *given* stops growing.

    A unit test of `_breeding_pool` passes whether or not anything calls it, which is the shape
    of green-and-proves-nothing this project keeps meeting. So this spies on the real search and
    asserts the invariant on every generation -- and then asserts that the archive grew well past
    the bound, because an archive that never got big would satisfy the first assertion for free.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.01,
        seed=0,
    )
    population = 16
    offered: list[tuple[int, int]] = []
    original = discover_module._next_generation

    def spy(alive, rng, pool, max_elements, pop, criterion=discover_module.DEFAULT_CRITERION, **kw):  # type: ignore[no-untyped-def]
        offered.append((len(alive), len(pareto_front(alive, criterion))))
        return original(alive, rng, pool, max_elements, pop, criterion, **kw)

    monkeypatch.setattr(discover_module, "_next_generation", spy)  # type: ignore[attr-defined]
    result = discover(
        data,
        pool=("R", "C", "L"),
        mode="evolve",
        generations=8,
        population=population,
        max_elements=4,
        search_maxiter=30,
        n_refine=3,
        final_restarts=2,
        seed=0,
    )

    assert offered, "the genetic search never bred"
    for n_alive, n_front in offered:
        # The shipped rule is the front itself (`BREEDING_EXTRA`), so this is an equality
        # rather than a bound. An inequality would pass just as well with the front-plus-forty
        # rule the ladder of section 3.4.3 measured as 9x worse.
        assert n_alive == n_front, (
            f"bred from {n_alive} candidates against a front of {n_front}"
        )
    assert result.n_evaluated > max(n for n, _f in offered), (
        "the archive never outgrew the pool, so the bound was never tested"
    )


def test_the_front_alone_and_the_front_plus_its_best_are_the_same_set() -> None:
    """Why `BREEDING_EXTRA` is 0 and not 1: the two are the same rule, not two rungs.

    The ladder of docs/EVOLVE_SEARCH_PLAN.md section 3.4.3 measured them as identical on every
    one of 120 seeds, which is what an identity looks like from the outside. It is one: the
    best-scoring candidate cannot be dominated, so it is already on the front and asking for it
    a second time adds nothing. The reason this is worth a test is that the *measurement* could
    have been read as a coincidence of one arena.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    archive = _archive(data)
    front = [c.circuit.canonical_form() for c in _breeding_pool(archive, 0, "aicc")]

    assert front == [c.circuit.canonical_form() for c in _breeding_pool(archive, 1, "aicc")]
    assert front == [c.circuit.canonical_form() for c in pareto_front(archive, "aicc")]
    # And the default is that rule rather than a number that happens to equal it today.
    assert front == [c.circuit.canonical_form() for c in _breeding_pool(archive, criterion="aicc")]


# -- Step 5: the mutation weights and the crowding penalty -----------------------------------
#
# docs/EVOLVE_SEARCH_PLAN.md §3.5. Both are tuning rather than structure, and both are reachable
# from the benchmarks and from nothing else; what these tests pin is that second half, because
# the numbers themselves are settled by measurement and not by assertion.


def test_the_mutation_weights_choose_the_operator_and_default_to_the_shipped_tuple() -> None:
    """`MUTATION_WEIGHTS` is the operator's own prior over structure, so it has to be aimable.

    The sweep of §3.5 measures arms that differ from the shipped search in this tuple alone, and
    an arm that quietly ignored the tuple it was given would produce a whole table of ties. So
    the weights are asserted to *reach* the choice: a tuple that leaves only one operator
    possible makes every mutation that operator.
    """
    rng = np.random.default_rng(0)
    node = Circuit.parse("R1-C1-p(R2,C2)").root

    retype_only = [mutate(node, rng, ("R", "C", "L"), 6, weights=(1.0, 0.0, 0.0, 0.0))
                   for _ in range(20)]
    assert all(count_elements(child) == 4 for child in retype_only)

    delete_only = [mutate(node, rng, ("R", "C", "L"), 6, weights=(0.0, 0.0, 0.0, 1.0))
                   for _ in range(20)]
    assert all(count_elements(child) == 3 for child in delete_only)

    insert_only = [mutate(node, rng, ("R", "C", "L"), 6, weights=(0.0, 0.5, 0.5, 0.0))
                   for _ in range(20)]
    assert all(count_elements(child) == 5 for child in insert_only)

    assert discover_module.MUTATION_WEIGHTS == (0.35, 0.25, 0.25, 0.15)


def test_neither_step_five_knob_is_reachable_from_discover() -> None:
    """CLAUDE.md's rule, held by the signature rather than by convention.

    "How much should the search prefer deleting an element" and "how hard should a crowded
    complexity be penalised" are exactly the search internals a non-expert cannot set
    correctly, and the project's answer to those is a measured module constant -- the shape
    `BREEDING_EXTRA` already has. A byte-identical wire payload cannot say this; only the
    absence of the parameter can.
    """
    import inspect

    taken = set(inspect.signature(discover).parameters)
    assert not taken & {"weights", "mutation_weights", "parsimony", "parsimony_scaling"}
    assert discover_module.PARSIMONY_SCALING == 0.0


def test_the_crowding_penalty_changes_which_parent_breeds_and_no_reported_number() -> None:
    """PySR's adaptive parsimony, and the one line of it that matters here.

    The archive is deliberately lopsided: the well-scoring candidate sits at the complexity the
    search has already spent almost all of its fits on, and the poor one sits alone. With the
    penalty off, selection is fitness and the crowded candidate is nearly every parent; turned
    up, it is nearly none of them. That is the *whole* intended effect.

    The other half is the invariant §3.5 states: the term may reach the tournament and nothing
    else. So the same candidates are asked for their scores afterwards and must answer exactly
    what they answered before -- a penalty folded into `Candidate.score` would re-rank the
    published report for a reason the report cannot state.
    """
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 8),
        {"R1.R": 50.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=0,
    )
    crowded = _fitted("R1-p(R2,C1)", data)
    lonely = _fitted("R1-C1", data)
    assert crowded.score("aicc") < lonely.score("aicc"), "the fixture must have a clear winner"
    assert crowded.complexity != lonely.complexity
    before = [crowded.score("aicc"), lonely.score("aicc")]

    # 40 fits at the crowded complexity against one at the lonely: what an archive looks like
    # after the search has settled on a size.
    archive = [crowded] * 40 + [lonely]
    frequencies = discover_module._complexity_frequencies(archive)
    assert math.isclose(sum(frequencies.values()), 1.0)

    def parents(parsimony: float, seed: int) -> int:
        offspring = discover_module._next_generation(
            [crowded, lonely],
            np.random.default_rng(seed),
            ("R", "C", "L"),
            5,
            40,
            "aicc",
            frequencies=frequencies,
            parsimony=parsimony,
        )
        return sum(
            1
            for _tree, parent in offspring
            if parent is not None and parent.complexity == crowded.complexity
        )

    # Compared seed by seed rather than as two totals, for the reason §3.4.4 of the plan gives
    # about every other comparison in this round: a threshold on one draw of a stochastic count
    # is a threshold on the draw. A two-member pool also caps the effect -- a tournament of
    # three drawn with replacement from two picks the crowded one only 3 times in 4, so "every
    # parent" is about 30 of 40 and not 40.
    off = [parents(0.0, seed) for seed in range(5)]
    on = [parents(1e6, seed) for seed in range(5)]
    assert all(a > b for a, b in zip(off, on, strict=True)), (
        f"the crowding penalty did not move selection: {off} against {on}"
    )
    assert min(off) > 20, f"fitness selection did not favour the better score ({off})"
    assert max(on) < 20, f"the crowding penalty left the crowded parent in charge ({on})"

    assert [crowded.score("aicc"), lonely.score("aicc")] == before
