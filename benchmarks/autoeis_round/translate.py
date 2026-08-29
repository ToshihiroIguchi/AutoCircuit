"""Translate circuit strings and parameters between AutoEIS and this repository's grammar.

This is a benchmark helper for `docs/AUTOEIS_COMPARISON_PLAN.md`: comparing AutoCircuit against
AutoEIS (`EquivalentCircuits.jl` under the hood) needs a faithful conversion between the two
circuit description languages, in both directions. A bug here would silently turn into a wrong
benchmark score with no visible symptom -- a mistranslated circuit still parses and still fits
something -- which is why this module gets its own test suite rather than being trusted on sight.

This module runs in the PROJECT environment (the one with `autocircuit` installed), not the
AutoEIS one, and must never import `autoeis`; the two environments never meet, and any AutoEIS
circuit strings or parameter dicts arrive here as plain Python built-ins produced elsewhere.

The two grammars, confirmed from the installed AutoEIS 0.0.44 (do not re-derive; see
`docs/AUTOEIS_COMPARISON_PLAN.md`):

AutoEIS / EquivalentCircuits.jl
    * series is ``-``, e.g. ``R1-C2``.
    * parallel is ``[a,b]`` (two or more comma-separated branches), e.g. ``[R1,C2]``; each
      branch is itself a series expression, e.g. ``[P1-L2,R3]``; nesting is arbitrary.
    * element labels are a type letter (``R``, ``C``, ``L``, ``P``) followed by an integer, and
      numbering is a SINGLE GLOBAL COUNTER across all types, assigned left to right.
    * parameters arrive as ``dict[str, float]``: ``R1`` -> resistance, ``C2`` -> capacitance,
      ``L3`` -> inductance, and a CPE contributes two keys, ``P4w`` and ``P4n``.
    * CPE impedance is ``Z = 1 / (Pw * (j*omega)**Pn)``.

This repository (see `autocircuit.core.dsl` for the authoritative grammar)
    * series is ``-``; parallel is ``p(a,b)``.
    * element codes are ``R``, ``C``, ``L``, ``CPE`` (AutoEIS's ``P`` maps to ``CPE``), and
      numbering is PER TYPE, starting at 1: ``R1-p(R2,CPE1)``.
    * parameter names are ``"<label>.<param>"``: ``R1.R``, ``C1.C``, ``L1.L``, ``CPE1.Q``,
      ``CPE1.n``.
    * CPE impedance is ``Z = 1 / (Q * (j*omega)**n)``, so ``Pw`` maps to ``Q`` and ``Pn`` maps
      to ``n`` with no unit conversion.

Only ``R``, ``C``, ``L`` and ``CPE`` have an AutoEIS equivalent. Every other code in
``autocircuit.core.elements.REGISTRY`` has none, and translating a circuit that contains one
raises :class:`TranslationError`. That set is read from the registry rather than listed here, so
an element added to this project cannot quietly become translatable.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocircuit.core.dsl import CircuitSyntaxError, parse_circuit
from autocircuit.core.elements import CODES_BY_LENGTH, REGISTRY


class TranslationError(ValueError):
    """Raised when an AutoEIS <-> AutoCircuit circuit or parameter translation cannot be made."""


# ==============================================================================================
# A grammar-agnostic tree, used only inside this module. Both grammars describe the same shape
# -- series chains of parallel blocks of series chains, bottoming out in labelled elements -- so
# one pair of recursive-descent parsers (one per grammar) and one renumbering pass serve both
# translation directions, and the actual output syntax is chosen only at the final formatting
# step.
# ==============================================================================================


@dataclass(frozen=True)
class _Element:
    """One leaf element, carrying the exact label it had in the string it was parsed from.

    The original label is kept (rather than discarded at parse time) because a caller's
    parameter dict is keyed by it; the label a translated element gets in the *output* string is
    always freshly assigned by :func:`_renumber_to_autocircuit` / :func:`_renumber_to_autoeis`,
    never inherited from the input.
    """

    code: str
    label: str


@dataclass(frozen=True)
class _Series:
    children: tuple[_Node, ...]


@dataclass(frozen=True)
class _Parallel:
    children: tuple[_Node, ...]


_Node = _Element | _Series | _Parallel


def _walk(node: _Node) -> list[_Element]:
    """Every leaf element, left to right, depth first -- the order both grammars print in."""
    if isinstance(node, _Element):
        return [node]
    out: list[_Element] = []
    for child in node.children:
        out.extend(_walk(child))
    return out


def _rebuild(node: _Node, new_leaves: dict[int, _Element]) -> _Node:
    """Copy ``node``, replacing each leaf (identified by ``id()``) with its renumbered form."""
    if isinstance(node, _Element):
        return new_leaves[id(node)]
    children = tuple(_rebuild(child, new_leaves) for child in node.children)
    return type(node)(children)


# ==============================================================================================
# AutoEIS grammar: parsing and formatting
# ==============================================================================================

#: The only element types AutoEIS / EquivalentCircuits.jl knows.
_AUTOEIS_CODES = ("R", "C", "L", "P")

#: AutoEIS code -> AutoCircuit code.
_AUTOEIS_TO_AUTOCIRCUIT_CODE: dict[str, str] = {"R": "R", "C": "C", "L": "L", "P": "CPE"}


class _AutoEISParser:
    """Recursive-descent parser for the AutoEIS / EquivalentCircuits.jl grammar.

    Grammar (whitespace insignificant)::

        series  := term ('-' term)*
        term    := '[' series (',' series)* ']' | element
        element := ('R' | 'C' | 'L' | 'P') DIGITS
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def _skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str:
        self._skip_space()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _fail(self, message: str) -> TranslationError:
        marker = " " * self.pos + "^"
        return TranslationError(f"{message} at position {self.pos}\n  {self.text}\n  {marker}")

    def parse(self) -> _Node:
        node = self.parse_series()
        self._skip_space()
        if self.pos != len(self.text):
            raise self._fail(f"unexpected {self.text[self.pos]!r} (trailing junk)")
        return node

    def parse_series(self) -> _Node:
        terms = [self.parse_term()]
        while self._peek() == "-":
            self.pos += 1
            terms.append(self.parse_term())
        return terms[0] if len(terms) == 1 else _Series(tuple(terms))

    def parse_term(self) -> _Node:
        if self._peek() == "[":
            return self.parse_parallel()
        return self.parse_element()

    def parse_parallel(self) -> _Node:
        self._skip_space()
        self.pos += 1  # consume '['
        branches = [self.parse_series()]
        while self._peek() == ",":
            self.pos += 1
            branches.append(self.parse_series())
        if self._peek() != "]":
            raise self._fail("expected ',' or ']' in parallel block")
        self.pos += 1
        if len(branches) < 2:
            raise self._fail("a parallel block needs at least two branches")
        return _Parallel(tuple(branches))

    def parse_element(self) -> _Node:
        self._skip_space()
        if self.pos >= len(self.text):
            raise self._fail("unexpected end of circuit")
        letter = self.text[self.pos].upper()
        if letter not in _AUTOEIS_CODES:
            raise self._fail(
                f"unknown element type {self.text[self.pos]!r} "
                f"(AutoEIS elements are one of {', '.join(_AUTOEIS_CODES)})"
            )
        self.pos += 1
        digits_start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos == digits_start:
            raise self._fail(f"element {letter!r} is missing its numeric label")
        return _Element(letter, f"{letter}{self.text[digits_start:self.pos]}")


