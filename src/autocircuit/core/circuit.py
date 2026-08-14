"""Circuit representation: an expression tree of series and parallel element combinations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from . import elements
from .elements import BoundsContext, Complex, Float

if TYPE_CHECKING:
    from .spectrum import Spectrum


@dataclass(frozen=True)
class ElementNode:
    """A leaf: one circuit element, optionally carrying a user-visible label such as ``R1``."""

    code: str
    label: str = ""


@dataclass(frozen=True)
class Series:
    """Series connection; impedances add."""

    children: tuple[Node, ...]


@dataclass(frozen=True)
class Parallel:
    """Parallel connection; admittances add."""

    children: tuple[Node, ...]


Node = ElementNode | Series | Parallel


class CircuitError(ValueError):
    """Raised for structurally invalid circuits."""


def series(*children: Node) -> Node:
    """Build a series node, flattening nested series and collapsing single children."""
    flat: list[Node] = []
    for child in children:
        if isinstance(child, Series):
            flat.extend(child.children)
        else:
            flat.append(child)
    if not flat:
        raise CircuitError("series connection needs at least one child")
    return flat[0] if len(flat) == 1 else Series(tuple(flat))


def parallel(*children: Node) -> Node:
    """Build a parallel node, flattening nested parallels and collapsing single children."""
    flat: list[Node] = []
    for child in children:
        if isinstance(child, Parallel):
            flat.extend(child.children)
        else:
            flat.append(child)
    if not flat:
        raise CircuitError("parallel connection needs at least one child")
    return flat[0] if len(flat) == 1 else Parallel(tuple(flat))


def _walk(node: Node) -> list[ElementNode]:
    """Return every element leaf in evaluation order (depth first, children left to right)."""
    if isinstance(node, ElementNode):
        return [node]
    out: list[ElementNode] = []
    for child in node.children:
        out.extend(_walk(child))
    return out


def _relabel(node: Node, counter: Counter[str], used: set[str]) -> Node:
    """Fill in missing labels with ``<code><n>`` while preserving explicit ones."""
    if isinstance(node, ElementNode):
        if node.label:
            return node
        while True:
            counter[node.code] += 1
            label = f"{node.code}{counter[node.code]}"
            if label not in used:
                used.add(label)
                return ElementNode(node.code, label)
    children = tuple(_relabel(child, counter, used) for child in node.children)
    return Series(children) if isinstance(node, Series) else Parallel(children)


class Circuit:
    """An equivalent circuit: a topology plus the flat parameter layout it implies.

    The parameter vector is ordered by the element evaluation order, so index ``i`` of the
    values array always refers to ``param_names[i]``.
    """

    __slots__ = ("root", "_leaves", "_specs", "param_names")

    def __init__(self, root: Node) -> None:
        explicit = {leaf.label for leaf in _walk(root) if leaf.label}
        duplicates = [
            label for label, count in Counter(
                leaf.label for leaf in _walk(root) if leaf.label
            ).items() if count > 1
        ]
        if duplicates:
            raise CircuitError(f"duplicate element labels: {', '.join(sorted(duplicates))}")
        root = _relabel(root, Counter(), set(explicit))

        leaves = _walk(root)
        if not leaves:
            raise CircuitError("circuit contains no elements")
        for leaf in leaves:
            elements.get(leaf.code)  # validates the code, raises for unknown ones

        self.root: Node = root
        self._leaves: tuple[ElementNode, ...] = tuple(leaves)
        self._specs: tuple[tuple[ElementNode, elements.Element], ...] = tuple(
            (leaf, elements.get(leaf.code)) for leaf in leaves
        )
        self.param_names: tuple[str, ...] = tuple(
            f"{leaf.label}.{spec.name}" for leaf, el in self._specs for spec in el.params
        )

    # -- Construction ---------------------------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> Circuit:
        """Parse the circuit DSL, e.g. ``R1-L1-p(R2,C1)``."""
        from .dsl import parse_circuit

        return parse_circuit(text)

    # -- Layout ---------------------------------------------------------------------------
    @property
    def n_params(self) -> int:
        return len(self.param_names)

    @property
    def leaves(self) -> tuple[ElementNode, ...]:
        return self._leaves

    @property
    def complexity(self) -> float:
        """Structural cost used to rank candidates in the topology search."""
        return float(sum(el.complexity for _, el in self._specs))

    def param_specs(self) -> list[elements.ParamSpec]:
        return [spec for _, el in self._specs for spec in el.params]

    def log_mask(self) -> NDArray[np.bool_]:
        """Boolean mask marking parameters that are searched in log10 space."""
        return np.array([spec.log_scale for spec in self.param_specs()], dtype=bool)

    def slices(self) -> dict[str, slice]:
        """Map each element label to its slice of the parameter vector."""
        out: dict[str, slice] = {}
        i = 0
        for leaf, el in self._specs:
            out[leaf.label] = slice(i, i + el.n_params)
            i += el.n_params
        return out

    # -- Evaluation -----------------------------------------------------------------------
    def impedance(self, omega: Float, values: Float | list[float]) -> Complex:
        """Evaluate Z(omega) for one parameter vector, or for a whole batch of them.

        ``values`` of shape ``(n_params,)`` returns ``(n_freq,)``. ``values`` of shape
        ``(n_params, n_candidates)`` returns ``(n_candidates, n_freq)`` in a single
        vectorised pass, which is how the global optimizer scores an entire population
        without a Python loop.
        """
        omega = np.asarray(omega, dtype=np.float64)
        vals = np.asarray(values, dtype=np.float64)
        if vals.ndim == 2:
            if vals.shape[0] != self.n_params:
                raise CircuitError(
                    f"expected {self.n_params} parameter rows, got {vals.shape[0]}"
                )
            omega = omega[np.newaxis, :]
            vals = vals[:, :, np.newaxis]
        elif vals.shape != (self.n_params,):
            raise CircuitError(
                f"expected {self.n_params} parameter values, got {vals.size}"
            )
        cursor = [0]
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            return _evaluate(self.root, omega, vals, cursor)

    def bounds(self, ctx: BoundsContext) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return (lower, upper) search bounds derived from the data scale."""
        lo: list[float] = []
        hi: list[float] = []
        for _, el in self._specs:
            for a, b in el.bounds(ctx):
                lo.append(a)
                hi.append(b)
        return np.array(lo, dtype=np.float64), np.array(hi, dtype=np.float64)

    def bounds_for(self, spectrum: Spectrum, margin_decades: float = 3.0) -> tuple[
        NDArray[np.float64], NDArray[np.float64]
    ]:
        """Convenience wrapper deriving bounds straight from a spectrum."""
        ctx = BoundsContext.from_data(spectrum.omega, spectrum.z, margin_decades)
        return self.bounds(ctx)

    def values_dict(self, values: Float | list[float]) -> dict[str, float]:
        """Turn a flat parameter vector into a ``{"R1.R": value}`` mapping."""
        vals = np.asarray(values, dtype=np.float64)
        return {name: float(v) for name, v in zip(self.param_names, vals, strict=True)}

    def canonicalize_values(self, values: Float | list[float]) -> NDArray[np.float64]:
        """Reorder interchangeable branches into a deterministic order.

        ``p(R1,C1)-p(R2,C2)`` describes the same network whichever way round the two blocks
        are labelled, so an optimizer may return either assignment. Left alone this makes
        repeated runs look like they disagree and triggers spurious "the fit is not unique"
        warnings. This method sorts the value blocks of structurally identical sibling
        branches, which leaves the impedance untouched but makes the answer reproducible.
        """
        out = np.array(values, dtype=np.float64).copy()
        if out.shape != (self.n_params,):
            raise CircuitError(f"expected {self.n_params} parameter values")
        _canonicalize_values(self.root, out, 0)
        return out

    def values_array(self, mapping: dict[str, float]) -> NDArray[np.float64]:
        """Inverse of :meth:`values_dict`; raises if a parameter is missing."""
        missing = [n for n in self.param_names if n not in mapping]
        if missing:
            raise CircuitError(f"missing parameter values: {', '.join(missing)}")
        return np.array([mapping[n] for n in self.param_names], dtype=np.float64)

    # -- Text forms -----------------------------------------------------------------------
    def to_string(self) -> str:
        return _format(self.root, labelled=True)

    def canonical_form(self) -> str:
        """Label-free, order-independent string used to detect duplicate topologies."""
        return _canonical(self.root)

    def __str__(self) -> str:
        return self.to_string()

    def __repr__(self) -> str:
        return f"Circuit({self.to_string()!r}, n_params={self.n_params})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Circuit) and self.canonical_form() == other.canonical_form()

    def __hash__(self) -> int:
        return hash(self.canonical_form())


