"""Reader for Gamry Instruments EXPLAIN-format text files (.DTA), EIS technique.

A Gamry ``.DTA`` file is tab-delimited throughout. A preamble of ``TAG\\tTYPE\\tVALUE\\t...``
metadata lines is followed by one or more ``TABLE`` blocks; a conditioning or open-circuit
trace (``OCVCURVE``) commonly precedes the impedance data, so this reader looks specifically
for a line reading ``ZCURVE\\tTABLE`` rather than the first table in the file. Every row of a
table -- the column-name row, the units row, and the data rows -- carries a stray leading tab,
so every one of them tokenizes with an empty first field; that field is dropped rather than
treated as a column.

The Gamry ``Zimag`` column is already signed the way this project's convention wants it
(negative for a capacitive response), unlike BioLogic's ``-Im(Z)/Ohm`` -- see
:mod:`autocircuit.io.biologic` -- so no negation is applied here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from autocircuit.core.spectrum import Spectrum
from autocircuit.io.errors import ColumnMappingError
from autocircuit.io.generic_csv import _try_float

_TABLE_TAG = "ZCURVE"


def _read_lines(p: Path) -> list[str]:
    with open(p, encoding="utf-8-sig", errors="replace") as fh:
        return [ln.rstrip("\r\n") for ln in fh.readlines()]


def _drop_leading_blank(tokens: list[str]) -> list[str]:
    return tokens[1:] if tokens and tokens[0] == "" else tokens


def _find_zcurve_tables(lines: list[str]) -> list[int]:
    """Line indices where a ``ZCURVE\\tTABLE`` tag opens an EIS data table."""
    starts = []
    for i, line in enumerate(lines):
        tokens = line.split("\t")
        if len(tokens) >= 2 and tokens[0].strip() == _TABLE_TAG and tokens[1].strip() == "TABLE":
            starts.append(i)
    return starts


def _harvest_metadata(lines: list[str], before: int) -> dict[str, Any]:
    """Best-effort ``TAG -> VALUE`` map from the preamble lines strictly before ``before``.

    A line belonging to some other table's own header, units or data rows always starts with
    the stray leading tab :func:`_drop_leading_blank` strips elsewhere, so those are excluded
    here by construction rather than by tracking each table's own extent.
    """
    metadata: dict[str, Any] = {}
    for line in lines[:before]:
        tokens = line.split("\t")
        if len(tokens) < 3 or tokens[0].strip() == "":
            continue
        key = re.sub(r"\s+", "_", tokens[0].strip().lower())
        if key:
            metadata.setdefault(key, tokens[2].strip())
    return metadata


def _parse_table(lines: list[str], start: int, p: Path) -> tuple[Spectrum, int]:
    if start + 2 >= len(lines):
        raise ColumnMappingError(f"ZCURVE TABLE at line {start + 1} has no data rows in {p}")

    header_tokens = [t.strip().lower() for t in _drop_leading_blank(lines[start + 1].split("\t"))]
    idx = {name: i for i, name in enumerate(header_tokens)}
    missing = [name for name in ("freq", "zreal", "zimag") if name not in idx]
    if missing:
        raise ColumnMappingError(
            f"ZCURVE table is missing column(s) {missing} in {p}; found {header_tokens!r}"
        )
    freq_idx, re_idx, im_idx = idx["freq"], idx["zreal"], idx["zimag"]
    needed = max(freq_idx, re_idx, im_idx)

    freqs: list[float] = []
    reals: list[float] = []
    imags: list[float] = []
    i = start + 3  # past the TABLE tag, the column-name row and the units row
    while i < len(lines):
        raw = lines[i]
        if raw.strip() == "":
            break
        tokens = _drop_leading_blank(raw.split("\t"))
        if len(tokens) <= needed:
            break
        values = [_try_float(t) for t in tokens]
        if values[freq_idx] is None or values[re_idx] is None or values[im_idx] is None:
            break
        f_val, re_val, im_val = values[freq_idx], values[re_idx], values[im_idx]
        assert f_val is not None and re_val is not None and im_val is not None
        freqs.append(f_val)
        reals.append(re_val)
        imags.append(im_val)
        i += 1

    if not freqs:
        raise ColumnMappingError(f"No parsable ZCURVE data rows found in {p}")

    f_arr: NDArray[np.float64] = np.asarray(freqs, dtype=np.float64)
    re_arr: NDArray[np.float64] = np.asarray(reals, dtype=np.float64)
    im_arr: NDArray[np.float64] = np.asarray(imags, dtype=np.float64)
    spectrum = Spectrum.from_parts(
        f_arr,
        re_arr,
        im_arr,
        {"imag_sign_convention": "as-is (Gamry's Zimag column already gives signed Im(Z))"},
    )
    return spectrum, i


def read(path: str | Path, **hints: Any) -> Spectrum:
    p = Path(path)
    lines = _read_lines(p)
    starts = _find_zcurve_tables(lines)
    if not starts:
        raise ColumnMappingError(f"No ZCURVE TABLE (EIS data) found in Gamry file {p}")
    spectrum, _ = _parse_table(lines, starts[0], p)
    spectrum.metadata.update(_harvest_metadata(lines, starts[0]))
    return spectrum


def read_many(path: str | Path, **hints: Any) -> list[Spectrum]:
    p = Path(path)
    lines = _read_lines(p)
    starts = _find_zcurve_tables(lines)
    if not starts:
        raise ColumnMappingError(f"No ZCURVE TABLE (EIS data) found in Gamry file {p}")
    metadata = _harvest_metadata(lines, starts[0])
    spectra = []
    for start in starts:
        spectrum, _ = _parse_table(lines, start, p)
        spectrum.metadata.update(metadata)
        spectra.append(spectrum)
    return spectra
