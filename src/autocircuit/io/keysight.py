"""Reader for Keysight/Agilent impedance analyzer CSV exports (E4990A, 4294A, E4991B).

These files start with a metadata preamble of ``"Key",value`` or ``Key,value`` lines,
followed by a header row such as ``"Frequency","Trace 1","Trace 2"`` where the trace-name
cells identify the measured quantity pair. Supported combinations:

* R + X                -> ``Spectrum.from_parts`` (already R + jX)
* Z + THR/THD/THETA     -> ``Spectrum.from_polar`` (|Z| and phase in degrees)
* LS + RS               -> ``Z = RS + j * omega * LS``
* CS + RS               -> ``Z = RS - j / (omega * CS)``
* CS + D                -> ``Z = (D - j) / (omega * CS)``

Unrecognized trace-name pairs fall back to :mod:`autocircuit.io.generic_csv` heuristics.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import numpy as np

from autocircuit.core.spectrum import Spectrum
from autocircuit.io import generic_csv
from autocircuit.io.errors import ColumnMappingError
from autocircuit.io.generic_csv import _parse_lines

_FREQ_UNIT_MULT = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}

_TRACE_ALIASES = {
    "R": "R",
    "X": "X",
    "Z": "Z",
    "THR": "THETA",
    "THD": "THETA",
    "THETA": "THETA",
    "PHASE": "THETA",
    "ANGLE": "THETA",
    "LS": "LS",
    "RS": "RS",
    "CS": "CS",
    "D": "D",
}

_COMBOS = {
    frozenset({"R", "X"}): "r_x",
    frozenset({"Z", "THETA"}): "z_theta",
    frozenset({"LS", "RS"}): "ls_rs",
    frozenset({"CS", "RS"}): "cs_rs",
    frozenset({"CS", "D"}): "cs_d",
}


def _norm_trace(name: str) -> str:
    n = re.sub(r"[^A-Za-z]", "", name).upper()
    return _TRACE_ALIASES.get(n, n)


def read(path: str | Path, **hints: Any) -> Spectrum:
    p = Path(path)
    with open(p, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.reader(fh))

    metadata: dict[str, Any] = {}
    header_idx: int | None = None
    trace_names: list[str] = []

    for i, row in enumerate(rows):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        if len(cells) >= 3 and cells[0].lower().replace(" ", "") in ("frequency", "freq"):
            header_idx = i
            trace_names = cells[1:]
            break
        if len(cells) == 2:
            key = re.sub(r"[^a-z0-9_]", "", cells[0].strip().lower().replace(" ", "_"))
            if key:
                metadata[key] = cells[1].strip()

    if header_idx is None:
        # No recognizable Keysight-style header; fall back to generic CSV heuristics.
        return generic_csv.read(p, **hints)

    data_rows = [
        [c.strip() for c in row] for row in rows[header_idx + 1 :] if any(c.strip() for c in row)
    ]
    if not data_rows:
        raise ColumnMappingError(f"No data rows found after header in Keysight file {p}")

    try:
        freqs = np.asarray([float(r[0]) for r in data_rows], dtype=np.float64)
        trace_cols = [
            np.asarray([float(r[j]) for r in data_rows], dtype=np.float64)
            for j in range(1, 1 + len(trace_names))
        ]
    except (ValueError, IndexError) as exc:
        raise ColumnMappingError(
            f"Could not parse numeric data in Keysight file {p}: {exc}"
        ) from exc

    freq_unit = str(hints.get("freq_unit", "HZ")).upper()
    if freq_unit not in _FREQ_UNIT_MULT:
        raise ColumnMappingError(f"Unknown freq_unit hint {freq_unit!r}")
    freqs = freqs * _FREQ_UNIT_MULT[freq_unit]

    norm_names = [_norm_trace(t) for t in trace_names]
    role_by_name = dict(zip(norm_names, range(len(norm_names)), strict=True))
    combo = _COMBOS.get(frozenset(norm_names))

    metadata["trace_names"] = trace_names

    if combo is None:
        # Reconstruct just the header + data rows (skipping the metadata preamble, which
        # generic_csv does not know how to strip) and hand them to the generic CSV parser.
        fallback_lines = [",".join(["Frequency", *trace_names])]
        fallback_lines += [",".join(row) for row in data_rows]
        try:
            return _parse_lines(fallback_lines, p, **hints)
        except Exception as exc:
            raise ColumnMappingError(
                f"Unrecognized Keysight trace combination {trace_names!r} in {p}, and the "
                f"generic CSV fallback also failed: {exc}"
            ) from exc

    omega = 2.0 * np.pi * freqs

    if combo == "r_x":
        r = trace_cols[role_by_name["R"]]
        x = trace_cols[role_by_name["X"]]
        metadata["imag_sign_convention"] = "as-is (Keysight R/X trace pair, R + jX)"
        return Spectrum.from_parts(freqs, r, x, metadata)
    if combo == "z_theta":
        z_mag = trace_cols[role_by_name["Z"]]
        theta = trace_cols[role_by_name["THETA"]]
        metadata["imag_sign_convention"] = (
            "derived from magnitude and phase (degrees, Keysight Z/theta trace pair)"
        )
        return Spectrum.from_polar(freqs, z_mag, theta, metadata)
    if combo == "ls_rs":
        ls = trace_cols[role_by_name["LS"]]
        rs = trace_cols[role_by_name["RS"]]
        metadata["imag_sign_convention"] = (
            "derived: Z = RS + j*omega*LS (Keysight Ls/Rs trace pair)"
        )
        return Spectrum.from_parts(freqs, rs, omega * ls, metadata)
    if combo == "cs_rs":
        cs = trace_cols[role_by_name["CS"]]
        rs = trace_cols[role_by_name["RS"]]
        metadata["imag_sign_convention"] = (
            "derived: Z = RS - j/(omega*CS) (Keysight Cs/Rs trace pair)"
        )
        return Spectrum.from_parts(freqs, rs, -1.0 / (omega * cs), metadata)
    if combo == "cs_d":
        cs = trace_cols[role_by_name["CS"]]
        d = trace_cols[role_by_name["D"]]
        metadata["imag_sign_convention"] = (
            "derived: Z = (D - j)/(omega*CS) (Keysight Cs/D trace pair)"
        )
        return Spectrum.from_parts(freqs, d / (omega * cs), -1.0 / (omega * cs), metadata)

    raise ColumnMappingError(f"Unhandled Keysight trace combination {combo!r}")  # pragma: no cover


def read_many(path: str | Path, **hints: Any) -> list[Spectrum]:
    return [read(path, **hints)]
