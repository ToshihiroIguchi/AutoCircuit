# SCREEN_STATE_PLAN.md — where a result lives, and where it is shown

Phase 8. Four questions about the web UI that turn out to be one defect, plus the architecture
question they raise: **what is allowed to travel from the Discover screen to the Fit screen.**

The four, as asked:

1. Why does the Discover screen have no Plots when the Fit screen does? Should it?
2. Why does data disappear when moving from Discover to Fit?
3. Discover and Fit are independent. Should it be possible to move data from Discover to Fit?
   (The asker's own note: *this idea is likely wrong.* It is, and §3 says why.)
4. The Discover indicator moves twice. Is that appropriate?

---

## 1. Four questions, one defect

Questions 1 and 2 have the same root, and it is not a UI oversight. `App.tsx` lifts state out of a
screen when *another screen* needs it, and only then. So:

* `discovery` is in `App` — because the **Report** screen reads it.
* `manualFit` is in `App` — because the **Report** screen exports it.
* `excluded` and `drt` are in `App` — because they are long jobs the Report screen starts.
* The Discover screen's own `report`, `picked`, `progress`, `running` are **not**, because no other
  screen reads them. Nor are the Fit screen's `values`, `fit`, `held`, `bounds`.

A React screen is unmounted the moment the user looks at another tab. The rule "lift what another
screen needs" therefore has an unintended second half: **a result is preserved for every screen
except the one that produced it.** That is the whole of question 2, and it produces the following
measured pair.

## 2. What was measured, before

Chrome, `npm run dev`, the Maxwell-Wagner sample (81 points), exhaustive limit 3, four workers.

**[measured] A finished search survives everywhere except on the screen that ran it.** After the
search completed, one click to the Fit tab and one back to Discover left
`document.querySelector('.discover-report')` null — no coverage sentence, no front, no selected
circuit, no schematic. The Report tab, at the same moment, still rendered
`.report-screen__discovery` with the identical sentence: *"Coverage: every plausible topology with
up to 3 elements from this pool was evaluated."* The search itself was never lost; only its screen
was.

**[measured] The same for a manual fit, and it is sharper there.** After fitting `R1` on the Fit
screen, one click to Report and one back left the Fit panel reading *"Not fitted. The preview curve
is 1037.7% from the data"* — while the Report screen that had just been visited was, at that
instant, offering a panel headed **"Download the fit of R1"**. The application offers a download of
a fit that the screen which produced it denies having made.

**[measured] The indicator is three bars, and two of them restart from zero.** Sampling the
progress panel every 200 ms across a whole run:

| t (s) | stage | counts | bar |
|---|---|---|---|
| — | Starting the worker pool | 0 / 4 workers ready | 0% → 100% |
| 12.3 | Screening candidates | 63 / 66 screened | 95.5% |
| 15.7 | Screening candidates | 64 / 66 screened | 97.0% |
| 15.7 | **Refitting the shortlist** | **0 / 31** refitted | **0%** |
| 39.5 | Refitting the shortlist | 30 / 31 refitted | 96.8% |
| 39.7 | *(panel gone, report shown)* | | |

Two resets to zero, and neither completed stage is ever left on screen at 100% for long enough to
be seen at a 200 ms sampling interval. Nothing here is wrong about the *search* — screening and
refitting really are two tiers with per-item costs three orders of magnitude apart — but a single
bar that silently changes what it is counting is a bar that reports a regression twice per run.

**[measured] No Plots on Discover, and no data to draw them from either.** `.plots-panel` count on
the Discover screen after a finished search: 0. Reading `core/types.ts` says why the panel could
not simply be dropped in: `CandidateRowWire` carries scores and counts and *no* `z_model` and *no*
fitted values. A front row, as it reaches the browser today, cannot be plotted.

## 3. The architecture question

Question 3 asks whether Discover should be able to hand data to Fit. Five arrangements are
possible. They are listed with what each costs, because the choice is not a matter of taste — one
of them contradicts a rule this project already enforces in three other places.

### A. Status quo — topology only, one way

`onFitCircuit` carries the circuit string and nothing else, documented at
`DiscoverScreenProps.onFitCircuit`: the fitted values are deliberately not carried, because this
fitter takes no starting guess and carrying numbers would make a screen that says *"these do not
seed the fit"* look as though they did.

Correct as far as it goes, and it is kept. It is not, by itself, an answer: it leaves the discovered
fit visible nowhere at all (§2), which is what makes the hand-off look lossy in a bad way rather
than a principled one.

### B. Carry the fit

The chosen row's `FitResult` becomes the Fit screen's fit: values in the parameter table, standard
errors, statistics.

Rejected, on two independent grounds.

*Epistemically*, a Pareto row is **one of several topologies the data cannot tell apart** — that is
the sentence the Report screen exists to protect, and `equivalence_classes` is that sentence in
data form. Installing one row as "the fit" on a screen whose entire framing is *the user asserted
this circuit* converts a ranked candidate into an assertion, and drops the qualification in the
conversion. This is the same failure mode as `docs/HANDOFF.md` §3 and `docs/DISCOVERY_V2_PLAN.md`
§3.4: the report still looks healthy.

*Practically*, it buys nothing. The search's refit runs `final_restarts=5`, `seed=0` and the
search's weighting — the Fit screen's own defaults. Refitting the same topology against the same
data therefore reproduces the same numbers (gate G2 below measures this rather than asserting it).
The only case where carrying values would save work is the case where the user changes nothing on
the Fit screen — and once the plots are on the Discover screen (§4) there is no reason to walk over
to Fit and change nothing. The moment they *do* change something, the carried values are values of
a different model.

Doing B correctly would also require carrying the search's weighting, restart count and seed into
the Fit panel's controls, or the screen would display a fit under settings that did not produce it.

### C. One shared "current model" store

A single App-level object `{circuit, values, fit, spectrum, settings}` that both screens read and
write; the tabs become two views of one model.

Rejected. It makes "which spectrum, which weighting, which restart count is this fit of?" ambiguous
at exactly the point where this project has already been burned into being explicit: `ManualFit`
carries *the spectrum itself* rather than a reference, because a netlist header states the
frequency band the model is valid over and an export against a re-trimmed window would put a false
claim in a file that outlives the session. A shared mutable model means an edit on one screen
silently redefines what the other screen is claiming. The Discover screen would keep its coverage
sentence while the model underneath it changed.

### D. Merge Discover and Fit into one screen

Rejected. The two screens differ in *who asserted the topology*, and that difference is the axis the
whole report language turns on: `complete_up_to`'s sentence, `skeleton`, `unsupported_assertion`.
Merging the screens deletes the visible boundary between "the search proposed this" and "you
asserted this" from the UI while every string in the report still depends on it.

### E. Never unmount — keep all four screens mounted, hidden with CSS

Fixes every symptom in §2 in one line, and answers no question. It also makes *editing* state
permanent alongside results — a half-typed circuit string, an armed palette button — runs four
screens' effects for every visitor including those who never open them, and keeps three
`PlotsPanel`s (twelve live Plotly canvases) resident on a page already carrying a 17 MB Pyodide
runtime. It treats "state survived" as the goal, when the actual goal is that a *result* survives
and a *draft* need not.

### F. Chosen — the session owns results; a screen owns only what is being typed

One rule, stated positively:

> **A result belongs to the session. A screen owns only what the user is in the middle of
> composing.** A finished search, a finished fit, a probe, and the run that is producing one, are
> results. A half-typed circuit string, an armed palette button, a parse error under a field are
> drafts.

`App` already applies this to `excluded` and `drt`, and its own header comment already states the
danger ("state left inside it is state the user loses by glancing away"). The search and the manual
fit were simply the two cases where the rule was applied only far enough to serve the *Report*
screen. Applying it fully is the fix for question 2, and it fixes the one real bug hiding behind the
cosmetics: with `running` inside the screen, switching tabs during a search and returning re-enables
the Discover button, and a second search can be started onto the pool the first one is still using.

And F has a corollary, which is the answer to question 1:

> **Because the discovered fit may not travel to the Fit screen, the Discover screen owes the
> user a full view of it where it was made.**

The current design took the first half (§3.A, correctly) without the second. That is why the
absence of plots on Discover is not a missing nicety but the unpaid half of a decision already
taken.

So the answer to question 3 is: the asker's suspicion is right, and for a sharper reason than
"it would be complicated". The hand-off is **lossy on purpose** — what crosses is the *topology*,
which the user is now asserting, and not the *fit*, which was a ranked candidate. One thing is
added to what crosses, though (§5): the **spectrum selection**, because a search that ran against
spectrum A must not hand its topology to a Fit screen that is pointed at spectrum B.

## 4. Plots on the Discover screen

Yes, and they cost almost nothing, because the fit already exists.

Every row of `report.candidates` — and therefore of `report.pareto` — was produced by a tier-2
refit dispatched from this browser (`SearchRun.refit` → `pool.map` → `refitTask`), and
`_op_refit_task` already answers with the whole `FitResult.to_wire()`, `z_model` and all. The
orchestrator worker keeps those fits for the lifetime of the job — it must, since `job.candidate()`
is what the exports are rendered from.

So a plot needs no new computation, only a way to ask for what is already held:

* **New bridge op `discover_candidate(job, circuit)`** → the same `FitWire` shape `fit` answers
  with: the fit, its relative error, the weighted residuals **split in Python**, its warnings and
  its summary sentence. Split in Python for the reason `_op_fit` already gives: the concatenation
  order of the residual vector is a detail of the objective function and not a promise, so no front
  end hard-codes it. `BRIDGE_VERSION` 5 → 6.
* **Lazy, not bulk.** Nothing is added to the refit payload, which crosses the wire once per
  shortlisted topology; the fit is fetched when a row is selected and cached per `job|circuit`.
* **Drawn against the spectrum the search ran on**, captured when the search started — not against
  whichever spectrum is selected now, and not against a window that has been re-trimmed since. The
  panel is captioned with that spectrum's name for the same reason `ManualFit` carries its
  spectrum.

`PlotsPanel` takes `LoadedSpectrum` today, which is a Data-screen record (id, label, validation
status). It is narrowed to `spectrum: SpectrumWire` plus an optional `validation` bundle that only
the Data screen passes, so the same four panels serve all three screens.

## 5. The search becomes a session-owned job

`SearchState` in `App`, alongside `ExcludedState` and `DrtState` and for the same stated reason:

```ts
interface SearchState {
  token: string;                                                      // which run this is
  spectrumId: string; spectrumLabel: string; spectrum: SpectrumWire;  // what it ran against
  options: SearchOptions; workers: number;                            // what it ran with
  progress: SearchProgress; running: boolean;                          // where it has got to
  report: ReportWire | null; picked: string | null;                    // what it found
  pickedFit: FitWire | null; pickedError: string | null; picking: boolean;
  stoppedEarly: boolean; error: string | null;
}
```

`token` rather than the job id, because the job id does not exist until the space has been
enumerated — and the gap between pressing Discover and that answer is exactly when a
cancel-and-restart happens. Without it, a superseded run's final `running: false` would land on its
successor.

`Discovery` — what the Report screen consumes — is derived from it, so that screen is untouched.
The `SearchRun` moves into an `App` ref so that a cancel issued after a tab switch still reaches the
run that is going. The same treatment is applied to the Fit screen's `FitState` (values, holds,
bounds, the fit, and the weighting/restarts/seed that produced it): because every write goes through
an `App` setter, a fit that lands while the user is on another tab now arrives instead of being
dropped into an unmounted component.

