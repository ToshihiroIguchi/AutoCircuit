# Web UI — Phase 6 Plan

Status: steps 1–5 built and measured (2026-08-14); step 6 is a draft awaiting approval.
The one architectural question this plan carried is settled and prototyped — see §2.1 — and
that prototype changed §2.2 and the work order, which is what prototypes are for. Step 2 did
the same to §1: the cold-start figure there came from Node and is wrong for a browser by 3×, see
§2.3. Step 3 closed gate W1 and, in doing so, replaced an assumption §2.2 had explicitly left
unmeasured — see §2.4. Step 4 closed W2 and W4 and found that **one clause of W2 was not
achievable and never had been** — see §2.5, and §6, where the gate now carries what was measured
instead of a softer promise. Step 5 added a gate rather than closing one: W6, that a downloaded
file is the file the command line writes, see §2.6.
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

### 2.4 What step 3 built, and the assumption it retired

Step 3 is the Fit screen: an element palette, a schematic canvas, a live preview of the model
against the data, and a manual fit with honest standard errors. Five operations join the
bridge's four — `elements`, `circuit`, `edit`, `preview`, `fit` — and `BRIDGE_VERSION` is 2.

**The canvas edits a tree in Python, not a string in JavaScript.** Every box and slot carries the
path that `subtree_at` takes, and an edit is "insert an R after this path"; `edit` performs the
surgery with `series`/`parallel`/`replace_subtree`/`remove_subtree` and answers with the circuit
that resulted. So there is one implementation of the grammar and one of the tree operations,
both in Python. The alternative — a JavaScript circuit builder emitting DSL text — is a second
implementation of the thing the CLI parses, and it would disagree eventually.

**The preview starts where the fitter starts.** `fit.search_space()` was lifted out of the
private `_Problem` so that the value a freshly drawn circuit is drawn with is literally the
value differential evolution begins from, rather than a display default that resembles it.
`_Problem` calls the same function, so the two cannot drift.

Three consequences of the "no initial values" claim showed up as UI problems rather than code
problems, and are worth stating because they will recur on the Discover screen:

- **A table of editable numbers next to a Fit button implies the numbers seed the fit.** They do
  not: Fit runs the same global search the CLI runs, from the same data-derived bounds. The
  table says so in a line under it. The one control that *does* bind a number is Fix, which
  removes the parameter from the fit rather than nudging it.
- **The neutral starting point looks broken, and it is not.** The preview curve of a new circuit
  sits ~160% away from the data, because the geometric centre of an interval spanning fifteen
  decades is not near anything. That is what "no starting guess" costs on screen, and hiding it
  would mean inventing a guess.
- **Editing the circuit retires the fit.** The parameters stay (they are the next preview's
  starting point) but the statistics do not, because they describe a model that is no longer on
  screen.

**[measured] Gate W1 passes at the precision the CLI reports, and only at that precision.**
`benchmarks/pyodide/fit_parity.py` writes the command line's fit of all nine circuits in
`tests/test_fit.py`'s corpus — carrying the *spectra*, not a recipe for regenerating them — and
`run_fit_parity.mjs` refits them through `bridge.handle` inside Pyodide:

| comparison | result |
|------------|--------|
| 34 fitted parameters, six significant digits | **all agree** |
| 34 fitted parameters, bit for bit | **none agree**; worst relative difference 2.4e-7 |
| 1042 impedance components at CPython's fitted values | 96.1% bit-identical, worst 5.0e-14 |

The second row is the finding. A fitted parameter travels through differential evolution and a
trust-region solve, and a last-bit difference in either compounds into the optimizer's path, so
cross-interpreter bit-identity is not available for a fit and a gate that demanded it would fail
for the wrong reason. The third row says where the difference enters: evaluating a circuit is
bit-identical in every case except the one built on `tanh` and complex `sqrt` (skin effect on a
wire), where the WASM libm and the desktop's differ at 5e-14.

