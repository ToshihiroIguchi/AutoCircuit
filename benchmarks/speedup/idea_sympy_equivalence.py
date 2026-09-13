"""docs/ALGEBRAIC_EQUIVALENCE_PLAN.md section 3, run: a small SymPy spike testing whether
symbolic rational-function comparison can automatically verify (or reject) equivalent-circuit
pairs -- explicitly dev-only tooling (`CLAUDE.md`'s numpy+scipy-only runtime rule), never
imported by `autocircuit.core`.

Operationalisation, decided here rather than in the plan (the plan scoped the question, not the
exact test): given two topologies each with a *concrete* numeric parameter assignment, build
their impedance as a SymPy rational function of `s = j*omega` and check whether
`sympy.simplify(Z_a - Z_b)` is identically zero. This verifies "these two fitted candidates are
provably, algebraically equivalent" -- an exact upgrade on this project's existing post-hoc
`EQUIVALENCE_RTOL = 1e-6` numeric check -- rather than trying to *discover* a general
reparameterisation, which is a harder, open-ended problem this spike does not attempt.

Positive controls: idea A's known pair (`R1-p(R2,C1)` / `p(R1,C1-R2)`, closed-form parameters)
and idea A2's order-2 Foster/Cauer pair (`benchmarks/speedup/idea_a2_foster_cauer.py`'s own
closed form). Negative controls: pairs of genuinely different topologies with independently
chosen parameters, where SymPy must say "not equal."

Pre-registered stop/go (docs/ALGEBRAIC_EQUIVALENCE_PLAN.md section 3): (1) zero false positives
on negative controls; (2) both known positive-control pairs recognised automatically; (3)
per-pair comparison time a small fraction of one tier-1 screen (~1s).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import sympy

_SPEEDUP_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _SPEEDUP_DIR.parent
_ROOT = _BENCH_DIR.parent
for p in (_BENCH_DIR, _ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from autocircuit.core.circuit import Circuit, ElementNode, Parallel, Series  # noqa: E402

s = sympy.symbols("s")


def node_impedance(node, values: dict[str, float]):
    """Build a SymPy impedance expression for a parsed circuit node, R/C/L only."""
    if isinstance(node, ElementNode):
        code, label = node.code, node.label
        value = sympy.nsimplify(values[f"{label}.{code}"], rational=False)
        if code == "R":
            return value
        if code == "C":
            return 1 / (s * value)
        if code == "L":
            return s * value
        raise ValueError(f"sympy spike only supports R/C/L, got {code}")
    if isinstance(node, Series):
        return sum(node_impedance(c, values) for c in node.children)
    if isinstance(node, Parallel):
        terms = [node_impedance(c, values) for c in node.children]
        return 1 / sum(1 / t for t in terms)
    raise TypeError(type(node))


def circuit_impedance(text: str, values: dict[str, float]):
    circuit = Circuit.parse(text)
    return node_impedance(circuit.root, values)


def compare(text_a: str, values_a: dict[str, float], text_b: str, values_b: dict[str, float]):
    """Returns (is_zero, elapsed, diff, max_relative_coeff).

    ``is_zero`` is exact symbolic equality. Concrete parameters coming from a real fit (or, as
    in idea A2's closed form, from float division) are never exact rationals, so an exact
    residual is not always literally 0 even for a provably identical family -- the numerator's
    largest coefficient, relative to the two impedances' own coefficient scale, is reported
    alongside it as the practical "effectively zero" reading a real deployment would need.
    """
    za = circuit_impedance(text_a, values_a)
    zb = circuit_impedance(text_b, values_b)
    t0 = time.perf_counter()
    diff = sympy.simplify(sympy.together(za - zb))
    elapsed = time.perf_counter() - t0
    is_zero = diff == 0
    numer, _denom = sympy.fraction(sympy.together(diff))
    numer_poly = sympy.Poly(sympy.expand(numer), s)
    diff_coeffs = (
        [abs(complex(c)) for c in numer_poly.all_coeffs()] if numer_poly.degree() >= 0 else [0.0]
    )
    scale_numer, _ = sympy.fraction(sympy.together(za + zb))
    scale_poly = sympy.Poly(sympy.expand(scale_numer), s)
    scale_coeffs = (
        [abs(complex(c)) for c in scale_poly.all_coeffs()] if scale_poly.degree() >= 0 else [1.0]
    )
    max_relative = max(diff_coeffs, default=0.0) / max(max(scale_coeffs, default=1.0), 1e-300)
    return is_zero, elapsed, diff, max_relative


def main() -> None:
    print("=== Positive control 1: idea A's known pair ===")
    R1, R2, C1 = 10.0, 50.0, 1.0e-6
    # Closed form from benchmarks/speedup/idea_a_algebraic_equivalence.py
    R1p = R1 + R2
    R2p = R1 * (R1 + R2) / R2
    C1p = R2**2 * C1 / (R1 + R2) ** 2
    ok, elapsed, diff, rel1 = compare(
        "R1-p(R2,C1)",
        {"R1.R": R1, "R2.R": R2, "C1.C": C1},
        "p(R1,C1-R2)",
        {"R1.R": R1p, "C1.C": C1p, "R2.R": R2p},
    )
    print(
        f"  exactly zero: {ok}  effectively zero (rel<1e-6): {rel1 < 1e-6}  "
        f"({elapsed:.4f}s)  max relative coeff: {rel1:.3e}"
    )

    print("\n=== Positive control 2: idea A2's order-2 Foster/Cauer pair ===")
    sys.path.insert(0, str(_SPEEDUP_DIR))
    from idea_a2_foster_cauer import foster_to_cauer_closedform_order2  # noqa: E402

    blocks = [(20.0, 1e-5), (200.0, 1e-7)]  # (R, C) pairs, per Block = tuple[float, float]
    ca, rb, rc, cc = foster_to_cauer_closedform_order2(blocks)
    # Foster form: p(R1,C1)-p(R2,C2), two parallel RC blocks in series.
    foster_text = "p(R1,C1)-p(R2,C2)"
    foster_values = {
        "R1.R": blocks[0][0],
        "C1.C": blocks[0][1],
        "R2.R": blocks[1][0],
        "C2.C": blocks[1][1],
    }
    # Cauer ladder, order 2: matches idea_a2's own `cauer_impedance_order2` structure:
    # Z = 1/(s*Ca) || (Rb + (Rc||(1/(s*Cc))))
    cauer_text = "p(C1,R1-p(R2,C2))"
    cauer_values = {"C1.C": ca, "R1.R": rb, "R2.R": rc, "C2.C": cc}
    ok2, elapsed2, diff2, rel2 = compare(foster_text, foster_values, cauer_text, cauer_values)
    print(
        f"  exactly zero: {ok2}  effectively zero (rel<1e-6): {rel2 < 1e-6}  "
        f"({elapsed2:.4f}s)  max relative coeff: {rel2:.3e}"
    )

    print("\n=== Negative controls: genuinely different topologies/params ===")
    rng = np.random.default_rng(0)
    negative_pairs = [
        ("R1-C1", "R1-L1"),
        ("p(R1,C1)", "R1-C1"),
        ("R1-p(R2,C1)", "R1-p(R2,C1)-R3"),
        ("p(R1,C1)-R2", "p(R1,C1)-p(R2,C2)"),
        ("R1-C1-L1", "p(R1,C1)-L1"),
        ("p(R1,R2-C1)", "p(R1-R2,C1)"),
    ]
    n_false_positive = 0
    n_run = 0
    total_time = 0.0
    for text_a, text_b in negative_pairs:
        for trial in range(3):
            circuit_a = Circuit.parse(text_a)
            circuit_b = Circuit.parse(text_b)
            values_a = {
                f"{el.label}.{el.code}": float(rng.uniform(1, 1000)) for el in circuit_a.leaves
            }
            values_b = {
                f"{el.label}.{el.code}": float(rng.uniform(1, 1000)) for el in circuit_b.leaves
            }
            _ok, elapsed, _diff, rel = compare(text_a, values_a, text_b, values_b)
            n_run += 1
            total_time += elapsed
            if rel < 1e-6:
                n_false_positive += 1
                print(f"  FALSE POSITIVE: {text_a} vs {text_b}, trial {trial}, rel={rel:.3e}")
    print(
        f"  {n_run} negative-control comparisons, {n_false_positive} false positives, "
        f"mean {total_time / n_run:.4f}s each"
    )

    print("\n=== Pre-registered stop/go ===")
    print(
        f"  1. zero false positives on negative controls: "
        f"{'PASS' if n_false_positive == 0 else 'FAIL'} ({n_false_positive}/{n_run})"
    )
    print(
        f"  2. both known positive-control pairs recognised (rel<1e-6): "
        f"{'PASS' if rel1 < 1e-6 and rel2 < 1e-6 else 'FAIL'} "
        f"(control1 rel={rel1:.3e}, control2 rel={rel2:.3e})"
    )
    per_pair = max(elapsed, elapsed2, total_time / n_run)
    print(
        f"  3. per-pair time << ~1s tier-1 screen: "
        f"{'PASS' if per_pair < 0.1 else 'MARGINAL' if per_pair < 1.0 else 'FAIL'} "
        f"(worst observed {per_pair:.4f}s)"
    )


if __name__ == "__main__":
    main()
