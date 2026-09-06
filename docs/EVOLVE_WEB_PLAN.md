# Porting the genetic search fallback ("evolve") to the browser

**Status: implemented and measured, all four phases.** `docs/WEB_UI_PLAN.md` section 7 stated
the gap this closes outright: "the browser searches exhaustively only: there is no generator
behind the genetic stage, so above the element limit *nothing was looked at*." The browser now
runs the same escalation `discover(mode="auto")` runs on the command line -- exhaustive search,
then a possible pool widening, then a possible fall-back to the genetic search
(`docs/EVOLVE_SEARCH_PLAN.md`) -- and reaches the same answer, measured field-for-field against
the CLI on a spectrum the fallback actually has to run on to explain.

## What this is not

A user-facing "run the genetic search" toggle was considered and rejected before any code was
written, for two reasons -- and a third, originally listed alongside them, turned out on
inspection not to hold and is recorded here rather than quietly dropped.

- **The browser is the surface CLAUDE.md's own rule is written for.** "A knob the target user
  cannot set correctly is not a feature ... search internals must have measured defaults instead
  of being handed over." `mode` is not a fact about the physical part the way `pool` and
  `skeleton` are: a named pool or a skeleton encodes something the user actually knows about
  their component, and the report states what that assertion excluded. Choosing `exhaustive` vs.
  `evolve` encodes no such thing -- nothing about a spectrum tells a non-expert which is the right
  search to run, and `evolve` is strictly dominated whenever `exhaustive` is affordable
  (`docs/EVOLVE_SEARCH_PLAN.md`'s 30/30 recovery against the fallback's 1/9-5/9). A toggle here
  would not be a narrowing the user asked for; it would be a coin flip dressed as a setting. The
  CLI exposes `--mode` anyway, because its audience already carries the burden of every other
  algorithm-internal flag it accepts (`--workers`, `--growth-width`, a raw element pool); the
  browser is the front end built specifically so a non-expert reaches the same answer an expert
  would (CLAUDE.md's purpose point 3), so the same knob is withheld there without that being
  inconsistent with the CLI shipping it to a different audience.
- **No automatic trigger is known to do better, so there is nothing better to expose instead.**
  `docs/TOPOLOGY_6PLUS_PLAN.md` X3 scored four *automatic* decision rules for when to escalate --
  the current runs test, a nested F-test, a parametric bootstrap of it, and a pole-count margin --
  against a 108-row labelled set, and none dominates the incumbent runs test on both recovery and
  false-positive rate. This means the escalation already running is not a stand-in for some
  known-better rule; it is the best rule measured so far.
- **Retracted: "a manual override reintroduces analyst dependence."** This was the third reason
  originally given, and it proves too much: the same sentence applies unchanged to `pool` and
  `skeleton`, which this project keeps as legitimate opt-in narrowings precisely because the user
  supplies real knowledge about the part and the report discloses what was excluded. X3 also does
  not bear on this question either way -- a human tapping a checkbox was never one of the four
  candidates it measured, so it is neither evidence for nor against a manual toggle. The actual
  reason a mode switch is withheld is the first bullet above (there is no part-specific knowledge
  a `mode` choice could encode), not an analyst-dependence argument that would equally forbid
  `pool` and `skeleton`.

So the browser does not gain a mode switch. It gains the same automatic capability the CLI
already defaults to: when `_is_underfitted` says the best exhaustive fit still looks
systematic and there is room under `max_elements`, the fallback now actually runs instead of
there being nothing behind the escalation. The user-visible effect is that six/seven-element
parts the browser used to report as "not reached" become reachable, exactly when and because
the CLI would also reach for the fallback -- never because of anything the user selected.

## Design: two more generators, the same shape the exhaustive stage already has

`screen_plan` and `refit_plan` (`core/discover.py`) already decouple *what to run* from *who
runs it*: each is a `Generator[Batch, Outcomes, Result]` that yields stateless tasks and expects
their outcomes back through `.send()`, so the same generator drives identically whether the
caller is `_exhaustive`'s in-process loop, a `multiprocessing.Pool`, or `web/job.py`'s
`DiscoveryJob` fanning batches across a browser's Web Workers. `_evolve` had no such interface
for either of its two tiers before this project: it owned a `multiprocessing.Pool` for its
whole run and dispatched a whole generation via `executor.map`, and its tier 2 called a
bespoke, non-generator function (`_refine`) rather than the existing `refit_plan`. Porting it
meant giving both tiers that same shape.

### Phase 1 -- `evolve_plan`, tier 1 generator-ized

`evolve_plan(...)` owns the generation loop `_evolve` used to run inline: it seeds the initial
population (from caller-supplied seeds plus random topologies), and for each generation yields
one `EvolveBatch` per window of `item_chunk` offspring, receiving each one's `(polish, search)`
wire-form outcome back through `.send()`. `item_chunk` is the same idea as `screen_plan`'s
`chunk`, generalising *both* of `_evolve`'s previous code paths into one:

- `item_chunk=1` reproduces the fully sequential single-process evaluation (every offspring
  judged against the cache and best-cost-per-complexity exactly as updated by everything
  evaluated before it, this generation included).
- `item_chunk=population` (or larger) reproduces the whole-generation batch dispatch a
  `multiprocessing.Pool` has always used, where every offspring in a generation reads the cache
  and best cost as of the *start* of that generation -- the staleness
  `_Evaluator.evaluate_all`'s executor branch already documented and accepted.

`_evolve_polish_then_search_worker` (the per-offspring computation) was split into
`_evolve_one` (spectrum/weighting/context as explicit parameters) with the worker becoming a
thin process-global-reading wrapper over it -- the same split `_screen_one`/`_screen_worker`
already established, and the reason the browser can call it directly instead of relying on
`multiprocessing`'s per-process globals, which do not exist there.

`_Evaluator`/`evaluate_all` were left completely unmodified, because they are directly exercised
by `tests/test_discover.py` and monkey-patched by three `benchmarks/screening_round/` scripts;
`evolve_plan` reimplements the same prepare/dispatch/reconcile steps as a generator rather than
routing through the class, at the cost of one small, deliberately parallel piece of logic
(justified the same way `screen_plan`'s own docstring justifies existing precedent).

**Gate:** a byte-identical fingerprint (`benchmarks/ev5_fingerprint.py --mode evolve`) of
`_evolve`'s full output before and after the refactor, on `workers=1` and `workers=2`, across
all three `REFERENCES`. **Passed: zero diff, both worker counts, all three references.**

### Phase 2 -- `evolve_refit_plan`, tier 2 generator-ized

`_evolve`'s tier 2 used `_refine`, not the exhaustive stage's `refit_plan`, and not by
oversight: two of its decisions are genuinely different from the exhaustive stage's tier 2. The
shortlist comes from `_shortlist_candidates`, not `_shortlist` -- this tier's inputs are
already-fitted `Candidate`s with a real covariance behind their score, not a screen's cost-only
approximation. And the shortlist is walked in `_refit_order`, not the quota's own build order,
because this tier answers to a deadline and the exhaustive stage's tier 2 never does; walking it
in the wrong order is a measured failure mode (`_refit_order`'s own docstring: a six-element
truth ranked 1 of 270 sat at shortlist position 53 while the deadline cut at 40). So
`evolve_refit_plan` is a new generator with the same `RefitBatch`-shaped yield as `refit_plan`,
built around those two existing, documented rules rather than a second implementation of them
-- and it tags each finished candidate with the generation that proposed it, which the
always-generation-0 exhaustive stage has no equivalent of. `_refine` itself is untouched, for
the same reason `_Evaluator` is: `tests/test_discover.py` calls it directly and
`benchmarks/screening_round/report_probe.py` monkey-patches it.

**Gate:** the same byte-identical fingerprint, now covering the whole pipeline (tier 1 + tier
2), still desktop-only. **Passed: zero diff, both worker counts, all three references.**

### Phase 3 -- wire protocol and `web/job.py`

`web/bridge.py` gained two operations mirroring the existing screen/refit ones exactly:
`evolve_task` (stateless -- one offspring's turn, builds its own `FitContext` from the wire
spectrum every call, the same cost `screen_task`/`refit_task` already accept) and
`discover_evolve` (the fallback's own batch-in/batch-out driver, mirroring `discover_screen`).

`web/job.py`'s `DiscoveryJob` gained `next_evolve`/`submit_evolve` for tier 1, structurally
identical to `next_screen`/`submit_screen`. Tier 2 needed no new pair at all: once tier 1
finishes, `_open_evolve_refit` simply replaces `self._refit` with `evolve_refit_plan(...)` and
resets the handful of fields `_consider_widening` already resets for the same reason --
`next_refit`/`submit_refit` do not care which generator `self._refit` holds, so reusing them is
one tier-2 driving loop rather than two. The trigger itself
(`_consider_evolve`) calls `_is_underfitted` -- literally the same function
`discover(mode="auto")` calls, not a reimplementation -- after the widening question has been
asked and answered, in the same order `discover()` asks the two questions, and seeds the
fallback's initial population from the current best five candidates exactly as `discover()`
does. `DiscoveryJob.report()`/`plan_summary()` now say `mode: "auto"` rather than the
always-`"exhaustive"` placeholder, since the search has always run that same escalation --
whether or not either stage actually fires was simply not asked of it before.

One real bug surfaced and was fixed here: `WARM_ACCEPT_FACTOR` ships as `math.inf`, and an
early version of `evolve_task`'s wire payload carried it raw, which `json.dumps(allow_nan=False)`
rejects. Fixed with the same `to_wire_cost`/`from_wire_cost` sentinel-encoding this codebase
already uses for an infinite abandon threshold.

**Gate W-EV1:** the browser's `DiscoveryJob`, driven end to end through `bridge.handle` exactly
as JavaScript will, against `discover(mode="auto")` on the same spectrum and seed, on a scenario
engineered to make the fallback fire for a real reason (a diffusion spectrum no finite R/C tree
reproduces, screened with `pool=["R", "C"]` — the same scenario
`test_a_named_pool_is_an_assertion_and_is_never_widened` already used to prove the fallback
opens at all). Compared candidate list, AICc values, recommendation, `complete_up_to`,
`n_evaluated`, and the full JSON export against `discover(mode="auto")`'s own `to_dict()`.
**Passed: exact match on every field**, on the first run with no discrepancy to debug --
`tests/test_web_job.py::test_the_genetic_fallback_in_the_browser_matches_discover_mode_auto`.

### Phase 4 -- the TypeScript driver

`client.ts` gained `evolveTask` (mirrors `screenTask`/`refitTask`) and `discoverEvolve` (mirrors
`discoverScreen`/`discoverRefit`). `search.ts`'s `SearchRun.run()` pass loop gained one branch:
`refit()` now returns `{ more, evolve }` instead of a bare boolean, and when `evolve` is true the
loop drives `evolve()` (a new method, fanning `evolveTask` across the worker pool exactly as
`screen()` fans `screenTask`) before looping back -- at which point `screen()` no-ops (nothing
left to screen) and `refit()` starts answering from the fallback's own shortlist. No new UI
control: `SearchProgress.stage` gained an `"evolving"` value purely so the existing progress
panel can say what is running, the same way it already says "Refitting the shortlist" with no
user input involved.

**Gate:** `npm run check` (typecheck, schematic, sample consistency) and `npm run smoke`, the
latter extended with a dedicated "genetic fallback" section using the same diffusion/`["R","
C"]` scenario as gate W-EV1, driven through the real Pyodide bridge with no shortcuts. **Passed,
all checks**, including a new assertion that `generations > 0` in the finished report -- which
required adding a `generations` key to `report_payload()`'s JSON that had never existed before,
since it was always zero and therefore never worth exposing until now.

## What was measured and what was assumed

Every claim above the "Gate" lines is measured, not asserted from reading the code -- each phase
was run against its own gate before the next began, and Phase 3's bridge bug (the `Infinity`
encoding) was caught by that discipline rather than by inspection. What is *not* yet measured:
wall-clock cost in a real browser (every gate here ran inside Node/pytest's Pyodide, not a
loaded browser tab under `STARTUP_AND_EDITING_PLAN.md`'s cold-start conditions), and recovery
rate on the large multi-element references `docs/TOPOLOGY_6PLUS_PLAN.md`'s X-series used --
this work proves the browser's fallback computes what the CLI's does, not that the fallback
itself recovers more truths than `EVOLVE_SEARCH_PLAN.md`'s already-documented 5/9 ceiling.
Nothing here changes that ceiling; it only makes the browser subject to it instead of to a hard
wall.
