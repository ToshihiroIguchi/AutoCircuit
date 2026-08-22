"""Core library: elements, circuits, fitting, validation, discovery and SPICE export.

This package is kept free of OS-, CLI- and GUI-specific code so the exact same modules run
under Pyodide in the browser.

The re-exports are lazy (PEP 562), for the reason :mod:`autocircuit`'s own ``__init__`` gives:
``from .circuit import Circuit`` here would mean that importing *any* submodule -- including
:mod:`autocircuit.core.spectrum`, which is pure numpy -- imports the element registry and with it
``scipy.special``. The browser's data path loads before scipy does
(``docs/STARTUP_AND_EDITING_PLAN.md`` section 3.2). Every ``from autocircuit.core import X`` that
worked before works now and imports the same module; it happens on the attribute access instead of
on the package import.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # resolved statically; nothing is imported at run time
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
    from .descriptors import PoolChoice, choose_pool, diffusion_branch_decades
    from .dsl import CircuitSyntaxError, format_circuit, parse_circuit
    from .elements import REGISTRY, BoundsContext, Element, ParamSpec
    from .interpret import Interpretation, Quantity, interpret, interpret_values
    from .spectrum import Spectrum

#: Which submodule each exported name comes from.
_LAZY: dict[str, str] = {
    "Circuit": "circuit",
    "CircuitError": "circuit",
    "ElementNode": "circuit",
    "Parallel": "circuit",
    "Series": "circuit",
    "canonical_form": "circuit",
    "count_elements": "circuit",
    "parallel": "circuit",
    "series": "circuit",
    "simplify": "circuit",
    "PoolChoice": "descriptors",
    "choose_pool": "descriptors",
    "diffusion_branch_decades": "descriptors",
    "CircuitSyntaxError": "dsl",
    "format_circuit": "dsl",
    "parse_circuit": "dsl",
    "REGISTRY": "elements",
    "BoundsContext": "elements",
    "Element": "elements",
    "ParamSpec": "elements",
    "Interpretation": "interpret",
    "Quantity": "interpret",
    "interpret": "interpret",
    "interpret_values": "interpret",
    "Spectrum": "spectrum",
}

__all__ = [
    "REGISTRY",
    "BoundsContext",
    "Circuit",
    "CircuitError",
    "CircuitSyntaxError",
    "Element",
    "ElementNode",
    "Interpretation",
    "Parallel",
    "ParamSpec",
    "PoolChoice",
    "Quantity",
    "Series",
    "Spectrum",
    "canonical_form",
    "choose_pool",
    "count_elements",
    "diffusion_branch_decades",
    "format_circuit",
    "interpret",
    "interpret_values",
    "parallel",
    "parse_circuit",
    "series",
    "simplify",
]


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f".{module}", __name__), name)
