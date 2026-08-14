# Web UI — Phase 6 Plan

Status: steps 1 and 2 built and measured (2026-08-14); steps 3–6 are a draft awaiting approval.
The one architectural question this plan carried is settled and prototyped — see §2.1 — and that
prototype changed §2.2 and the work order, which is what prototypes are for. Step 2 did the same
to §1: the cold-start figure there came from Node and is wrong for a browser by 3×, see §2.3.
Prerequisite reading: `docs/IMPLEMENTATION_PLAN.md` §9 (the original sketch, now partly
superseded by measurement), `benchmarks/pyodide/README.md` (every performance number below),
and `docs/HANDOFF.md` §3.

## 1. What is already settled by measurement

The original §9 sketch was written before anything had been run under WASM, and it hedged
accordingly: "if in-browser topology search proves too slow, options are (a) reduced default
budgets, (b) Rust/WASM port of the fitness inner loop". Both hedges can be dropped.

| question | answer | evidence |
|----------|--------|----------|
| How much slower is WASM? | 1.3–1.8× on numerical work, 3.9× on the import | `benchmarks/pyodide` |
| Does the fitter need a smaller web budget? | **No** | same fit budget, 1.3× |
| Rust port of the inner loop? | **No** | the cost is already in WASM-compiled numpy/scipy |
| Cold start to first fit | ~4 s under Node — **~13 s in a browser**, §2.3 | same, then step 2 |
| `discover` at `exhaustive_limit=4`, 1 thread | 169 s | same |
| Worker pool speed-up (tier 1) | ~2.3× at 4 workers, saturating; 8 is worse than 6 | `run_workers.mjs` |
| Does the browser get the CLI's answer? | **Yes, to an AICc difference of 0.0** | `run_orchestrated.mjs` |

Two consequences shape the whole design:

1. **A real search takes minutes, not seconds.** 169 s single-threaded; 287 s as first
   prototyped across four workers, which is worse than it sounds and is explained in §2.2, and
   123 s measured once the fix there landed. There is no arrangement of this software that makes
   topology discovery feel instant in a browser, so the UI has to be built around a long-running
   job — streamed progress, partial results, and a cancel button — rather than around a
   request/response.
2. **`fit` on a known topology takes under a second**, and that is the interactive path. The
   two modes deserve different treatment in the UI: manual fitting is live, discovery is a job.

A third point is worth stating because it is counter-intuitive: **the screening budget must not
be reduced for the browser.** `benchmarks/discovery_v2.py screen-rank` measured what happens
when it is, and the answer is that the truth drops off the tier-2 shortlist while its exact
equivalents stay on it — so the report still looks healthy. Trading correctness for browser
latency is exactly the trade this project exists not to make. Reduce `exhaustive_limit`
instead: that costs *coverage*, which `complete_up_to` reports honestly.

## 2. Architecture

```
  main thread (React)        orchestrator worker         screening pool (N workers)
  ┌────────────────────┐     ┌───────────────────┐       ┌───────────────────────┐
  │ import, plots,     │     │ enumerate+filter  │ batch │ screen(text, abandon) │
  │ circuit canvas,    │────>│ screen_plan()     │──────>│                       │
  │ Pareto, report     │<────│ _shortlist()      │<──────│  -> costs             │
  └────────────────────┘     │ tier-2 refit      │ costs └───────────────────────┘
                   progress  └───────────────────┘
```

Every decision sits in the middle box, in Python. The right-hand boxes are told what to screen
and against what threshold; JavaScript only moves batches and costs between them.

- **Static site, no server.** Vite + TypeScript + React, deployable to GitHub Pages. Confirmed
  viable: everything the CLI does runs in Pyodide unchanged.
- **The core is shipped as source, not a wheel.** `benchmarks/pyodide/make_zip.py` already
  demonstrates the mechanism (`unpackArchive` into the Pyodide FS, put it on `sys.path`).
  A wheel is nicer but adds a build step for no measured benefit; revisit if it matters.
  **It now might**: importing the package from that archive is 5.8 s of the browser's 13 s cold
  start (§2.3), against 1.6 s under Node, and it is the largest single item.
- **Worker pool sized 4 by default**, `navigator.hardwareConcurrency` capped at 4, because the
  measured speed-up saturates there and eight workers were *slower* than six. Each worker costs
  ~1.5 s of start-up and its own copy of numpy/scipy, so the pool is created once at load and
  kept.
