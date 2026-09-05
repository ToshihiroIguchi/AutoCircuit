"""The files the report screen offers to download, assembled where the CLI assembles them.

A download is a claim leaving the browser, and it is the one artefact of this program that
outlives the session -- it gets attached to a report, opened in SPICE, or read a year later by
someone who was never at the screen. So none of these files is rendered in JavaScript. Each is
the same text the command line writes:

* ``json`` is :meth:`~autocircuit.core.discover.DiscoveryResult.to_dict` and
  :func:`~autocircuit.core.fit.report_dict`, i.e. ``--json`` from ``discover`` and from ``fit``;
* ``csv`` is :meth:`~autocircuit.core.discover.DiscoveryResult.to_csv`, i.e. ``--csv``;
* ``netlist`` is :func:`~autocircuit.core.spice.to_netlist`, i.e. ``--spice``;
* ``model-csv`` (manual fit only) is :func:`~autocircuit.io.writers.spectrum_csv_text` of the
  fitted model spectrum, i.e. ``fit --model-csv``.

The one thing decided here is what a file is *called*, because the command line takes a path
from the user and a browser has to invent one.

Note what the JSON text can carry that the bridge's own responses cannot: ``json.dumps``
default settings, and therefore bare ``Infinity`` where an exact fit gives an infinite
information criterion. That is fine and deliberate -- the file is a *string* by the time it
reaches the response envelope, so the envelope is still strict JSON (``bridge.handle`` dumps
with ``allow_nan=False``), and what lands on the user's disk is byte-for-byte what
``--json`` writes rather than a browser dialect of it.
"""

from __future__ import annotations

import json
from typing import Any

from autocircuit.core.discover import ExcludedEquivalents
from autocircuit.core.fit import FitResult, report_dict
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.spice import to_netlist
from autocircuit.io.writers import spectrum_csv_text
from autocircuit.web.job import DiscoveryJob

#: Default SPICE subcircuit name, as on the command line (``--subckt``).
DEFAULT_SUBCKT = "AUTOCIRCUIT"

#: Default accuracy target for ladder synthesis of fractional elements (``--spice-error``).
DEFAULT_SPICE_ERROR = 0.01


def _artifact(filename: str, mime: str, content: str) -> dict[str, Any]:
    """One downloadable file: its name, its type, and its whole text."""
    return {"filename": filename, "mime": mime, "content": content}


def discovery(
    job: DiscoveryJob,
    kind: str,
    *,
    top: int | None = None,
    excluded: ExcludedEquivalents | None = None,
    circuit: str | None = None,
    name: str = DEFAULT_SUBCKT,
    error_target: float = DEFAULT_SPICE_ERROR,
) -> dict[str, Any]:
    """A file describing a finished -- or stopped -- search.

    ``circuit`` names which candidate the netlist is of; the recommended one by default, which
    is the same candidate the CLI exports. The JSON and CSV forms describe the whole search,
    coverage sentence included, so they are the ones worth keeping.
    """
    result = job.report()
    if kind == "json":
        return _artifact(
            "autocircuit-discovery.json",
            "application/json",
            json.dumps(result.to_dict(top=top, excluded=excluded), indent=2),
        )
    if kind == "csv":
        return _artifact(
            "autocircuit-candidates.csv", "text/csv", result.to_csv(top=top)
        )
    if kind == "netlist":
        candidate = job.candidate(circuit)
        return _artifact(
            # Named for what it is rather than for the subcircuit inside it. [browser] Deriving
            # the file name from ``name`` gave the search's netlist and a manual fit's the same
            # one, since both default to the same subcircuit name, and a user who downloaded both
            # got two files distinguishable only by the browser's "(1)".
            "autocircuit-discovery.cir",
            "text/plain",
            to_netlist(
                candidate.circuit,
                candidate.result.values,
                f_min=float(job.spectrum.f[0]),
                f_max=float(job.spectrum.f[-1]),
                name=name,
                error_target=error_target,
                header="Topology discovered automatically by AutoCircuit",
            ),
        )
    raise ValueError(f"unknown export kind {kind!r}")


def manual_fit(
    result: FitResult,
    spectrum: Spectrum,
    kind: str,
    *,
    source: str | None = None,
    name: str = DEFAULT_SUBCKT,
    error_target: float = DEFAULT_SPICE_ERROR,
) -> dict[str, Any]:
    """A file describing one fitted topology the user drew themselves.

    ``source`` is what the data is called *to the user*: the browser reads a file from a scratch
    path it invented, so the name in the spectrum's metadata is not one anybody would recognise
    in a netlist header a year later.
    """
    if kind == "json":
        return _artifact(
            "autocircuit-fit.json",
            "application/json",
            json.dumps(report_dict(result, spectrum, source=source), indent=2),
        )
    if kind == "netlist":
        return _artifact(
            "autocircuit-fit.cir",
            "text/plain",
            to_netlist(
                result.circuit,
                result.values,
                f_min=float(spectrum.f[0]),
                f_max=float(spectrum.f[-1]),
                name=name,
                error_target=error_target,
                header=f"Fitted to {source or spectrum.metadata.get('source_path', 'data')}",
            ),
        )
    if kind == "model-csv":
        return _artifact(
            "autocircuit-fit-model.csv",
            "text/csv",
            spectrum_csv_text(Spectrum(spectrum.f, result.z_model)),
        )
    raise ValueError(f"unknown export kind {kind!r}")
