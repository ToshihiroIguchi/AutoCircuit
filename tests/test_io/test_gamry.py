from __future__ import annotations

from pathlib import Path

from numpy.testing import assert_allclose

from autocircuit.io import gamry, read

DATA = Path(__file__).parent / "data"

FREQS = [1000.0, 10000.0, 100000.0]
RE = [12.5, 8.3, 5.1]
IM = [-150.2, -15.0, -1.6]


def test_zcurve_round_trip_skips_the_ocvcurve_table() -> None:
    spec = gamry.read(DATA / "gamry_sample.DTA")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE)
    assert_allclose(spec.z.imag, IM)


def test_zimag_is_not_negated() -> None:
    spec = gamry.read(DATA / "gamry_sample.DTA")
    assert "as-is" in spec.metadata["imag_sign_convention"]


def test_preamble_metadata_is_harvested_and_ocvcurve_rows_are_not() -> None:
    spec = gamry.read(DATA / "gamry_sample.DTA")
    assert spec.metadata["date"] == "1/1/2020"
    assert spec.metadata["area"] == "1.00000E+000"
    assert "" not in spec.metadata


def test_sniff_picks_gamry_for_dot_dta_extension() -> None:
    spec = read(DATA / "gamry_sample.DTA")
    assert spec.metadata["format"] == "gamry"
    assert_allclose(spec.f, FREQS)


def test_read_many_returns_one_spectrum_for_a_single_zcurve_table() -> None:
    spectra = gamry.read_many(DATA / "gamry_sample.DTA")
    assert len(spectra) == 1
    assert_allclose(spectra[0].f, FREQS)
