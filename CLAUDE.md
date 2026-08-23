# CLAUDE.md

## Language policy

- **Conversation with the user: Japanese.**
- **Everything else: English.** This includes code, identifiers, comments, docstrings,
  documentation, commit messages, CLI messages, log output, test names, and Web UI strings.
- Do not mix Japanese into source files or docs, even in comments.

## Model / cost policy

Fable and Opus are very expensive. Delegate work to cheaper models via subagents:

- **Simple investigation** (locating code, summarizing a file/library, checking a format spec,
  routine web lookups): spawn a subagent with `model: "haiku"`.
- **Simple implementation** (boilerplate, a well-specified function, straightforward tests,
  format readers following an existing pattern, mechanical refactors): spawn a subagent with
  `model: "sonnet"`.
- Reserve the main (expensive) model for architecture decisions, numerical-algorithm design and
  debugging, fitting/optimization logic, and anything with subtle correctness requirements.
- When a task decomposes into several independent simple parts, run the cheap subagents in
  parallel.

## Project overview

### Purpose

**AutoCircuit takes measured impedance-vs-frequency data of an electronic component and
returns both the equivalent-circuit topology and its parameter values.** Three sentences say
what that is for, and they are the tie-breaker whenever a design decision is arguable:

1. **Search the circuit out of the data, parameters included.** Not "fit a circuit the user
   already wrote down" — that is one supported mode, not the goal. The goal is that the data
   chooses the topology *and* the values.
2. **The circuit is a means, not the end: the target is what is inside the part.** Impedance is
   swept over many frequencies on a ceramic (or another passive component), the equivalent
   circuit is extracted, and the circuit is then read as internal structure — grain versus grain
   boundary, dielectric loss, electrode and interface contributions, ESR/ESL and skin effect.
   **The only input is the spectrum: frequency and impedance, and nothing else.** No sample
   geometry, no part number, no material data sheet. This is a decision, not a gap to be filled
   later, and it draws a hard line through what "internal structure" may mean here — see the
   consequence below.
3. **Automate the two steps that used to require an expert, so that a non-expert gets the same
   answer.** Historically a human chose the topology and hand-picked fitting initial values, so
   the result depended on who ran it. Both steps are to be automated well enough that an analyst
   with little background reaches a defensible answer.

Consequences that follow from those three, and that outrank local convenience:

