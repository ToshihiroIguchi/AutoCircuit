"""Tests for the spectrum-derived noise scale, ``docs/IMPACT_PLAN.md`` item B."""

from __future__ import annotations

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import fit
from autocircuit.core.noise import estimate_sigma, resolve_weights
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.weighting import weight_vectors

TRUTH = {"R1.R": 20.0, "R2.R": 1e3, "C1.C": 1e-8}
DENSE = log_frequencies(1e1, 1e7, 10)  # 61 points, 6 decades, 10 per decade


def test_estimate_sigma_is_strictly_positive_on_noise_free_data() -> None:
    """``weight_vectors``'s ``"sigma"`` case requires it, and a round-trip test builds exactly
    this: a spectrum with zero residual everywhere."""
    data = simulate("R1-p(R2,C1)", DENSE, TRUTH, seed=0)
    sigma = estimate_sigma(data)
    assert np.all(sigma > 0.0)
    assert np.all(np.isfinite(sigma))


def test_estimate_sigma_recovers_proportional_noise_level() -> None:
    """1% proportional noise (``simulate``'s default model) must come back as about 1% of |Z|.

    Generous bounds: this is a model-free estimator reading a noise level off 61 points, not a
    fitter with the true circuit in hand. What matters is that it lands within a factor of two
    of the truth, on the *typical* point -- the self-resonance / sharpest-curvature points are
    allowed to read high (see ``core/noise.py``'s module docstring) and are exactly why the
    check is a median over the whole spectrum rather than a per-point bound.
    """
    data = simulate("R1-p(R2,C1)", DENSE, TRUTH, noise=0.01, seed=3)
    sigma = estimate_sigma(data)
    ratio = sigma / np.abs(data.z)
    assert 0.005 <= float(np.median(ratio)) <= 0.02


def test_estimate_sigma_handles_two_widely_separated_relaxations() -> None:
    """Maxwell-Wagner (``docs/IMPACT_PLAN.md`` item B section 2.2): the shape a *fixed*-window
    smoother got wrong by up to 100x, and the reason this module cross-validates its window
    instead of using one constant for every spectrum.
    """
    circuit = "p(R1,C1)-p(R2,C2)"
    truth = {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8}
    data = simulate(circuit, log_frequencies(1e-1, 1e7, 10), truth, noise=0.01, seed=0)
    sigma = estimate_sigma(data)
    ratio = sigma / (0.01 * np.abs(data.z))
    assert 0.5 <= float(np.median(ratio)) <= 2.0


def test_estimate_sigma_recovers_absolute_noise_level() -> None:
    """The other noise family ``simulate`` supports: a flat sigma in ohms, not a fraction of |Z|.

    ``R1-p(R2,C1)`` spans |Z| from about 20 to 1000 ohms over this window, so a flat 5 ohm noise
    floor is a small fraction of |Z| at the high end and a large one at the low end -- a shape
    ``estimate_sigma`` has no reason to know about in advance, unlike the proportional case above.
    """
    data = simulate("R1-p(R2,C1)", DENSE, TRUTH, noise=5.0, noise_model="absolute", seed=3)
    sigma = estimate_sigma(data)
    assert 2.5 <= float(np.median(sigma)) <= 10.0


def test_resolve_weights_matches_manual_sigma_dispatch_under_auto() -> None:
    data = simulate("R1-p(R2,C1)", DENSE, TRUTH, noise=0.01, seed=0)
    w_re, w_im = resolve_weights(data, "auto")
    expected_re, expected_im = weight_vectors(data.z, "sigma", sigma=estimate_sigma(data))
    np.testing.assert_array_equal(w_re, expected_re)
    np.testing.assert_array_equal(w_im, expected_im)


@pytest.mark.parametrize("weighting", ["unit", "modulus", "proportional"])
def test_resolve_weights_is_a_pure_passthrough_for_every_other_weighting(weighting: str) -> None:
    """The one property gate N0 in ``docs/IMPACT_PLAN.md`` depends on: nothing about the four
    pre-existing weightings has a second code path to go out of sync with ``weight_vectors``."""
    data = simulate("R1-p(R2,C1)", DENSE, TRUTH, noise=0.01, seed=0)
    w_re, w_im = resolve_weights(data, weighting)  # type: ignore[arg-type]
    expected_re, expected_im = weight_vectors(data.z, weighting)  # type: ignore[arg-type]
    np.testing.assert_array_equal(w_re, expected_re)
    np.testing.assert_array_equal(w_im, expected_im)


def test_resolve_weights_rejects_an_explicit_sigma_under_auto() -> None:
    data = simulate("R1-p(R2,C1)", DENSE, TRUTH, seed=0)
    with pytest.raises(ValueError, match="not accepted with weighting"):
        resolve_weights(data, "auto", sigma=np.ones(data.n))


def test_estimate_sigma_inflates_rather_than_deflates_near_an_anti_resonance() -> None:
    """Gate N4's premise (``docs/IMPACT_PLAN.md`` item B section 2.2): a genuine parallel
    resonance is not fixed by this design -- no local smoother tracks a pole -- but the failure
    must be over-estimation, not under-estimation, because a fit trusts an under-estimated sigma
    and that is the dangerous direction. This does not assert the estimate is *usable* there
    (see the next test for that); only that it errs the safe way.
    """
    data = simulate(
        "R1-p(R2,L1,C1)", log_frequencies(1e4, 1e9, 10),
        {"R1.R": 0.1, "R2.R": 1e4, "L1.L": 1e-6, "C1.C": 1e-11}, noise=0.01, seed=0,
    )
    sigma = estimate_sigma(data)
    ratio = sigma / (0.01 * np.abs(data.z))
    assert float(np.median(ratio)) >= 1.0


def test_fit_recovers_a_resonance_despite_local_sigma_inflation_under_auto() -> None:
    """Gate N4: does the safe-direction argument above actually hold at the fitter, or only in
    the abstract? ``R1-p(R2,L1,C1)`` (a ferrite bead) has the anti-resonance the estimator
    cannot track, and the parsimony this project cares about is whether the fit still lands on
    the true parameters despite that region being locally down-weighted rather than ignored.
    """
    circuit = Circuit.parse("R1-p(R2,L1,C1)")
    truth = {"R1.R": 0.1, "R2.R": 1e4, "L1.L": 1e-6, "C1.C": 1e-11}
    data = simulate(circuit, log_frequencies(1e4, 1e9, 10), truth, noise=0.01, seed=7)
    result = fit(circuit, data, weighting="auto", seed=0)

    assert result.relative_error < 0.05
    got = circuit.values_dict(result.values)
    for name, value in truth.items():
        assert got[name] == pytest.approx(value, rel=0.2)


def test_fit_recovers_parameters_from_noisy_data_under_auto_weighting() -> None:
    """The round-trip test every fitter feature gets (``CLAUDE.md``), for ``weighting="auto"``.

    Same shape as ``test_fit.py::test_recovers_parameters_from_noisy_data``, because that is
    exactly the contract ``"auto"`` must also satisfy: no initial values, no true circuit
    handed to the noise estimate, and the fit still lands near the truth.
    """
    circuit = Circuit.parse("R1-p(R2,C1)")
    data = simulate(circuit, DENSE, TRUTH, noise=0.01, seed=11)
    result = fit(circuit, data, weighting="auto", seed=0)

    assert result.relative_error < 0.03
    got = circuit.values_dict(result.values)
    for name, value in TRUTH.items():
        assert got[name] == pytest.approx(value, rel=0.15)
