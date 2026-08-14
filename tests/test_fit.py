"""Fitting-engine tests.

The central claim of AutoCircuit is that a user never has to supply initial parameter values.
These tests hold that claim to account: every fit below starts from nothing but the data, and
is required to recover parameters that span fifteen orders of magnitude.
"""

from __future__ import annotations

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import (  # _Problem is private: exercised directly, see below
    _Problem,
    fit,
    search_space,
    weight_vectors,
)
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum

# (label, circuit, true parameters, f_min, f_max)
SYNTHETIC_SUITE = [
    ("series RC", "R1-C1", {"R1.R": 25.0, "C1.C": 4.7e-6}, 1e0, 1e6),
    ("parallel RC", "p(R1,C1)", {"R1.R": 1e4, "C1.C": 1e-9}, 1e0, 1e7),
    (
        "capacitor with ESR and ESL",
        "C1-R1-L1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        1e2,
        1e9,
    ),
    (
        "capacitor with skin effect",
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        1e2,
        1e9,
    ),
    (
        "Randles cell",
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 100.0, "W1.A": 150.0},
        1e-2,
        1e5,
    ),
    (
        "Maxwell-Wagner, two blocks",
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        1e-1,
        1e7,
    ),
    (
        "brick layer with CPE",
        "R1-p(R2,C1)-p(R3,CPE1)",
        {
            "R1.R": 50.0,
            "R2.R": 1e4,
            "C1.C": 1e-10,
            "R3.R": 8e4,
            "CPE1.Q": 3e-9,
            "CPE1.n": 0.8,
        },
        1e-1,
        1e7,
    ),
    (
        "depressed semicircle",
        "R1-p(R2,CPE1)",
        {"R1.R": 12.0, "R2.R": 500.0, "CPE1.Q": 2e-6, "CPE1.n": 0.75},
        1e-1,
        1e6,
    ),
    (
        "skin effect on a wire",
        "R1-L1-SKINW1",
        {"R1.R": 5e-3, "L1.L": 1e-8, "SKINW1.Rdc": 2e-2, "SKINW1.tau_s": 1e-7},
        1e2,
        1e9,
    ),
]


def _canonical_params(circuit: Circuit, values: dict[str, float] | np.ndarray) -> dict[str, float]:
    """Parameters in canonical branch order, so a relabelling is not counted as an error."""
    array = circuit.values_array(values) if isinstance(values, dict) else np.asarray(values)
    return circuit.values_dict(circuit.canonicalize_values(array))


@pytest.mark.parametrize(
    ("label", "dsl", "truth", "f_min", "f_max"),
    SYNTHETIC_SUITE,
    ids=[case[0] for case in SYNTHETIC_SUITE],
)
def test_recovers_parameters_from_noise_free_data(
    label: str, dsl: str, truth: dict[str, float], f_min: float, f_max: float
) -> None:
    """With clean data the fit must land on the true parameters, starting from no guess."""
    circuit = Circuit.parse(dsl)
    data = simulate(circuit, log_frequencies(f_min, f_max, 10), truth, seed=0)
    result = fit(circuit, data, seed=0)

    expected = _canonical_params(circuit, truth)
    got = _canonical_params(circuit, result.values)
    for name, value in expected.items():
        assert got[name] == pytest.approx(value, rel=1e-3), f"{label}: {name}"
    assert result.relative_error(data) < 1e-6


@pytest.mark.parametrize(
    ("label", "dsl", "truth", "f_min", "f_max"),
    SYNTHETIC_SUITE,
    ids=[case[0] for case in SYNTHETIC_SUITE],
)
def test_recovers_parameters_from_noisy_data(
    label: str, dsl: str, truth: dict[str, float], f_min: float, f_max: float
) -> None:
    """With 1% noise the fit must still track the data and stay near the true parameters."""
    circuit = Circuit.parse(dsl)
    data = simulate(circuit, log_frequencies(f_min, f_max, 10), truth, noise=0.01, seed=11)
    result = fit(circuit, data, seed=0)

    assert result.relative_error(data) < 0.03
    expected = _canonical_params(circuit, truth)
    got = _canonical_params(circuit, result.values)
    stderr = dict(zip(circuit.param_names, result.statistics.stderr, strict=True))
    for name, value in expected.items():
        deviation = abs(got[name] - value)
        # Either close in relative terms, or inside a generous multiple of the reported
        # uncertainty. A parameter that is genuinely hard to resolve must at least *say* so.
        assert deviation <= 0.15 * abs(value) or deviation <= 5.0 * stderr[name], (
            f"{label}: {name} off by {deviation:.3g} "
            f"(value {value:.3g}, stderr {stderr[name]:.3g})"
        )