def _evaluate(node: Node, omega: Float, values: Float, cursor: list[int]) -> Complex:
    if isinstance(node, ElementNode):
        el = elements.get(node.code)
        i = cursor[0]
        cursor[0] = i + el.n_params
        return el.impedance(omega, values[i : i + el.n_params])
    # Accumulate by adding onto the first child rather than into a pre-shaped zero array, so
    # that a batched evaluation broadcasts to (n_candidates, n_freq) on its own.
    if isinstance(node, Series):
        total: Complex | None = None
        for child in node.children:
            term = _evaluate(child, omega, values, cursor)
            total = term if total is None else total + term
        assert total is not None
        return total
    admittance: Complex | None = None
    for child in node.children:
        term = 1.0 / _evaluate(child, omega, values, cursor)
        admittance = term if admittance is None else admittance + term
    assert admittance is not None
    return 1.0 / admittance


#: Elements that collapse when several of them sit in series or in parallel. Two resistors in
#: parallel are exactly one resistor, so a topology search that emits them is wasting
#: parameters on a shape the data can never distinguish.
_MERGEABLE = ("R", "C", "L")


def simplify(node: Node) -> Node:
    """Remove exactly-redundant structure from a topology.

    This is not an approximation: R-R, R||R, C-C, C||C, L-L and L||L each have exactly the
    same impedance as a single element of the same type, so the extra parameters are
    unidentifiable by construction. Collapsing them keeps the topology search from spending
    its budget on circuits that differ only in ways no measurement could resolve.
    """
    if isinstance(node, ElementNode):
        return ElementNode(node.code)

    children = [simplify(child) for child in node.children]
    kept: list[Node] = []
    seen: set[str] = set()
    for child in children:
        if isinstance(child, ElementNode) and child.code in _MERGEABLE:
            if child.code in seen:
                continue
            seen.add(child.code)
        kept.append(child)

    return series(*kept) if isinstance(node, Series) else parallel(*kept)


