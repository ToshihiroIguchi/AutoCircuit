"""Immutable container for a measured or simulated impedance spectrum."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from autocircuit.core.wire import (
    decode_array,
    decode_complex_array,
    encode_array,
    encode_complex_array,
)

#: Version of :meth:`Spectrum.to_wire`, for the same reason :data:`autocircuit.core.fit.
#: WIRE_VERSION` exists: a worker and its orchestrator can be different builds, and a silently
#: mismatched payload would surface as a wrong plot rather than as an error.
WIRE_VERSION = 1


def _json_safe(value: Any) -> Any:
    """Coerce one metadata value into something ``json.dumps(allow_nan=False)`` accepts.

    Metadata is free-form -- readers put provenance in it and anyone may add more -- so unlike
    the numeric payloads it cannot be encoded by knowing its type in advance. Anything that is
    not already a JSON scalar or a list of them becomes its ``repr``: metadata is shown to the
    user, never computed with, so a lossy rendering is the right failure mode and a payload
    that cannot be delivered at all is not.
    """
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return repr(value)


@dataclass(frozen=True)
class Spectrum:
    """An impedance spectrum: complex impedance sampled at a set of frequencies.

    Attributes:
        f: Frequencies in Hz, strictly positive, sorted ascending.
        z: Complex impedance in ohms, same length as ``f``.
        metadata: Free-form provenance information (source file, instrument, ...).
    """

    f: NDArray[np.float64]
    z: NDArray[np.complex128]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        f = np.ascontiguousarray(self.f, dtype=np.float64)
        z = np.ascontiguousarray(self.z, dtype=np.complex128)
        if f.ndim != 1 or z.ndim != 1:
            raise ValueError("f and z must be one-dimensional")
        if f.size != z.size:
            raise ValueError(f"f and z must have equal length, got {f.size} and {z.size}")
        if f.size == 0:
            raise ValueError("spectrum is empty")
        if not np.all(np.isfinite(f)) or not np.all(np.isfinite(z)):
            raise ValueError("spectrum contains non-finite values")
        if np.any(f <= 0.0):
            raise ValueError("frequencies must be strictly positive")
        order = np.argsort(f, kind="stable")
        object.__setattr__(self, "f", f[order])
        object.__setattr__(self, "z", z[order])

    @classmethod
    def from_parts(
        cls,
        f: ArrayLike,
        real: ArrayLike,
        imag: ArrayLike,
        metadata: dict[str, Any] | None = None,
    ) -> Spectrum:
        """Build a spectrum from separate real and imaginary impedance columns."""
        z = np.asarray(real, dtype=np.float64) + 1j * np.asarray(imag, dtype=np.float64)
        return cls(np.asarray(f, dtype=np.float64), z, metadata or {})

    @classmethod
    def from_polar(
        cls,
        f: ArrayLike,
        magnitude: ArrayLike,
        phase_deg: ArrayLike,
        metadata: dict[str, Any] | None = None,
    ) -> Spectrum:
        """Build a spectrum from |Z| and phase in degrees."""
        mag = np.asarray(magnitude, dtype=np.float64)
        phi = np.deg2rad(np.asarray(phase_deg, dtype=np.float64))
        z = np.asarray(mag * np.exp(1j * phi), dtype=np.complex128)
        return cls(np.asarray(f, dtype=np.float64), z, metadata or {})

    @property
    def omega(self) -> NDArray[np.float64]:
        """Angular frequency in rad/s."""
        return 2.0 * np.pi * self.f

    @property
    def n(self) -> int:
        return int(self.f.size)

    def select(self, f_min: float | None = None, f_max: float | None = None) -> Spectrum:
        """Return the sub-spectrum inside the given frequency window (inclusive)."""
        mask = np.ones(self.n, dtype=bool)
        if f_min is not None:
            mask &= self.f >= f_min
        if f_max is not None:
            mask &= self.f <= f_max
        if not mask.any():
            raise ValueError("frequency window selects no points")
        return replace(self, f=self.f[mask], z=self.z[mask])

    def to_wire(self) -> dict[str, Any]:
        """JSON-safe form of this spectrum, for the boundary between browser threads.

        The measured data has to *travel* rather than be recomputed on the far side. The
        step-1 benchmark got away with rebuilding it -- each worker re-ran ``simulate()`` from
        the same parameters and seed -- because its data was synthetic; a spectrum the user
        loaded from a file has no such recipe.
        """
        return {
            "version": WIRE_VERSION,
            "f": encode_array(self.f),
            "z": encode_complex_array(self.z),
            "metadata": {str(key): _json_safe(value) for key, value in self.metadata.items()},
        }

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> Spectrum:
        """Inverse of :meth:`to_wire`."""
        version = int(payload.get("version", 0))
        if version != WIRE_VERSION:
            raise ValueError(f"Spectrum wire format version {version} is not {WIRE_VERSION}")
        return cls(
            f=decode_array(payload["f"]),
            z=decode_complex_array(payload["z"]),
            metadata=dict(payload.get("metadata", {})),
        )

    def __len__(self) -> int:
        return self.n

    def __repr__(self) -> str:
        return (
            f"Spectrum(n={self.n}, f={self.f[0]:.4g}..{self.f[-1]:.4g} Hz, "
            f"|Z|={np.abs(self.z).min():.4g}..{np.abs(self.z).max():.4g} ohm)"
        )