Draft state stays in the screens: `armedCode`, `selectedLabel`, the parse error, `describe` and
`preview` (both recomputed from the circuit string in one round trip).

`fitCircuit` additionally re-selects the spectrum the search ran against, when it is still loaded.

## 6. The progress indicator

Two tiers is the truth, and a single bar cannot tell it: the shortlist size is not known until
screening finishes (`_shortlist` admits near-ties above `n_refine`), and per-item costs differ by
three orders of magnitude, so any unified percentage would be a fabricated weighting. The measured
refit gap between two consecutive completions reached 8.6 s (`docs/WEB_UI_PLAN.md` §2.5); a bar that
invents motion to cover that is worse than one that stops.

So the fix is not to merge the bars but to stop pretending there is one:

* **All stages visible at once**, each with its own bar and its own units, labelled
  *Stage 1 of 2 — Screening* and *Stage 2 of 2 — Refitting*, plus the pool boot as a preparation row.
* **A row never disappears and never decreases.** When screening ends its row stays, filled, marked
  done; the refit row is present from the start showing "not yet known" until the shortlist size
  arrives. Monotonicity becomes structural — each row has its own counter — rather than something a
  reader has to trust.
* The elapsed clock, and the rule that counts move only when the search actually knows more, are
  unchanged (`useLiveElapsed`, `docs/WEB_UI_PLAN.md` §2.5).