def count_elements(node: Node) -> int:
    """Number of element leaves in a topology."""
    return len(_walk(node))


# -- Tree addressing -----------------------------------------------------------------------
# A position in a topology is the path of child indices from the root, so that a caller can
# name a subtree, read it and put a different one in its place. The genetic operators in
# `discover.py` and the skeleton-growing enumerator in `enumerate.py` both work this way, which
# is why these live here rather than in either of them.


def subtree_paths(node: Node) -> list[tuple[int, ...]]:
    """Every subtree position, as a path of child indices from the root (the root included)."""
    out: list[tuple[int, ...]] = [()]
    if not isinstance(node, ElementNode):
        for index, child in enumerate(node.children):
            out.extend((index, *rest) for rest in subtree_paths(child))
    return out


def subtree_at(node: Node, path: Sequence[int]) -> Node:
    """The subtree addressed by ``path``."""
    for index in path:
        if isinstance(node, ElementNode):
            raise CircuitError(f"path {tuple(path)!r} runs past a leaf")
        node = node.children[index]
    return node


def replace_subtree(node: Node, path: Sequence[int], new: Node) -> Node:
    """A copy of ``node`` with the subtree at ``path`` replaced by ``new``.

    The rebuild goes through :func:`series`/:func:`parallel`, so nested nodes of the same type
    are flattened exactly as they would be in a freshly parsed circuit. That matters for
    deduplication: inserting an element beside a leaf of a series block and appending it to
    that block have to produce the identical tree, or the same topology is counted twice.
    """
    if not path:
        return new
    if isinstance(node, ElementNode):
        raise CircuitError(f"path {tuple(path)!r} runs past a leaf")
    index, rest = path[0], path[1:]
    children = list(node.children)
    children[index] = replace_subtree(children[index], rest, new)
    return series(*children) if isinstance(node, Series) else parallel(*children)


