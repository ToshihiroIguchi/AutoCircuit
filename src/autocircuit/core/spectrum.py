"""Immutable container for a measured or simulated impedance spectrum."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray


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

    def __len__(self) -> int:
        return self.n

    def __repr__(self) -> str:
        return (
            f"Spectrum(n={self.n}, f={self.f[0]:.4g}..{self.f[-1]:.4g} Hz, "
            f"|Z|={np.abs(self.z).min():.4g}..{np.abs(self.z).max():.4g} ohm)"
        )
