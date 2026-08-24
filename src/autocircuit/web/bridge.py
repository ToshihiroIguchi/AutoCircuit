"""Everything the browser can ask for once scipy is installed.

The worker calls :func:`handle` and nothing else. Every request names an operation and carries
its arguments; every response is either ``{"ok": true, "result": ...}`` or
``{"ok": false, "error": ...}``.

:func:`handle`, the envelope it writes and the four operations that need no scipy live in
:mod:`autocircuit.web.light`, which imports this module the first time a request arrives for
anything below. That is one dispatch completed in two pieces, not two bridges: the split is at
the line the *browser's load* is split at (`docs/STARTUP_AND_EDITING_PLAN.md` section 3), and it
is why ``from autocircuit.web import handle`` costs numpy rather than numpy and scipy.

Three properties are worth stating because they are the reason this module exists rather than
the worker running Python of its own:

* **The failure mode of a bad file is a message, not a dead worker.** Reading whatever the user
  dropped is the one operation here guaranteed to meet input nobody anticipated, and a Pyodide
  worker that raises has to be rebuilt at a cost of about 1.5 s plus its own copy of numpy and
  scipy. Every exception therefore becomes a response.

* **The wire is strictly JSON.** Responses are serialised with ``allow_nan=False``, which is the
  real contract rather than a strictness preference: Python's default ``json.dumps`` emits bare
  ``Infinity`` and ``NaN`` tokens, ``JSON.parse`` rejects them, and a payload that dumps fine
  here can still be undeliverable to the main thread. `core/wire.py` carries the non-finite
  values as string sentinels so this never has to be relaxed.

* **The bridge holds no state, with one deliberate exception.** A spectrum travels with each
  request that needs it instead of living in the worker under a handle, which is what lets the
  screening pool hand the same spectrum to every worker and what makes a worker replaceable
  without the user losing the data they loaded. A *search* cannot work that way -- it is a pair
  of generators that hold the enumeration and the shortlist quota between batches, and it runs
  for minutes -- so it lives in :mod:`autocircuit.web.job`, in the one worker that orchestrates
  it. The workers doing the fitting stay stateless, which is the property that mattered.
"""

from __future__ import annotations

from typing import Any, cast

from autocircuit.core.circuit import (
    Circuit,
    ElementNode,
    Node,
    Series,
    move_subtree,
    parallel,
    remove_subtree,
    replace_subtree,
    series,
    subtree_at,
    subtree_paths,
)
from autocircuit.core.discover import RefitTask, ScreenTask, run_refit, run_screen
from autocircuit.core.drt import DEFAULT_POINTS_PER_DECADE, drt
from autocircuit.core.drt import WIRE_VERSION as DRT_WIRE_VERSION
from autocircuit.core.elements import POOLS, REGISTRY
from autocircuit.core.fit import WIRE_VERSION as FIT_WIRE_VERSION
from autocircuit.core.fit import FitResult, Weighting, fit, relative_error, search_space
from autocircuit.core.objective import DEFAULT_OBJECTIVE, Objective, discovery_report
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.stats import DEFAULT_CRITERION
from autocircuit.core.wire import (
    encode_array,
    encode_complex_array,
    encode_float,
    encode_payload,
)
from autocircuit.web import export, job
from autocircuit.web.light import BRIDGE_VERSION, Operation, handle

__all__ = ["BRIDGE_VERSION", "OPERATIONS", "handle"]


def _op_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    """The versions of the parts that only exist once scipy is in.

    The rest of the build's identity -- the protocol version the handshake turns on, the reader
    list, the criteria menu -- is answered by ``version`` in the first load stage
    (`docs/STARTUP_AND_EDITING_PLAN.md` section 3.2). Asking this at all is how the front end
    learns that the second stage has landed, so it is deliberately an operation and not a status
    message: the answer arrives through the same channel the fits will.
    """
    return {"fit": FIT_WIRE_VERSION, "drt": DRT_WIRE_VERSION}


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

    ``"move"`` relocates a subtree already in the circuit rather than adding a new element: it
    reads ``to`` (the target path, validated with the same ``_path`` helper as ``path``) and
    ``connect``/``position`` for how it joins what is already there, and does the remove-and-
    reinsert as the single :func:`~autocircuit.core.circuit.move_subtree` operation, because
    ``to`` addresses the circuit before anything has moved and a caller cannot predict what its
    own path becomes once ``path`` is torn out.
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
    elif action == "move":
        to = _path(payload.get("to", ()), root)
        connect = payload.get("connect")
        if connect not in ("series", "parallel"):
            raise ValueError(f"unknown move connect {connect!r}; expected 'series' or 'parallel'")
        position = payload.get("position", "after")
        new_root = move_subtree(root, path, to, connect, position)
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
    return _fit_payload(result)


