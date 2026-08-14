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
from typing import Any, cast

from autocircuit import io
from autocircuit.core.circuit import (
    Circuit,
    ElementNode,
    Node,
    Series,
    parallel,
    remove_subtree,
    replace_subtree,
    series,
    subtree_at,
    subtree_paths,
)
from autocircuit.core.elements import POOLS, REGISTRY
from autocircuit.core.fit import WIRE_VERSION as FIT_WIRE_VERSION
from autocircuit.core.fit import Weighting, fit, relative_error, search_space
from autocircuit.core.spectrum import WIRE_VERSION as SPECTRUM_WIRE_VERSION
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import DEFAULT_MU_CRITERION, DEFAULT_RESIDUAL_LIMIT, lin_kk
from autocircuit.core.validate import WIRE_VERSION as VALIDATE_WIRE_VERSION
from autocircuit.core.wire import encode_array, encode_complex_array, encode_float

#: Version of the request/response protocol below. The worker checks it against its own build
#: at start-up, so a stale cached bundle fails loudly rather than answering the wrong question.
BRIDGE_VERSION = 2

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


def _op_elements(payload: dict[str, Any]) -> dict[str, Any]:
    """The element catalogue the palette is drawn from, straight out of the registry."""
    return {
        "elements": [
            {
                "code": code,
                "name": element.name,
                "complexity": encode_float(element.complexity),
                "spice_form": element.spice_form,
                "params": [
                    {
                        "name": spec.name,
                        "unit": spec.unit,
                        "log_scale": spec.log_scale,
                        "hard_lo": encode_float(spec.hard_lo),
                        "hard_hi": encode_float(spec.hard_hi),
                    }
                    for spec in element.params
                ],
            }
            for code, element in sorted(REGISTRY.items())
        ],
        "pools": {name: list(codes) for name, codes in POOLS.items()},
    }


