"""Reader for Touchstone network-parameter files (.s1p, .s2p, .z1p, .y1p, ...).

Parses the option line ``# <freq_unit> <parameter> <format> R <reference>`` (default
``GHZ S MA R 50``), tolerates ``!`` comments and unknown ``[Keyword]`` v2 header lines, and
converts S/Z/Y network parameters to impedance:

* 1-port S: ``Z = z0 * (1 + S11) / (1 - S11)``
* 2-port S, ``port_config="series_thru"`` (default): ``Z = 2 * z0 * (1 - S21) / S21``
* 2-port S, ``port_config="shunt_thru"``: ``Z = z0 * S21 / (2 * (1 - S21))``
* Z parameter: normalized to z0 by spec, so ``Z = z0 * S_entry`` unless ``normalized=False``.
* Y parameter: ``Z = z0 / Y_entry`` (Y normalized) or ``Z = 1 / Y_entry`` if ``normalized=False``.

``port_config`` is exposed as a hint; when a 2-port S-parameter file leaves it unset, this
module defaults to "series_thru" and records a warning in ``metadata["warnings"]`` noting
that "shunt_thru" is the physically correct choice for low-ESR devices such as capacitors
measured near resonance.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from autocircuit.core.spectrum import Spectrum
from autocircuit.io.errors import IOFormatError

_FREQ_MULT = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}
_PARAMETERS = {"S", "Z", "Y", "G", "H"}
_FORMATS = {"RI", "MA", "DB"}
_PORTS_RE = re.compile(r"\.[a-z](\d+)p$", re.IGNORECASE)


def read(path: str | Path, **hints: Any) -> Spectrum:
    p = Path(path)
    with open(p, encoding="utf-8-sig", errors="replace") as fh:
        raw_lines = fh.readlines()

    freq_unit = "GHZ"
    parameter = "S"
    data_format = "MA"
    z0 = 50.0
    option_line_found = False
    bracket_metadata: dict[str, str] = {}
    numbers: list[float] = []

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("!"):
            continue
        if "!" in line:
            line = line.split("!", 1)[0].strip()
            if not line:
                continue
        if line.startswith("#"):
            tokens = line[1:].split()
            i = 0
            while i < len(tokens):
                tok = tokens[i].upper()
                if tok in _FREQ_MULT:
                    freq_unit = tok
                elif tok in _PARAMETERS:
                    parameter = tok
                elif tok in _FORMATS:
                    data_format = tok
                elif tok == "R":
                    i += 1
                    if i < len(tokens):
                        with contextlib.suppress(ValueError):
                            z0 = float(tokens[i])
                i += 1
            option_line_found = True
            continue
        if line.startswith("["):
            # Touchstone v2 bracketed keyword, e.g. "[Version] 2.0", "[Number of Ports] 2".
            m = re.match(r"\[([^\]]+)]\s*(.*)", line)
            if m:
                key = re.sub(r"\s+", "_", m.group(1).strip().lower())
                bracket_metadata[key] = m.group(2).strip()
            continue
        for tok in line.replace(",", " ").split():
            with contextlib.suppress(ValueError):
                numbers.append(float(tok))

    metadata: dict[str, Any] = dict(bracket_metadata)
    warnings: list[str] = []
    if not option_line_found:
        warnings.append(
            f"No Touchstone option line ('#...') found in {p}; using defaults GHZ S MA R 50"
        )

    n_ports_hint = hints.get("n_ports")
    if n_ports_hint is not None:
        n_ports = int(n_ports_hint)
    else:
        m = _PORTS_RE.search(p.suffix.lower())
        if m:
            n_ports = int(m.group(1))
        elif "number_of_ports" in bracket_metadata:
            n_ports = int(bracket_metadata["number_of_ports"])
        else:
            n_ports = 1

    values_per_point = 1 + 2 * n_ports * n_ports
    if len(numbers) % values_per_point != 0:
        raise IOFormatError(
            f"Touchstone data in {p} has {len(numbers)} numeric tokens, not a multiple of "
            f"{values_per_point} (1 frequency + 2*{n_ports}^2 values for {n_ports}-port data)"
        )
    if len(numbers) == 0:
        raise IOFormatError(f"No numeric data found in Touchstone file {p}")
    n_points = len(numbers) // values_per_point
    arr = np.asarray(numbers, dtype=np.float64).reshape(n_points, values_per_point)

    freqs_hz = arr[:, 0] * _FREQ_MULT[freq_unit]
    pairs = arr[:, 1:].reshape(n_points, n_ports * n_ports, 2)
    complex_matrix = _pairs_to_complex(pairs, data_format, p)

    metadata.update(
        {
            "touchstone_parameter": parameter,
            "touchstone_format": data_format,
            "touchstone_freq_unit": freq_unit,
            "reference_impedance": z0,
            "n_ports": n_ports,
        }
    )

    if parameter == "S":
        if n_ports == 1:
            s11 = complex_matrix[:, 0]
            z = z0 * (1.0 + s11) / (1.0 - s11)
            metadata["port_config"] = "one_port"
        elif n_ports == 2:
            port_config = hints.get("port_config")
            if port_config is None:
                port_config = "series_thru"
                warnings.append(
                    "port_config not specified for 2-port S-parameter data; defaulting to "
                    "'series_thru'. Use port_config='shunt_thru' for low-ESR/low-impedance "
                    "devices such as capacitors measured near resonance."
                )
            # Touchstone 2-port column order: S11, S21, S12, S22.
            s21 = complex_matrix[:, 1]
            if port_config == "series_thru":
                z = 2.0 * z0 * (1.0 - s21) / s21
            elif port_config == "shunt_thru":
                z = z0 * s21 / (2.0 * (1.0 - s21))
            else:
                raise IOFormatError(f"Unknown port_config {port_config!r} in {p}")
            metadata["port_config"] = port_config
        else:
            raise IOFormatError(
                f"S-parameter to impedance conversion is only implemented for 1- and 2-port "
                f"Touchstone files (got {n_ports} ports) in {p}"
            )
    elif parameter in ("Z", "Y"):
        if n_ports != 1:
            raise IOFormatError(
                f"{parameter}-parameter to impedance conversion is only implemented for "
                f"1-port Touchstone files (got {n_ports} ports) in {p}"
            )
        normalized = hints.get("normalized", True)
        entry = complex_matrix[:, 0]
        if parameter == "Z":
            z = entry * z0 if normalized else entry
        else:
            y = entry / z0 if normalized else entry
            z = 1.0 / y
        metadata["port_config"] = "one_port"
        metadata["normalized"] = bool(normalized)
    else:
        raise IOFormatError(f"Unsupported Touchstone parameter {parameter!r} in {p}")

    if warnings:
        metadata["warnings"] = warnings
    metadata["imag_sign_convention"] = (
        "derived from Touchstone network-parameter conversion (R + jX convention)"
    )

    return Spectrum.from_parts(freqs_hz, z.real, z.imag, metadata)


def read_many(path: str | Path, **hints: Any) -> list[Spectrum]:
    return [read(path, **hints)]


def _pairs_to_complex(
    pairs: NDArray[np.float64], data_format: str, p: Path
) -> NDArray[np.complex128]:
    a = pairs[..., 0]
    b = pairs[..., 1]
    if data_format == "RI":
        c = a + 1j * b
    elif data_format == "MA":
        c = a * np.exp(1j * np.deg2rad(b))
    elif data_format == "DB":
        mag = 10.0 ** (a / 20.0)
        c = mag * np.exp(1j * np.deg2rad(b))
    else:
        raise IOFormatError(f"Unsupported Touchstone data format {data_format!r} in {p}")
    return c