def _fit_payload(result: FitResult) -> dict[str, Any]:
    """One fit, in the shape every screen that plots a model curve reads.

    The residual vector is real parts then imaginary parts, which is a detail of the objective
    function rather than a promise to anyone. The panel that plots them gets them already split,
    so a front end never hard-codes that layout and cannot silently mis-plot if it changes. They
    are the weighted residuals the fit actually minimised, not a re-derivation.

    Shared by the manual fit and by :func:`_op_discover_candidate` so that the two screens draw
    the same picture of the same thing from one definition rather than two.
    """
    half = result.residuals.size // 2
    return {
        "fit": result.to_wire(),
        "relative_error": encode_float(result.relative_error),
        "residual_real": encode_array(result.residuals[:half]),
        "residual_imag": encode_array(result.residuals[half:]),
        "warnings": list(result.warnings),
        "summary": result.summary(),
    }


# -- Topology discovery -----------------------------------------------------------------------
#
# Two halves that run in different workers. ``screen_task`` and ``refit_task`` are what a pool
# worker answers: a topology and a spectrum in, a number or a fit out, no state and no opinion
# about what to run next. The ``discover_*`` operations are what the orchestrator answers, and
# they are a thin skin over :mod:`autocircuit.web.job` -- every decision they appear to make
# was made in ``core/discover.py`` (see that module's docstring).


def _op_screen_task(payload: dict[str, Any]) -> dict[str, Any]:
    """One tier-1 screen. ``abandon_above`` of null means infinity: nothing to beat yet."""
    spectrum = Spectrum.from_wire(payload["spectrum"])
    cost = run_screen(
        ScreenTask(str(payload["circuit"]), job.from_wire_cost(payload.get("abandon_above"))),
        spectrum,
        weighting=job.cast_weighting(payload.get("weighting", "modulus")),
        seed=int(payload.get("seed", 0)),
    )
    return {"cost": job.to_wire_cost(cost)}


def _op_refit_task(payload: dict[str, Any]) -> dict[str, Any]:
    """One tier-2 refit, whole. A topology that cannot be fitted answers with null.

    The fit crosses back as :meth:`FitResult.to_wire` -- covariance, restart spread and all --
    because handing back only the fitted values is exactly the shortcut that discards how a
    non-identifiable model announces itself (docs/DISCOVERY_V2_PLAN.md section 5.1).
    """
    spectrum = Spectrum.from_wire(payload["spectrum"])
    result = run_refit(
        RefitTask(
            str(payload["circuit"]),
            int(payload.get("restarts", 5)),
            int(payload.get("seed", 0)),
        ),
        spectrum,
        weighting=job.cast_weighting(payload.get("weighting", "modulus")),
    )
    return {"fit": None if result is None else result.to_wire()}