def _format_autoeis(node: _Node) -> str:
    if isinstance(node, _Element):
        return node.label
    parts = [_format_autoeis(child) for child in node.children]
    if isinstance(node, _Series):
        return "-".join(parts)
    return "[" + ",".join(parts) + "]"


# ==============================================================================================
# AutoCircuit grammar: parsing and formatting
#
# The authoritative grammar and parser live in ``autocircuit.core.dsl``; this module keeps its
# own small parser for it instead of reusing that one, so that it never has to reach into
# ``autocircuit.core.circuit`` for the parsed tree's node types.
#
# The element vocabulary, however, is **taken from the registry rather than restated here**. A
# copy of the code list would be correct on the day it was written and wrong the day an element
# is added, and this module's failure mode is a benchmark score with no visible symptom, so it
# gets the one list there is. ``dsl.py`` reads the same two names.
#
# The parser accepts the FULL vocabulary (not just the four codes with an AutoEIS equivalent) so
# that a garbled string is diagnosed as a syntax error rather than a spurious "unknown element";
# an element with no AutoEIS equivalent is instead rejected, naming the offending code, when
# :func:`to_autoeis` maps it in :func:`_renumber_to_autoeis`.
# ==============================================================================================

_AUTOCIRCUIT_CODES = tuple(REGISTRY)
_AUTOCIRCUIT_CODES_BY_LENGTH = CODES_BY_LENGTH
_AUTOCIRCUIT_CANONICAL_BY_LOWER: dict[str, str] = {
    code.lower(): code for code in _AUTOCIRCUIT_CODES
}