def test_fit_is_reproducible_from_seed() -> None:
    circuit = Circuit.parse("R1-p(R2,CPE1)")
    truth = {"R1.R": 12.0, "R2.R": 500.0, "CPE1.Q": 2e-6, "CPE1.n": 0.75}
    data = simulate(circuit, log_frequencies(1e-1, 1e6, 10), truth, noise=0.01, seed=2)
    first = fit(circuit, data, seed=7)
    second = fit(circuit, data, seed=7)
    np.testing.assert_allclose(first.values, second.values, rtol=1e-12)


def test_fit_accepts_a_circuit_string() -> None:
    truth = {"R1.R": 25.0, "C1.C": 4.7e-6}
    data = simulate("R1-C1", log_frequencies(1e0, 1e6, 10), truth, seed=0)
    result = fit("R1-C1", data, seed=0)
    assert result.params["R1.R"] == pytest.approx(25.0, rel=1e-4)


def test_fixed_parameters_are_held_exactly() -> None:
    circuit = Circuit.parse("C1-R1-L1")
    truth = {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}
    data = simulate(circuit, log_frequencies(1e2, 1e9, 10), truth, noise=0.005, seed=3)
    result = fit(circuit, data, fixed={"L1.L": 5e-10}, seed=0)

    assert result.params["L1.L"] == 5e-10
    assert result.statistics.n_params == 2
    assert result.params["C1.C"] == pytest.approx(1e-6, rel=0.02)


def test_fixing_every_parameter_is_rejected() -> None:
    data = simulate("R1-C1", log_frequencies(1.0, 1e5, 5), {"R1.R": 10.0, "C1.C": 1e-6}, seed=0)
    with pytest.raises(ValueError, match="all parameters are fixed"):
        fit("R1-C1", data, fixed={"R1.R": 10.0, "C1.C": 1e-6})


def test_unknown_parameter_names_are_rejected() -> None:
    data = simulate("R1-C1", log_frequencies(1.0, 1e5, 5), {"R1.R": 10.0, "C1.C": 1e-6}, seed=0)
    with pytest.raises(ValueError, match="unknown"):
        fit("R1-C1", data, fixed={"R9.R": 1.0})
    with pytest.raises(ValueError, match="unknown"):
        fit("R1-C1", data, bounds={"R9.R": (1.0, 2.0)})
    with pytest.raises(ValueError, match="unknown"):
        fit("R1-C1", data, initial={"R9.R": 1.0})


def test_explicit_bounds_are_respected() -> None:
    circuit = Circuit.parse("R1-C1")
    truth = {"R1.R": 25.0, "C1.C": 4.7e-6}
    data = simulate(circuit, log_frequencies(1e0, 1e6, 10), truth, seed=0)
    result = fit(circuit, data, bounds={"R1.R": (100.0, 200.0)}, seed=0)
    assert 100.0 <= result.params["R1.R"] <= 200.0


def test_local_refinement_requires_an_initial_guess() -> None:
    data = simulate("R1-C1", log_frequencies(1.0, 1e5, 5), {"R1.R": 10.0, "C1.C": 1e-6}, seed=0)
    with pytest.raises(ValueError, match="requires an initial guess"):
        fit("R1-C1", data, global_search=False)


