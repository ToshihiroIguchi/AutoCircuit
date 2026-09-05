"""Tests for multi-condition joint fitting (docs/IMPACT_PLAN.md section 3).

Fits here use small point counts and few restarts throughout -- the numeric engine under test
is the same ``least_squares``/``compute_statistics`` machinery :mod:`autocircuit.core.fit`
already has extensive coverage for, so what these tests check is the *joint* bookkeeping
(status assignment, the Arrhenius reparameterisation, pooled statistics), not fit quality in
general. ``benchmarks/multi_condition.py`` carries the full-scale, publication-grade gates
(A1-A4) this feature is measured against.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from autocircuit.core.circuit import Circuit
from autocircuit.core.multicondition import (
    BOLTZMANN_EV_PER_K,
    _param_class,
    _present_classes,
    discover_set,
    fit_joint,
    select_level2,
)
from autocircuit.core.spectrum import Spectrum, SpectrumSet


def _make_spectrum(circuit: Circuit, values: np.ndarray, f: np.ndarray, seed: int) -> Spectrum:
    rng = np.random.default_rng(seed)
    omega = 2 * np.pi * f
    z = circuit.impedance(omega, values)
    noise = (
        0.01 * np.abs(z) * (rng.normal(size=z.shape) + 1j * rng.normal(size=z.shape)) / np.sqrt(2)
    )
    return Spectrum(f, z + noise)


class TestSpectrumSet:
    def test_rejects_length_mismatch(self) -> None:
        f = np.geomspace(1.0, 1e4, 11)
        sp = Spectrum(f, np.ones_like(f, dtype=complex))
        with pytest.raises(ValueError, match="must match"):
            SpectrumSet((sp, sp), (1.0,))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            SpectrumSet((), ())

    def test_n_conditions_and_len(self) -> None:
        f = np.geomspace(1.0, 1e4, 11)
        sp = Spectrum(f, np.ones_like(f, dtype=complex))
        sset = SpectrumSet((sp, sp), (300.0, 350.0), "temperature_K")
        assert sset.n_conditions == 2
        assert len(sset) == 2

    def test_default_condition_kind_is_index(self) -> None:
        f = np.geomspace(1.0, 1e4, 11)
        sp = Spectrum(f, np.ones_like(f, dtype=complex))
        sset = SpectrumSet((sp,), (0.0,))
        assert sset.condition_kind == "index"


class TestParamClass:
    def test_resistor_is_resistive(self) -> None:
        circuit = Circuit.parse("R1")
        assert _param_class(circuit.param_specs()[0]) == "resistive"

    def test_capacitor_and_inductor_are_reactive(self) -> None:
        circuit = Circuit.parse("C1-L1")
        specs = circuit.param_specs()
        assert _param_class(specs[0]) == "reactive"
        assert _param_class(specs[1]) == "reactive"

    def test_cpe_exponent_falls_to_other(self) -> None:
        circuit = Circuit.parse("CPE1")
        specs = circuit.param_specs()  # Q, then n
        assert _param_class(specs[0]) == "other"
        assert _param_class(specs[1]) == "other"

    def test_present_classes_is_deterministic_and_deduplicated(self) -> None:
        circuit = Circuit.parse("R1-p(R2,C1)")
        assert _present_classes(circuit) == ("resistive", "reactive")


class TestFitJoint:
    def test_shared_reactive_recovers_one_capacitance_across_conditions(self) -> None:
        f = np.geomspace(1e2, 1e5, 31)
        circuit = Circuit.parse("R1-C1")
        c_true = 2e-7
        spectra = []
        conditions = (0.0, 1.0)
        for i, r_true in enumerate((100.0, 400.0)):
            spectra.append(_make_spectrum(circuit, np.array([r_true, c_true]), f, seed=i))
        sset = SpectrumSet(tuple(spectra), conditions, "index")

        result = fit_joint(
            circuit, sset, {"resistive": "free", "reactive": "shared"}, seed=0, restarts=2
        )
        assert result.per_condition[0].values[0] == pytest.approx(100.0, rel=0.05)
        assert result.per_condition[1].values[0] == pytest.approx(400.0, rel=0.05)
        # Both conditions' capacitance slot must be the identical shared value.
        assert result.per_condition[0].values[1] == result.per_condition[1].values[1]
        assert result.per_condition[0].values[1] == pytest.approx(c_true, rel=0.05)
        assert result.relative_error < 0.05

    def test_lawful_resistance_recovers_arrhenius_law(self) -> None:
        f = np.geomspace(1e1, 1e6, 41)
        circuit = Circuit.parse("R1-C1")
        ea_true = 0.2
        x0_true = 500.0 / math.exp(ea_true / (BOLTZMANN_EV_PER_K * 300.0))
        c_true = 1e-7
        temps = (300.0, 340.0, 380.0)
        spectra = []
        for i, temperature in enumerate(temps):
            r = x0_true * math.exp(ea_true / (BOLTZMANN_EV_PER_K * temperature))
            spectra.append(_make_spectrum(circuit, np.array([r, c_true]), f, seed=i))
        sset = SpectrumSet(tuple(spectra), temps, "temperature_K")

        result = fit_joint(
            circuit, sset, {"resistive": "lawful", "reactive": "shared"}, seed=0, restarts=3
        )
        law = result.laws["R1.R"]
        assert law.ea_ev == pytest.approx(ea_true, abs=3 * law.ea_stderr + 0.02)
        assert result.relative_error < 0.05

    def test_lawful_law_is_centred_at_the_first_condition_not_at_t_infinity(self) -> None:
        """Regression test: an x0-at-T-infinity parameterisation put the true prefactor below
        the resistor's own hard lower bound for an ordinary 0.3-0.8 eV activation energy,
        landing the joint fit ~1000x worse than the equivalent "free" fit (chi2_reduced ~1244
        vs ~1.28). Centring the law at the first condition's own temperature keeps the fitted
        reference value inside the same bounds "shared"/"free" already use.
        """
        f = np.geomspace(1.0, 1e6, 61)
        circuit = Circuit.parse("R1-C1")
        ea_true = 0.8  # deliberately large: exp(0.8/(kB*300)) ~ 2.8e13
        temps = (300.0, 350.0, 400.0)
        x_ref_true = 2000.0
        c_true = 1e-6
        spectra = []
        for i, temperature in enumerate(temps):
            r = x_ref_true * math.exp(
                ea_true
                * (1.0 / (BOLTZMANN_EV_PER_K * temperature) - 1.0 / (BOLTZMANN_EV_PER_K * temps[0]))
            )
            spectra.append(_make_spectrum(circuit, np.array([r, c_true]), f, seed=i))
        sset = SpectrumSet(tuple(spectra), temps, "temperature_K")

        lawful = fit_joint(
            circuit, sset, {"resistive": "lawful", "reactive": "shared"}, seed=0, restarts=3
        )
        free = fit_joint(
            circuit, sset, {"resistive": "free", "reactive": "shared"}, seed=0, restarts=3
        )
        assert lawful.statistics.chi2_reduced < 5 * free.statistics.chi2_reduced
        law = lawful.laws["R1.R"]
        assert law.t_ref == temps[0]
        assert law.x_ref == pytest.approx(x_ref_true, rel=0.1)
        assert law.ea_ev == pytest.approx(ea_true, abs=3 * law.ea_stderr + 0.05)

    def test_lawful_status_requires_temperature_condition_kind(self) -> None:
        f = np.geomspace(1e2, 1e5, 21)
        circuit = Circuit.parse("R1-C1")
        spectra = tuple(
            _make_spectrum(circuit, np.array([100.0, 1e-7]), f, seed=i) for i in range(2)
        )
        sset = SpectrumSet(spectra, (0.0, 1.0), "index")
        with pytest.raises(ValueError, match="temperature_K"):
            fit_joint(circuit, sset, {"resistive": "lawful", "reactive": "shared"})

    def test_lawful_status_requires_at_least_two_conditions(self) -> None:
        f = np.geomspace(1e2, 1e5, 21)
        circuit = Circuit.parse("R1-C1")
        sset = SpectrumSet(
            (_make_spectrum(circuit, np.array([100.0, 1e-7]), f, seed=0),),
            (300.0,),
            "temperature_K",
        )
        with pytest.raises(ValueError, match="at least two"):
            fit_joint(circuit, sset, {"resistive": "lawful", "reactive": "shared"})

    def test_status_missing_a_present_class_is_an_error(self) -> None:
        f = np.geomspace(1e2, 1e5, 21)
        circuit = Circuit.parse("R1-C1")
        spectra = tuple(
            _make_spectrum(circuit, np.array([100.0, 1e-7]), f, seed=i) for i in range(2)
        )
        sset = SpectrumSet(spectra, (0.0, 1.0), "index")
        with pytest.raises(ValueError, match="missing"):
            fit_joint(circuit, sset, {"resistive": "free"})


class TestSelectLevel2:
    def test_prefers_lawful_when_the_data_was_generated_that_way(self) -> None:
        f = np.geomspace(1e1, 1e6, 41)
        circuit = Circuit.parse("R1-C1")
        ea_true = 0.15
        x0_true = 300.0 / math.exp(ea_true / (BOLTZMANN_EV_PER_K * 300.0))
        c_true = 1e-7
        temps = (300.0, 330.0, 360.0, 390.0)
        spectra = []
        for i, temperature in enumerate(temps):
            r = x0_true * math.exp(ea_true / (BOLTZMANN_EV_PER_K * temperature))
            spectra.append(_make_spectrum(circuit, np.array([r, c_true]), f, seed=i))
        sset = SpectrumSet(tuple(spectra), temps, "temperature_K")

        best = select_level2(circuit, sset, seed=0, restarts=3)
        assert best.status["resistive"] == "lawful"


class TestDiscoverSet:
    def test_pools_two_conditions_and_reports_pareto_and_recommended(self) -> None:
        f = np.geomspace(1e2, 1e5, 31)
        truth = Circuit.parse("R1-C1")
        spectra = tuple(
            _make_spectrum(truth, np.array([r, 1e-7]), f, seed=i)
            for i, r in enumerate((80.0, 120.0))
        )
        sset = SpectrumSet(spectra, (0.0, 1.0), "index")

        result = discover_set(
            sset,
            pool=("R", "C"),
            exhaustive_limit=2,
            seed=0,
            refit_top_k=5,
        )
        assert result.candidates
        assert result.complete_up_to is not None and result.complete_up_to >= 1
        assert result.recommended is not None
        truth_form = truth.canonical_form()
        assert any(c.circuit.canonical_form() == truth_form for c in result.pareto)

    def test_set_candidate_pools_ssr_and_scales_params_by_condition_count(self) -> None:
        f = np.geomspace(1e2, 1e5, 31)
        truth = Circuit.parse("R1-C1")
        spectra = tuple(
            _make_spectrum(truth, np.array([r, 1e-7]), f, seed=i)
            for i, r in enumerate((80.0, 120.0, 150.0))
        )
        sset = SpectrumSet(spectra, (0.0, 1.0, 2.0), "index")
        result = discover_set(sset, pool=("R", "C"), exhaustive_limit=2, seed=0, refit_top_k=5)
        recommended = result.recommended
        assert recommended is not None
        expected_params = recommended.per_condition[0].statistics.n_params * 3
        assert recommended.n_params_total == expected_params
        expected_data = sum(fr.statistics.n_data for fr in recommended.per_condition)
        assert recommended.n_data_total == expected_data
