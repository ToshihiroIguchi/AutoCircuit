"""Synthetic spectrum generation, used for testing, benchmarking and documentation."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .circuit import Circuit
from .spectrum import Spectrum

Float = NDArray[np.float64]


def log_frequencies(f_min: float, f_max: float, points_per_decade: int = 10) -> Float:
    """Logarithmically spaced frequencies, the way impedance analysers sweep."""
    if f_min <= 0 or f_max <= f_min:
        raise ValueError("require 0 < f_min < f_max")
    decades = np.log10(f_max / f_min)
    n = max(int(round(decades * points_per_decade)) + 1, 2)
    return np.logspace(np.log10(f_min), np.log10(f_max), n)


def simulate(
    circuit: Circuit | str,
    f: Float,
    values: dict[str, float] | Float,
    *,
    noise: float = 0.0,
    noise_model: str = "proportional",
    seed: int | None = None,
    metadata: dict[str, object] | None = None,
) -> Spectrum:
    """Generate a spectrum from a circuit and its parameters, optionally with noise.

    Args:
        circuit: Circuit object or DSL string.
        f: Frequencies in Hz.
        values: Parameter mapping (``{"R1.R": 0.01}``) or a flat array in ``param_names`` order.
        noise: Noise level. For ``noise_model='proportional'`` this is the relative standard
            deviation applied independently to the real and imaginary parts; for ``'absolute'``
            it is the standard deviation in ohms.
        noise_model: ``'proportional'`` (instrument-like) or ``'absolute'``.
        seed: Seed for reproducible noise.
        metadata: Extra metadata to attach to the returned spectrum.
    """
    if isinstance(circuit, str):
        circuit = Circuit.parse(circuit)
    array = (
        circuit.values_array(values) if isinstance(values, dict)
        else np.asarray(values, dtype=np.float64)
    )
    f = np.asarray(f, dtype=np.float64)
    z = circuit.impedance(2.0 * np.pi * f, array)

    if noise > 0.0:
        rng = np.random.default_rng(seed)
        if noise_model == "proportional":
            scale = np.abs(z) * noise
        elif noise_model == "absolute":
            scale = np.full(z.shape, float(noise))
        else:
            raise ValueError(f"unknown noise_model {noise_model!r}")
        z = z + rng.normal(0.0, scale) + 1j * rng.normal(0.0, scale)

    meta: dict[str, object] = {
        "format": "synthetic",
        "circuit": circuit.to_string(),
        "true_parameters": circuit.values_dict(array),
        "noise": noise,
        "noise_model": noise_model,
        "seed": seed,
    }
    meta.update(metadata or {})
    return Spectrum(f, z, meta)