def test_local_refinement_from_a_good_guess_converges() -> None:
    circuit = Circuit.parse("C1-R1-L1")
    truth = {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}
    data = simulate(circuit, log_frequencies(1e2, 1e9, 10), truth, seed=0)
    guess = {"C1.C": 1.5e-6, "R1.R": 3e-2, "L1.L": 2e-10}
    result = fit(circuit, data, initial=guess, global_search=False, seed=0)
    for name, value in truth.items():
        assert result.params[name] == pytest.approx(value, rel=1e-3)


def test_degenerate_model_is_flagged_rather_than_reported_confidently() -> None:
    """Fitting a two-CPE-block model to single-relaxation data must warn, not stay silent."""
    data = simulate(
        "R1-p(R2,C1)",
        log_frequencies(1e-1, 1e6, 10),
        {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8},
        noise=0.005,
        seed=4,
    )
    result = fit("R1-p(R2,CPE1)-p(R3,CPE2)", data, seed=0)
    assert result.warnings, "an over-parameterised fit reported no warnings at all"


def test_bad_weighting_name_is_rejected() -> None:
    z = np.array([1 + 1j, 2 + 2j])
    with pytest.raises(ValueError, match="unknown weighting"):
        weight_vectors(z, "nonsense")  # type: ignore[arg-type]


def test_sigma_weighting_requires_sigma() -> None:
    z = np.array([1 + 1j, 2 + 2j])
    with pytest.raises(ValueError, match="requires the sigma"):
        weight_vectors(z, "sigma")
    with pytest.raises(ValueError, match="strictly positive"):
        weight_vectors(z, "sigma", np.array([1.0, 0.0]))


def test_weighting_schemes_have_the_expected_shape() -> None:
    z = np.array([3 + 4j, 30 + 40j])
    unit_re, unit_im = weight_vectors(z, "unit")
    np.testing.assert_allclose(unit_re, [1.0, 1.0])
    np.testing.assert_allclose(unit_im, [1.0, 1.0])

    mod_re, mod_im = weight_vectors(z, "modulus")
    np.testing.assert_allclose(mod_re, [1 / 5.0, 1 / 50.0])
    np.testing.assert_allclose(mod_re, mod_im)

    prop_re, prop_im = weight_vectors(z, "proportional")
    np.testing.assert_allclose(prop_re, [1 / 3.0, 1 / 30.0])
    np.testing.assert_allclose(prop_im, [1 / 4.0, 1 / 40.0])


def test_modulus_weighting_beats_unit_weighting_on_a_wide_dynamic_range() -> None:
    """A capacitor spans five decades of |Z|; unit weighting ignores the low-|Z| region."""
    circuit = Circuit.parse("C1-R1-L1")
    truth = {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}
    data = simulate(circuit, log_frequencies(1e2, 1e9, 10), truth, noise=0.01, seed=5)

    modulus = fit(circuit, data, weighting="modulus", seed=0)
    unit = fit(circuit, data, weighting="unit", seed=0)
    # ESR sits at the bottom of the |Z| curve, exactly where unit weighting has no leverage.
    modulus_error = abs(modulus.params["R1.R"] - truth["R1.R"]) / truth["R1.R"]
    unit_error = abs(unit.params["R1.R"] - truth["R1.R"]) / truth["R1.R"]
    assert modulus_error < unit_error


def test_result_serialises_to_json_friendly_types() -> None:
    import json

    circuit = Circuit.parse("R1-C1")
    data = simulate(circuit, log_frequencies(1.0, 1e5, 10), {"R1.R": 10.0, "C1.C": 1e-6}, seed=0)
    payload = fit(circuit, data, seed=0).to_dict()
    text = json.dumps(payload)
    restored = json.loads(text)
    assert restored["circuit"] == "R1-C1"
    assert set(restored["parameters"]) == set(circuit.param_names)
    assert restored["statistics"]["n_params"] == 2


def test_summary_mentions_every_parameter() -> None:
    circuit = Circuit.parse("C1-R1-L1")
    truth = {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}
    data = simulate(circuit, log_frequencies(1e2, 1e9, 10), truth, seed=0)
    text = fit(circuit, data, seed=0).summary(data)
    for name in circuit.param_names:
        assert name in text
    assert "chi^2" in text