That retires the assumption `FitResult.to_wire` was written around. Its docstring says `z_model`
is carried rather than recomputed because recomputing "would stake the browser's agreement with
the CLI on numpy returning bit-identical results in a second WASM interpreter, which is an
assumption nobody has measured". It is measured now, and it would have been **wrong** — not for
most circuits, but for exactly the ones with transcendental elements, which is the failure mode
that would have looked like a bug in an element rather than in a transport.

### 2.5 What step 4 built, and where the gate's own wording was wrong

Step 4 is the Discover screen: a job, with streamed progress, a partial Pareto front, and a
cancel button that stops the fitting rather than only the display. `BRIDGE_VERSION` is 3 —
`screen_task`, `refit_task`, `discover_start`, `discover_screen`, `discover_refit`,
`discover_report` and `discover_cancel` join the nine before them.

**The completeness rule was extracted rather than reimplemented.** `benchmarks/pyodide/`'s
prototype enumerated for itself — no level boundaries, no candidate ceiling — which is fine for
a benchmark and would have been a second implementation of the one claim this project exists to
make. `discover.enumerate_candidates()` now returns an `Enumeration`, which carries the level
boundaries and derives `complete_up_to` from them in `Enumeration.coverage()`; `_exhaustive` is
a driver over it, and so is the browser. Three generators now hold every decision the search
makes — enumeration, screening, refitting — and there are four drivers of them (in-process,
process pool, benchmark, browser) that hold none.

**The bridge holds state for exactly one thing, and it is not the data.** A search is a pair of
generators that must survive between batches, so `autocircuit.web.job.DiscoveryJob` lives in the
orchestrator worker. The workers that do the fitting stay stateless — a spectrum travels with
every `screen_task` and `refit_task` — which is the property that mattered: a worker can be
terminated and replaced without the user losing anything.

**A stopped run has to claim less, and the claim it has to drop is not the obvious one.**
Cancelling during the screen lowers `complete_up_to` through the same arithmetic a `time_limit`
uses, and that was expected. Cancelling during the *refit* does not touch `complete_up_to` at
all — the screen really did cover every topology — while leaving a Pareto front built from part
of the shortlist, which looks exactly like a finished one. `DiscoveryResult.refit_progress` is
what makes the coverage sentence say "only 8 of the 37 shortlisted topologies have fitted
parameters: the ranking below is partial". Without it, the honest half of the report would have
been carrying the dishonest half.

**[measured] Gate W2's results pass exactly; its streaming clause was written before anyone had
measured a refit.** In Chrome, on the capacitor reference at `exhaustive_limit=4`, four workers:
741 topologies screened, `complete_up_to` 4, and a Pareto front identical to
`python -m autocircuit discover --workers 4` row for row — `C1-L1`, `C1-SKINF1`, `C1-L1-SKINF1`,
`R1-C1-L1-SKINF1` at −306.011, −654.405, −1208.84, −1316.28 — same recommendation, and the
verbatim report carries the same equivalence class (`C1-L1 == L1-CPE1`) and the same "lowest
AICc is not supported by the data" caveat. Repeated at `exhaustive_limit=3`: identical again.
The clock: ~84 s in the browser against 77.6 s for the CLI at four processes.

| what updates | measured interval |
|--------------|------------------:|
| tier-1 screen, one batch of 64 fanned across the pool | < 1.5 s throughout |
| tier-2 refit, per finished fit | up to **8.6 s** |
| the panel's elapsed clock | 0.25 s |

The gate asks for progress "at least once a second". Tier 1 meets it. **Tier 2 cannot**: the
smallest thing that can finish there is one full-budget fit, and one of those took 8.6 s. The
options were to invent motion or to say what is true, so the panel runs a clock of its own —
the elapsed time ticks, the counts and the front move only when the search actually knows more.
A progress bar that advances on a timer is a lie about a search that might have hung.

