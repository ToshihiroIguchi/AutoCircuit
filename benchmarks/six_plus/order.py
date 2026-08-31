"""X9 (``docs/TOPOLOGY_6PLUS_PLAN.md`` sec. 3.3 and 4.3): can a rational approximation of the
measured Z(s) tell us how many relaxations a spectrum supports, without enumerating a single
circuit?

The question this feeds: ``mode="auto"`` currently decides to widen its element budget using a
runs test on the best five-element fit's residual signs, and ``docs/AUTOEIS_COMPARISON.md``
section 2.2 measured that trigger reading ``z`` in [-0.45, 0.67] on five- and six-element truths
that plainly need a sixth element -- the genetic fallback it is supposed to arm never ran once in
forty scored comparisons. X9 asks whether a *model-order oracle* -- something that looks only at
the data's own rational structure, the way a modal-analysis engineer reads a stabilisation diagram
off a frequency response -- can do better, and whether it can do it *without* first enumerating
circuits the way the runs test's caller (an already-completed five-element fit) requires.

Physics behind the question. With s = j*omega, an impedance built only from R, C and L is a
*rational* function of s with a finite McMillan degree: one energy-storage element, one state, one
finite pole (barring degenerate coincidences). A CPE or a Warburg element is *not* rational -- both
have a branch point at s = 0 -- so no finite-order rational function reproduces one exactly, and any
finite-order fit to one is only ever a local approximation whose apparent order should keep growing
as the fit is asked to work harder (tighter tolerance, wider bandwidth). That growth is treated here
as a second, independent signal: a fractional-element detector, not just a nuisance.

Three estimators, all numpy/scipy only:

  (a) ``aaa_order``            -- pole count of a ``scipy.interpolate.AAA`` barycentric fit, after
                                   discarding poles that are not physically admissible (see below).
  (b) ``loewner_order``        -- the classical Loewner/shifted-Loewner pencil (Mayo & Antoulas
                                   2007; applied to EIS by Patel/Sorrentino/Vidakovic-Koch, iScience
                                   28:111987, 2025, and Sorrentino et al., J. Power Sources
                                   585:233575, 2023), hand-rolled in numpy -- no package for this
                                   exists. Order read off the singular-value drop of the pencil, by
                                   two competing rules that are BOTH reported.
  (c) ``stabilisation_order``  -- a stabilisation diagram: fit at growing order and keep the poles
                                   that do not move. This is the one rule in the modal-analysis
                                   literature that needs no user-supplied noise estimate, which
                                   matters because the other two do.

The harness below scores all three, plus both Loewner order rules, against a labelled reference set
of R/C/L truths (finite, known-ish degree) and CPE/Warburg truths (no finite degree, by
construction), over a noise x points-per-decade grid, and reports:

  - the ground-truth order each estimator reports on a dense, noise-free simulation of each truth
    (established empirically, per estimator, rather than asserted -- see ``reference_orders``);
  - the headline number: at 1% noise and 10 points per decade -- the realistic case -- how often
    each estimator/rule recovers that reference order, is off by one, or is off by more;
  - for the two fractional truths, whether the reported order grows monotonically as AAA's ``rtol``
    tightens and as the sampled bandwidth widens, with the numbers, not just a verdict.

This experiment does not fit a single circuit. Nothing here calls ``discover`` or ``fit``; it only
asks what a rational (or knowingly-not-rational) approximation of Z(f) says about itself.
"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import AAA
from scipy.linalg import LinAlgError, block_diag, eig

from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

# =============================================================================================
# Estimator 1 -- AAA barycentric rational approximation
# =============================================================================================

#: rtol sweep spanning typical instrument noise, per the task spec.
DEFAULT_AAA_RTOLS: tuple[float, ...] = (1e-2, 3e-3, 1e-3, 3e-4, 1e-4, 1e-6)

#: A pole further than this many times the sampled omega_max from the origin is treated as an
#: artefact of forcing a bounded-at-infinity barycentric form to track unbounded growth (e.g. the
#: sL term of a series inductor), not a resolved relaxation. See ``aaa_order``'s docstring.
DEFAULT_FAR_FACTOR = 1.0e4

#: A pole is "admissible" (physically realisable by a passive network) if its real part is not
#: positive, up to this relative slack for fit noise. Poles sitting on the imaginary axis (a
#: lossless LC resonance) are admissible; poles resolved to a tiny positive real part by fit
#: noise should be too, hence the slack rather than a hard ``<= 0``.
DEFAULT_RHP_TOL = 1e-6


@dataclass
class AAAResult:
    """One AAA fit at one ``rtol``, with poles split by physical admissibility."""

    rtol: float
    n_terms: int
    all_poles: Complex
    admissible_poles: Complex
    rhp_poles: Complex
    far_poles: Complex

    @property
    def n_admissible(self) -> int:
        return int(self.admissible_poles.size)

    @property
    def n_rhp_rejected(self) -> int:
        return int(self.rhp_poles.size)

    @property
    def n_far_rejected(self) -> int:
        return int(self.far_poles.size)


def _conjugate_augment(omega: Float, z: Complex) -> tuple[Complex, Complex]:
    """Append the mirror image at negative frequency, enforcing Z(-s) = conj(Z(s)).

    The measured spectrum only samples s = j*omega for omega > 0, one half of the imaginary axis.
    A real physical network has Z(-j*omega) = conj(Z(j*omega)); supplying that mirror explicitly is
    what lets AAA (which has no notion of "this system is real") settle on an approximant whose
    poles come in the conjugate pairs (or lie on the real axis) a real rational function requires,
    instead of an arbitrary complex-coefficient fit that happens to interpolate one-sided data.
    """
    s = np.concatenate([1j * omega, -1j * omega])
    v = np.concatenate([z, np.conj(z)])
    return s, v


def aaa_order(
    spectrum: Spectrum,
    *,
    rtol: float = 1e-3,
    max_terms: int = 100,
    far_factor: float = DEFAULT_FAR_FACTOR,
    rhp_tol: float = DEFAULT_RHP_TOL,
) -> AAAResult:
    """Fit Z(s) with ``scipy.interpolate.AAA`` and count physically admissible poles.

    A pole is rejected, not silently dropped, on two independent grounds:

      - **right-half-plane** (``Re(pole) > rhp_tol * |pole|``): a passive impedance has no such
        poles (Brune 1931), so one appearing here means the fit is telling us the noise or the
        bandwidth defeated it, not that a relaxation was found.
      - **far** (``|pole| > far_factor * omega_max``): a pole many decades outside the sampled band
        is very often the barycentric form's way of faking the *unbounded* growth of a series
        inductor or CPE tail -- the barycentric representation is bounded as s -> infinity by
        construction (it evaluates to sum(w_j f_j) / sum(w_j) there), so it can only mimic true
        divergence locally, with poles pushed toward the edge of, or past, the fitted domain.

    Both rejected sets are returned alongside the admissible ones, exactly so this trade-off is
    visible rather than laundered into a single count.
    """
    omega = spectrum.omega
    s, v = _conjugate_augment(omega, spectrum.z)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        fit = AAA(s, v, rtol=rtol, max_terms=max_terms)
    poles = fit.poles()
    finite = poles[np.isfinite(poles)]
    omega_max = float(omega.max())
    far_mask = np.abs(finite) > far_factor * omega_max
    near = finite[~far_mask]
    rhp_mask = near.real > rhp_tol * np.abs(near)
    return AAAResult(
        rtol=rtol,
        n_terms=int(fit.support_points.size),
        all_poles=poles,
        admissible_poles=near[~rhp_mask],
        rhp_poles=near[rhp_mask],
        far_poles=finite[far_mask],
    )


# =============================================================================================
# Estimator 2 -- the Loewner framework, hand-rolled
# =============================================================================================


@dataclass
class LoewnerResult:
    """A Loewner/shifted-Loewner realisation of Z(s) and the order read off it two ways."""

    singular_values_l: Float
    """Singular values of the real Loewner matrix L alone."""
    singular_values_l_ls: Float
    """Singular values of the real matrix [L, Ls] (L and shifted-Loewner Ls concatenated)."""
    noise_estimate: float
    order_threshold: int
    """Rule (a): count of singular values of L above ``noise_estimate * sigma_max``."""
    order_gap: int
    """Rule (b): 1 + argmax of the ratio sigma[k] / sigma[k+1] -- the largest relative drop."""
    order: int
    """The order used to extract ``poles`` below -- ``order_gap``, because it is self-contained
    (rule (a) needs a noise estimate the Loewner framework's own literature does not supply)."""
    poles: Complex
    admissible_poles: Complex
    rhp_poles: Complex
    max_imag_residual: float
    """Diagnostic for the realification step (see ``_realify``): the largest imaginary part left
    in L after the block transform, relative to its scale. Should be at machine precision; a large
    value here would mean the transform is wrong, not that the data is unusual."""


#: The real block-diagonalising transform (Mayo & Antoulas 2007, sec. "case of complex data";
#: Ionita & Antoulas 2014). For a conjugate pair of complex numbers (z, conj(z)) written as a
#: length-2 vector [z, conj(z)], Q maps it to a real length-2 vector: Q^H [z, conj(z)]^T =
#: sqrt(2) * [Re(z), Im(z)]^T. Applied as a block-diagonal similarity to the *whole* Loewner pencil
#: (whose rows and columns are built, by construction below, from adjacent conjugate pairs), it
#: turns L and Ls real without touching their singular values or the eigenvalues of the pencil
#: they define -- verified empirically for this file (see the module-level self-test) by checking
#: the residual imaginary part left after the transform, which is reported in every result as
#: ``max_imag_residual`` rather than assumed away.
_REALIFY_Q = (1.0 / np.sqrt(2.0)) * np.array([[1.0, -1.0j], [1.0, 1.0j]])


def _augment_conjugate_pairs(nodes: Complex, values: Complex) -> tuple[Complex, Complex]:
    """Interleave each (node, value) with its conjugate: [n0, conj(n0), n1, conj(n1), ...].

    The adjacent-pair ordering is what lets ``_realify`` apply a block-diagonal transform built
    from 2x2 blocks without any bookkeeping of which entries pair with which.
    """
    out_nodes = np.empty(2 * nodes.size, dtype=np.complex128)
    out_values = np.empty(2 * nodes.size, dtype=np.complex128)
    out_nodes[0::2] = nodes
    out_nodes[1::2] = np.conj(nodes)
    out_values[0::2] = values
    out_values[1::2] = np.conj(values)
    return out_nodes, out_values


def _build_loewner(
    omega: Float, z: Complex
) -> tuple[Complex, Complex, Complex, Complex, Complex, Complex]:
    """Split the samples into interleaved left/right sets, augment each with its conjugate mirror,
    and build the (complex) Loewner matrix L and shifted-Loewner matrix Ls.

    Following the task's naming: "left" is {mu_j, v_j}, "right" is {lambda_i, w_i}, and
    ``L[i, j] = (v_j - w_i) / (mu_j - lambda_i)``, ``Ls[i, j] = (mu_j*v_j - lambda_i*w_i) /
    (mu_j - lambda_i)`` -- so rows are indexed by the right set, columns by the left set. The split
    is by alternating index, the standard choice: even-indexed samples become the right set, odd
    the left.
    """
    n = omega.size
    idx = np.arange(n)
    lam0 = 1j * omega[idx[0::2]]
    w0 = z[idx[0::2]]
    mu0 = 1j * omega[idx[1::2]]
    v0 = z[idx[1::2]]
    lam, w = _augment_conjugate_pairs(lam0, w0)
    mu, v = _augment_conjugate_pairs(mu0, v0)

    denom = mu[np.newaxis, :] - lam[:, np.newaxis]
    local_scale = np.abs(mu)[np.newaxis, :] + np.abs(lam)[:, np.newaxis]
    if np.any(np.abs(denom) < 1e-9 * (local_scale + 1e-300)):
        raise ValueError(
            "Loewner split produced coincident left/right frequency nodes; "
            "the spectrum must have distinct, non-degenerate sample frequencies."
        )
    L = (v[np.newaxis, :] - w[:, np.newaxis]) / denom
    Ls = (mu[np.newaxis, :] * v[np.newaxis, :] - lam[:, np.newaxis] * w[:, np.newaxis]) / denom
    return L, Ls, lam, w, mu, v


def _realify(L: Complex, Ls: Complex) -> tuple[Float, Float, float]:
    """Apply the block-diagonal transform ``_REALIFY_Q`` to both sides of L and Ls.

    Both the row index (built from conjugate pairs of the right set) and the column index (built
    from conjugate pairs of the left set) are transformed, each by its own block-diagonal matrix of
    ``_REALIFY_Q`` blocks. Returns the real parts plus the largest imaginary part discarded, as a
    diagnostic that the transform did what it claims rather than a silent ``.real``.
    """
    rows, cols = L.shape
    q_rows = block_diag(*([_REALIFY_Q] * (rows // 2)))
    q_cols = block_diag(*([_REALIFY_Q] * (cols // 2)))
    l_complex = q_rows.conj().T @ L @ q_cols
    ls_complex = q_rows.conj().T @ Ls @ q_cols
    scale = max(float(np.abs(l_complex).max()), float(np.abs(ls_complex).max()), 1e-300)
    residual = max(float(np.abs(l_complex.imag).max()), float(np.abs(ls_complex.imag).max()))
    return l_complex.real, ls_complex.real, residual / scale


def _order_from_singular_values(sigma: Float, noise_estimate: float) -> tuple[int, int]:
    """Both order rules asked for: (threshold, gap). Neither is picked silently over the other."""
    if sigma.size == 0:
        return 0, 0
    sigma_max = float(sigma[0])
    if sigma_max <= 0.0:
        return 0, 0
    threshold = max(noise_estimate, np.finfo(np.float64).eps ** 0.75) * sigma_max
    order_threshold = int(np.count_nonzero(sigma > threshold))
    if sigma.size >= 2:
        # No noise-scaled floor here, deliberately: the whole point of this rule is to catch the
        # sharp drop from "last real singular value" to "SVD numerical noise floor", and that drop
        # is often 6-8 orders of magnitude. Flooring the denominator at anything data-scaled (as an
        # earlier version of this function did, at sigma_max * sqrt(eps)) washes out exactly the
        # signal being looked for. Only an absolute floor near zero is used, purely to avoid a
        # literal division by zero.
        denom = np.maximum(sigma[1:], 1e-300)
        ratios = sigma[:-1] / denom
        order_gap = int(np.argmax(ratios)) + 1
    else:
        order_gap = sigma.size
    return order_threshold, order_gap


def _poles_at_order(
    Lr: Float, Lsr: Float, order: int
) -> Complex:
    """Truncate the pencil to ``order`` via the SVD of Lr and solve the reduced generalized
    eigenvalue problem for poles, following the Mayo-Antoulas projection construction."""
    if order <= 0:
        return np.array([], dtype=np.complex128)
    u, s, vh = np.linalg.svd(Lr, full_matrices=False)
    order = min(order, s.size)
    un = u[:, :order]
    vn = vh[:order, :].conj().T
    lr_hat = un.conj().T @ Lr @ vn
    lsr_hat = un.conj().T @ Lsr @ vn
    try:
        poles = eig(lsr_hat, lr_hat, right=False)
    except LinAlgError:
        return np.array([], dtype=np.complex128)
    return np.asarray(poles, dtype=np.complex128)


def loewner_order(
    spectrum: Spectrum,
    *,
    noise_estimate: float | None = None,
    rhp_tol: float = DEFAULT_RHP_TOL,
) -> LoewnerResult:
    """Order and poles from the Loewner/shifted-Loewner pencil of the measured Z(s).

    ``noise_estimate`` calibrates rule (a) (the singular-value threshold); it is a relative noise
    level, the same units as ``simulate``'s ``noise`` argument. Real usage without a controlled
    noise level would have to get this from elsewhere (repeat measurements, or the residual left
    by a Lin-KK check) -- rule (a) is not, and does not claim to be, free of that requirement.
    Passing ``None`` falls back to a tolerance near machine precision, appropriate only for
    noise-free (or already-clean) data.
    """
    omega = spectrum.omega
    L, Ls, *_ = _build_loewner(omega, spectrum.z)
    Lr, Lsr, residual = _realify(L, Ls)
    noise = noise_estimate if noise_estimate is not None else np.finfo(np.float64).eps ** 0.5

    sigma_l = np.linalg.svd(Lr, compute_uv=False)
    sigma_both = np.linalg.svd(np.hstack([Lr, Lsr]), compute_uv=False)
    order_threshold, order_gap = _order_from_singular_values(sigma_l, noise)

    poles = _poles_at_order(Lr, Lsr, order_gap)
    finite = poles[np.isfinite(poles)]
    rhp_mask = finite.real > rhp_tol * np.abs(finite)
    return LoewnerResult(
        singular_values_l=sigma_l,
        singular_values_l_ls=sigma_both,
        noise_estimate=noise,
        order_threshold=order_threshold,
        order_gap=order_gap,
        order=order_gap,
        poles=poles,
        admissible_poles=finite[~rhp_mask],
        rhp_poles=finite[rhp_mask],
        max_imag_residual=residual,
    )


# =============================================================================================
# Estimator 3 -- stabilisation diagram
# =============================================================================================


@dataclass
class StabilisationResult:
    """A stabilisation diagram: poles of an independent AAA fit at each trial order.

    Design choice, stated per the task spec ("use the truncated Loewner realisation, or AAA with
    max_terms=n, your choice -- say which and why"): **AAA, one independent fit per trial order**,
    not a truncation of one fixed Loewner pencil. The first version of this function did the
    latter, and it was measured to fail at the one thing a stabilisation diagram exists to do.
    Truncating a single fixed SVD at growing rank means the directions past the data's true rank
    are a *fixed* numerical-noise subspace -- the same noise, just admitting one more of its basis
    vectors at a time -- so two of those directions can land within the matching tolerance of each
    other between two consecutive over-rank orders purely by the coincidence of that one SVD, and
    then look exactly like a stabilised physical pole. This was not a hypothetical: on this
    project's own noise-free four-relaxation reference, that construction reported 6 stable poles
    for a circuit with 4, because a numerical-floor pole pair near 1.3e-5 happened to repeat within
    5% across the two highest trial orders. An independent AAA fit at each order has no such fixed
    subspace to be coincidentally stable in -- each fit re-solves its own least-squares problem
    from scratch, so a spurious pole is free to (and, empirically, does) land somewhere different
    every time order grows, while a genuine pole is pinned by the data and does not move. Re-run on
    the same reference, this version reports the poles at -1e5 and -1e3 fixed at every order from
    their first appearance through the top of the tested range, and every other pole scattered.
    """

    orders_tested: tuple[int, ...]
    poles_by_order: dict[int, Complex]
    stable_mask_by_order: dict[int, NDArray[np.bool_]]
    """For each order n (except the last tested), which of its poles matched a pole at n+1."""
    stable_count: int
    """Stable-pole count at the highest tested order transition -- the estimator's headline
    order."""


def _match_stable(poles_a: Complex, poles_b: Complex, reltol: float) -> NDArray[np.bool_]:
    """For each pole in ``poles_a``, is there an unused pole in ``poles_b`` within ``reltol``
    relative distance? Greedy nearest-neighbour matching, adequate for counting stabilised poles
    in a benchmark (not claiming an optimal assignment)."""
    stable = np.zeros(poles_a.size, dtype=bool)
    used = np.zeros(poles_b.size, dtype=bool)
    order_by_closeness = np.argsort(-np.abs(poles_a))  # match large-magnitude poles first
    for i in order_by_closeness:
        if poles_b.size == 0:
            break
        scale = max(abs(poles_a[i]), 1e-300)
        dist = np.abs(poles_b - poles_a[i]) / scale
        dist = np.where(used, np.inf, dist)
        j = int(np.argmin(dist))
        if dist[j] < reltol:
            stable[i] = True
            used[j] = True
    return stable


def stabilisation_order(
    spectrum: Spectrum,
    *,
    orders: tuple[int, ...] = tuple(range(1, 9)),
    reltol: float = 5e-2,
    rhp_tol: float = DEFAULT_RHP_TOL,
    far_factor: float = DEFAULT_FAR_FACTOR,
) -> StabilisationResult:
    """Stabilisation diagram: which poles survive, at the same location, as the trial order grows?

    One independent ``scipy.interpolate.AAA`` fit per trial order n, forced to exactly n terms by
    passing ``max_terms=n`` with ``rtol=0`` (which AAA cannot satisfy in n iterations for any but
    trivial data, so it always runs the full n greedy steps rather than stopping early -- see the
    class docstring for why an independent fit per order, rather than one reused pencil, is the
    point). Only *admissible* poles (``Re <= rhp_tol * |pole|`` and not absurdly far outside the
    sampled band) are eligible to be counted stable -- a pole with a positive real part or one
    parked many decades outside the data is already known to be an artefact by the same criteria
    ``aaa_order`` uses, and should not be rewarded for coincidentally landing close to another
    artefact.
    """
    omega = spectrum.omega
    s, v = _conjugate_augment(omega, spectrum.z)
    omega_max = float(omega.max())
    tested = tuple(n for n in sorted(set(orders)) if n >= 1)

    poles_by_order: dict[int, Complex] = {}
    for n in tested:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            fit = AAA(s, v, rtol=0.0, max_terms=n)
        poles = fit.poles()
        finite = poles[np.isfinite(poles)]
        far_mask = np.abs(finite) > far_factor * omega_max
        near = finite[~far_mask]
        admissible = near[near.real <= rhp_tol * np.abs(near)]
        poles_by_order[n] = admissible

    stable_mask_by_order: dict[int, NDArray[np.bool_]] = {}
    for n, n_next in zip(tested[:-1], tested[1:], strict=False):
        stable_mask_by_order[n] = _match_stable(
            poles_by_order[n], poles_by_order[n_next], reltol
        )

    if len(tested) >= 2:
        second_last = tested[-2]
        stable_count = int(np.count_nonzero(stable_mask_by_order[second_last]))
    else:
        stable_count = int(poles_by_order[tested[0]].size) if tested else 0

    return StabilisationResult(
        orders_tested=tested,
        poles_by_order=poles_by_order,
        stable_mask_by_order=stable_mask_by_order,
        stable_count=stable_count,
    )


# =============================================================================================
# Reference truths
# =============================================================================================


@dataclass
class Truth:
    name: str
    circuit: str
    values: dict[str, float]
    finite_degree: bool
    """True for R/C/L-only circuits (a finite McMillan degree exists); False for CPE/Warburg
    truths, where no finite-order rational function is exact."""
    note: str = ""


#: A shared, wide band (11 decades) so every truth's relaxation frequencies (0.016 Hz to 15.9 kHz,
#: see the per-truth time constants below) sit comfortably inside it with margin on both sides, and
#: the CPE/Warburg truths have room for the bandwidth-widening check in ``fractional_growth``.
F_MIN = 1e-4
F_MAX = 1e7

TRUTHS: tuple[Truth, ...] = (
    Truth(
        name="1relax",
        circuit="p(R1,C1)",
        values={"R1.R": 100.0, "C1.C": 1e-7},  # tau = 1e-5 s, f0 = 1.59e4 Hz
        finite_degree=True,
        note="one Debye relaxation, one finite pole expected.",
    ),
    Truth(
        name="2relax",
        circuit="p(R1,C1)-p(R2,C2)",
        values={"R1.R": 100.0, "C1.C": 1e-7, "R2.R": 300.0, "C2.C": 10.0 / 3000.0 * 1e-3},
        finite_degree=True,
        note="two relaxations two decades apart in tau (1e-5 s, 1e-3 s).",
    ),
    Truth(
        name="3relax",
        circuit="p(R1,C1)-p(R2,C2)-p(R3,C3)",
        values={
            "R1.R": 100.0,
            "C1.C": 1e-7,
            "R2.R": 300.0,
            "C2.C": 10.0 / 3000.0 * 1e-3,
            "R3.R": 900.0,
            "C3.C": 0.1 / 900.0,
        },
        finite_degree=True,
        note="three relaxations, tau = 1e-5, 1e-3, 1e-1 s.",
    ),
    Truth(
        name="4relax",
        circuit="p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)",
        values={
            "R1.R": 100.0,
            "C1.C": 1e-7,
            "R2.R": 300.0,
            "C2.C": 10.0 / 3000.0 * 1e-3,
            "R3.R": 900.0,
            "C3.C": 0.1 / 900.0,
            "R4.R": 2700.0,
            "C4.C": 10.0 / 2700.0,
        },
        finite_degree=True,
        note="four relaxations, tau = 1e-5, 1e-3, 1e-1, 1e1 s.",
    ),
    Truth(
        name="rcl_relax",
        circuit="C1-R1-L1-p(R2,C2)",
        values={"C1.C": 1e-6, "R1.R": 50.0, "L1.L": 1e-3, "R2.R": 200.0, "C2.C": 1e-5},
        finite_degree=True,
        note=(
            "Degree worked out by hand: Z(s) = 1/(sC1) + R1 + sL1 + R2/(1+sR2C2). Over the common "
            "denominator s(1+sR2C2) (degree 2), the numerator has degree 3 -- one more than the "
            "denominator, which is exactly what a series inductor does (Z ~ s at high frequency, "
            "an *improper* rational function). The finite poles -- roots of the degree-2 "
            "denominator -- number 2 (s=0 from C1, s=-1/(R2C2) from the relaxation); the state "
            "count (McMillan degree in the sense of independent energy-storage elements: C1, L1, "
            "C2) is 3. AAA's barycentric form is bounded as s -> infinity by construction and so "
            "cannot represent the sL1 growth with a finite pole at all -- it is expected to need "
            "extra poles pushed toward the edge of the sampled band to fake it, which is exactly "
            "the 'far' rejection category ``aaa_order`` reports separately. This truth is included "
            "to see which of {2, 3, something else} each estimator's own noise-free run settles "
            "on, not to assert one number is correct."
        ),
    ),
    Truth(
        name="cpe",
        circuit="R1-p(R2,CPE1)",
        values={"R1.R": 50.0, "R2.R": 500.0, "CPE1.Q": 1.0e-5, "CPE1.n": 0.8},
        finite_degree=False,
        note="depressed-arc CPE relaxation; no finite degree exists.",
    ),
    Truth(
        name="randles_warburg",
        circuit="R1-p(C1,R2-W1)",
        values={"R1.R": 20.0, "C1.C": 1.0e-6, "R2.R": 200.0, "W1.A": 50.0},
        finite_degree=False,
        note="Randles cell with a semi-infinite Warburg branch; no finite degree exists.",
    ),
)


def build_spectrum(truth: Truth, *, ppd: int, noise: float, seed: int | None) -> Spectrum:
    f = log_frequencies(F_MIN, F_MAX, ppd)
    return simulate(
        truth.circuit, f, truth.values, noise=noise, noise_model="proportional", seed=seed
    )


# =============================================================================================
# Per-estimator "give me one integer" wrappers, shared between the reference run and the grid
# =============================================================================================

#: Trial orders for the stabilisation diagram: enough headroom above the largest finite truth (4)
#: to let extra, unstable poles show up and be rejected rather than accidentally define the count.
STABILISATION_ORDERS: tuple[int, ...] = tuple(range(1, 9))


def estimate_aaa(spectrum: Spectrum, noise: float) -> tuple[int, AAAResult]:
    """AAA order at a noise-calibrated rtol (3x the known noise level, floored near machine eps).

    3x is not tuned; it is the smallest round number comfortably above one noise standard
    deviation, on the reasoning that AAA's stopping rule is itself phrased as a multiple of the
    data's dynamic range (see the AAA docstring) and should not be asked for accuracy finer than
    the data supports.
    """
    rtol = max(3.0 * noise, 1e-6)
    result = aaa_order(spectrum, rtol=rtol)
    return result.n_admissible, result


def estimate_loewner_threshold(spectrum: Spectrum, noise: float) -> tuple[int, LoewnerResult]:
    result = loewner_order(spectrum, noise_estimate=max(noise, 1e-9))
    return result.order_threshold, result


def estimate_loewner_gap(spectrum: Spectrum, noise: float) -> tuple[int, LoewnerResult]:
    result = loewner_order(spectrum, noise_estimate=max(noise, 1e-9))
    return result.order_gap, result


def estimate_stabilisation(spectrum: Spectrum, _noise: float) -> tuple[int, StabilisationResult]:
    result = stabilisation_order(spectrum, orders=STABILISATION_ORDERS)
    return result.stable_count, result


ESTIMATORS = {
    "aaa": estimate_aaa,
    "loewner_threshold": estimate_loewner_threshold,
    "loewner_gap": estimate_loewner_gap,
    "stabilisation": estimate_stabilisation,
}

#: Dense, noise-free reference sampling -- 40 points/decade over the full band.
REFERENCE_PPD = 40


def reference_orders() -> dict[str, dict[str, int]]:
    """Run every estimator on a dense, noise-free simulation of every truth.

    Per the task spec: this is *not* asserted analytically (aside from the commentary on
    ``rcl_relax`` above) -- it is what each estimator actually reports, and that is what the noisy
    grid below is scored against. If an estimator's noise-free number disagrees with the truth's
    known relaxation count for the four simple RC-ladder truths, that is reported loudly, because
    it means the estimator is broken, not that the truth is wrong.
    """
    out: dict[str, dict[str, int]] = {}
    for truth in TRUTHS:
        spectrum = build_spectrum(truth, ppd=REFERENCE_PPD, noise=0.0, seed=None)
        out[truth.name] = {}
        for est_name, est_fn in ESTIMATORS.items():
            order, _detail = est_fn(spectrum, 0.0)
            out[truth.name][est_name] = order
    return out


# =============================================================================================
# The noise x points-per-decade grid
# =============================================================================================

DEFAULT_NOISE_LEVELS: tuple[float, ...] = (0.0, 0.001, 0.003, 0.01, 0.03)
DEFAULT_PPD_LEVELS: tuple[int, ...] = (5, 10, 20)
DEFAULT_SEEDS = 5


def _bucket(estimate: int, reference: int) -> str:
    diff = estimate - reference
    if diff == 0:
        return "exact"
    if diff == 1:
        return "plus_one"
    if diff == -1:
        return "minus_one"
    return "further"


@dataclass
class GridCell:
    truth: str
    estimator: str
    noise: float
    ppd: int
    reference: int
    estimates: list[int] = field(default_factory=list)
    buckets: dict[str, int] = field(
        default_factory=lambda: {"exact": 0, "plus_one": 0, "minus_one": 0, "further": 0}
    )

    def add(self, estimate: int) -> None:
        self.estimates.append(estimate)
        self.buckets[_bucket(estimate, self.reference)] += 1

    def fraction(self, bucket: str) -> float:
        total = len(self.estimates)
        return self.buckets[bucket] / total if total else float("nan")


def run_grid(
    truths: tuple[Truth, ...],
    references: dict[str, dict[str, int]],
    *,
    noise_levels: tuple[float, ...],
    ppd_levels: tuple[int, ...],
    seeds: int,
) -> list[GridCell]:
    cells: list[GridCell] = []
    for truth in truths:
        for ppd in ppd_levels:
            for noise in noise_levels:
                per_estimator = {
                    name: GridCell(
                        truth=truth.name,
                        estimator=name,
                        noise=noise,
                        ppd=ppd,
                        reference=references[truth.name][name],
                    )
                    for name in ESTIMATORS
                }
                n_seeds = 1 if noise == 0.0 else seeds
                for seed in range(n_seeds):
                    spectrum = build_spectrum(
                        truth, ppd=ppd, noise=noise, seed=seed if noise > 0.0 else None
                    )
                    for name, est_fn in ESTIMATORS.items():
                        try:
                            estimate, _detail = est_fn(spectrum, noise)
                        except (LinAlgError, ValueError):
                            estimate = -1  # recorded as "further", never silently dropped
                        per_estimator[name].add(estimate)
                cells.extend(per_estimator.values())
    return cells


def headline(cells: list[GridCell], *, noise: float, ppd: int) -> dict[str, float]:
    """The number the experiment is pre-registered to produce: exact-recovery rate at 1% noise,
    10 points/decade, averaged over the finite-degree truths (the ones with a well-posed answer)."""
    finite_truth_names = {t.name for t in TRUTHS if t.finite_degree}
    out: dict[str, float] = {}
    for name in ESTIMATORS:
        matching = [
            c
            for c in cells
            if c.estimator == name
            and c.noise == noise
            and c.ppd == ppd
            and c.truth in finite_truth_names
        ]
        if not matching:
            out[name] = float("nan")
            continue
        exact = sum(c.buckets["exact"] for c in matching)
        total = sum(len(c.estimates) for c in matching)
        out[name] = exact / total if total else float("nan")
    return out


# =============================================================================================
# Fractional-element growth check (CPE, Warburg)
# =============================================================================================


@dataclass
class GrowthPoint:
    x: float
    order: int


def rtol_growth(truth: Truth) -> list[GrowthPoint]:
    """AAA admissible-pole count as ``rtol`` tightens, at the fixed shared band, noise-free.

    For a truth with no finite degree, this is expected to grow (not necessarily strictly, but on
    average) as the tolerance tightens -- there is always a better finite-order approximation to be
    had by adding one more pole, unlike a genuinely finite-degree circuit where it plateaus (see
    ``reference_orders``, where it does not move once ``rtol`` is smaller than the noise floor).
    """
    spectrum = build_spectrum(truth, ppd=REFERENCE_PPD, noise=0.0, seed=None)
    points = []
    for rtol in DEFAULT_AAA_RTOLS:
        result = aaa_order(spectrum, rtol=rtol)
        points.append(GrowthPoint(x=rtol, order=result.n_admissible))
    return points


def bandwidth_growth(truth: Truth, *, rtol: float = 1e-4, n_steps: int = 5) -> list[GrowthPoint]:
    """AAA admissible-pole count as the sampled bandwidth widens by decades, at fixed ``rtol``.

    Each step multiplies both ``f_min`` and ``f_max`` outward by one decade around the truth's own
    band, keeping the number of points per decade fixed, so more bandwidth genuinely means more
    of the CPE/Warburg's power-law tail is visible rather than just more points at the same
    frequencies.
    """
    points = []
    for step in range(n_steps):
        f_min = F_MIN / (10.0**step)
        f_max = F_MAX * (10.0**step)
        f = log_frequencies(f_min, f_max, REFERENCE_PPD)
        spectrum = simulate(truth.circuit, f, truth.values, noise=0.0)
        result = aaa_order(spectrum, rtol=rtol)
        points.append(GrowthPoint(x=f_max / f_min, order=result.n_admissible))
    return points


def fractional_growth_report() -> dict[str, dict[str, list[GrowthPoint]]]:
    out: dict[str, dict[str, list[GrowthPoint]]] = {}
    for truth in TRUTHS:
        if truth.finite_degree:
            continue
        out[truth.name] = {
            "rtol_growth": rtol_growth(truth),
            "bandwidth_growth": bandwidth_growth(truth),
        }
    return out


def _is_monotonic_nondecreasing(points: list[GrowthPoint], *, x_ascending: bool) -> bool:
    ordered = sorted(points, key=lambda p: p.x, reverse=not x_ascending)
    orders = [p.order for p in ordered]
    return all(b >= a for a, b in zip(orders[:-1], orders[1:], strict=False))


# =============================================================================================
# Reporting
# =============================================================================================


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, complex | np.complexfloating):
        return {"re": float(obj.real), "im": float(obj.imag)}
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return [_to_jsonable(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, GrowthPoint):
        return {"x": obj.x, "order": obj.order}
    if isinstance(obj, GridCell):
        return {
            "truth": obj.truth,
            "estimator": obj.estimator,
            "noise": obj.noise,
            "ppd": obj.ppd,
            "reference": obj.reference,
            "estimates": obj.estimates,
            "buckets": obj.buckets,
        }
    return obj


def render_markdown(
    references: dict[str, dict[str, int]],
    cells: list[GridCell],
    growth: dict[str, dict[str, list[GrowthPoint]]],
    *,
    noise_levels: tuple[float, ...],
    ppd_levels: tuple[int, ...],
) -> str:
    lines: list[str] = []
    lines.append("# X9 -- rational-approximation order estimation")
    lines.append("")
    lines.append(
        f"## Noise-free dense reference (ppd={REFERENCE_PPD}, band {F_MIN:.0e}-{F_MAX:.0e} Hz)"
    )
    lines.append("")
    lines.append(
        "| truth | expected (finite-degree truths only) | aaa | loewner (threshold) | "
        "loewner (gap) | stabilisation |"
    )
    lines.append("|---|---|---|---|---|---|")
    for truth in TRUTHS:
        expected_relax = {
            "1relax": "1",
            "2relax": "2",
            "3relax": "3",
            "4relax": "4",
            "rcl_relax": "2 finite poles / 3 states (see note)",
            "cpe": "none (fractional)",
            "randles_warburg": "none (fractional)",
        }[truth.name]
        row = references[truth.name]
        lines.append(
            f"| {truth.name} | {expected_relax} | {row['aaa']} | {row['loewner_threshold']} | "
            f"{row['loewner_gap']} | {row['stabilisation']} |"
        )
    lines.append("")

    lines.append("## Headline: exact-recovery rate at 1% noise, 10 points/decade")
    lines.append("(averaged over the four finite-degree RC-ladder truths)")
    lines.append("")
    if 0.01 in noise_levels and 10 in ppd_levels:
        head = headline(cells, noise=0.01, ppd=10)
        lines.append("| estimator | exact-recovery rate |")
        lines.append("|---|---|")
        for name, rate in head.items():
            lines.append(f"| {name} | {rate:.2f} |")
    else:
        lines.append("(not computed: 1% / 10ppd not in this run's grid)")
    lines.append("")

    lines.append("## Full grid: recovery buckets by (truth, estimator, noise, ppd)")
    lines.append("")
    lines.append("| truth | estimator | noise | ppd | reference | exact | +1 | -1 | further |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for cell in cells:
        lines.append(
            f"| {cell.truth} | {cell.estimator} | {cell.noise} | {cell.ppd} | {cell.reference} | "
            f"{cell.fraction('exact'):.2f} | {cell.fraction('plus_one'):.2f} | "
            f"{cell.fraction('minus_one'):.2f} | {cell.fraction('further'):.2f} |"
        )
    lines.append("")

    lines.append("## Fractional-element growth (CPE, Warburg truths)")
    lines.append("")
    for name, data in growth.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("rtol sweep (rtol tightens left to right):")
        rtol_pts = data["rtol_growth"]
        lines.append(
            "| " + " | ".join(f"{p.x:.0e}" for p in rtol_pts) + " |"
        )
        lines.append("|" + "---|" * len(rtol_pts))
        lines.append("| " + " | ".join(str(p.order) for p in rtol_pts) + " |")
        monotone = _is_monotonic_nondecreasing(rtol_pts, x_ascending=False)
        lines.append(f"monotonic non-decreasing as rtol tightens: **{monotone}**")
        lines.append("")
        lines.append("bandwidth sweep (decades widen left to right):")
        bw_pts = data["bandwidth_growth"]
        lines.append("| " + " | ".join(f"{p.x:.0e}" for p in bw_pts) + " |")
        lines.append("|" + "---|" * len(bw_pts))
        lines.append("| " + " | ".join(str(p.order) for p in bw_pts) + " |")
        monotone_bw = _is_monotonic_nondecreasing(bw_pts, x_ascending=True)
        lines.append(f"monotonic non-decreasing as bandwidth widens: **{monotone_bw}**")
        lines.append("")

    return "\n".join(lines)


# =============================================================================================
# CLI
# =============================================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, required=True, help="path to write the JSON dump")
    parser.add_argument("--quick", action="store_true", help="small grid, for a fast smoke test")
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS, help="noise seeds per cell")
    parser.add_argument(
        "--noise", type=float, nargs="+", default=list(DEFAULT_NOISE_LEVELS), help="noise levels"
    )
    parser.add_argument(
        "--ppd", type=int, nargs="+", default=list(DEFAULT_PPD_LEVELS), help="points per decade"
    )
    args = parser.parse_args()

    if args.quick:
        noise_levels = (0.0, 0.01)
        ppd_levels = (10,)
        seeds = 2
        truths = TRUTHS
    else:
        noise_levels = tuple(args.noise)
        ppd_levels = tuple(args.ppd)
        seeds = args.seeds
        truths = TRUTHS

    t0 = time.time()
    print("Computing noise-free dense reference orders...")
    references = reference_orders()
    for truth_name, row in references.items():
        print(f"  {truth_name}: {row}")

    print(
        f"Running the noise x ppd grid ({len(noise_levels)} x {len(ppd_levels)}, "
        f"{seeds} seeds)..."
    )
    cells = run_grid(
        truths, references, noise_levels=noise_levels, ppd_levels=ppd_levels, seeds=seeds
    )

    print("Running the fractional-element growth check...")
    growth = fractional_growth_report()

    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f} s.")

    if 0.01 in noise_levels and 10 in ppd_levels:
        head = headline(cells, noise=0.01, ppd=10)
        print("\nHeadline (1% noise, 10 ppd, exact-recovery rate over finite-degree truths):")
        for name, rate in head.items():
            print(f"  {name}: {rate:.2f}")
    else:
        print("\n(--quick or a custom grid: 1%/10ppd headline not available this run)")

    payload = {
        "reference_orders": references,
        "grid": {
            "noise_levels": list(noise_levels),
            "ppd_levels": list(ppd_levels),
            "seeds": seeds,
            "cells": [_to_jsonable(c) for c in cells],
        },
        "headline_1pct_10ppd": (
            headline(cells, noise=0.01, ppd=10)
            if 0.01 in noise_levels and 10 in ppd_levels
            else None
        ),
        "fractional_growth": _to_jsonable(growth),
        "elapsed_seconds": elapsed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, allow_nan=False))
    print(f"\nWrote {args.out}")

    md_path = args.out.with_suffix(".md")
    md_path.write_text(
        render_markdown(references, cells, growth, noise_levels=noise_levels, ppd_levels=ppd_levels)
    )
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