## 7. Gates

All four measured in Chrome against `npm run dev`, Maxwell-Wagner sample (81 points, `p(R1,C1)-p(R2,C2)`
plus 1% noise), exhaustive limit 3, four workers, seed 0, modulus weighting — the same run as §2.

* **G1 — a result survives its own screen. [met]** After the search finished, each of the other
  three tabs was visited and returned from in turn. The coverage sentence, all three front rows,
  the selected circuit and all four plots were byte-identical after every round trip. The same for
  a fit: `p(R1-CPE1,C1)` fitted on the Fit screen still read *Converged*, AIC −324.335, with its
  overlay drawn, after visiting Data, Discover and Report. The Report screen's export panel now
  names the same circuit the Fit screen is showing, rather than one it denies having fitted.

  A **running** search survives the same trip, which is the half that was a bug rather than a
  cosmetic loss. Leaving the Discover tab six seconds into a search (rows reading `0 / 4 workers
  ready`, both tiers "not started") and returning five seconds later showed `4 / 4 workers ready`
  and `61 / 66 screened` — the run had carried on and the panel had followed it — and the only
  button on the screen was **Cancel**. The Discover button is not merely disabled but absent while
  a search is running, so the second-search-onto-a-busy-pool path is closed.
* **G2 — the hand-off loses nothing worth carrying. [met, exactly]** The search's own refit of
  `p(R1-CPE1,C1)` scored **AIC −324.335, χ²(reduced) 0.13180**. Pressing *Fit this circuit* and then
  *Fit* — an independent global search from the data-derived interval, no starting guess — gave
  **AIC −324.335, χ²(reduced) 0.13180**, and AICc −324.080, BIC −311.984 beside them. So carrying the
  fitted values across would have saved one refit and changed no number on the screen. That is the
  measurement §3.B rests on, and it is why the hand-off stays topology-only rather than staying
  topology-only "for now".
