from __future__ import annotations

from pathlib import Path

from numpy.testing import assert_allclose

from autocircuit.io import biologic, read

DATA = Path(__file__).parent / "data"

FREQS = [1000.0, 10000.0, 100000.0]
RE = [12.5, 8.3, 5.1]
IM = [-150.2, -15.0, -1.6]  # true, signed Im(Z)


def test_dash_im_column_is_negated() -> None:
    spec = biologic.read(DATA / "biologic_sample.mpt")
    assert_allclose(spec.f, FREQS)
    assert_allclose(spec.z.real, RE)
    assert_allclose(spec.z.imag, IM)
    assert "negated" in spec.metadata["imag_sign_convention"]


def test_plain_im_column_is_not_negated() -> None:
    spec = biologic.read(DATA / "biologic_noneg.mpt")
    assert_allclose(spec.z.imag, IM)
    assert "as-is" in spec.metadata["imag_sign_convention"]


def test_header_metadata_is_harvested() -> None:
    spec = biologic.read(DATA / "biologic_sample.mpt")
    assert spec.metadata["device"] == "Test SP-150"


def test_sniff_picks_biologic_for_dot_mpt_extension() -> None:
    spec = read(DATA / "biologic_sample.mpt")
    assert spec.metadata["format"] == "biologic"
    assert_allclose(spec.f, FREQS)


def test_read_many_splits_on_cycle_number() -> None:
    spectra = biologic.read_many(DATA / "biologic_multi.mpt")
    assert len(spectra) == 2
    assert_allclose(spectra[0].f, FREQS)
    assert_allclose(spectra[0].z.real, RE)
    assert_allclose(spectra[1].z.real, [r + 100.0 for r in RE])


def test_read_returns_every_row_as_one_spectrum_regardless_of_cycle() -> None:
    spec = biologic.read(DATA / "biologic_multi.mpt")
    assert spec.n == 2 * len(FREQS)


def test_read_many_without_a_varying_cycle_number_is_one_spectrum() -> None:
    spectra = biologic.read_many(DATA / "biologic_sample.mpt")
    assert len(spectra) == 1
    assert_allclose(spectra[0].f, FREQS)