def remove_subtree(node: Node, path: Sequence[int]) -> Node:
    """A copy of ``node`` with the subtree at ``path`` deleted.

    The parent is rebuilt through :func:`series`/:func:`parallel`, so a connection left with a
    single child collapses into that child -- deleting one branch of a two-branch parallel
    block leaves the other branch in series where the block was, which is what the network
    actually becomes. Deleting the root is an error: a circuit with no elements is not a
    circuit, and the caller has to decide what to put there instead.
    """
    if not path:
        raise CircuitError("cannot delete the whole circuit")
    parent_path, index = tuple(path[:-1]), path[-1]
    parent = subtree_at(node, parent_path)
    if isinstance(parent, ElementNode):
        raise CircuitError(f"path {tuple(path)!r} runs past a leaf")
    if not 0 <= index < len(parent.children):
        raise CircuitError(f"path {tuple(path)!r} addresses no child")
    kept = [child for i, child in enumerate(parent.children) if i != index]
    if not kept:
        raise CircuitError(f"path {tuple(path)!r} leaves its connection empty")
    rebuilt = series(*kept) if isinstance(parent, Series) else parallel(*kept)
    return replace_subtree(node, parent_path, rebuilt)


def canonical_form(node: Node) -> str:
    """Label-free, order-independent string for a bare topology tree.

    The same normal form :meth:`Circuit.canonical_form` produces, but usable before a
    :class:`Circuit` is built. Topology enumeration and the genetic operators need to
    deduplicate millions of candidate trees, and constructing a full ``Circuit`` (which
    validates and relabels) for each one just to get its key is wasted work.
    """
    return _canonical(node)


def _canonicalize_values(node: Node, values: Float, start: int) -> int:
    """Sort the value blocks of identical sibling branches; returns the params consumed."""
    if isinstance(node, ElementNode):
        return elements.get(node.code).n_params

    spans: list[tuple[str, int, int]] = []
    pos = start
    for child in node.children:
        length = _canonicalize_values(child, values, pos)
        spans.append((_canonical(child), pos, length))
        pos += length

    groups: dict[str, list[tuple[int, int]]] = {}
    for key, offset, length in spans:
        groups.setdefault(key, []).append((offset, length))
    for members in groups.values():
        if len(members) < 2:
            continue
        blocks = [values[offset : offset + length].copy() for offset, length in members]
        blocks.sort(key=tuple)
        for (offset, length), block in zip(members, blocks, strict=True):
            values[offset : offset + length] = block
    return pos - start


def _format(node: Node, labelled: bool) -> str:
    if isinstance(node, ElementNode):
        return node.label if labelled and node.label else node.code
    parts = [_format(child, labelled) for child in node.children]
    if isinstance(node, Series):
        return "-".join(parts)
    return "p(" + ",".join(parts) + ")"


def _canonical(node: Node) -> str:
    if isinstance(node, ElementNode):
        return node.code
    parts = sorted(_canonical(child) for child in node.children)
    if isinstance(node, Series):
        return "[" + "-".join(parts) + "]"
    return "p(" + ",".join(parts) + ")"
