"""The part of the bridge that answers before scipy has loaded.

There is one ``handle``, one JSON envelope and one dispatch; this module holds the envelope and
the four operations a browser needs to *look at data* -- ``version``, ``read``, ``trim`` and
``validate`` -- and finds everything else in :mod:`autocircuit.web.bridge`, which it imports the
first time such a request arrives.

Why the split is here and not somewhere tidier: the web front end installs numpy, comes up, and
installs scipy afterwards, because scipy is 18.3 MB of the 41 MB a first visit fetches and nothing
on the Data screen uses it (``docs/STARTUP_AND_EDITING_PLAN.md`` section 3). During that window the
worker can already read a file, trim it and run Lin-KK -- but only if the code path that does so
can be imported without scipy, which is what this module is. Everything it imports at module scope
is pure numpy; the import of :mod:`autocircuit.web.bridge` is deferred into
:func:`_operation` for that reason and no other.

A second entry point for the browser would be a second implementation of the science
(``docs/WEB_UI_PLAN.md`` section 4). This is not one: the operations are looked up in the same
table the full bridge builds, and the response envelope is written once, here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from autocircuit import io
from autocircuit.core.spectrum import WIRE_VERSION as SPECTRUM_WIRE_VERSION
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.stats import CRITERIA, CRITERION_LABELS, CRITERION_NOTES, DEFAULT_CRITERION
from autocircuit.core.validate import DEFAULT_MU_CRITERION, DEFAULT_RESIDUAL_LIMIT, lin_kk
from autocircuit.core.validate import WIRE_VERSION as VALIDATE_WIRE_VERSION

#: Version of the request/response protocol. The worker checks it against its own build at
#: start-up, so a stale cached bundle fails loudly rather than answering the wrong question.
#:
#: 5 (2026-08-16): a search carries a model-selection ``criterion``, and every results row
#: carries all six scores plus the one the ranking used.
#: 6 (2026-08-16): ``discover_candidate`` hands back the fit behind one results row, so the
#: screen that ran the search can plot what it found instead of only tabulating it.
#: 7 (2026-08-16): every results row carries ``relative_error``, the RMS |dZ|/|Z| that the Fit
#: screen already showed -- the one fit-quality number that does not move with the weighting.
#: 8 (2026-08-16): the load is staged, so ``version`` answers what is knowable without scipy and
#: the new ``runtime`` answers the rest; ``discover_report`` carries the weighting, seed and
#: restart count its rows were refitted under; ``edit`` gains the ``move`` action.
#: 9 (2026-08-23): ``discover_start`` takes ``pool: null`` -- the spectrum chooses, as
#: ``--pool auto`` does on the command line -- so the search can widen its own pool mid-run;
#: ``discover_screen`` says whether it is on the widened pass and ``discover_refit`` whether
#: there is more to do after it, and ``discover_report`` carries ``pool_choice``.
#: 10 (2026-08-24): ``discover_interpret`` -- the recommended circuit read as internal
#: structure, checked against every topology the data cannot tell it apart from.
#: 11 (2026-08-24): ``discover_interpret`` becomes ``discover_objective``, which answers either
#: report -- ``model`` (a circuit to simulate with, its band and its terminal readouts) or
#: ``interpret`` (the same class reading as before). The objective travels with the request for
#: a *report*; no search operation takes one, which is gate O1's structural half.
#: 12 (2026-09-05): ``discover_start`` takes ``growth_width``/``max_elements``, so the browser's
#: Discover panel can ask for the same growth stage the CLI's ``--growth-width`` already
#: exposes (``docs/TOPOLOGY_6PLUS_PLAN.md`` section 5.13). Both already had bridge-side defaults
#: (0 and 7) matching ``GROWTH_DEFAULT``, so an old cached bundle that never sends them keeps its
#: prior behaviour exactly -- this is a new capability, not a changed default.
BRIDGE_VERSION = 12

#: One operation: a request payload in, a JSON-safe result out.
Operation = Callable[[dict[str, Any]], Any]

__all__ = ["BRIDGE_VERSION", "LIGHT_OPERATIONS", "Operation", "handle"]


def handle(request: str) -> str:
    """Answer one request. Never raises: a failure comes back as an error response.

    The one boundary in the whole web path where an exception is caught rather than propagated;
    :mod:`autocircuit.web.bridge`'s module docstring says why (a Pyodide worker that raises has to
    be rebuilt, and reading whatever the user dropped is the operation guaranteed to meet input
    nobody anticipated).
    """
    try:
        payload = json.loads(request)
        operation = payload["op"]
        result = _operation(operation)(payload)
        return json.dumps({"ok": True, "op": operation, "result": result}, allow_nan=False)
    except Exception as exc:  # noqa: BLE001 - the boundary; see the docstring
        return json.dumps(
            {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}},
            allow_nan=False,
        )


def _operation(name: str) -> Operation:
    """The handler for *name*, importing the rest of the bridge if that is where it lives.

    An unknown operation is an error either way; what differs is that asking for a fit before
    scipy is installed raises out of the *import*, with Pyodide's own message naming the package,
    rather than being reported as an unknown operation. The worker never sends one -- it waits for
    the second load stage first -- so this path is what a caller who bypasses it gets to see.
    """
    light = LIGHT_OPERATIONS.get(name)
    if light is not None:
        return light
    from autocircuit.web import bridge

    try:
        return bridge.OPERATIONS[name]
    except KeyError:
        raise ValueError(f"unknown operation {name!r}") from None


def _op_version(payload: dict[str, Any]) -> dict[str, Any]:
    """What this build is, so the caller can refuse to talk to the wrong one.

    Everything answerable without scipy, which is everything the front end needs before the
    second load stage lands: the protocol version the handshake turns on, the two wire versions
    of the data path, the reader list, and the model-selection menu. The fit and DRT wire
    versions come from ``runtime`` once the fitter is in.

    ``criteria`` rides along because it is the same kind of fact as ``formats``: what the
    *running core* offers, not a list the front end keeps its own copy of and has to be
    remembered to update. ``light_operations`` is there for a sharper version of the same reason
    -- the worker uses it to decide which requests may go straight through and which wait for the
    second stage, and a copy of that list in TypeScript would turn one forgotten line into a
    request answered with "scipy is not installed" instead of an answer.
    """
    return {
        "bridge": BRIDGE_VERSION,
        "spectrum": SPECTRUM_WIRE_VERSION,
        "validate": VALIDATE_WIRE_VERSION,
        "formats": sorted(io.REGISTRY),
        "light_operations": sorted(LIGHT_OPERATIONS),
        "criteria": [
            {"name": name, "label": CRITERION_LABELS[name], "note": CRITERION_NOTES[name]}
            for name in CRITERIA
        ],
        "default_criterion": DEFAULT_CRITERION,
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


#: The operations that need numpy and nothing else. Everything else is in
#: :mod:`autocircuit.web.bridge`, and asking for one imports it.
LIGHT_OPERATIONS: dict[str, Operation] = {
    "version": _op_version,
    "read": _op_read,
    "trim": _op_trim,
    "validate": _op_validate,
}