def test_fit_handles_a_spectrum_built_by_hand() -> None:
    f = np.logspace(0, 5, 40)
    z = 10.0 + 1.0 / (1j * 2 * np.pi * f * 1e-6)
    result = fit("R1-C1", Spectrum(f, z), seed=0)
    assert result.params["R1.R"] == pytest.approx(10.0, rel=1e-4)
    assert result.params["C1.C"] == pytest.approx(1e-6, rel=1e-4)


# =============================================================================================
# search_space / _Problem
#
# `_Problem` calls `search_space` internally and must use exactly what it returns: the same
# starting point, and the same log-transformed bounds. `_Problem` keeps only the transformed
# bounds (`lower_x`/`upper_x`, restricted to the free parameters), so the comparison below
# reproduces that transform from `search_space`'s own (lower, upper) rather than reaching into
# a second, private copy of it.
# =============================================================================================


def _expected_x_bounds(
    lower: np.ndarray, upper: np.ndarray, free_idx: np.ndarray, log_mask_all: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    log_mask = log_mask_all[free_idx]
    lo, hi = lower[free_idx], upper[free_idx]
    lo_x = np.where(log_mask, np.log10(np.maximum(lo, 1e-300)), lo)
    hi_x = np.where(log_mask, np.log10(np.maximum(hi, 1e-299)), hi)
    return lo_x, hi_x


def test_problem_template_and_bounds_match_search_space_without_overrides() -> None:
    circuit = Circuit.parse("R1-p(R2,C1)")
    data = simulate(
        circuit,
        log_frequencies(1e1, 1e5, 6),
        {"R1.R": 12.0, "R2.R": 800.0, "C1.C": 5e-8},
        noise=0.01,
        seed=4,
    )
    lower, upper, start = search_space(circuit, data)
    problem = _Problem(circuit, data, "modulus", None, {}, None, 3.0)

    assert np.array_equal(problem.template, start)
    expected_lo_x, expected_hi_x = _expected_x_bounds(
        lower, upper, problem.free_idx, circuit.log_mask()
    )
    assert np.array_equal(problem.lower_x, expected_lo_x)
    assert np.array_equal(problem.upper_x, expected_hi_x)


def test_problem_template_and_bounds_match_search_space_with_fixed_and_bounds_overrides() -> None:
    circuit = Circuit.parse("C1-R1-L1")
    data = simulate(
        circuit,
        log_frequencies(1e2, 1e9, 8),
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
        noise=0.005,
        seed=3,
    )
    fixed = {"L1.L": 5e-10}
    bounds = {"R1.R": (1e-3, 1.0)}
    lower, upper, start = search_space(circuit, data, fixed=fixed, bounds=bounds)
    problem = _Problem(circuit, data, "modulus", None, fixed, bounds, 3.0)

    assert np.array_equal(problem.template, start)
    l1_index = circuit.param_names.index("L1.L")
    assert start[l1_index] == 5e-10
    assert problem.template[l1_index] == 5e-10

    expected_lo_x, expected_hi_x = _expected_x_bounds(
        lower, upper, problem.free_idx, circuit.log_mask()
    )
    assert np.array_equal(problem.lower_x, expected_lo_x)
    assert np.array_equal(problem.upper_x, expected_hi_x)


def test_search_space_rejects_unknown_fixed_parameter_names() -> None:
    circuit = Circuit.parse("R1-C1")
    data = simulate(circuit, log_frequencies(1.0, 1e5, 5), {"R1.R": 10.0, "C1.C": 1e-6}, seed=0)
    with pytest.raises(ValueError, match="unknown"):
        search_space(circuit, data, fixed={"R9.R": 1.0})


def test_search_space_rejects_unknown_bounds_parameter_names() -> None:
    circuit = Circuit.parse("R1-C1")
    data = simulate(circuit, log_frequencies(1.0, 1e5, 5), {"R1.R": 10.0, "C1.C": 1e-6}, seed=0)
    with pytest.raises(ValueError, match="unknown"):
        search_space(circuit, data, bounds={"R9.R": (1.0, 2.0)})
