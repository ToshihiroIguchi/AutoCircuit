"""Parser for the circuit description language.

Grammar (whitespace is insignificant)::

    circuit := series
    series  := term ('-' term)*
    term    := ('p' | 'P') '(' series (',' series)* ')' | element
    element := CODE DIGITS?

Examples::

    R1-L1-p(R2,C1)          series R, series L, and an R||C block
    p(R1,C1)-p(R2,CPE1)     two Maxwell-Wagner relaxations in series
    C1-R1-L1-SKINF1         capacitor with ESR, ESL and a skin-effect term
    R1-p(C1,R2-Ws1)         Randles cell

Element codes are matched longest-first and case-insensitively, so ``Ws1`` parses as the
finite-length Warburg rather than a Warburg followed by stray text.
"""

from __future__ import annotations

from .circuit import Circuit, CircuitError, ElementNode, Node, parallel, series
from .elements import CODES_BY_LENGTH, REGISTRY

_CANONICAL_BY_LOWER: dict[str, str] = {code.lower(): code for code in REGISTRY}


class CircuitSyntaxError(CircuitError):
    """Raised when a circuit string cannot be parsed."""


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    # -- Low-level helpers ----------------------------------------------------------------
    def _skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str:
        self._skip_space()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _fail(self, message: str) -> CircuitSyntaxError:
        marker = " " * self.pos + "^"
        return CircuitSyntaxError(f"{message} at position {self.pos}\n  {self.text}\n  {marker}")

    # -- Grammar --------------------------------------------------------------------------
    def parse(self) -> Node:
        node = self.parse_series()
        self._skip_space()
        if self.pos != len(self.text):
            raise self._fail(f"unexpected {self.text[self.pos]!r}")
        return node

    def parse_series(self) -> Node:
        terms = [self.parse_term()]
        while self._peek() == "-":
            self.pos += 1
            terms.append(self.parse_term())
        return series(*terms)

    def parse_term(self) -> Node:
        char = self._peek()
        if char == "":
            raise self._fail("unexpected end of circuit")
        if char in "pP" and self._starts_parallel():
            return self.parse_parallel()
        return self.parse_element()

    def _starts_parallel(self) -> bool:
        """Distinguish ``p(`` from an element code that happens to start with 'p'."""
        self._skip_space()
        rest = self.text[self.pos + 1 :].lstrip()
        return rest.startswith("(")

    def parse_parallel(self) -> Node:
        self._skip_space()
        self.pos += 1  # 'p'
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
        return parallel(*branches)

    def parse_element(self) -> Node:
        self._skip_space()
        start = self.pos
        rest = self.text[self.pos :]
        for code in CODES_BY_LENGTH:
            if rest[: len(code)].lower() == code.lower():
                self.pos += len(code)
                break
        else:
            raise self._fail(
                "expected an element code "
                f"(one of {', '.join(sorted(REGISTRY))}) or a 'p(...)' block"
            )
        canonical = _CANONICAL_BY_LOWER[self.text[start : self.pos].lower()]
        digits_start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        suffix = self.text[digits_start : self.pos]
        return ElementNode(canonical, f"{canonical}{suffix}" if suffix else "")


def parse_circuit(text: str) -> Circuit:
    """Parse a circuit string into a :class:`Circuit`."""
    if not text or not text.strip():
        raise CircuitSyntaxError("empty circuit string")
    return Circuit(_Parser(text.strip()).parse())


def format_circuit(circuit: Circuit, labelled: bool = True) -> str:
    """Render a circuit back to the DSL, with or without element labels."""
    from .circuit import _format

    return _format(circuit.root, labelled=labelled)
