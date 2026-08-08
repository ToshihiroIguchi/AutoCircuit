from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from numpy.testing import assert_allclose

from autocircuit.io import generic_csv, read
from autocircuit.io.errors import ColumnMappingError

DATA = Path(__file__).parent / "data"

FREQS = [1000.0, 10000.0, 100000.0]
RE = [12.5, 8.3, 5.1]
IM = [-150.2, -15.0, -1.6]  # capacitive: negative imaginary


def test_re_im_header_round_trip() -> None:
    spec = generic_csv.read(DATA / "generic_re_im.csv")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE, rtol=1e-6)
    assert_allclose(spec.z.imag, IM, rtol=1e-6)


def test_re_im_capacitive_sign() -> None:
    spec = generic_csv.read(DATA / "generic_re_im.csv")
    assert np.all(spec.z.imag < 0)
    assert "as-is" in spec.metadata["imag_sign_convention"]


def test_mag_phase_header_round_trip() -> None:
    spec = generic_csv.read(DATA / "generic_mag_phase.tsv")
    assert_allclose(spec.f, FREQS)
    mag = [150.72, 17.32, 5.23]
    phase = [-85.24, -61.18, -17.58]
    expected_re = [m * math.cos(math.radians(p)) for m, p in zip(mag, phase, strict=True)]
    expected_im = [m * math.sin(math.radians(p)) for m, p in zip(mag, phase, strict=True)]
    assert_allclose(spec.z.real, expected_re, rtol=1e-4)
    assert_allclose(spec.z.imag, expected_im, rtol=1e-4)
    assert np.all(spec.z.imag < 0)  # capacitive
    assert spec.metadata["phase_unit_detected"] == "deg"


def test_zpp_positive_up_convention_is_negated() -> None:
    spec = generic_csv.read(DATA / "generic_zpp_convention.csv")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE, rtol=1e-6)
    assert_allclose(spec.z.imag, IM, rtol=1e-6)
    assert np.all(spec.z.imag < 0)
    assert "negated" in spec.metadata["imag_sign_convention"]


def test_no_header_positional_round_trip() -> None:
    spec = generic_csv.read(DATA / "generic_no_header.txt")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE, rtol=1e-6)
    assert_allclose(spec.z.imag, IM, rtol=1e-6)
    assert spec.metadata["header_detected"] is False


def test_omega_column_converted_to_hz() -> None:
    spec = generic_csv.read(DATA / "generic_omega.csv")
    assert_allclose(spec.f, FREQS, rtol=1e-6)
    assert_allclose(spec.z.real, RE, rtol=1e-6)
    assert_allclose(spec.z.imag, IM, rtol=1e-6)


def test_explicit_positional_hints_override() -> None:
    # Same data as generic_re_im.csv but forced through explicit positional hints, bypassing
    # header detection entirely.
    spec = generic_csv.read(
        DATA / "generic_re_im.csv", has_header=False, col_f=0, col_re=1, col_im=2
    )
    # The header row itself will fail float parsing and be silently skipped as a bad row.
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE, rtol=1e-6)
    assert_allclose(spec.z.imag, IM, rtol=1e-6)


def test_negate_imag_hint_overrides_header_detection() -> None:
    spec = generic_csv.read(DATA / "generic_re_im.csv", negate_imag=True)
    assert_allclose(spec.z.imag, [-v for v in IM], rtol=1e-6)


def test_unmappable_columns_raise_column_mapping_error() -> None:
    with pytest.raises(ColumnMappingError):
        generic_csv.read(DATA / "generic_bad_columns.csv")


def test_positional_no_hints_no_header_ambiguous_column_count(tmp_path: Path) -> None:
    # Only 2 columns and no header: default col_re/col_im=1/2 is out of range -> error.
    two_col = tmp_path / "two_col.txt"
    two_col.write_text("1000 12.5\n10000 8.3\n100000 5.1\n", encoding="utf-8")
    with pytest.raises(ColumnMappingError):
        generic_csv.read(two_col)


def test_sniff_picks_generic_csv() -> None:
    spec = read(DATA / "generic_re_im.csv")
    assert spec.metadata["format"] == "generic_csv"
    assert spec.metadata["source_path"] == str(DATA / "generic_re_im.csv")
    assert_allclose(spec.f, FREQS)