def _op_discover_start(payload: dict[str, Any]) -> dict[str, Any]:
    """Enumerate the candidate space and open both plans. Nothing is fitted yet.

    The answer says how much work was just committed to, per element count, which is the
    number worth seeing before a search that takes minutes rather than after.
    """
    # ``None`` -- an absent key, an explicit null, or "auto" -- means the spectrum chooses, and
    # it is passed on as None rather than resolved here. Naming `DEFAULT_POOL` at this line was
    # the browser's standing violation of `CLAUDE.md`'s rule that the automatic path takes the
    # spectrum and nothing else: the search would then report a pool the user never asserted
    # and never widen it, whatever the residuals said.
    requested = payload.get("pool")
    if isinstance(requested, str):
        requested = None if requested == "auto" else [requested]
    started = job.DiscoveryJob(
        Spectrum.from_wire(payload["spectrum"]),
        pool=None if not requested else tuple(requested),
        skeleton=payload.get("skeleton"),
        exhaustive_limit=(
            None if payload.get("exhaustive_limit") is None
            else int(payload["exhaustive_limit"])
        ),
        exhaustive_min=int(payload.get("exhaustive_min", 1)),
        max_candidates=int(payload.get("max_candidates", 20_000)),
        feasibility_filter=bool(payload.get("feasibility_filter", True)),
        weighting=job.cast_weighting(payload.get("weighting", "modulus")),
        seed=int(payload.get("seed", 0)),
        criterion=job.cast_criterion(payload.get("criterion", DEFAULT_CRITERION)),
        final_restarts=int(payload.get("restarts", 5)),
        n_refine=(
            None if payload.get("n_refine") is None else int(payload["n_refine"])
        ),
        screen_chunk=int(payload.get("screen_chunk", job.SCREEN_CHUNK)),
        refit_chunk=int(payload.get("refit_chunk", job.REFIT_CHUNK)),
    )
    return job.plan_summary(job.install(started))


def _op_discover_screen(payload: dict[str, Any]) -> dict[str, Any]:
    """Take the last batch's costs, hand out the next batch."""
    running = job.current(str(payload["job"]))
    costs = payload.get("costs")
    if costs is not None:
        running.submit_screen([job.from_wire_cost(cost) for cost in costs])
    tasks = running.next_screen()
    return {
        "tasks": (
            None if tasks is None
            else [[text, job.to_wire_cost(abandon)] for text, abandon in tasks]
        ),
        "screened": running.screened,
        "total": len(running.enumeration.texts),
        "best": running.best_screened,
        # A widened search screens a second, larger space, so ``screened`` and ``total`` both
        # restart. Saying which pass they belong to is what keeps a progress bar that goes
        # backwards from looking like a bug -- and it is also the first moment the user can be
        # told that the data asked for more elements than the default pool has.
        "widened": running.widened,
        "pool": list(running.pool),
        # The per-size breakdown of the space being screened *now*. It is on every step rather
        # than only the first because a widening replaces the enumeration mid-run, and a
        # breakdown of the space the search has moved on from is worse than none.
        "levels": job.levels_of(running),
    }


def _op_discover_refit(payload: dict[str, Any]) -> dict[str, Any]:
    """Take the last batch's fits, hand out the next batch, and report the front so far.

    The partial Pareto front comes back with every batch because a search that runs for
    minutes should show what it already knows. It is built from
    :attr:`RefitBatch.done` -- the plan's own candidates -- so there is no second place where
    a fit is decoded or a hopeless topology is dropped.
    """
    running = job.current(str(payload["job"]))
    results = payload.get("results")
    if results is not None:
        running.submit_refit(list(results))
    tasks = running.next_refit()
    return {
        "tasks": (
            None if tasks is None
            else [[text, restarts, seed] for text, restarts, seed in tasks]
        ),
        "refitted": running.refitted,
        "shortlisted": running.shortlisted,
        "front": [job.candidate_row(c, running.criterion) for c in running.front],
        # Tier 2 running out is no longer the end of the search: under ``pool: null`` the
        # completed fit is the evidence the pool question needs, so a widening starts here and
        # the driver has to go back to screening. It asks this rather than being told to loop a
        # fixed number of times, because how many passes there are is the core's decision.
        "more": not running.finished,
    }


def _op_discover_report(payload: dict[str, Any]) -> dict[str, Any]:
    """The report, finished or stopped, with the sentence saying which it is."""
    return job.report_payload(job.current(str(payload["job"])))


def _op_discover_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """The fit behind one row of this search: the curve it drew, and the residuals it minimised.

    Nothing is fitted here. Every row a search reports came from a tier-2 refit, and the job has
    held that :class:`~autocircuit.core.fit.FitResult` ever since -- it is the same object the
    exports are rendered from. This op only hands it over, so the screen that ran the search can
    plot what it found rather than only tabulating it (docs/SCREEN_STATE_PLAN.md section 4).

    Answered lazily, one row at a time, rather than folded into ``refit_task``: the whole
    shortlist crosses the wire during a search and almost none of it is ever looked at.

    Every number in the answer -- the RMS relative error included -- was computed against the
    job's own spectrum, the data the search actually ran against, which is not necessarily the
    one the user has selected by the time they read the answer.
    """
    running = job.current(str(payload["job"]))
    candidate = running.candidate(payload.get("circuit"))
    return _fit_payload(candidate.result)


