"""A noise scale estimated from the spectrum itself, model-free.

``docs/IMPACT_PLAN.md`` item B: ``weighting`` is a knob with four values, and picking between
them is exactly the kind of judgement ``CLAUDE.md``'s first consequence rules out asking a
non-expert to make -- whether an instrument's error is proportional to ``|Z|``, proportional to
each component separately, or has an additive floor is not something an analyst with little
background knows going in. ``"auto"`` removes the question the way ``--pool auto``
(``docs/POOL_FROM_SPECTRUM_PLAN.md``) removed a different one: instead of asking, estimate the
one thing a weighting scheme is actually a guess about -- how much noise is on this point -- from
the data.

**This is a scale, not a shape.** :func:`autocircuit.core.weighting.weight_vectors`'s ``sigma``
case already takes one array and applies it to both the real and imaginary residual
(``return 1.0 / s, 1.0 / s``), so what this module estimates is one noise amplitude per
frequency, in ohms, common to both components. A real instrument's real and imaginary errors can
in principle differ, and this does not attempt to separate them -- doing so would need
``weight_vectors`` to accept two arrays instead of one, which is a larger change than the
evidence for asking it justifies today (see gate N1, and the record in ``docs/IMPACT_PLAN.md``
item B). Pooling the two components' residuals into one estimate is also what makes the
estimator usable with as few as a handful of points per decade.

**The window width is chosen by the data, not by this module.** ``docs/IMPACT_PLAN.md`` item B
section 2.2 records the investigation this design comes from, and it is worth reading before
touching :data:`CANDIDATE_SPAN_FRACTIONS`: a *fixed* local-polynomial window, tuned by sweeping
it until one named reference (Maxwell-Wagner, two relaxations several decades apart) passed, was
built first and rejected once that was recognised for what it was -- a constant fitted to the
test, with no argument for why it would still be right on the next spectrum. What ships instead
picks the window per spectrum by **generalised cross-validation (GCV)**, the same principle
:mod:`autocircuit.core.drt` already uses to select its own regularisation strength, applied here
to a bandwidth instead: at each of a handful of candidate widths, score the in-sample fit's mean
squared residual *penalised by how much flexibility the fit was given* (the average leverage,
i.e. the hat-matrix trace over the point count), and keep the width with the lowest score. On a
spectrum with sharp local structure this comes out narrow; on a smooth one it comes out wide.
Nothing here says which in advance.

**Why GCV and not plain leave-one-out cross-validation, which was tried first.** LOOCV picked
spans that were measurably too narrow -- on the capacitor reference (a sharp fractional
skin-effect element) it under-estimated the injected sigma by roughly half, consistently across
seeds. This is not a coincidence: minimising held-out prediction error alone rewards a narrower
window for the variance it removes without charging it for the degrees of freedom it spent
getting there, so it systematically favours over-flexible fits -- a documented property of
leave-one-out bandwidth selection, and the exact reason the statistics literature reaches for
GCV's degrees-of-freedom correction instead. Measured here: GCV moves the capacitor's median
ratio from about 0.5 (borderline-failing) to 0.6-0.8 without moving Maxwell-Wagner or Randles's
already-good numbers.

**Not fixed by this design: a genuine anti-resonance.** No local smoother -- polynomial or
otherwise -- distinguishes "noise" from "a feature this family of curves cannot express" any
better than :mod:`autocircuit.core.validate`'s Lin-KK basis does (``docs/KK_RESONANCE_PLAN.md``),
and a parallel resonance (a pole) is exactly such a feature. Measured on a ferrite-bead reference
(item B section 2.2): every candidate width, including the widest tried, still overestimates
sigma there by a large factor. What makes shipping this defensible regardless is the *direction*
of that failure for this specific consumer: an inflated sigma near an unmodelled feature
down-weights it in a least-squares fit rather than over-trusting it, which is the safe side of
the two possible errors -- gate N4 in the plan checks that claim rather than assuming it.

**No circuit, and no scipy.** Everything here is ``numpy.linalg.lstsq``. That is not an
optimisation for its own sake: :mod:`autocircuit.core.weighting` was split out of
:mod:`autocircuit.core.fit` for exactly the reason that :mod:`autocircuit.core.validate` needs it
without pulling in ``scipy.optimize``, because the browser reads and trims a spectrum before
``scipy`` has finished loading (``docs/STARTUP_AND_EDITING_PLAN.md`` section 3). This module sits
on the same side of that line, so ``lin_kk`` can resolve ``"auto"`` weighting without moving that
line.
"""

from __future__ import annotations

import math

import numpy as np

from .spectrum import Spectrum
from .weighting import Float, Weighting, weight_vectors

