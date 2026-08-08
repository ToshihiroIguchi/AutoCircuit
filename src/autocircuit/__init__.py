"""AutoCircuit: equivalent circuit analysis of passive-component frequency characteristics."""

from __future__ import annotations

__version__ = "0.1.0"

from .core import Circuit, Spectrum, parse_circuit

__all__ = ["Circuit", "Spectrum", "__version__", "parse_circuit"]