def _op_discover_objective(payload: dict[str, Any]) -> dict[str, Any]:
    """One finished search, rendered for what the reader came for.

    The two objectives (`docs/OBJECTIVE_PLAN.md`): ``model`` is a circuit to simulate with, and
    its claim is checkable from the data alone -- the band, the agreement in it, the terminal
    readouts. ``interpret`` is what the spectrum says is inside the part, and its claim is
    conditional on the reported form, so it leads with the equivalence class.

    **The objective arrives with the request for a report and never with the request for a
    search.** ``discover_start`` does not take one and `core/discover.py` cannot receive one;
    that is gate O1's structural half, and it is why this operation exists separately rather
    than as a flag on the search.

    Nothing is fitted. Every member is a tier-2 result the job still holds, so this is arithmetic
    over fits that already exist, which is why it is answered on demand rather than folded into
    the report.

    ``summary`` travels rendered, for the same reason ``completeness`` does: the sentence saying
    what may and may not be claimed is the part a second implementation would get subtly wrong.

    The payload goes through :func:`encode_payload` rather than out as it stands: a report can
    carry an infinite class spread, and this wire is strict JSON, so one such value would make
    the whole response undeliverable rather than merely odd.
    """
    running = job.current(str(payload["job"]))
    chosen = running.candidate(payload.get("circuit"))
    result = running.report()
    objective = cast(Objective, payload.get("objective") or DEFAULT_OBJECTIVE)
    report = discovery_report(result, running.spectrum, objective, candidate=chosen)
    return {"objective": encode_payload(report.to_dict()), "summary": report.summary()}


def _op_discover_cancel(payload: dict[str, Any]) -> dict[str, Any]:
    """Stop handing out work. The job stays available so its report can still be read.

    Stopping the fits already dispatched is the caller's half of this: a Web Worker inside a
    differential evolution stops when it is terminated and not before.
    """
    running = job.current(str(payload["job"]))
    running.cancel()
    return {"job": running.id, "screened": running.screened, "refitted": running.refitted}


# -- What a skeleton excluded ------------------------------------------------------------------
#
# The same two halves again: the pool workers answer ``screen_task``, unchanged and unaware that
# this is a different question, while the orchestrator holds
# :class:`autocircuit.web.job.ExcludedJob`. The one thing this pass does that the search does not
# is send the *target* out with the tasks -- an excluded topology is screened against the
# reported candidate's fitted response, not against the measured data, and choosing that target
# is a decision that stays in ``core/discover.py``.


def _op_excluded_start(payload: dict[str, Any]) -> dict[str, Any]:
    """Enumerate what the skeleton excluded, without screening any of it yet.

    The counts come back first on purpose: this pass costs about as much as the search that
    preceded it, so "1,132 topologies to check" is worth seeing before it starts rather than
    after.
    """
    search = job.current(str(payload["job"]))
    started = job.ExcludedJob(
        search,
        search.candidate(payload.get("circuit")),
        chunk=int(payload.get("chunk", job.EXCLUDED_CHUNK)),
    )
    running = job.install_excluded(started)
    return {**job.excluded_payload(running), "target": running.target.to_wire()}


def _op_excluded_screen(payload: dict[str, Any]) -> dict[str, Any]:
    """Take the last batch's costs, hand out the next batch."""
    running = job.current_excluded(str(payload["job"]))
    costs = payload.get("costs")
    if costs is not None:
        running.submit([job.from_wire_cost(cost) for cost in costs])
    tasks = running.next_batch()
    return {
        "tasks": (
            None if tasks is None
            else [[text, job.to_wire_cost(abandon)] for text, abandon in tasks]
        ),
        "screened": running.screened,
        "total": running.total,
        "equivalents": list(running.report().equivalents),
    }