#: Candidate window widths for the cross-validated smoother, as fractions of the spectrum's
#: point count. [measured, docs/IMPACT_PLAN.md item B section 2.2] Log-spaced from "as narrow as
#: :data:`MIN_LOCAL_POINTS` lets a spectrum with under ~75 points go" to "half the spectrum",
#: which bracketed the width every one of the investigation's four reference shapes actually
#: wanted: 8% for a spectrum with a sharp fractional (skin-effect) element, 15-20% for a plain
#: relaxation or two, and the widest available for a spectrum with no width that helps at all
#: (the anti-resonance case, where cross-validation correctly fails to find a good option rather
#: than settling on a falsely reasonable-looking one).
CANDIDATE_SPAN_FRACTIONS: tuple[float, ...] = (0.08, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5)

#: Smallest local window, in points. A local quadratic has three coefficients; six points
#: leaves three degrees of freedom to judge the fit's own scatter by, which is little but not
#: nothing.
MIN_LOCAL_POINTS = 6

#: Degree of the local polynomial (fitted in ``log10(f)``, centred on the query point). Not
#: swept alongside the window width: quadratic is the standard LOESS choice and the
#: investigation's four shapes gave no reason to make degree a second free parameter here.
LOESS_DEGREE = 2

#: Floor on the estimated sigma, as a fraction of the spectrum's largest |Z|. Without it a
#: noise-free synthetic spectrum -- every round-trip test in this repository builds one --
#: returns an estimate of exactly zero at some points, and ``weight_vectors``'s ``"sigma"`` case
#: requires strictly positive values. The floor is far below anything a real measurement or a
#: deliberately noisy synthetic spectrum would ever estimate, so it only ever bites there.
SIGMA_FLOOR_FRACTION = 1e-9


def _tricube(u: Float) -> Float:
    """LOESS's usual kernel: 1 at zero distance, 0 at and beyond the window edge."""
    return (1.0 - np.clip(u, 0.0, 1.0) ** 3) ** 3


def _local_window(i: int, n: int, span_points: int) -> tuple[int, int]:
    """The ``[lo, hi)`` slice of ``span_points`` neighbours around index ``i``, clipped to
    ``[0, n)`` and shifted rather than shrunk at either edge so it stays full width."""
    half = span_points // 2
    lo, hi = i - half, i + half + 1
    if lo < 0:
        hi -= lo
        lo = 0
    if hi > n:
        lo -= hi - n
        hi = n
    return max(lo, 0), min(hi, n)


def _loess_fit(x: Float, y: Float, span_points: int, degree: int) -> tuple[Float, Float]:
    """The locally-weighted polynomial smooth of ``y(x)``, plus each point's own leverage.

    One weighted least-squares solve per point, each using the ``span_points`` neighbours
    closest in ``x`` (``x`` is already sorted, since :class:`Spectrum` sorts by frequency) and a
    tricube weight that favours the near ones. The design matrix is centred on ``x[i]`` at each
    step (``xw - x[i]``) so the fitted value at the query point is simply the constant term --
    the usual trick that avoids evaluating a polynomial away from where it was fitted, which is
    where a local fit is least trustworthy.

    The leverage is ``y[i]``'s own coefficient in that solve -- the diagonal of the hat matrix a
    linear smoother always has, here computed one point at a time via the local normal
    equations' pseudo-inverse rather than assembled as one ``n x n`` matrix. It is not used by
    the smooth curve itself; it is what lets :func:`_gcv_score` tell a window that fits well
    from one that was simply given enough flexibility to fit anything.
    """
    n = x.size
    fitted = np.empty(n, dtype=np.float64)
    leverage = np.empty(n, dtype=np.float64)
    for i in range(n):
        lo, hi = _local_window(i, n, span_points)
        idx = np.arange(lo, hi)
        xw = x[idx] - x[i]
        yw = y[idx]
        reach = float(np.max(np.abs(xw))) if xw.size else 1.0
        w = _tricube(np.abs(xw) / (reach or 1.0))
        design = np.vander(xw, degree + 1, increasing=True)
        gram = design.T @ (design * w[:, None])
        hat_row = np.linalg.pinv(gram) @ (design.T * w)  # (degree + 1, len(idx))
        fitted[i] = float(hat_row[0] @ yw)
        self_pos = np.flatnonzero(idx == i)
        leverage[i] = float(hat_row[0, self_pos[0]]) if self_pos.size else 0.0
    return fitted, leverage


def _gcv_score(residual: Float, leverage: Float) -> float:
    """Generalised cross-validation score: in-sample MSE, penalised for the fit's own leverage.

    ``GCV = (RSS / n) / (1 - tr(H)/n)^2``, the standard form for a linear smoother. Leave-one-out
    cross-validation is the same idea without the ``(1 - tr(H)/n)^2`` correction, and it was
    tried first here and rejected (see the module docstring) because omitting that correction
    rewards a window for its own flexibility, not for how well it actually predicts.
    """
    denominator = 1.0 - float(np.mean(leverage))
    if abs(denominator) < 1e-6:
        return math.inf
    return float(np.mean(residual**2)) / (denominator**2)