**[measured] Gate W4 passes, and cancelling costs at most one batch of finished refits.**
Pyodide is single-threaded, so a worker inside a differential evolution never reads a message
asking it to stop; the pool is terminated and rebuilt instead (~1.5 s per worker, plus its own
numpy and scipy). Measured in the browser: cancel during the refit, and the report says the
screen's coverage stands while 0 of 37 topologies were refitted; a search started immediately
afterwards runs to completion on a fresh pool. The fits that were in flight are discarded rather
than submitted, because `refit_plan` takes one outcome per task and the only way to submit a
partial batch is to report the unfinished ones as `null` — which means "this topology could not
be fitted", a claim about the topology rather than about the interruption.

Two smaller things the browser found that nothing else would have:

- **The version guard fired on the first load, exactly as designed.** `protocol.ts` still said
  bridge 2 while Python answered 3, and the page refused to run rather than mis-dispatching.
- **The elapsed clock ran backwards.** A progress report is stamped when the run emits it and
  rendered some time later, so a fresh report can be behind the clock extrapolated from the
  previous one. The displayed value is monotone now.

One deviation from §2 worth recording: the pool is **not** created at page load. Four more
Pyodide workers would be added to a cold start that is already ~13 s, for every visitor who
never presses Discover; it is built on the first search and kept afterwards.

### 2.6 What step 5 built, and the third generator it needed

Step 5 is the Report screen: equivalence classes shown as classes, what a skeleton excluded,
the downloads, and the DRT probe. `BRIDGE_VERSION` is 4 — `excluded_start`, `excluded_screen`,
`excluded_report`, `excluded_cancel`, `drt` and `export` join the sixteen before them.

**The one feature here that is not a rendering is the excluded-equivalents pass**, and it is the
feature `CLAUDE.md` calls non-optional: a skeleton chooses between forms the data cannot
distinguish, and the report has to name what the choice removed. It could not simply be called:
`excluded_equivalents()` is 1,132 screens on the capacitor reference (§3.3 of
`docs/PARTIAL_TOPOLOGY_PLAN.md`), which is ~137 s on one desktop core and would be minutes of a
frozen single-threaded interpreter in the browser, with no progress and no way out. So it was
split the way the search was, into `excluded_plan()` — **the third generator of that shape**,
after `screen_plan` and `refit_plan` — and drivers over it: `excluded_equivalents()` in-process
or across a process pool, and `core/excluded.ts` across the same four Pyodide workers the search
uses. There are now three generators holding every decision the discovery machinery makes, and
five drivers of them holding none.

Three things about that pass are worth not re-deriving.

- **The target is the reported candidate's own fitted response, not the data.** It is carried on
  the wire (`excluded_start` answers with a whole spectrum) rather than named, because choosing
  it is a decision: against a noisy sample an exact reparameterisation looks no better than a
  topology that merely fits well, and the pass would answer a question nobody asked.
- **A stopped pass claims less, and the claim it drops is the useful one.** "None of them
  reproduces your model" is a statement about every excluded topology; a pass stopped after 8 of
  55 knows nothing about the other 47. `ExcludedEquivalents.screened` is what makes the sentence
  say *"Only 8 of them have been checked … 47 were never checked"* instead. This is the same
  failure `refit_progress` was added for in step 4, in its third location, and it was found the
  same way: by asking what the finished sentence would mean if the run had been cut short.
- **The pool workers did not change.** An excluded screen is a `screen_task` like any other; what
  makes it a different question is the target it is handed. That is what "JavaScript makes no
  decisions" buys — a second kind of work, fanned out and cancellable, with no second worker
  protocol.

**Nothing that leaves the browser is rendered in the browser.** A download outlives the session:
it gets attached to a report, opened in SPICE, or read a year later by someone who was never at
the screen. So `export` returns the *text* the command line writes — `DiscoveryResult.to_dict()`,
`DiscoveryResult.to_csv()`, `fit.report_dict()`, `to_netlist()` — and the CLI grew `--csv` so
that the table the browser offers has a command-line counterpart rather than being the browser's
own invention. One consequence is worth stating because it looks like a contradiction: those
files may contain bare `Infinity` (an exact fit has `-inf` information criteria), which the
bridge's own responses may never contain. They can, because by then the file is a *string* inside
a response that is still strict JSON.