def _op_excluded_report(payload: dict[str, Any]) -> dict[str, Any]:
    """What the pass may claim, finished or stopped -- the difference is inside the sentence."""
    return job.excluded_payload(job.current_excluded(str(payload["job"])))


def _op_excluded_cancel(payload: dict[str, Any]) -> dict[str, Any]:
    """Stop handing out work; the partial report stays readable and says it is partial."""
    running = job.current_excluded(str(payload["job"]))
    running.cancel()
    return {"job": running.id, "screened": running.screened, "total": running.total}


# -- The structure probe, and the files that leave the browser ---------------------------------


def _op_drt(payload: dict[str, Any]) -> dict[str, Any]:
    """The distribution of relaxation times, beside the search and never inside it.

    Advisory, exactly as on the command line: a DRT peak count is read off a regularised
    inversion of noisy data, and letting it raise the enumeration floor would let it delete the
    right answer from a search still calling itself exhaustive
    (docs/DISCOVERY_V2_PLAN.md section 3.4).
    """
    spectrum = Spectrum.from_wire(payload["spectrum"])
    lam = payload.get("regularisation")
    result = drt(
        spectrum,
        points_per_decade=int(payload.get("points_per_decade", DEFAULT_POINTS_PER_DECADE)),
        series_inductance=_optional_bool(payload.get("series_inductance")),
        series_capacitance=_optional_bool(payload.get("series_capacitance")),
        lam=None if lam is None else float(lam),
    )
    return {"drt": result.to_wire()}


def _op_export(payload: dict[str, Any]) -> dict[str, Any]:
    """One downloadable file, rendered by the same code the command line writes it with.

    Two sources, because there are two ways to arrive at a fitted circuit here: a search this
    worker still holds, named by ``job``, or a manual fit the user drew on the Fit screen, whose
    whole :class:`~autocircuit.core.fit.FitResult` travels back in ``fit``.
    """
    kind = str(payload["kind"])
    name = str(payload.get("name", export.DEFAULT_SUBCKT))
    error_target = float(payload.get("error_target", export.DEFAULT_SPICE_ERROR))
    top = payload.get("top")
    if payload.get("fit") is not None:
        return export.manual_fit(
            FitResult.from_wire(payload["fit"]),
            Spectrum.from_wire(payload["spectrum"]),
            kind,
            source=payload.get("source"),
            name=name,
            error_target=error_target,
        )
    running = job.current(str(payload["job"]))
    excluded = payload.get("excluded")
    return export.discovery(
        running,
        kind,
        top=None if top is None else int(top),
        # The pass is included in the file only if one was actually run: an absent key and an
        # empty result mean different things here, as they do everywhere a skeleton is involved.
        excluded=(
            None if excluded is None else job.current_excluded(str(excluded)).report()
        ),
        circuit=payload.get("circuit"),
        name=name,
        error_target=error_target,
    )


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


def _optional_bool(raw: Any) -> bool | None:
    """A tri-state flag from the wire. None is not a default here: it means "decide from the
    data", which is what the DRT's series terms do when nobody asserts one."""
    return None if raw is None else bool(raw)


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


#: Everything that needs scipy. `autocircuit.web.light` holds the four that do not and looks the
#: rest up here, so a caller still sees one flat set of operations.
OPERATIONS: dict[str, Operation] = {
    "runtime": _op_runtime,
    "elements": _op_elements,
    "circuit": _op_circuit,
    "edit": _op_edit,
    "preview": _op_preview,
    "fit": _op_fit,
    "screen_task": _op_screen_task,
    "refit_task": _op_refit_task,
    "discover_start": _op_discover_start,
    "discover_screen": _op_discover_screen,
    "discover_refit": _op_discover_refit,
    "discover_report": _op_discover_report,
    "discover_candidate": _op_discover_candidate,
    "discover_objective": _op_discover_objective,
    "discover_cancel": _op_discover_cancel,
    "excluded_start": _op_excluded_start,
    "excluded_screen": _op_excluded_screen,
    "excluded_report": _op_excluded_report,
    "excluded_cancel": _op_excluded_cancel,
    "drt": _op_drt,
    "export": _op_export,
}