- **Nothing but strings and numbers crosses the boundary.** `core/discover.py`'s tier-1 worker
  already re-parses a circuit string by design, so the same contract works here unchanged.
  This is the one place where the existing code was built for the browser in advance and it
  should be kept that way. One wrinkle: JSON has no infinity, JS rejects Python's bare
  `Infinity` and silently turns its own into `null` — so `null` is the wire representation in
  both directions, and both an infinite abandon threshold and an infinite cost are routine
  values here, not edge cases.

### 2.1 Where the screen is orchestrated — decided, and prototyped

The parallel screen lives inside `discover()`, which uses `multiprocessing`; in the browser the
fan-out has to happen in JavaScript. The choice was between exposing the stages so JS
orchestrates them — which moves the per-element-count shortlist quota that gate G1 depends on
into untested JavaScript — and keeping orchestration in Python. **Orchestration stays in
Python.**

The obvious way to implement that (Python awaiting a JS callback) needs either `async` all
through the core or `SharedArrayBuffer` + `Atomics.wait`, and the latter needs COOP/COEP
headers that GitHub Pages cannot send. So the transport is inverted instead:
`discover.screen_plan()` is a **generator that yields batches of screening work and receives
their costs back**, holding every between-batch decision — batching, and each candidate's
early-abandon threshold — while knowing nothing about how the work runs. `_screen_all` and
`_screen_parallel` are now thin drivers over it, and so is the browser.

**[measured] The refactor changed nothing.** Discovery output on the Maxwell-Wagner and Randles
references, at one and four workers, is identical before and after — every candidate, every
AICc to nine decimals.

**[measured] The browser reproduces the CLI exactly.** `benchmarks/pyodide/run_orchestrated.mjs`
drives that generator from JavaScript across four Pyodide workers on the capacitor reference at
`exhaustive_limit=4`, and against CPython with four processes: same 741 candidates screened,
same `complete_up_to`, same 37 refitted candidates in the same order, **same AICc to a
difference of 0.0**, same Pareto front, same recommendation (the true `C-R-L-SKINF`). That is
gate W1 demonstrated in advance of the UI, and it is only true because there is one
implementation of the logic rather than two.

### 2.2 What the prototype found that the plan had wrong — and what fixing it took

| stage | browser, 4 workers | after step 1 | CPython, 4 processes |
|-------|-------------------:|-------------:|---------------------:|
| tier 1 screen (741 candidates) | 55 s | 37 s | — |
| tier 2 refit (37 candidates) | 232 s | 86 s | — |
| **total** | **287 s** | **123 s** | **90 s** |

Tier 1 parallelises and was never the problem. **Tier 2 was 80% of the browser's time**, not
the ~25% assumed above, because it ran serially in the orchestrator while CPython fans it
across its pool as well. The single-threaded WASM penalty is 1.3×; the gap was 3.2×, and all of
the difference was that one serial stage. It is now 1.4×.

Tier 2 was serial for a reason: a refit returns a whole `FitResult` — covariance, statistics,
restart spread — which is a Python object, and handing back only the fitted values is precisely
the shortcut that discards the restart spread a non-identifiable model uses to announce itself
(`docs/DISCOVERY_V2_PLAN.md` §5.1). Fanning it out needed a lossless serialisation of
`FitResult` across the worker boundary. **Step 1 built it**; four things about it are worth not
re-deriving.

- **`FitResult.to_dict()` could not be the starting point, and widening it would have been
  wrong.** It is a *report* — the CLI's `--json` — and it carries no `z_model`, no residuals,
  no correlation matrix, no rank, no raw values array, no restart count and no fixed-parameter
  values, so a `Statistics` cannot be rebuilt from it, and without that neither can a
  `Candidate`. Extending it would have put megabytes of arrays into every report file to serve
  a transport nobody reading that file uses. `to_wire()` / `from_wire()` are separate, in
  `core/wire.py`, `core/stats.py` and `core/fit.py`.
- **Nothing is recomputed on arrival.** `z_model` could be regenerated from `circuit.impedance()`
  for about 300 numbers per candidate less traffic, against a stage costing minutes — but it
  would stake the browser's agreement with the CLI on numpy returning bit-identical results in
  a second WASM interpreter, which nobody has measured. The whole payload is ~7 KB per
  candidate at 71 points.