**The DRT needed a wire form before it could be shown at all.** `DRTResult.to_dict()` — the CLI's
`--json` — writes a bare `inf` for the series capacitance whenever the data does not block, which
is the ordinary case; `json.dumps(..., allow_nan=False)` refuses it and `JSON.parse` would refuse
it too. So `to_wire()` joins the ones on `Spectrum`, `FitResult` and `KKResult`, and `hints()`
travels with the numbers as the Lin-KK verdict does.

**[measured] The whole screen, in Chrome.** On the capacitor reference with the skeleton `C1-R1`
at `exhaustive_limit=3` over the component pool: the search covers 3 elements in ~40 s, and the
excluded pass then checks **132 of the 146 three-element topologies in ~7 s across four workers**
and finds one exact equivalent of the reported `C1-R1-SKINF1` — `R1-CPE1-SKINF1`, which is the
same substitution `docs/PARTIAL_TOPOLOGY_PLAN.md` §3.3 measured at four elements, because a CPE
with n = −1 *is* a capacitor. Cancelled mid-pass it reports 64 of 132 checked, keeps the
equivalent it had found, and says *"Another 68 were never checked, so this list is not the whole
of what was lost."* The exports download as files; the DRT declines to describe this spectrum, as
it does on the command line.

Three things a real browser found that nothing else would have, all of them about *state*:

- **A screen is unmounted when the user changes tab, and everything in it is lost.** True since
  step 2 and harmless while the screens were three things you did in order; a fourth screen you
  walk back and forth to makes it a trap. It cost a wrong measurement here — a form still showing
  "3 elements, with a skeleton" ran an unconstrained four-element search, because the *displayed*
  settings were defaults that had been silently restored. `App` now owns the search settings, the
  excluded pass and the DRT result, so nothing that costs time or states an intent dies on a tab
  switch.
- **Both netlists downloaded under the same file name.** The name came from the SPICE subcircuit
  name, which defaults to `AUTOCIRCUIT` for a discovered model and a manual fit alike, so
  downloading both gave two files distinguishable only by the browser's "(1)". They are named for
  what they are now.
- **A column of "Class n — 1 topology" headings buries the answer.** The panel's headline is how
  many classes hold more than one member, so it says that in a line before the list — including
  when the number is none, which is a result rather than an absence of one.

## 3. Screens

Following ZView's workflow, which is what the target users know:

1. **Data** — ~~drag-drop import (all four readers already exist), a table of loaded spectra,
   frequency-window trimming, and the Lin-KK verdict shown *before* anything is fitted. The
   validator's runs-test explanation text is already written; reuse it verbatim.~~ **Built**
   (§2.3). Validation runs automatically on load and after every trim, so the verdict is not
   something the user has to go and ask for, and `KKResult.summary()` is rendered verbatim
   rather than paraphrased.
2. **Fit** — ~~circuit canvas (drag-drop series/parallel blocks reading like a schematic) with a
   live model preview overlaid on the data before fitting. This is the differentiator and it
   should feel like the point of the app: no initial values, press Fit, get parameters with
   honest standard errors. Sub-second, so no progress UI needed.~~ **Built** (§2.4). One thing
   the sketch had wrong: a fit is *not* sub-second in the browser. The three-element demo took
   5.2 s at five restarts and the nine-circuit corpus ranged to 36 s at three, so the button
   shows its state and the canvas locks while it runs. It is still the interactive path — no
   streaming, no cancel — but "no progress UI needed" was optimism from a machine where the same
   fit takes 0.2 s.
3. **Discover** — ~~the job screen. Pool selection, `exhaustive_limit`, live progress, streamed
   partial Pareto front, cancel. Progress comes from the batch loop itself rather than from
   `on_progress`: the driver knows how many candidates each batch carried, which is what the
   prototype already prints.~~ **Built** (§2.5). Progress comes from finer than the batch loop —
   the driver fans a batch task by task, so it counts finished tasks without shrinking the
   batch, which is the one thing a driver could do that the search would notice. The
   completeness line (`complete_up_to`) is displayed as a first-class result, not a footnote —
   it is the thing the genetic search could never say — and it is rendered verbatim, together
   with the sentence a cancelled run adds to it. The browser searches exhaustively only: there
   is no generator behind the genetic stage, so above the element limit *nothing was looked at*,
   and the panel says so rather than leaving "full auto" to be assumed.
