"""How a residual is weighted: the choice, and the vectors it produces.

Split out of :mod:`autocircuit.core.fit` rather than living there, and the reason is a load
order rather than tidiness. These two names are pure numpy, and :mod:`autocircuit.core.validate`
-- which is all a browser needs to read, trim and check a spectrum -- imported the whole fitter
to get them, and with it ``scipy.optimize``. The web front end loads scipy *after* the page is
usable (``docs/STARTUP_AND_EDITING_PLAN.md`` section 3), so anything the data path touches has to
be reachable without it.

:mod:`autocircuit.core.fit` re-exports both names, so ``from autocircuit.core.fit import
Weighting, weight_vectors`` keeps working and no caller has to know this file exists.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import NDArray

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

Weighting = Literal["unit", "modulus", "proportional", "sigma", "auto"]

#: ``weight_vectors`` never sees ``"auto"``: it is resolved against a spectrum first, by
#: :func:`autocircuit.core.noise.resolve_weights`, into a concrete ``sigma`` array. It is a
#: member of this type rather than of a separate one so that a caller can write
#: ``weighting: Weighting = "auto"`` in one place and have every accepted value in one type.


def weight_vectors(
    z: Complex, weighting: Weighting = "modulus", sigma: Float | None = None
) -> tuple[Float, Float]:
    """Return the (real, imaginary) residual weights for the chosen weighting scheme.

    - ``unit``: ordinary least squares; dominated by the largest-|Z| points.
    - ``modulus``: weight 1/|Z|; equivalent to minimising *relative* error and the right
      default for spectra spanning several decades of magnitude (e.g. capacitors).
    - ``proportional``: weight each component by its own magnitude; the classic CNLS choice
      when the instrument error is proportional to each measured component.
    - ``sigma``: user-supplied per-point standard deviations.
    - ``auto``: **not accepted here.** It needs the whole spectrum, not just ``z``, to
      estimate a noise scale from -- call :func:`autocircuit.core.noise.resolve_weights`
      instead, which resolves it into ``sigma`` and only then calls this function.
    """
    mag = np.abs(z)
    if weighting == "unit":
        ones = np.ones_like(mag)
        return ones, ones
    if weighting == "modulus":
        floor = np.max(mag) * 1e-12
        w = 1.0 / np.maximum(mag, floor)
        return w, w
    if weighting == "proportional":
        floor = np.max(mag) * 1e-6
        return 1.0 / np.maximum(np.abs(z.real), floor), 1.0 / np.maximum(np.abs(z.imag), floor)
    if weighting == "sigma":
        if sigma is None:
            raise ValueError("weighting='sigma' requires the sigma argument")
        s = np.asarray(sigma, dtype=np.float64)
        if s.shape != mag.shape:
            raise ValueError("sigma must have the same length as the spectrum")
        if np.any(s <= 0):
            raise ValueError("sigma must be strictly positive")
        return 1.0 / s, 1.0 / s
    raise ValueError(f"unknown weighting {weighting!r}")