- **Non-finite values travel as the string sentinels `"inf"`, `"-inf"`, `"nan"`**, not as the
  `null`-means-infinity convention the screening costs use (§2 above). A cost is one-sided, so
  `null` is unambiguous there; a standard error can be either infinite or `nan` and those mean
  different things. [measured] The path is routine, not defensive: an exact fit on noise-free
  data has `ssr == 0.0` and therefore AIC, AICc and BIC all `-inf` — which is exactly what the
  equivalence-class report is built to surface. The strict test is `json.dumps(..., allow_nan=False)`,
  because Python's default emits bare `Infinity`/`NaN` tokens that `JSON.parse` rejects.
- **`refit_plan()` is a generator mirroring `screen_plan()`.** The per-element-count shortlist
  quota that gate G1 rests on stays in Python, and `_refit_shortlist` is now a thin driver over
  it exactly as `_screen_parallel` is over `screen_plan`. `_refit_worker` returns the wire
  payload rather than a pickled object even on the desktop, so every parallel CLI run exercises
  the browser's transport.

[measured] The round trip is bit-identical, and so is the whole search: a full-precision dump
of `discover()` on all three reference spectra at four workers — every candidate's values,
fitted response, residuals, standard errors and correlation matrix — is unchanged before and
after, and the browser's report on the capacitor reference matches the pre-fan-out run
candidate for candidate.

### 2.3 What step 2 built, and what a browser measured that Node could not

Step 2 is the Data screen: import, plots, and the Lin-KK panel. It is `web/` — Vite, React and
TypeScript — plus one new Python module, and `web/README.md` is its map.

**`autocircuit.web.bridge` is the whole Python surface.** One function, `handle(request) -> str`,
JSON in and JSON out, dispatching four operations: `version`, `read`, `trim`, `validate`. Three
of its properties are load-bearing rather than stylistic:

- **A bad file is a message, not a dead worker.** Reading whatever the user dropped is the one
  operation guaranteed to meet input nobody anticipated, and a Pyodide worker that raises costs
  ~1.5 s plus its own copy of numpy and scipy to replace. Every exception becomes a response.
- **Responses are serialised with `allow_nan=False`**, for the reason in §2.2: the default dump
  emits tokens `JSON.parse` rejects, so it proves nothing.
- **The bridge holds no state.** A spectrum travels with each request rather than living in the
  worker under a handle, which is what will let step 4's pool hand the same spectrum to every
  worker, and what makes a worker replaceable without the user losing their data.

The file itself never crosses the wire as JSON: JavaScript writes the bytes into the Pyodide
filesystem and sends the path, so the browser reads through `autocircuit.io.read_many` against a
real path and gets the CLI's format sniffing, extension hints and multi-sweep readers unchanged.
`Spectrum.to_wire()/from_wire()` and `KKResult.to_wire()` join `FitResult`'s from step 1 —
which also closes the loose end §2.2 left, since a spectrum now travels rather than being
recomputed on the far side.

On the JavaScript side, `web/src/core/wire.ts` decodes and **deliberately cannot encode**: a
spectrum is held in exactly the form Python produced it and handed back unaltered, so there is
no second implementation of the float format for the browser to disagree with the CLI through.

**[measured] The browser reproduces the CLI's verdict.** Three files — a capacitor sweep as
generic CSV, a cell as ZView, and the same cell with a synthetic drift — read with the format
sniffed correctly, and their Lin-KK verdicts, element counts, residuals and runs *z* match
`python -m autocircuit validate` on the same files digit for digit, including the failing one.
The drifted sweep's residuals show exactly what the runs test caught.

**[measured] Cold start is ~13 s in a browser, not the ~4 s §1 predicted, and it is not the
download.** From navigation to a usable page, on the production build: 14.2 s cold, 12.9 s with
a warm HTTP cache — so ~1.3 s of that is transfer, and the assets are served from the same
origin (§2 below) rather than a CDN. The stages, from the worker's own progress messages:

| stage | browser | Node (`benchmarks/pyodide`) |
|-------|--------:|----------------------------:|
| Pyodide boot | 6.6 s | 1.2 s |
| numpy + scipy | 0.8 s | 1.1 s |
| unpack + `import autocircuit` | 5.8 s | 1.6 s |
| **total to ready** | **~13 s** | **~4 s** |

The two interpreter-bound stages are 3–5× worse in the browser while the package load is
slightly *better*, which is the same shape as §1's other rows — WASM numerics are fine, the
interpreter is what costs. Single-run figures from an automated Chrome on this machine, so treat
the ratio rather than the seconds as the result. What it settles: **gate W3 does not pass today**
(it asks for under 10 s to an interactive first fit, and 13 s is before any fit exists), the
loading state built in step 2 is not optional, and the lever worth pulling is the import — the
package is unpacked from a zip and imported from source, and a wheel or a precompiled bytecode
cache is the obvious thing to measure next. That is a step 6 problem; it is recorded here so it
is not discovered there.

