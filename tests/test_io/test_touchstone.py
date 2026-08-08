from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.testing import assert_allclose

from autocircuit.io import read, touchstone

DATA = Path(__file__).parent / "data"

FREQS = [1.0e3, 1.0e4, 1.0e5, 1.0e6]
Z0 = 50.0
R_ESR = 0.05
C_CAP = 10.0e-6


def _expected_z() -> np.ndarray:
    w = 2.0 * np.pi * np.asarray(FREQS)
    return R_ESR - 1j / (w * C_CAP)


def test_1port_s_parameter_round_trip() -> None:
    spec = touchstone.read(DATA / "cap_1port.s1p")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z, _expected_z(), rtol=1e-6)


def test_1port_capacitive_sign() -> None:
    spec = touchstone.read(DATA / "cap_1port.s1p")
    assert np.all(spec.z.imag < 0)
    assert spec.metadata["port_config"] == "one_port"
    assert spec.metadata["reference_impedance"] == Z0


def test_2port_series_thru_round_trip() -> None:
    spec = touchstone.read(DATA / "cap_series_thru.s2p", port_config="series_thru")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z, _expected_z(), rtol=1e-6)


def test_2port_shunt_thru_round_trip() -> None:
    spec = touchstone.read(DATA / "cap_shunt_thru.s2p", port_config="shunt_thru")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z, _expected_z(), rtol=1e-6)


def test_2port_default_port_config_is_series_thru_with_warning() -> None:
    spec = touchstone.read(DATA / "cap_series_thru.s2p")
    assert_allclose(spec.z, _expected_z(), rtol=1e-6)
    assert spec.metadata["port_config"] == "series_thru"
    assert any("shunt_thru" in w for w in spec.metadata["warnings"])


def test_shunt_thru_wrong_config_gives_wrong_answer() -> None:
    # Sanity check that the two conversions are not accidentally equivalent: reading the
    # shunt-thru fixture with the series-thru formula must NOT recover the true Z.
    spec = touchstone.read(DATA / "cap_shunt_thru.s2p", port_config="series_thru")
    assert not np.allclose(spec.z, _expected_z(), rtol=1e-3)


def test_bracketed_v2_keywords_are_ignored_gracefully() -> None:
    # cap_shunt_thru.s2p contains [Version] and [Number of Ports] lines before the option
    # line; they must not break parsing.
    spec = touchstone.read(DATA / "cap_shunt_thru.s2p", port_config="shunt_thru")
    assert spec.metadata["number_of_ports"] == "2"
    assert spec.metadata["version"] == "2.0"
    assert spec.n == len(FREQS)


def test_capacitive_sign_convention_metadata() -> None:
    spec = touchstone.read(DATA / "cap_1port.s1p")
    assert "R + jX" in spec.metadata["imag_sign_convention"]


def test_sniff_picks_touchstone_for_s2p_extension() -> None:
    spec = read(DATA / "cap_series_thru.s2p", port_config="series_thru")
    assert spec.metadata["format"] == "touchstone"
    assert_allclose(spec.z, _expected_z(), rtol=1e-6)