- **A knob the target user cannot set correctly is not a feature.** Point 3 is broken by any
  required input that only an expert could supply — initial values above all, but also
  algorithm internals. Budget-shaped controls ("how long", "how thorough", "how large a
  circuit") are the user's; search internals must have measured defaults instead of being
  handed over. "What kind of part is this?" is *not* a budget control and is ruled out by the
  next consequence.
- **The automatic path takes the spectrum and nothing else; every other input is an optional
  narrowing the user asked for.** `pool` and `skeleton` (mode 2) stay, because a user who does
  know something about the part may say so and the report already states what the constraint
  excluded. But nothing beyond frequency and impedance may ever be *required*, and the software
  must not ask what kind of part this is — that question is precisely the expert judgement
  point 3 exists to remove, and a non-expert's wrong answer to it would silently narrow the
  search. Whatever the search would have gained from an answer must instead be **derived from
  the spectrum's own shape**: presence of a resonance, the low-frequency slope, a 45-degree
  diffusion branch, the number of relaxations the data can distinguish.
- **Geometry-free quantities are in scope; absolute material constants are not, and never will
  be.** Z(f) fixes a capacitance; it cannot fix a permittivity, because the two differ by A/d,
  a factor the spectrum does not contain. So permittivity, conductivity, layer thickness and
  every other quantity needing an absolute length or area are **out of scope by decision** —
  not "not yet". What survives the geometry ban is a large and useful set, and it is the set to
  build out: ESR, ESL, self-resonant frequency, Q, tan δ, time constants τ = RC, relaxation
  frequencies, the number of relaxations the data can actually distinguish, each block's share
  of the total polarisation, and dimensionless *ratios* such as grain-to-grain-boundary
  capacitance. Those are internal structure stated in the only terms the input supports.
- **Point 2 is under way and not finished.** `core/interpret.py` computes the geometry-free
  readouts from a fitted circuit -- `autocircuit fit --interpret`, and `interpretation` in the
  `--json` report. What it is built around is the split that matters: every quantity is marked
  **invariant** (the same for every topology in the equivalence class, because it is a property
  of `Z` -- terminal resistances, self-resonance, tan delta, and the poles and zeros of `Z(s)`)
  or **form-dependent** (a feature of the tree that was reported, such as a block's `R*C`).
  Gate I1 has both halves: the invariant quantities must agree across an exact
  reparameterisation, *and* the form-dependent ones must be seen to disagree, because a label
  nothing can falsify is not a label. Still missing: the discovery report does not carry an
  interpretation, the browser does not show one, and the `objective` split below is not wired
  anywhere.
- **Honest reporting outranks a satisfying answer**, because point 3 removes the expert who
  would otherwise catch an over-claim. This is why discovery reports a Pareto front and
  equivalence classes rather than "the answer", and why every claim below is either measured or
  marked as not.

### Objectives — what the user wants out, which is not what the search does

There are two reasons to bring an impedance spectrum here, and they want different reports from
the *same* analysis:

- **`model`** — an equivalent circuit to use, typically in a simulator. Deliverable: the SPICE
  subcircuit plus the band it is valid over. Readouts: ESR(f), ESL, self-resonant frequency, Q,
  minimum |Z|, tan δ, DC resistance. Bode is the plot that matters. Its claim is complete and
  checkable from the data alone: *this reproduces the measured Z over this band*.
- **`interpret`** — what the spectrum says is happening inside the part. Deliverable: the
  processes the data can distinguish — how many relaxations, each one's τ and relaxation
  frequency, each block's share of the total polarisation, the CPE exponent as a measure of how
  distributed a process is, whether there is a diffusion branch and of which kind, and
  dimensionless ratios such as grain-to-grain-boundary capacitance. Nyquist and DRT are the
  plots that matter. Its claim is always conditional.

**Objective and mode are orthogonal axes and must not be conflated.** The mode says how much of
the topology the user fixes and it changes the *search*; the objective says what the user wants
out and it must change **only the report**.

**The invariant: the objective never reaches a number.** `discover()` and `fit()` do not take it
— it is a parameter of the reporting layer, so the rule is enforced by construction rather than
by convention. Two people with the same spectrum must get the same circuit and the same values
whatever they came for; the moment an objective narrows the pool, reorders the Pareto front or
changes what is recommended, the analyst-independence that is this project's whole differentiator
against ZView is gone. Nothing upstream needs to differ, and that was checked rather than
assumed: the pool is derived from the data rather than fixed (see the consequence above, and
`docs/POOL_FROM_SPECTRUM_PLAN.md` — the CLI default is now `--pool auto`, which searches
`("R","C","L","CPE")` and widens it only when *that pool's own completed fit* leaves a
systematic residual, because the obvious shape detector was built and measured not to separate
the composite spectra that matter; the browser is not yet wired), every element exports to
SPICE because `core/spice.py` synthesises
ladders from the impedance function rather than per element, and
parsimony-with-every-parameter-resolved is the right recommendation rule for both.

**Gate O1 — the objective changes no number.** The full pipeline run under both objectives on the
same spectrum and seed produces a **byte-identical** `DiscoveryResult` wire payload; only the
rendered report differs. Fingerprint it the way EV5 does. *Not implemented yet.*

**Why the split exists at all is the equivalence classes, not the vocabulary.** `R1-p(R2,C1)` and
`p(R1,C1-R2)` fit the same data to 1.2e-15. Under `model` that is harmless — same terminal
behaviour, either one exports and simulates identically, and asking which is "right" has no
content. Under `interpret` it *is* the question: whether R2 is a grain boundary or an electrode
interface is exactly that difference in form, and the spectrum does not contain the answer. So
what the objective legitimately changes is **how loudly the report says the data cannot decide** —
loudest under `interpret`, where a non-expert is most likely to read a topology as a mechanism.

**One extension belongs to `interpret` alone**, and it stays inside the frequency-and-impedance
rule because it only adds more spectra: several sweeps at different temperatures or DC bias, fitted
to one circuit simultaneously. It yields activation energies, and it is the only instrument
available here that can actually *break* a degeneracy, since two forms that are indistinguishable
at one condition often depend on temperature differently. It buys `model` nothing.

### Modes

Three modes, which differ only in how much of the topology the user fixes (and note that this is
an axis orthogonal to the objective above):
1. **Manual topology**: the user supplies the whole equivalent circuit; AutoCircuit fits all
   parameters **without any user-supplied initial values** (global optimization; this is the key
   differentiator vs. ZView).
2. **Partial topology** (implemented, gates measured; see `docs/PARTIAL_TOPOLOGY_PLAN.md`):
   the user supplies a *skeleton* — the
   part they already know is there, such as a series ESR/ESL on a capacitor or an electrolyte
   resistance on a cell — and the search adds the remaining elements. The candidate space is
   defined generatively, as every topology that reduces to the skeleton once the added elements
   are removed, so it is enumerated by growing the skeleton rather than by filtering the full
   space. (A skeleton is a *constraint*; `discover(seeds=...)` is a *hint* that merely adds
   circuits to the candidate list. They are not the same feature, and a seed that does not
   contain the skeleton is an error rather than a silent choice between them.)
3. **Full auto**: both the circuit topology and its parameters are discovered automatically,
   reported as an accuracy-versus-complexity Pareto front plus equivalence classes — never as
   a single "the answer", because different topologies are frequently exact
   reparameterisations of one another. Exhaustive enumeration up to 5 elements, with the
   genetic search as a fallback above that (see `docs/DISCOVERY_V2_PLAN.md`).

**A user-supplied constraint narrows what the report is allowed to claim, and saying so is not
optional.** Mode 2 is the same shape as two failures this project has already measured — a
screening budget that drops the truth while its equivalents stay on the shortlist, and a DRT
peak count that would delete the right answer from a search still calling itself exhaustive
(`docs/HANDOFF.md` §3, `docs/DISCOVERY_V2_PLAN.md` §3.4). In all three the report still *looks*
healthy. So a constrained search must state its constraint in `complete_up_to`'s sentence
("every plausible topology up to N elements **that contains this skeleton**"), and must report
which equivalence-class members the skeleton excluded: choosing between forms the data cannot
distinguish is something the user did, never a finding.

Other pillars: full ZView-equivalent element set plus skin-effect and Maxwell-Wagner support,
SPICE netlist export (with RC/RL ladder synthesis for fractional elements), readers for common
instrument formats (ZView/Solartron, Keysight CSV, Touchstone, generic CSV), CLI first, then a
static-site Web UI running the same core via WASM (Pyodide).

### Start here

1. `docs/HANDOFF.md` — current state, environment quirks, and the hard-won facts that must not
   be re-derived or accidentally "fixed".
2. `docs/IMPLEMENTATION_PLAN.md` — the overall design. Claims marked **[measured]** are
   backed by `benchmarks/`; do not contradict them without re-running the benchmark.
3. `docs/DISCOVERY_V2_PLAN.md` — exhaustive-first topology discovery. **Implemented**; kept
   because its corrections record why several obvious-looking choices are wrong.
4. `docs/PARTIAL_TOPOLOGY_PLAN.md` — skeleton-constrained discovery (mode 2 above).
   **Implemented; gates P1–P4 measured.** Its §3 is the part that matters — what a constrained
   search is allowed to claim — and §3.2 is where a guess was replaced by a measurement: a
   wrong skeleton is invisible in the residuals and in chi², and surfaces only as an asserted
   element the fit had to switch off.
5. `docs/WEB_UI_PLAN.md` — phase 6, web UI. **Complete: all seven steps done and measured**, and
   the site is live at <https://toshihiroiguchi.github.io/AutoCircuit/> (a lossless
   `FitResult` across a worker boundary, so the browser fans out both tiers, 287 s → 123 s; the
   Data screen, whose Lin-KK verdicts match the CLI's digit for digit; the Fit screen, whose
   fits match the CLI's to every reported digit — gate W1; the Discover screen, whose search
   matches the CLI's front row for row — gates W2 and W4; the Report screen, whose downloads
   are the files the CLI writes — gate W6; and the finish — example data, light/dark, honest
   loading states, and a deployment workflow that gates on the type check and the Pyodide smoke
   run). Its §2.3 is where a browser contradicted a number taken from Node, §2.4 is
   where a measurement retired an assumption the transport had been designed around (a fit is
   *not* bit-reproducible across interpreters, only its reported digits are), §2.5 is where
   a measurement showed one clause of a gate to be unachievable — tier-2 progress cannot stream
   once a second, because one refit takes several — and the gate was rewritten around what was
   measured rather than quietly reinterpreted, §2.6 is where a report that can be *stopped*
   turned out to need a weaker sentence than the one it was written with, §2.7 is where a
   step shipped with two of its gates still open and said so instead of reading them down, and
   §2.8 is where those two were answered in opposite ways. **W3 is met on a rested machine and
   missed on a loaded one** — the cold start went ~13 s → ~5 s once the build began shipping
   bytecode instead of source, so a first fit is finished ~6.6 s after navigation when this
   machine is rested and ~13 s when it is not, which is reported as the pair it is rather than as
   the flattering half — and **W5 is retired**: its `file://` half was measured to be
   impossible for any packaging of this application, and its offline half was declined rather than
   built, because a service worker would put a cache between every visitor and a site that
   republishes on every push. A gate written from an expectation is withdrawn with the measurement
   beside it, never reworded into something the build already does.
6. `docs/METRICS_AND_UX_PLAN.md` -- the seven model-selection criteria and six UI questions.
   **Implemented; gates M1-M3 measured.** Its §2.3 is where WAIC had to be given a stated
   approximation rather than refused or faked, §2.4 is why an F-test is offered as a *test* and
   never as a score, §2.5 is what a criterion is not allowed to change (the recommendation), and
   and §1.5 is where **both** versions of the obvious cold-start fix were built and neither
   survived its own measurement: a document's preload cache does not serve a Web Worker's fetch
   (17 MB downloaded twice), and doing it inside the worker cut the stage it targeted by 3-4x
   while making the *total* worse, because the load is bandwidth-bound. The stage breakdown said
   win and the total said loss; that is the part to remember.
7. `docs/SCREEN_STATE_PLAN.md` — where a result lives and where it is shown. **Implemented; gates
   G1–G4 measured.** Its §3 is the one to read before wiring any two screens together: it
   enumerates five arrangements for the Discover→Fit hand-off and rejects the obvious one, because
   installing a Pareto row as "the fit" converts *one of several topologies the data cannot tell
   apart* into an assertion. §7's G2 is that argument measured rather than asserted — the search's
   refit and an independent refit on the Fit screen agree to every digit (AIC −324.335,
   χ² 0.13180), so carrying the values across would save a refit and change nothing. The rule this
   phase establishes is *a result belongs to the session, a screen owns only what is being typed*;
   the corollary is that a screen which may not hand its result on owes the user a full view of
   it, which is why Discover now plots. §8 records where a "before" measurement was
   over-claimed at a 200 ms sampling interval and was left as the timeline it is rather than
   restated.
8. `docs/STARTUP_AND_EDITING_PLAN.md` — three questions the deployed site raised, and the three
   different kinds of answer they got. **Implemented; gates E1–E5 measured.** Its §1 is the one to
   read before touching the Discover→Fit hand-off: carrying the *topology and not the fit* is
   right and stays, but the sentence it prints ("refitting there lands in the same place") was
   false whenever the search had been run at a weighting or seed the Fit screen did not share —
   measured as the same topology coming back with a capacitance 2.6× different — so the settings
   now travel with the topology. §2.2 is why *moving* an element is one Python operation
   (`move_subtree`) rather than a remove and an insert the browser re-derives a path for. §3 is
   the staged load: **scipy is 18.3 MB of the 41 MB a first visit fetched and nothing on the Data
   screen uses it**, so the page comes up on numpy and fetches the fitter behind it — which is
   *not* the prefetch `METRICS_AND_UX_PLAN` §1.5 rejected, because nothing is fetched earlier than
   before, only later. §6 is where splitting the bytecode overlay the obvious way produced a
   22-byte file that broke nothing and would have cost every visitor a recompile. **§8 is the
   second half of §3 and was added after the site had been live for a while**: making the page
   usable sooner did not make it *look* unfinished while it was, and [measured] a first visit from
   GitHub Pages is 22.3 s to read data and 28.5 s to fit, spent staring at a fully painted page
   whose only disclaimer was an eleven-point caption in the header. The load state now sits in the
   content column, the tab strip marks what is not live, and the finish is announced instead of
   merely ceasing — and there is still no progress bar, because `loadPackage` reports no bytes and
   an animated bar would look identical to a dead worker.
9. `docs/SCHEMATIC_PLAN.md` — how the Fit screen draws the circuit. **Implemented; gates S1–S4
   measured.** The picture is computed rather than laid out: `web/src/core/schematic.ts` turns the
   parsed tree into coordinates, which is what makes "every wire is axis-aligned", "no wire ends
   in mid-air" and "a junction dot exactly where three or more wires meet" assertions rather than
   screenshots — `npm run schematic`, and `npm run check` runs it, so a broken schematic cannot
   be published. Its §3 is the part to read before adding an element symbol: R, C and L are drawn
   as IEC 60617 has them, and everything else is drawn as a box carrying its code **because no
   standard symbol for a CPE or a Warburg exists**, which is a fact about the field and not a
   placeholder to be improved on. §5 records the five mutants the geometry gate was shown to
   catch, one of which it did not catch until a check was added for it.

10. `docs/EVOLVE_SEARCH_PLAN.md` — the genetic search, which is what `mode="auto"` falls back to
   above five elements and the only part of discovery that had **no quality gate at all**.
   **Steps 1–3 of 6 implemented; steps 4–6 planned.** Its §1 is four measurements saying the
   fallback is worse than merely unmeasured — a six-element truth never evaluated in 349 s, an
   archive that is never retired so selection pressure falls 8.2× over 12 generations, and
   **82% of the reported Pareto rows carrying screening-grade numbers** in violation of the rule
   `discover.py` states at its top. That last one is fixed (step 2, gate EV2) and §3.2.1 is the
   part to read before touching the shortlist: extracting the per-size quota into
   `_quota_by_size` silently dropped the tiebreak that decides between *exactly equal* scores —
   which is what an exact reparameterisation looks like — and the whole suite passed with the
   bug in place; only a byte-for-byte fingerprint of an exhaustive run caught it (gate EV5). Its
   §1.5 records a suspicion that measurement demoted rather than confirmed, and §3.2 records a
   parameter sweep the plan asked for that turned out to be **arithmetically incapable of
   showing a difference**. G5 of `DISCOVERY_V2_PLAN.md` is withdrawn there, with the reason
   beside it. **EV1's bar is now written from a completed baseline of 1/9** — a *ratchet plus a
   ceiling*, because a pass fraction cannot be invented out of one recovery in nine, and because
   the exhaustive stage's 30/30 and the fallback's 1/9 must never be reported as one capability.
   Step 3 (parameter inheritance) passes EV3 on both halves, and §3.3.1 is the part to read
   before touching any tier-1 fit: the warm polish was running at the **publication** local
   budget inside a *screen*, so two of ten polishes cost as much as the global search they
   replaced, and the gate first read +39% at 120 s and +7% at 600 s because of it. The same
   section records the other way a two-sided gate nearly went wrong — it was read as *failed* on
   a count of one event against zero, and the response to a bar that cannot resolve its own
   question is more seeds, never a reworded bar. §3.2.1's fourth bullet is the newest and the
   cheapest to re-learn the hard way: step 2's refit deadline had **no order behind it**, so the
   report walked past a candidate ranked *1 of 270* and published forty others. The quota says
   which candidates deserve a refit and says nothing about the sequence; a tier that can stop
   early needs both.

11. `docs/KK_RESONANCE_PLAN.md` — the Lin-KK test and the resonance its basis cannot express.
   **Implemented; gates K1–K4 measured.** Its §2 is the one to read, and it is the whole point
   of the document: the obvious fix was *built* and the measurement rejected it. Giving the
   basis complex poles keeps the solve linear and does fix the resonator, and it **destroys the
   test** — an uncounted 200-column resonant bank fits a 61-point spectrum drifting 1000% to
   0.00% residual with random residual signs, because 122 equations cannot constrain 223
   unknowns. So the bank is a *probe* asked only of spectra that already failed, budgeted at
   15% of 2N columns, able only to turn `fail` into `inconclusive` and never into a pass —
   which is what makes it safe to add to the check that protects every other result here.
   §5 says what is still not fixed and does not pretend otherwise: this test cannot validate a
   resonator, and a spectrum of pure noise still passes.

12. `docs/POOL_FROM_SPECTRUM_PLAN.md` — the default element pool, which used to be a decision
   about the part rather than about the data. **Implemented in the core and the CLI (`--pool
   auto`); gates C1–C5 measured; the browser is not wired.** Two of its sections are the ones to
   read. §3 is where the obvious detector — find a 45-degree branch, add the diffusion elements —
   was built and *rejected by its own measurement*: it separates a pure diffusion spectrum from a
   pure relaxation one completely and lands `R1-p(R2,CPE1)-Wo1` at 0.20–0.60 decades against a
   no-diffusion range of 0.00–0.50, so on the composite spectra that are the realistic case there
   is no threshold at all. §5 is the instrument that replaced it, and the trap it walked into
   first: a systematic residual means *either* the vocabulary is too small *or* the element limit
   is, the runs test cannot tell them apart, and the two remedies pull against each other because
   widening the pool costs a completeness level. At the production limit of five the ambiguity
   resolves — but so does most of the signal, because given five elements the default pool builds
   an eight-parameter CPE stack that reaches the noise floor in place of a three-parameter
   Warburg. **`W` is the one code with a measured reason never to add**: a CPE at `n = 0.5` *is* a
   semi-infinite Warburg, matching it to 1.3344% against 1.3344%. And §1's other half is why the
   whole exercise is not cosmetic: `Ws`, `Wo` and `G` are transmission lines that no finite tree
   of R, C, L and CPE reproduces, and the default pool's best answer for them is 4x to 17x the
   noise floor.

13. `docs/SEARCH_ALGORITHM_SURVEY.md` and `docs/SEARCH_ALGORITHM_SCREENING.md` — what could
   replace the topology search, and what a cheap round of measurement says about it. The survey
   is a map with no measurement in it; the screening round is the measurement, and **it
   contradicts the survey's own top recommendation**, so read them in that order and trust the
   second. Its method is the part to reuse: `evolve-gate` costs 2.5–3 h per arm because its
   budget is wall-clock and it fits as it goes, so the round screens every topology in the space
   *once* into a frozen table and then compares searches in **fits** rather than seconds
   (`benchmarks/screening_round/`). Four things it settled, all against expectations. **The
   criterion is not the problem** — the truth's class ranks 1–17 on every arena built. **The
   element cap is not the problem** — 6 against 7 changes nothing. **A compiled kernel cannot be
   the answer** — the impedance kernel is 36–47% of a screen's own time, so Amdahl caps C/C++/
   numba at 1.4–1.7x against a 13x gap. And what *is* the problem is CPE, in two ways at once:
   1.77 s against 0.87 s per fit, and a truth-class density falling 0.55% → 0.085% because the
   pool multiplies the space by 10 and the exact equivalents by 1.5. §4.2 is the section to read
   before trusting any A/B in this repo: **every arm ties on the 11,033-topology arena and they
   separate on the 21,057 one**, so a round that had stopped at the cheap arena would have
   reported "nothing beats the incumbent" and been wrong — the same shape as `screen` versus
   `screen-rank`. Three arms do beat it (120/120 against 87/120), and what they share is not
   their operators but that they **bound the set they breed from**.

Update these when decisions change.

## Stack and conventions

- Python >= 3.12, package name `autocircuit`, layout `src/autocircuit/`.
- Tooling: `pytest`, `ruff` (lint + format), `mypy` (strict on core modules). Install with
  `pip install -e .` (`uv` is not available on this machine).
- **`numpy` and `scipy` are the only runtime dependencies, and that is a hard rule** — it is
  what lets the same wheel run under Pyodide in the browser. The CLI therefore uses stdlib
  `argparse`, not `typer`/`click`. Do not add a runtime dependency without changing this file.
- No file-dialog/GUI/OS-specific code anywhere in `autocircuit.core`.
- All angular frequency internally: `omega = 2 * pi * f` in rad/s; data files store Hz.
- Impedance is `complex128` numpy arrays throughout; never split re/im into separate paths.
- Every circuit element implements the same interface (impedance function, parameter metadata
  with units/bounds/log-scale flag, SPICE synthesis hook).
- Tests: every element gets an analytic-value test; every fitter feature gets a synthetic-data
  round-trip test (generate from known circuit + noise, recover within tolerance).
