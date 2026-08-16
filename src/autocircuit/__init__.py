"""AutoCircuit: equivalent circuit analysis of passive-component frequency characteristics.

The three names below are re-exported lazily (PEP 562) rather than imported here. Importing them
eagerly means that ``import autocircuit.io`` -- reading a file, which needs nothing but numpy --
pulls in the element registry and with it ``scipy.special``, because a package's ``__init__`` runs
before any of its submodules. The browser loads scipy *after* the page is usable, so the data path
has to be reachable without it (``docs/STARTUP_AND_EDITING_PLAN.md`` section 3.2).

``from autocircuit import Circuit`` still works, and still imports exactly what it did before; it
just does so when the name is asked for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

if TYPE_CHECKING:  # the type checker resolves the names statically; nothing is imported at run time
    from .core import Circuit, Spectrum, parse_circuit

__all__ = ["Circuit", "Spectrum", "__version__", "parse_circuit"]

_LAZY = frozenset({"Circuit", "Spectrum", "parse_circuit"})


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from . import core

        return getattr(core, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