def _select_span(x: Float, y_re: Float, y_im: Float, degree: int) -> int:
    """The candidate window width with the lowest GCV score for this spectrum."""
    n = x.size
    candidates = sorted(
        {
            int(round(frac * n))
            for frac in CANDIDATE_SPAN_FRACTIONS
            if round(frac * n) >= MIN_LOCAL_POINTS
        }
    )
    if not candidates:
        return min(MIN_LOCAL_POINTS, n)
    scored = []
    for span in candidates:
        fitted_re, leverage_re = _loess_fit(x, y_re, span, degree)
        fitted_im, leverage_im = _loess_fit(x, y_im, span, degree)
        score = _gcv_score(y_re - fitted_re, leverage_re) + _gcv_score(
            y_im - fitted_im, leverage_im
        )
        scored.append((span, score))
    return min(scored, key=lambda item: item[1])[0]


def _rolling_mad_scale(x: Float, resid_re: Float, resid_im: Float, window_points: int) -> Float:
    """A robust local noise scale from residuals already centred on zero by :func:`_loess_fit`.

    Each window pools the real *and* imaginary residuals together -- ``2 * window_points``
    numbers with (by construction) zero local mean -- and takes their median absolute
    deviation, scaled by 1.4826 so it estimates a Gaussian standard deviation rather than the
    MAD itself. The median is robust to the occasional point the local polynomial fit badly,
    which an RMS over the same window would not be.
    """
    n = x.size
    half = window_points // 2
    scale = np.empty(n, dtype=np.float64)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        pooled = np.concatenate([resid_re[lo:hi], resid_im[lo:hi]])
        scale[i] = 1.4826 * float(np.median(np.abs(pooled - np.median(pooled))))
    return scale


def estimate_sigma(spectrum: Spectrum) -> Float:
    """A per-frequency noise amplitude, in ohms, estimated without assuming any circuit.

    Three steps. First, :func:`_select_span` picks one window width for this spectrum by
    generalised cross-validation -- see the module docstring for why a fixed width was tried
    and rejected, and why GCV rather than plain cross-validation. Second, a local quadratic in
    ``log10(f)`` at that width is fitted to ``Re Z`` and to ``Im Z`` independently, and the
    residual from that smooth curve stands in for the noise at each point. Third, because a
    single residual is itself noisy, a rolling median absolute deviation over both components
    turns the pointwise residuals into a smooth scale.

    Returns:
        One value per point of ``spectrum``, strictly positive, in the same units as ``spectrum
        .z``. Feed it to :func:`resolve_weights` (or directly to
        :func:`autocircuit.core.weighting.weight_vectors` as ``sigma``) rather than reading it
        as a measurement of anything -- it is a scale for weighting residuals, not a
        characterisation of the instrument, and section 2.2 of ``docs/IMPACT_PLAN.md`` item B
        records the one shape (a genuine anti-resonance) where it should not be trusted as one.
    """
    x = np.log10(spectrum.f)
    span = _select_span(x, spectrum.z.real, spectrum.z.imag, LOESS_DEGREE)
    smooth_re, _ = _loess_fit(x, spectrum.z.real, span, LOESS_DEGREE)
    smooth_im, _ = _loess_fit(x, spectrum.z.imag, span, LOESS_DEGREE)
    resid_re = spectrum.z.real - smooth_re
    resid_im = spectrum.z.imag - smooth_im
    sigma = _rolling_mad_scale(x, resid_re, resid_im, span)
    floor = float(np.max(np.abs(spectrum.z))) * SIGMA_FLOOR_FRACTION
    return np.maximum(sigma, floor)


def resolve_weights(
    spectrum: Spectrum, weighting: Weighting, sigma: Float | None = None
) -> tuple[Float, Float]:
    """The (real, imaginary) residual weights, resolving ``"auto"`` against ``spectrum`` first.

    Every call site that used to call
    :func:`~autocircuit.core.weighting.weight_vectors` directly calls this instead, because
    ``"auto"`` needs the whole spectrum -- :func:`estimate_sigma` reads ``f`` as well as ``z`` --
    and ``weight_vectors`` deliberately does not: it is the module :mod:`autocircuit.core.
    validate` imports to stay scipy-free, and adding a spectrum-shaped estimate to it would have
    made it exactly the kind of thing that module was split out to avoid depending on. This
    function does the same job for every other ``weighting`` value by simply forwarding to it,
    so nothing that already worked has a second code path to go out of sync with.
    """
    if weighting != "auto":
        return weight_vectors(spectrum.z, weighting, sigma)
    if sigma is not None:
        raise ValueError('sigma is not accepted with weighting="auto"; it is estimated')
    return weight_vectors(spectrum.z, "sigma", sigma=estimate_sigma(spectrum))


__all__ = ["estimate_sigma", "resolve_weights"]