## 3. Screens

Following ZView's workflow, which is what the target users know:

1. **Data** — ~~drag-drop import (all four readers already exist), a table of loaded spectra,
   frequency-window trimming, and the Lin-KK verdict shown *before* anything is fitted. The
   validator's runs-test explanation text is already written; reuse it verbatim.~~ **Built**
   (§2.3). Validation runs automatically on load and after every trim, so the verdict is not
   something the user has to go and ask for, and `KKResult.summary()` is rendered verbatim
   rather than paraphrased.
2. **Fit** — circuit canvas (drag-drop series/parallel blocks reading like a schematic) with a
   live model preview overlaid on the data before fitting. This is the differentiator and it
   should feel like the point of the app: no initial values, press Fit, get parameters with
   honest standard errors. Sub-second, so no progress UI needed.
3. **Discover** — the job screen. Pool selection, `exhaustive_limit`, live progress, streamed
   partial Pareto front, cancel. Progress comes from the batch loop itself rather than from
   `on_progress`: the driver knows how many candidates each batch carried, which is what the
   prototype already prints. The completeness line (`complete_up_to`) is displayed as a
   first-class result, not a footnote — it is the thing the genetic search could never say.
4. **Report** — equivalence classes shown as classes, never as a ranked list with a winner;
   JSON / CSV / netlist download; the DRT structure probe beside the search as the CLI already
   prints it.

Plots: linked Nyquist / Bode(|Z|, θ) / residuals, zoom-synced, log axes. Plotly.js to start
(fast to ship, replaceable) — the only external JS dependency of consequence.

## 4. What must not regress

- **`numpy` and `scipy` stay the only runtime dependencies of the Python core.** The web build
  may add JS dependencies freely; it may not add Python ones.
- **No file-dialog, GUI or OS-specific code in `autocircuit.core`.** File handling is the JS
  side's job; the core takes arrays.
- **The web UI must not fork the science.** Every number it displays comes from the same
  functions the CLI calls. If the browser needs different behaviour, it gets a different
  *argument*, not a different code path.

## 5. Work order

| step | contents | size |
|------|----------|------|
| 0 | ~~Pyodide worker harness, orchestration decision~~ | **done** — §2.1, `benchmarks/pyodide/run_orchestrated.mjs` |
| 1 | ~~Lossless `FitResult` across a worker boundary, so tier 2 fans out too~~ | **done** — §2.2; 287 s → 123 s |
| 2 | ~~Vite/React scaffold, data import, plots, Lin-KK panel~~ | **done** — §2.3 |
| 3 | Circuit canvas + live preview + manual fit | L |
| 4 | Discovery job screen: progress, streaming, cancel, completeness | M |
| 5 | Report: equivalence classes, exports, DRT panel | M |
| 6 | Example datasets, loading states, dark/light, deploy to Pages | S |

## 6. Acceptance gates

- **W1** — the browser and the CLI produce identical fitted parameters for the nine-circuit
  synthetic corpus, to the last reported digit. Same code, so any difference is a bug in the
  bridge.
- **W2** — `discover` at `exhaustive_limit=4` on the capacitor reference completes in the
  browser, streams progress at least once a second, and reports the same `complete_up_to` and
  equivalence classes as the CLI. *(The result half of this already passes headlessly, §2.1;
  what the UI adds is the streaming and the display.)*
- **W3** — cold load to an interactive first fit under 10 s on a mid-range laptop. **[measured]
  Does not pass: ~13 s to a usable page, before any fit.** §2.3 has the breakdown and says which
  stage is worth attacking. Failing this gate does not block steps 3–5; it is a step 6 item that
  now has a number instead of an assumption.
- **W4** — cancel actually stops the work (not just the UI), and a cancelled run reports the
  coverage it reached rather than a wrong number.
- **W5** — the site works offline after first load, and from `file://` as well as Pages.

## 7. Out of scope

- Server-side compute of any kind. The moment there is a backend, the "static site" property
  and its deployment story are gone.
- Multi-user features, project files, cloud storage.
- Rewriting the fitter in Rust/WASM. Measured as unnecessary (§1); revisit only if a profile
  says otherwise.
