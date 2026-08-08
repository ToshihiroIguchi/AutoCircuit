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

import numpy as np

from autocircuit.core.circuit import Circuit, count_elements, simplify
from autocircuit.core.discover import (
    Candidate,
    crossover,
    discover,
    is_plausible,
    mutate,
    pareto_front,
    random_topology,
)
from autocircuit.core.simulate import log_frequencies, simulate

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
        def __init__(self, complexity: float, aicc: float) -> None:
            self.complexity = complexity
            self.aicc = aicc
            self.circuit = complexity

    points = [Fake(1.0, 10.0), Fake(2.0, 5.0), Fake(3.0, 6.0), Fake(2.0, 8.0)]
    front = pareto_front(points)  # type: ignore[arg-type]
    assert [(p.complexity, p.aicc) for p in front] == [(1.0, 10.0), (2.0, 5.0)]


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
