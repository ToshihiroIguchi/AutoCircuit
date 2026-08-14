"""One JSON-in, JSON-out entry point for the browser's Pyodide worker.

The worker calls :func:`handle` and nothing else. Every request names an operation and carries
its arguments; every response is either ``{"ok": true, "result": ...}`` or
``{"ok": false, "error": ...}``. Three properties are worth stating because they are the reason
this module exists rather than the worker running Python of its own:

* **The failure mode of a bad file is a message, not a dead worker.** Reading whatever the user
  dropped is the one operation here guaranteed to meet input nobody anticipated, and a Pyodide
  worker that raises has to be rebuilt at a cost of about 1.5 s plus its own copy of numpy and
  scipy. Every exception therefore becomes a response.

* **The wire is strictly JSON.** Responses are serialised with ``allow_nan=False``, which is the
  real contract rather than a strictness preference: Python's default ``json.dumps`` emits bare
  ``Infinity`` and ``NaN`` tokens, ``JSON.parse`` rejects them, and a payload that dumps fine
  here can still be undeliverable to the main thread. `core/wire.py` carries the non-finite
  values as string sentinels so this never has to be relaxed.

* **The bridge holds no state.** A spectrum travels with each request that needs it instead of
  living in the worker under a handle. That is what lets the pool of step 4 hand the same
  spectrum to every worker, and it means a worker can be replaced without the user losing the
  data they loaded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autocircuit import io
from autocircuit.core.fit import WIRE_VERSION as FIT_WIRE_VERSION
from autocircuit.core.spectrum import WIRE_VERSION as SPECTRUM_WIRE_VERSION
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import DEFAULT_MU_CRITERION, DEFAULT_RESIDUAL_LIMIT, lin_kk
from autocircuit.core.validate import WIRE_VERSION as VALIDATE_WIRE_VERSION

#: Version of the request/response protocol below. The worker checks it against its own build
#: at start-up, so a stale cached bundle fails loudly rather than answering the wrong question.
BRIDGE_VERSION = 1

__all__ = ["BRIDGE_VERSION", "handle"]


def handle(request: str) -> str:
    """Answer one request. Never raises: a failure comes back as an error response."""
    try:
        payload = json.loads(request)
        operation = payload["op"]
        try:
            run = _OPERATIONS[operation]
        except KeyError:
            raise ValueError(f"unknown operation {operation!r}") from None
        result = run(payload)
        return json.dumps({"ok": True, "op": operation, "result": result}, allow_nan=False)
    except Exception as exc:  # noqa: BLE001 - the boundary; see the module docstring
        return json.dumps(
            {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}},
            allow_nan=False,
        )


def _op_version(payload: dict[str, Any]) -> dict[str, Any]:
    """What this build is, so the caller can refuse to talk to the wrong one."""
    return {
        "bridge": BRIDGE_VERSION,
        "fit": FIT_WIRE_VERSION,
        "spectrum": SPECTRUM_WIRE_VERSION,
        "validate": VALIDATE_WIRE_VERSION,
        "formats": sorted(io.REGISTRY),
    }


def _op_read(payload: dict[str, Any]) -> dict[str, Any]:
    """Read a file the caller has already written into the filesystem.

    The bytes are moved by whoever calls this -- ``FS.writeFile`` in the browser, an ordinary
    file on disk under pytest -- and only the path crosses the wire. That is not squeamishness
    about binary in JSON: it is what makes the browser use :func:`autocircuit.io.read_many`
    against a real path, so format sniffing, the extension hints and the multi-sweep readers all
    behave exactly as they do for the CLI instead of through a second entry point built for the
    web.
    """
    path = Path(payload["path"])
    hints = dict(payload.get("hints") or {})
    spectra = io.read_many(path, format=payload.get("format"), **hints)
    return {"spectra": [s.to_wire() for s in spectra]}


def _op_trim(payload: dict[str, Any]) -> dict[str, Any]:
    """Restrict a spectrum to a frequency window, inclusive of both ends."""
    spectrum = Spectrum.from_wire(payload["spectrum"])
    f_min = payload.get("f_min")
    f_max = payload.get("f_max")
    trimmed = spectrum.select(
        None if f_min is None else float(f_min),
        None if f_max is None else float(f_max),
    )
    return {"spectrum": trimmed.to_wire()}


def _op_validate(payload: dict[str, Any]) -> dict[str, Any]:
    """The Lin-KK verdict on a spectrum, with the residuals the panel plots."""
    spectrum = Spectrum.from_wire(payload["spectrum"])
    result = lin_kk(
        spectrum,
        mu_criterion=float(payload.get("mu_criterion", DEFAULT_MU_CRITERION)),
        residual_limit=float(payload.get("residual_limit", DEFAULT_RESIDUAL_LIMIT)),
    )
    return {"validation": result.to_wire(spectrum)}


_OPERATIONS = {
    "version": _op_version,
    "read": _op_read,
    "trim": _op_trim,
    "validate": _op_validate,
}
