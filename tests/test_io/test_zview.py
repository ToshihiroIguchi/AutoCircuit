from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.testing import assert_allclose

from autocircuit.io import read, zview

DATA = Path(__file__).parent / "data"

FREQS = [1000.0, 10000.0, 100000.0]
RE = [12.5, 8.3, 5.1]
IM = [-150.2, -15.0, -1.6]  # ZPlot already signs this column: capacitive negative


def test_header_row_round_trip() -> None:
    spec = zview.read(DATA / "sample_header.z")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE)
    assert_allclose(spec.z.imag, IM)


def test_header_row_capacitive_sign_and_metadata() -> None:
    spec = zview.read(DATA / "sample_header.z")
    assert np.all(spec.z.imag < 0)
    assert "as-is" in spec.metadata["imag_sign_convention"]
    assert spec.metadata["area"] == "1.0"
    assert spec.metadata["comment"] == "test capacitor"
    assert spec.metadata["instrument"] == "Solartron 1260"


def test_positional_fallback_round_trip() -> None:
    spec = zview.read(DATA / "sample_positional.z")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE)
    assert_allclose(spec.z.imag, IM)
    assert np.all(spec.z.imag < 0)


def test_negate_imag_hint() -> None:
    spec = zview.read(DATA / "sample_header.z", negate_imag=True)
    assert_allclose(spec.z.imag, [-v for v in IM])
    assert "negated" in spec.metadata["imag_sign_convention"]


def test_sniff_picks_zview_for_dot_z_extension() -> None:
    spec = read(DATA / "sample_header.z")
    assert spec.metadata["format"] == "zview"
    assert_allclose(spec.f, FREQS)
