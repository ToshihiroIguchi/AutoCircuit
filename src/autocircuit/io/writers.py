"""Writers for exporting a Spectrum to common file formats."""

from __future__ import annotations

from pathlib import Path

from autocircuit.core.spectrum import Spectrum


def write_csv(spectrum: Spectrum, path: str | Path) -> None:
    """Write a spectrum as generic CSV: header ``frequency_hz,re_z_ohm,im_z_ohm``.

    Values are written with the full ``repr()`` precision of the underlying float64 values
    so a subsequent :func:`autocircuit.io.generic_csv.read` round-trips exactly.
    """
    lines = ["frequency_hz,re_z_ohm,im_z_ohm"]
    for f, z in zip(spectrum.f.tolist(), spectrum.z.tolist(), strict=True):
        lines.append(f"{f!r},{z.real!r},{z.imag!r}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_zview(spectrum: Spectrum, path: str | Path) -> None:
    """Write a minimal but ZView/ZPlot-loadable text export.

    Uses the canonical ZPlot column layout (``Freq(Hz), Ampl, Bias, Time(Sec), Z'(a),
    Z''(b)``); the columns AutoCircuit does not track (amplitude, bias, time) are written as
    zero placeholders. ``Z''(b)`` is written with the sign already applied, matching what
    :func:`autocircuit.io.zview.read` expects by default (``negate_imag=False``).
    """
    lines = [
        "Source: AutoCircuit",
        f"Points: {spectrum.n}",
        "Freq(Hz)\tAmpl\tBias\tTime(Sec)\tZ'(a)\tZ''(b)",
    ]
    for f, z in zip(spectrum.f.tolist(), spectrum.z.tolist(), strict=True):
        lines.append(f"{f!r}\t0\t0\t0\t{z.real!r}\t{z.imag!r}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
