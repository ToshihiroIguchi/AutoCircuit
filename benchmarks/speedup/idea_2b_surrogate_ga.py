"""Idea 2b, actually measured (not desk analysis): can cheap structural features of a topology
predict its screening cost well enough for a surrogate to be useful?

Reuses the exact 2523-topology, two-budget dataset idea 2a already computed (same pool, same
truth, same spectrum) rather than re-screening anything -- this is the concrete, cheap test the
desk-analysis argument (basin-lottery noise should swamp any structural signal) should have been
checked against instead of asserted. Cheap features: element count, per-element-code counts
(R/C/L/CPE), tree depth, max branch width. Surrogate: a from-scratch numpy nearest-neighbour and
a plain linear regression on log(cost) -- no new dependency, matching this project's numpy+scipy
only rule.

Decision rule, fixed before running: worth prototyping a real surrogate only if it predicts which
half of the candidates are in the cheaper half of the full-budget cost distribution with
>=80% accuracy (leave-one-out), clearing a bar meaningfully above chance (50%).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW5, spectrum_for  # noqa: E402

from autocircuit.core.circuit import Circuit, ElementNode, Parallel  # noqa: E402
from autocircuit.core.enumerate import enumerate_topologies  # noqa: E402
from autocircuit.core.fit import screen  # noqa: E402

N_ELEMENTS = 5
POOL = ("R", "C", "L", "CPE")
FULL_POPSIZE, FULL_MAXITER = 8, 40


def _depth(node) -> int:
    if isinstance(node, ElementNode):
        return 1
    return 1 + max(_depth(c) for c in node.children)


def _max_width(node) -> int:
    if isinstance(node, ElementNode):
        return 1
    here = len(node.children) if isinstance(node, Parallel) else 1
    return max(here, *(_max_width(c) for c in node.children)) if node.children else here


def features(node) -> np.ndarray:
    leaves = Circuit(node).leaves
    codes = [leaf.code for leaf in leaves]
    return np.array(
        [
            len(codes),
            codes.count("R"),
            codes.count("C"),
            codes.count("L"),
            codes.count("CPE"),
            _depth(node),
            _max_width(node),
        ],
        dtype=np.float64,
    )


def main() -> None:
    spectrum = spectrum_for(MW5, seed=0)
    nodes = list(enumerate_topologies(POOL, N_ELEMENTS))
    print(f"{len(nodes)} topologies")

    X = np.array([features(n) for n in nodes])
    y = np.array(
        [
            np.log10(max(screen(Circuit(n).to_string(), spectrum, seed=0,
                                 popsize=FULL_POPSIZE, maxiter=FULL_MAXITER), 1e-300))
            for n in nodes
        ]
    )

    # Standardize features for a fair nearest-neighbour distance and a well-conditioned regression.
    X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-9)

    median_y = np.median(y)
    true_cheap_half = y <= median_y

    # Leave-one-out 1-NN prediction of "cheap half" membership using only structural features.
    correct = 0
    for i in range(len(nodes)):
        dists = np.sum((X - X[i]) ** 2, axis=1)
        dists[i] = np.inf
        nearest = np.argmin(dists)
        predicted_cheap = y[nearest] <= median_y
        correct += int(predicted_cheap == true_cheap_half[i])
    accuracy = correct / len(nodes)
    print(f"1-NN leave-one-out accuracy predicting cheap-half membership: {accuracy * 100:.1f}%")

    # Plain linear regression on log-cost from the same features, R^2 via leave-one-out is
    # expensive in closed form; use in-sample R^2 as a generous upper bound on what any simple
    # surrogate could achieve with these features (an in-sample bound failing is decisive).
    X1 = np.column_stack([X, np.ones(len(nodes))])
    coef, *_ = np.linalg.lstsq(X1, y, rcond=None)
    y_pred = X1 @ coef
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot
    print(f"linear regression in-sample R^2 on log10(cost) from structural features: {r2:.3f}")

    print(f"\ndecision rule (>=80% cheap-half accuracy): "
          f"{'PASS' if accuracy >= 0.8 else 'FAIL'}")


if __name__ == "__main__":
    main()