def _op_circuit(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a circuit string into the tree the canvas draws and the parameters it lists."""
    return _describe(Circuit.parse(payload["circuit"]), payload)


def _op_edit(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one structural edit and return the circuit that results.

    The canvas sends a position and an action; the tree surgery happens here. That is the same
    rule the rest of this front end follows -- there is one implementation of the circuit
    grammar and one of the tree operations, both in Python, because a second one in JavaScript
    is a way for the browser to build a topology the CLI would read differently.
    """
    circuit = Circuit.parse(payload["circuit"])
    root = circuit.root
    path = _path(payload.get("path", ()), root)
    action = payload["action"]

    new_root: Node
    if action == "remove":
        new_root = remove_subtree(root, path)
    elif action == "replace":
        target = subtree_at(root, path)
        if not isinstance(target, ElementNode):
            raise ValueError("only an element can be replaced by another element")
        new_root = replace_subtree(root, path, ElementNode(_code(payload)))
    elif action in ("series", "parallel"):
        target = subtree_at(root, path)
        added = ElementNode(_code(payload))
        pair = (added, target) if payload.get("position") == "before" else (target, added)
        connected = series(*pair) if action == "series" else parallel(*pair)
        new_root = replace_subtree(root, path, connected)
    else:
        raise ValueError(f"unknown edit action {action!r}")

    return _describe(Circuit(new_root), payload)


def _op_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a circuit at the data's frequencies without fitting anything.

    Missing parameters take the value the fitter would start its own search from
    (:func:`autocircuit.core.fit.search_space`), so the curve a freshly drawn circuit shows is
    the fitter's starting point rather than a guess invented for the display.
    """
    circuit = Circuit.parse(payload["circuit"])
    spectrum = Spectrum.from_wire(payload["spectrum"])
    _, _, values = search_space(
        circuit,
        spectrum,
        fixed=_floats(payload.get("fixed")),
        bounds=_bounds(payload.get("bounds")),
        margin_decades=float(payload.get("margin_decades", 3.0)),
    )
    for name, value in _floats(payload.get("values")).items():
        if name not in circuit.param_names:
            raise ValueError(f"value given for unknown parameter {name!r}")
        values[circuit.param_names.index(name)] = value

    z_model = circuit.impedance(spectrum.omega, values)
    return {
        "circuit": circuit.to_string(),
        "z_model": encode_complex_array(z_model),
        "values": {
            name: encode_float(value)
            for name, value in circuit.values_dict(values).items()
        },
        "relative_error": encode_float(relative_error(z_model, spectrum)),
    }


def _op_fit(payload: dict[str, Any]) -> dict[str, Any]:
    """Fit one known topology. No initial values are asked for and none are needed."""
    circuit = Circuit.parse(payload["circuit"])
    spectrum = Spectrum.from_wire(payload["spectrum"])
    time_limit = payload.get("time_limit")
    result = fit(
        circuit,
        spectrum,
        weighting=cast(Weighting, payload.get("weighting", "modulus")),
        fixed=_floats(payload.get("fixed")),
        bounds=_bounds(payload.get("bounds")),
        restarts=int(payload.get("restarts", 5)),
        seed=int(payload.get("seed", 0)),
        margin_decades=float(payload.get("margin_decades", 3.0)),
        time_limit=None if time_limit is None else float(time_limit),
    )
    # The residual vector is real parts then imaginary parts, which is a detail of the objective
    # function rather than a promise to anyone. The panel that plots them gets them already
    # split, so a front end never hard-codes that layout and cannot silently mis-plot if it
    # changes. They are the weighted residuals the fit actually minimised, not a re-derivation.
    half = result.residuals.size // 2
    return {
        "fit": result.to_wire(),
        "relative_error": encode_float(result.relative_error(spectrum)),
        "residual_real": encode_array(result.residuals[:half]),
        "residual_imag": encode_array(result.residuals[half:]),
        "warnings": list(result.warnings),
        "summary": result.summary(spectrum),
    }


# -- Shared helpers ---------------------------------------------------------------------------


def _describe(circuit: Circuit, payload: dict[str, Any]) -> dict[str, Any]:
    """Everything the Fit screen needs about one circuit: its shape and its parameters.

    A spectrum is optional. With one, each parameter also carries the interval the fitter would
    search and the value it would start from, which is what the parameter table shows before
    the first fit and what a bounds override is edited against.
    """
    spectrum_payload = payload.get("spectrum")
    space: tuple[Any, Any, Any] | None = None
    if spectrum_payload is not None:
        space = search_space(
            circuit,
            Spectrum.from_wire(spectrum_payload),
            fixed=_floats(payload.get("fixed")),
            bounds=_bounds(payload.get("bounds")),
            margin_decades=float(payload.get("margin_decades", 3.0)),
        )

    params: list[dict[str, Any]] = []
    index = 0
    for leaf in circuit.leaves:
        element = REGISTRY[leaf.code]
        for spec in element.params:
            entry: dict[str, Any] = {
                "name": circuit.param_names[index],
                "label": leaf.label,
                "code": leaf.code,
                "param": spec.name,
                "unit": spec.unit,
                "log_scale": spec.log_scale,
                "hard_lo": encode_float(spec.hard_lo),
                "hard_hi": encode_float(spec.hard_hi),
            }
            if space is not None:
                lower, upper, start = space
                entry["lower"] = encode_float(lower[index])
                entry["upper"] = encode_float(upper[index])
                entry["start"] = encode_float(start[index])
            params.append(entry)
            index += 1

    return {
        "circuit": circuit.to_string(),
        "canonical": circuit.canonical_form(),
        "n_elements": len(circuit.leaves),
        "n_params": circuit.n_params,
        "complexity": encode_float(circuit.complexity),
        "tree": _tree(circuit.root, ()),
        "params": params,
    }


def _tree(node: Node, path: tuple[int, ...]) -> dict[str, Any]:
    """One node of the schematic, addressed the way an edit request addresses it."""
    if isinstance(node, ElementNode):
        return {
            "kind": "element",
            "path": list(path),
            "code": node.code,
            "label": node.label,
            "name": REGISTRY[node.code].name,
        }
    return {
        "kind": "series" if isinstance(node, Series) else "parallel",
        "path": list(path),
        "children": [_tree(child, (*path, i)) for i, child in enumerate(node.children)],
    }


def _path(raw: Any, root: Node) -> tuple[int, ...]:
    """Validate a position sent by the caller against the circuit it claims to address.

    Out-of-range indices are rejected here rather than deeper down, where a negative one would
    quietly select a different child and the edit would land somewhere the user did not click.
    """
    path = tuple(int(index) for index in raw)
    if path not in set(subtree_paths(root)):
        raise ValueError(f"path {list(path)} does not address any part of this circuit")
    return path


def _code(payload: dict[str, Any]) -> str:
    """The element code an edit is adding, checked against the registry before it is used."""
    code = str(payload["code"])
    if code not in REGISTRY:
        raise ValueError(
            f"unknown element code {code!r}; known codes: {', '.join(sorted(REGISTRY))}"
        )
    return code


def _floats(raw: Any) -> dict[str, float]:
    """A ``{"R1.R": 1.0}`` mapping from the wire, with every value forced to a float."""
    return {str(name): float(value) for name, value in dict(raw or {}).items()}


def _bounds(raw: Any) -> dict[str, tuple[float, float]]:
    """A ``{"R1.R": [lo, hi]}`` mapping from the wire; the pairs arrive as JSON arrays."""
    out: dict[str, tuple[float, float]] = {}
    for name, pair in dict(raw or {}).items():
        lo, hi = (float(value) for value in pair)
        out[str(name)] = (lo, hi)
    return out


_OPERATIONS = {
    "version": _op_version,
    "read": _op_read,
    "trim": _op_trim,
    "validate": _op_validate,
    "elements": _op_elements,
    "circuit": _op_circuit,
    "edit": _op_edit,
    "preview": _op_preview,
    "fit": _op_fit,
}
