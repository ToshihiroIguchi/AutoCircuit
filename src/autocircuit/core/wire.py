"""JSON-safe encoding for the numeric payloads that cross a worker boundary.

The browser front end runs the same search as the CLI, but its workers are Web Workers: the
only thing that can pass between them is JSON. Everything a worker computes therefore has to
survive ``json.dumps`` / ``JSON.parse`` and come back *bit-identical*, because the values on
the far side are the ones the report is built from -- a refit that loses its covariance to the
transport is a refit whose non-identifiability warning never reaches the user.

Two properties make that achievable:

* **Finite ``float64`` round-trips exactly through JSON.** Python's ``repr`` and JavaScript's
  ``JSON.stringify`` both emit the shortest decimal string that reads back as the same double,
  and both parsers are correctly rounded. No hex escape or base64 blob is needed.
* **The non-finite values do not**, and they are not rare here: an unidentifiable parameter
  gets an infinite standard error, a collapsed covariance gives ``nan`` correlations. They are
  encoded as the strings ``"inf"``, ``"-inf"`` and ``"nan"``.

The string sentinels are deliberately *not* the convention used for screening costs, which
travel as ``null`` for infinity (see ``docs/WEB_UI_PLAN.md`` section 2). A cost is one-sided --
it can be ``+inf`` and nothing else -- so ``null`` is unambiguous there and matches what
JavaScript does to its own ``Infinity`` on the way into JSON. A standard error can be either
infinite or ``nan``, and those mean different things, so this side needs to tell them apart.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

Float = NDArray[np.float64]
Complex = NDArray[np.complex128]

#: What a non-finite float looks like on the wire.
POSITIVE_INFINITY = "inf"
NEGATIVE_INFINITY = "-inf"
NOT_A_NUMBER = "nan"

_SENTINELS = {
    POSITIVE_INFINITY: math.inf,
    NEGATIVE_INFINITY: -math.inf,
    NOT_A_NUMBER: math.nan,
}


def encode_float(value: float) -> float | str:
    """One float as JSON, using a string sentinel when it is not finite."""
    x = float(value)
    if math.isfinite(x):
        return x
    if math.isnan(x):
        return NOT_A_NUMBER
    return POSITIVE_INFINITY if x > 0.0 else NEGATIVE_INFINITY


def decode_float(payload: float | str) -> float:
    """Inverse of :func:`encode_float`."""
    if isinstance(payload, str):
        try:
            return _SENTINELS[payload]
        except KeyError:
            raise ValueError(f"unknown float sentinel {payload!r}") from None
    return float(payload)


def encode_array(values: Float) -> dict[str, Any]:
    """A real array of any rank, with its shape, so 1-D and 2-D travel the same way."""
    array = np.asarray(values, dtype=np.float64)
    flat = array.reshape(-1)
    # The all-finite case is the common one and ``tolist`` is an order of magnitude faster
    # than a per-element Python loop; the sentinel path only pays for arrays that need it.
    data: list[float | str]
    if bool(np.all(np.isfinite(flat))):
        data = list(flat.tolist())
    else:
        data = [encode_float(x) for x in flat.tolist()]
    return {"shape": list(array.shape), "data": data}


def decode_array(payload: dict[str, Any]) -> Float:
    """Inverse of :func:`encode_array`."""
    return _decode_flat(payload["data"]).reshape(tuple(int(n) for n in payload["shape"]))


def _decode_flat(data: list[Any]) -> Float:
    """A flat encoded list back to ``float64``, taking the all-finite path when it can."""
    if any(isinstance(x, str) for x in data):
        return np.array([decode_float(x) for x in data], dtype=np.float64)
    return np.array(data, dtype=np.float64)


def encode_complex_array(values: Complex) -> dict[str, Any]:
    """A complex array as separate real and imaginary parts, each encoded as above."""
    array = np.asarray(values, dtype=np.complex128)
    return {
        "shape": list(array.shape),
        "re": encode_array(array.real)["data"],
        "im": encode_array(array.imag)["data"],
    }


def decode_complex_array(payload: dict[str, Any]) -> Complex:
    """Inverse of :func:`encode_complex_array`."""
    shape = tuple(int(n) for n in payload["shape"])
    # Assigned part by part rather than as ``real + 1j * imag``: that expression multiplies
    # ``complex(0, 1)`` by the imaginary part, and ``0 * inf`` is ``nan``, so a non-finite
    # imaginary component would poison the real one on the way back.
    out = np.empty(len(payload["re"]), dtype=np.complex128)
    out.real = _decode_flat(payload["re"])
    out.imag = _decode_flat(payload["im"])
    return out.reshape(shape)


def encode_mapping(values: dict[str, float]) -> dict[str, float | str]:
    """A name-to-float mapping, each value encoded as above."""
    return {name: encode_float(value) for name, value in values.items()}


def decode_mapping(payload: dict[str, float | str]) -> dict[str, float]:
    """Inverse of :func:`encode_mapping`."""
    return {name: decode_float(value) for name, value in payload.items()}