#: AutoCircuit code -> AutoEIS code, for the four codes AutoEIS actually has.
_AUTOCIRCUIT_TO_AUTOEIS_CODE: dict[str, str] = {"R": "R", "C": "C", "L": "L", "CPE": "P"}

#: Parameter names AutoCircuit uses for each of the four translatable element codes, in the
#: order AutoEIS's own parameter keys are built from (``Q`` before ``n``, matching ``Pw``/``Pn``).
_AUTOCIRCUIT_PARAM_NAMES: dict[str, tuple[str, ...]] = {
    "R": ("R",),
    "C": ("C",),
    "L": ("L",),
    "CPE": ("Q", "n"),
}


class _AutoCircuitParser:
    """Recursive-descent parser for (a superset of) this repository's circuit grammar.

    See the module docstring for why this duplicates rather than reuses
    ``autocircuit.core.dsl``.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def _skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str:
        self._skip_space()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _fail(self, message: str) -> TranslationError:
        marker = " " * self.pos + "^"
        return TranslationError(f"{message} at position {self.pos}\n  {self.text}\n  {marker}")

    def parse(self) -> _Node:
        node = self.parse_series()
        self._skip_space()
        if self.pos != len(self.text):
            raise self._fail(f"unexpected {self.text[self.pos]!r} (trailing junk)")
        return node

    def parse_series(self) -> _Node:
        terms = [self.parse_term()]
        while self._peek() == "-":
            self.pos += 1
            terms.append(self.parse_term())
        return terms[0] if len(terms) == 1 else _Series(tuple(terms))

    def parse_term(self) -> _Node:
        char = self._peek()
        if char == "":
            raise self._fail("unexpected end of circuit")
        if char.lower() == "p" and self._starts_parallel():
            return self.parse_parallel()
        return self.parse_element()

    def _starts_parallel(self) -> bool:
        """Distinguish ``p(`` from an element code (none of which start with 'p' or 'P')."""
        self._skip_space()
        rest = self.text[self.pos + 1 :].lstrip()
        return rest.startswith("(")

    def parse_parallel(self) -> _Node:
        self._skip_space()
        self.pos += 1  # consume 'p'/'P'
        self._skip_space()
        if self._peek() != "(":
            raise self._fail("expected '(' after 'p'")
        self.pos += 1
        branches = [self.parse_series()]
        while self._peek() == ",":
            self.pos += 1
            branches.append(self.parse_series())
        if self._peek() != ")":
            raise self._fail("expected ',' or ')' in parallel block")
        self.pos += 1
        if len(branches) < 2:
            raise self._fail("a parallel block needs at least two branches")
        return _Parallel(tuple(branches))

    def parse_element(self) -> _Node:
        self._skip_space()
        if self.pos >= len(self.text):
            raise self._fail("unexpected end of circuit")
        rest = self.text[self.pos :]
        for code in _AUTOCIRCUIT_CODES_BY_LENGTH:
            if rest[: len(code)].lower() == code.lower():
                self.pos += len(code)
                canonical = _AUTOCIRCUIT_CANONICAL_BY_LOWER[code.lower()]
                break
        else:
            raise self._fail(
                "expected an element code "
                f"(one of {', '.join(sorted(_AUTOCIRCUIT_CODES))}) or a 'p(...)' block"
            )
        digits_start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos == digits_start:
            raise self._fail(f"element {canonical!r} is missing its numeric label")
        return _Element(canonical, f"{canonical}{self.text[digits_start:self.pos]}")


def _format_autocircuit(node: _Node) -> str:
    if isinstance(node, _Element):
        return node.label
    parts = [_format_autocircuit(child) for child in node.children]
    if isinstance(node, _Series):
        return "-".join(parts)
    return "p(" + ",".join(parts) + ")"


# ==============================================================================================
# Renumbering
# ==============================================================================================


def _check_unique_labels(leaves: list[_Element], grammar: str) -> None:
    labels = [leaf.label for leaf in leaves]
    if len(set(labels)) != len(labels):
        duplicates = sorted({label for label in labels if labels.count(label) > 1})
        raise TranslationError(
            f"duplicate element labels in {grammar} circuit: {', '.join(duplicates)}"
        )


def _renumber_to_autocircuit(leaves: list[_Element]) -> dict[int, _Element]:
    """Per-type counter starting at 1, in order of first appearance."""
    counters: dict[str, int] = {}
    mapping: dict[int, _Element] = {}
    for leaf in leaves:
        new_code = _AUTOEIS_TO_AUTOCIRCUIT_CODE[leaf.code]
        counters[new_code] = counters.get(new_code, 0) + 1
        mapping[id(leaf)] = _Element(new_code, f"{new_code}{counters[new_code]}")
    return mapping


def _renumber_to_autoeis(leaves: list[_Element]) -> dict[int, _Element]:
    """Single global counter starting at 1, in order of first appearance."""
    mapping: dict[int, _Element] = {}
    for i, leaf in enumerate(leaves, start=1):
        if leaf.code not in _AUTOCIRCUIT_TO_AUTOEIS_CODE:
            raise TranslationError(
                f"element type {leaf.code!r} (as {leaf.label!r}) has no AutoEIS equivalent; "
                "AutoEIS only has R, C, L and P (CPE)"
            )
        new_code = _AUTOCIRCUIT_TO_AUTOEIS_CODE[leaf.code]
        mapping[id(leaf)] = _Element(new_code, f"{new_code}{i}")
    return mapping


# ==============================================================================================
# Parameter translation
# ==============================================================================================


def _expected_autoeis_keys(leaves: list[_Element]) -> set[str]:
    keys: set[str] = set()
    for leaf in leaves:
        if leaf.code == "P":
            keys.add(f"{leaf.label}w")
            keys.add(f"{leaf.label}n")
        else:
            keys.add(leaf.label)
    return keys


def _expected_autocircuit_keys(leaves: list[_Element]) -> set[str]:
    keys: set[str] = set()
    for leaf in leaves:
        for param in _AUTOCIRCUIT_PARAM_NAMES[leaf.code]:
            keys.add(f"{leaf.label}.{param}")
    return keys


def _check_param_keys(given: dict[str, float], expected: set[str], grammar: str) -> None:
    given_keys = set(given)
    if given_keys == expected:
        return
    missing = sorted(expected - given_keys)
    extra = sorted(given_keys - expected)
    parts = [f"parameter keys do not match the {grammar} circuit's elements"]
    if missing:
        parts.append(f"missing: {missing}")
    if extra:
        parts.append(f"unexpected: {extra}")
    raise TranslationError("; ".join(parts))


# ==============================================================================================
# Public API
# ==============================================================================================


def to_autocircuit(
    circuit: str, params: dict[str, float] | None = None
) -> tuple[str, dict[str, float]]:
    """Translate an AutoEIS circuit string (and optionally its parameters) into this
    repository's grammar.

    Args:
        circuit: An AutoEIS / EquivalentCircuits.jl circuit string, e.g. ``"R1-[P2,R3]"``.
        params: The AutoEIS parameter dict for ``circuit``, keyed by its own element labels
            (a CPE contributes two keys, ``"<label>w"`` and ``"<label>n"``). ``None`` translates
            the topology only.

    Returns:
        ``(autocircuit_string, autocircuit_params)``. ``autocircuit_params`` is ``{}`` when
        ``params`` is ``None``.

    Raises:
        TranslationError: on an empty string, a syntax error (unbalanced brackets, a trailing
            character, an empty parallel branch list), an element type other than R/C/L/P, or a
            ``params`` dict whose keys do not exactly match the circuit's elements.
    """
    if not circuit or not circuit.strip():
        raise TranslationError("empty circuit string")

    root = _AutoEISParser(circuit.strip()).parse()
    leaves = _walk(root)
    _check_unique_labels(leaves, "AutoEIS")

    new_leaves = _renumber_to_autocircuit(leaves)
    text = _format_autocircuit(_rebuild(root, new_leaves))

    try:
        parse_circuit(text)
    except CircuitSyntaxError as exc:
        raise TranslationError(
            f"translated circuit {text!r} was rejected by autocircuit.core.dsl.parse_circuit "
            f"(this is a bug in {__name__}): {exc}"
        ) from exc

    if params is None:
        return text, {}

    _check_param_keys(params, _expected_autoeis_keys(leaves), "AutoEIS")

    out_params: dict[str, float] = {}
    for leaf in leaves:
        new = new_leaves[id(leaf)]
        if leaf.code == "P":
            out_params[f"{new.label}.Q"] = params[f"{leaf.label}w"]
            out_params[f"{new.label}.n"] = params[f"{leaf.label}n"]
        else:
            param_name = _AUTOCIRCUIT_PARAM_NAMES[new.code][0]
            out_params[f"{new.label}.{param_name}"] = params[leaf.label]
    return text, out_params


def to_autoeis(
    circuit: str, params: dict[str, float] | None = None
) -> tuple[str, dict[str, float]]:
    """The inverse of :func:`to_autocircuit`: this repository's grammar into AutoEIS's.

    Args:
        circuit: An AutoCircuit circuit string, e.g. ``"R1-p(CPE1,R2)"``, using only element
            codes AutoEIS has an equivalent for (``R``, ``C``, ``L``, ``CPE``).
        params: The AutoCircuit parameter dict for ``circuit`` (``"<label>.<param>"`` keys).
            ``None`` translates the topology only.

    Returns:
        ``(autoeis_string, autoeis_params)``. ``autoeis_params`` is ``{}`` when ``params`` is
        ``None``.

    Raises:
        TranslationError: on an empty string, a syntax error (unbalanced parens, a trailing
            character, an empty parallel branch list), an element code with no AutoEIS
            equivalent (``W``, ``Ws``, ``Wo``, ``G``, ``CC``, ``HN``, ``SKINF``, ``SKINW``), or a
            ``params`` dict whose keys do not exactly match the circuit's elements.
    """
    if not circuit or not circuit.strip():
        raise TranslationError("empty circuit string")

    root = _AutoCircuitParser(circuit.strip()).parse()
    leaves = _walk(root)
    _check_unique_labels(leaves, "AutoCircuit")

    new_leaves = _renumber_to_autoeis(leaves)  # raises for a code with no AutoEIS equivalent
    text = _format_autoeis(_rebuild(root, new_leaves))

    if params is None:
        return text, {}

    _check_param_keys(params, _expected_autocircuit_keys(leaves), "AutoCircuit")

    out_params: dict[str, float] = {}
    for leaf in leaves:
        new = new_leaves[id(leaf)]
        if leaf.code == "CPE":
            out_params[f"{new.label}w"] = params[f"{leaf.label}.Q"]
            out_params[f"{new.label}n"] = params[f"{leaf.label}.n"]
        else:
            param_name = _AUTOCIRCUIT_PARAM_NAMES[leaf.code][0]
            out_params[new.label] = params[f"{leaf.label}.{param_name}"]
    return text, out_params
