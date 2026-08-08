from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from numpy.testing import assert_allclose

from autocircuit.io import keysight, read

DATA = Path(__file__).parent / "data"

FREQS = [1000.0, 10000.0, 100000.0]
RE = [12.5, 8.3, 5.1]
IM = [-150.2, -15.0, -1.6]


def test_r_x_round_trip() -> None:
    spec = keysight.read(DATA / "kv_r_x.csv")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE)
    assert_allclose(spec.z.imag, IM)
    assert np.all(spec.z.imag < 0)
    assert spec.metadata["title"] == "Keysight Test"


def test_z_theta_round_trip() -> None:
    spec = keysight.read(DATA / "kv_z_theta.csv")
    mag = [150.72, 17.32, 5.23]
    phase = [-85.24, -61.18, -17.58]
    expected_re = [m * math.cos(math.radians(p)) for m, p in zip(mag, phase)]
    expected_im = [m * math.sin(math.radians(p)) for m, p in zip(mag, phase)]
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, expected_re, rtol=1e-4)
    assert_allclose(spec.z.imag, expected_im, rtol=1e-4)
    assert np.all(spec.z.imag < 0)


def test_ls_rs_round_trip() -> None:
    spec = keysight.read(DATA / "kv_ls_rs.csv")
    freqs = [1.0e5, 1.0e6, 1.0e7]
    omega = 2.0 * np.pi * np.asarray(freqs)
    L, R = 1.0e-6, 0.5
    assert_allclose(spec.f, freqs)
    assert_allclose(spec.z.real, np.full(3, R))
    assert_allclose(spec.z.imag, omega * L)
    assert np.all(spec.z.imag > 0)  # inductive


def test_cs_rs_round_trip_capacitive_sign() -> None:
    spec = keysight.read(DATA / "kv_cs_rs.csv")
    freqs = [1.0e3, 1.0e4, 1.0e5]
    omega = 2.0 * np.pi * np.asarray(freqs)
    Cs, Rs = 10.0e-6, 0.05
    assert_allclose(spec.f, freqs)
    assert_allclose(spec.z.real, np.full(3, Rs))
    assert_allclose(spec.z.imag, -1.0 / (omega * Cs))
    assert np.all(spec.z.imag < 0)  # capacitive


def test_cs_d_round_trip_capacitive_sign() -> None:
    spec = keysight.read(DATA / "kv_cs_d.csv")
    freqs = [1.0e3, 1.0e4, 1.0e5]
    omega = 2.0 * np.pi * np.asarray(freqs)
    Cs, D = 10.0e-6, 0.02
    assert_allclose(spec.f, freqs)
    assert_allclose(spec.z.real, D / (omega * Cs))
    assert_allclose(spec.z.imag, -1.0 / (omega * Cs))
    assert np.all(spec.z.imag < 0)  # capacitive


def test_unrecognized_trace_names_fall_back_to_generic_csv() -> None:
    spec = keysight.read(DATA / "kv_fallback.csv")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE)
    assert_allclose(spec.z.imag, IM)


def test_sniff_picks_keysight_from_title_preamble() -> None:
    spec = read(DATA / "kv_r_x.csv")
    assert spec.metadata["format"] == "keysight"
    assert_allclose(spec.f, FREQS)