* **G3 — no indicator ever goes backwards. [met]** The whole run sampled every 100 ms, comparing
  each stage row's bar width against its own previous value: **zero violations across 33 distinct
  states**, and the row count never fell. Screening ends at 66 / 66 (100%) and *stays* there,
  filled, while the refit runs 0 → 30 / 31 beneath it. Compare §2, where the same run showed
  95.5% → 0% twice.
* **G4 — nothing else moved. [met]** `npm run check` (type check + the schematic geometry suite)
  passes, as does the production `npm run build`; `ruff check` passes; the Python suite is
  717 passed, 19 skipped, plus three new tests pinning `discover_candidate` to the fit the row was
  ranked on rather than a re-run. The front from this run is the same three rows in the same order
  as the pre-change run of §2 on the same sample, seed and limit.

  One test failed on the full-suite run and passes on its own:
  `test_discover.py::test_time_limit_stops_the_search`, which asserts a 5 s-limited search finishes
  inside 60 s of wall clock, took 71.8 s while this machine was also running a browser with five
  Pyodide workers, a Vite dev server and a command-line search. Re-run alone: 57.8 s, passed. It is
  a load-sensitive clock assertion in `core/discover.py`, which this phase does not touch — recorded
  rather than waved away, since a timing test that fails under load is a real property of the suite.

## 8. Corrections

*(What a measurement changed about the plan above. A gate written from an expectation is withdrawn
with the measurement beside it, never reworded into what the build already does.)*

**§2's "never seen at 100%" was over-claimed, and the fix stands anyway.** The before-run was
sampled at 200 ms, and the screening bar's step from 64 / 66 to the refit's 0 / 31 fell inside one
interval. That is enough to say the bar *restarted from zero twice* — which it did, and which is
what was asked about — but not enough to say the intermediate 100% frame was never painted. It may
have been, for less than 200 ms. The claim in §2 is left as the timeline it is, and the argument
does not need the stronger version: a bar that silently changes its denominator is the defect,
whether or not it flashes full on the way.

**The deploy gate caught a version pin the local checks could not, and the pin was the wrong shape.**
`BRIDGE_VERSION` 5 → 6 was changed in three places — `bridge.py`, `protocol.ts`, and the Python test
that deliberately pins the literal — and missed a fourth: `web/scripts/smoke.mjs` asserted
`bridge version is 5` against a hand-typed number. Nothing local runs that script (`npm run check` is
the type check and the schematic geometry; the smoke run is its own command), so the first thing to
notice was the Pages workflow, which failed the publish rather than shipping a mismatch. **The gate
did its job.** But a fourth hand-typed copy of one number is a thing to forget, so the check now
reads the expected version out of `protocol.ts`: the question it exists to answer is whether the
core being shipped answers the protocol the page being shipped speaks, which is what
`bridge.worker.ts` refuses to run without. The Python test keeps its literal, because that one is a
tripwire whose whole purpose is to make a human acknowledge the bump.

**Monotonicity is now structural rather than measured.** G3 samples one run on one machine, which
can only ever fail to find a violation. What actually rules them out is that each tier has its own
counter and its own row, and a row is only ever drawn full when `stateOf` says its stage is
finished — which it refuses to say on a cancelled run, because a cancelled tier did not complete.
The measurement is worth having as a check on the wiring; it is not what carries the guarantee.
