from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.testing import assert_allclose

from autocircuit.core.spectrum import Spectrum
from autocircuit.io import generic_csv, write_csv, write_zview, zview

FREQS = np.array([1000.0, 10000.0, 100000.0])
RE = np.array([12.5, 8.3, 5.1])
IM = np.array([-150.2, -15.0, -1.6])


def _sample_spectrum() -> Spectrum:
    return Spectrum.from_parts(FREQS, RE, IM, {"note": "unit test spectrum"})


def test_write_csv_round_trip(tmp_path: Path) -> None:
    spec = _sample_spectrum()
    out = tmp_path / "out.csv"
    write_csv(spec, out)
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "frequency_hz,re_z_ohm,im_z_ohm"

    read_back = generic_csv.read(out)
    assert_allclose(read_back.f, spec.f)
    assert_allclose(read_back.z.real, spec.z.real)
    assert_allclose(read_back.z.imag, spec.z.imag)


def test_write_zview_round_trip(tmp_path: Path) -> None:
    spec = _sample_spectrum()
    out = tmp_path / "out.z"
    write_zview(spec, out)

    read_back = zview.read(out)
    assert_allclose(read_back.f, spec.f)
    assert_allclose(read_back.z.real, spec.z.real)
    assert_allclose(read_back.z.imag, spec.z.imag)
    assert np.all(read_back.z.imag < 0)  # capacitive sign preserved through the round trip