4. **Report** — ~~equivalence classes shown as classes, never as a ranked list with a winner;
   JSON / CSV / netlist download; the DRT structure probe beside the search as the CLI already
   prints it.~~ **Built** (§2.6). Two things the sketch did not have. A constrained search gets
   a panel of its own — what the data could not test, where the skeleton sits ambiguously, and
   an opt-in pass naming the equivalent forms the assertion excluded — because that is the part
   `CLAUDE.md` calls non-optional and the part no other screen can carry. And the exports cover
   the *manual* fit as well as the search: mode 1 is this program's differentiator, and a fitted
   model nobody can take out of the browser is not a deliverable.

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
| 3 | ~~Circuit canvas + live preview + manual fit~~ | **done** — §2.4; gate W1 measured |
| 4 | ~~Discovery job screen: progress, streaming, cancel, completeness~~ | **done** — §2.5; gates W2 and W4 measured |
| 5 | ~~Report: equivalence classes, exports, DRT panel~~ | **done** — §2.6; gate W6 measured |
| 6 | Example datasets, loading states, dark/light, deploy to Pages | S |

## 6. Acceptance gates

- **W1** — the browser and the CLI produce identical fitted parameters for the nine-circuit
  synthetic corpus, to the last reported digit. Same code, so any difference is a bug in the
  bridge. **[measured] Passes**, §2.4: all 34 parameters agree at six significant digits. Note
  what the gate does *not* say, because the measurement showed it matters: none of them are
  bit-identical, and none can be — the optimizer's path is not reproducible across
  interpreters, only its answer is.
- **W2** — `discover` at `exhaustive_limit=4` on the capacitor reference completes in the
  browser, streams progress at least once a second, and reports the same `complete_up_to` and
  equivalence classes as the CLI. **[measured] The results pass exactly** (§2.5), in a real
  browser and not only headlessly. **The streaming clause passes for tier 1 and cannot pass for
  tier 2**: one refit is the smallest thing that can finish there and one took 8.6 s, so what
  updates every second is the elapsed clock, while the counts and the front update per finished
  fit. The gate was written before anyone had measured how long a browser refit takes; it is
  recorded here rather than quietly reinterpreted.
- **W3** — cold load to an interactive first fit under 10 s on a mid-range laptop. **[measured]
  Does not pass: ~13 s to a usable page, before any fit.** §2.3 has the breakdown and says which
  stage is worth attacking. Failing this gate does not block steps 3–5; it is a step 6 item that
  now has a number instead of an assumption.
- **W4** — cancel actually stops the work (not just the UI), and a cancelled run reports the
  coverage it reached rather than a wrong number. **[measured] Passes** (§2.5): the pool is
  terminated, since nothing else interrupts a running fit in a single-threaded interpreter, and
  the report distinguishes a complete screen from a shortlist that was only partly refitted.
- **W5** — the site works offline after first load, and from `file://` as well as Pages.
- **W6** — a file downloaded from the browser is the file the command line writes. Added with
  step 5, because an export is the one artefact of this program that outlives the session that
  produced it, and a browser-side renderer of the same format is a second implementation whose
  disagreement nobody would ever see. The test drives a whole search through the bridge, exports
  it, and compares against `discover()` on the same data: every key of the JSON report equal
  except the clocks, the CSV text equal, and the netlist of the recommended candidate equal.

## 7. Out of scope

- Server-side compute of any kind. The moment there is a backend, the "static site" property
  and its deployment story are gone.
- Multi-user features, project files, cloud storage.
- Rewriting the fitter in Rust/WASM. Measured as unnecessary (§1); revisit only if a profile
  says otherwise.
