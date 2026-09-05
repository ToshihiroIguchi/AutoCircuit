"""Reader for BioLogic EC-Lab ASCII exports (.mpt) of a Potentio EIS technique.

Line 1 is the literal tag ``EC-Lab ASCII FILE``; line 2 is ``Nb header lines : N``, where ``N``
counts the header block *up to and including* the column-title row -- so the column header sits
at (1-indexed) line ``N`` and the data table starts at line ``N + 1``. This is the one detail
that is easy to get off by one, so it is exercised directly in
``tests/test_io/test_biologic.py``.

EC-Lab writes the imaginary part as ``-Im(Z)/Ohm``: positive for the ordinary capacitive case,
the opposite of the sign this project's convention uses, so it is negated on the way in. Some
export templates instead carry a plain ``Im(Z)/Ohm`` column that is already signed the way this
project wants it, and that one is left alone -- the same either/or
:mod:`autocircuit.io.generic_csv` already makes for the bare ``Z''`` header.

``read_many`` splits into separate sweeps on the file's own ``cycle number`` column, when one
is present and actually varies. A file with several sweeps concatenated but no varying cycle
number (seen in at least one third-party test fixture) is not split -- inferring the split from
a frequency-direction reversal would misfire on any real sweep that legitimately re-measures a
point, and this reader does not carry a heuristic nothing here has measured a reason for.
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

_HEADER_COUNT_RE = re.compile(r"nb header lines\s*:\s*(\d+)", re.IGNORECASE)


def _read_lines(p: Path) -> list[str]:
    with open(p, encoding="utf-8-sig", errors="replace") as fh:
        return [ln.rstrip("\r\n") for ln in fh.readlines()]


def _header_line_count(lines: list[str], p: Path) -> int:
    for line in lines[:5]:
        m = _HEADER_COUNT_RE.search(line)
        if m is not None:
            return int(m.group(1))
    raise ColumnMappingError(f"Could not find 'Nb header lines : N' in BioLogic file {p}")


def _split_row(line: str) -> list[str]:
    tokens = line.split("\t")
    while tokens and tokens[-1].strip() == "":
        tokens.pop()
    return [t.strip() for t in tokens]


def _column_indices(header_tokens: list[str], p: Path) -> tuple[int, int, int, bool, int | None]:
    lower = [t.lower() for t in header_tokens]

    def find(name: str) -> int | None:
        return lower.index(name) if name in lower else None

    freq_idx = find("freq/hz")
    re_idx = find("re(z)/ohm")
    negate = True
    im_idx = find("-im(z)/ohm")
    if im_idx is None:
        im_idx = find("im(z)/ohm")
        negate = False
    if freq_idx is None or re_idx is None or im_idx is None:
        raise ColumnMappingError(
            f"Could not find freq/Hz, Re(Z)/Ohm and (-)Im(Z)/Ohm columns in BioLogic file {p}; "
            f"header was {header_tokens!r}"
        )
    cycle_idx = find("cycle number")
    return freq_idx, re_idx, im_idx, negate, cycle_idx


def _harvest_metadata(lines: list[str], header_count: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for line in lines[2 : header_count - 1]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key_norm = re.sub(r"\s+", "_", key.strip().lower())
        value = value.strip()
        if key_norm and value:
            metadata.setdefault(key_norm, value)
    return metadata


class _Parsed:
    def __init__(
        self,
        f: NDArray[np.float64],
        re_z: NDArray[np.float64],
        im_z: NDArray[np.float64],
        cycles: list[float | None],
        negate: bool,
        metadata: dict[str, Any],
    ) -> None:
        self.f = f
        self.re_z = re_z
        self.im_z = im_z
        self.cycles = cycles
        self.negate = negate
        self.metadata = metadata


def _parse(lines: list[str], p: Path) -> _Parsed:
    header_count = _header_line_count(lines, p)
    if header_count < 1 or header_count > len(lines):
        raise ColumnMappingError(f"'Nb header lines : {header_count}' is out of range for {p}")
    header_tokens = _split_row(lines[header_count - 1])
    freq_idx, re_idx, im_idx, negate, cycle_idx = _column_indices(header_tokens, p)
    needed = max(freq_idx, re_idx, im_idx)

    freqs: list[float] = []
    reals: list[float] = []
    imags: list[float] = []
    cycles: list[float | None] = []
    for line in lines[header_count:]:
        if not line.strip():
            continue
        tokens = _split_row(line)
        if len(tokens) <= needed:
            continue
        f_val = _try_float(tokens[freq_idx])
        re_val = _try_float(tokens[re_idx])
        im_val = _try_float(tokens[im_idx])
        if f_val is None or re_val is None or im_val is None:
            continue
        freqs.append(f_val)
        reals.append(re_val)
        imags.append(-im_val if negate else im_val)
        cyc = None
        if cycle_idx is not None and cycle_idx < len(tokens):
            cyc = _try_float(tokens[cycle_idx])
        cycles.append(cyc)

    if not freqs:
        raise ColumnMappingError(f"No parsable data rows found in BioLogic file {p}")

    metadata = _harvest_metadata(lines, header_count)
    metadata["imag_sign_convention"] = (
        "negated ('-Im(Z)/Ohm' column, EC-Lab's positive-up convention)"
        if negate
        else "as-is (column already gives signed Im(Z))"
    )
    return _Parsed(
        np.asarray(freqs, dtype=np.float64),
        np.asarray(reals, dtype=np.float64),
        np.asarray(imags, dtype=np.float64),
        cycles,
        negate,
        metadata,
    )


def read(path: str | Path, **hints: Any) -> Spectrum:
    p = Path(path)
    parsed = _parse(_read_lines(p), p)
    return Spectrum.from_parts(parsed.f, parsed.re_z, parsed.im_z, parsed.metadata)


def read_many(path: str | Path, **hints: Any) -> list[Spectrum]:
    p = Path(path)
    parsed = _parse(_read_lines(p), p)
    distinct = {round(c, 6) for c in parsed.cycles if c is not None}
    if (
        len(parsed.cycles) != len(parsed.f)
        or any(c is None for c in parsed.cycles)
        or len(distinct) <= 1
    ):
        return [Spectrum.from_parts(parsed.f, parsed.re_z, parsed.im_z, dict(parsed.metadata))]

    groups: list[list[int]] = []
    current: list[int] = []
    last_cycle: float | None = None
    for i, c in enumerate(parsed.cycles):
        if current and c != last_cycle:
            groups.append(current)
            current = []
        current.append(i)
        last_cycle = c
    if current:
        groups.append(current)

    return [
        Spectrum.from_parts(
            parsed.f[idx], parsed.re_z[idx], parsed.im_z[idx], dict(parsed.metadata)
        )
        for idx in (np.array(g) for g in groups)
    ]
