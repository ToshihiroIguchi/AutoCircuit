"""Core library: elements, circuits, fitting, validation, discovery and SPICE export.

This package is kept free of OS-, CLI- and GUI-specific code so the exact same modules run
under Pyodide in the browser.
"""

from __future__ import annotations

from .circuit import (
    Circuit,
    CircuitError,
    ElementNode,
    Parallel,
    Series,
    canonical_form,
    count_elements,
    parallel,
    series,
    simplify,
)
from .dsl import CircuitSyntaxError, format_circuit, parse_circuit
from .elements import REGISTRY, BoundsContext, Element, ParamSpec
from .spectrum import Spectrum

__all__ = [
    "REGISTRY",
    "BoundsContext",
    "Circuit",
    "CircuitError",
    "CircuitSyntaxError",
    "Element",
    "ElementNode",
    "Parallel",
    "ParamSpec",
    "Series",
    "Spectrum",
    "canonical_form",
    "count_elements",
    "format_circuit",
    "parallel",
    "parse_circuit",
    "series",
    "simplify",
]
