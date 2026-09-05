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
  readouts from a fitted circuit -- `autocircuit fit --objective interpret`, and
  `objective.interpretation` in the `--json` report. What it is built around is the split that matters: every quantity is marked
  **invariant** (the same for every topology in the equivalence class, because it is a property
  of `Z` -- terminal resistances, self-resonance, tan delta, and the poles and zeros of `Z(s)`)
  or **form-dependent** (a feature of the tree that was reported, such as a block's `R*C`).
  Gate I1 has both halves: the invariant quantities must agree across an exact
  reparameterisation, *and* the form-dependent ones must be seen to disagree, because a label
  nothing can falsify is not a label. The **discovery** report carries one on both front ends
  (`discover --objective interpret`, and the Report screen's panel), and it reads the recommendation's
  *whole equivalence class* rather than the recommendation alone -- [measured] the class agrees on the invariant quantities to
  2e-11 across independently fitted members, and disagrees about how many relaxations the part
  shows, which is exactly the reading a non-expert would otherwise take as a finding.
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
rendered report differs. Fingerprint it the way EV5 does. **Implemented and measured** on all
three references (`benchmarks/o1_objective.py`, `docs/OBJECTIVE_PLAN.md`), and it has two halves:
the byte comparison, and the *structural* one that actually holds the property — `discover()` and
`fit()` take no objective and neither module imports the reporting layer, so a value that cannot
reach the search cannot change it.

**Why the split exists at all is the equivalence classes, not the vocabulary.** `R1-p(R2,C1)` and
`p(R1,C1-R2)` fit the same data to 1.2e-15. Under `model` that is harmless — same terminal
behaviour, either one exports and simulates identically, and asking which is "right" has no
content. Under `interpret` it *is* the question: whether R2 is a grain boundary or an electrode
interface is exactly that difference in form, and the spectrum does not contain the answer. So
what the objective legitimately changes is **how loudly the report says the data cannot decide** —
loudest under `interpret`, where a non-expert is most likely to read a topology as a mechanism.

**Multi-condition (temperature- or bias-series) joint fitting is out of scope, by decision.**
An earlier draft of this file argued that several sweeps at different temperatures or bias
points, fitted to one circuit simultaneously with an Arrhenius law across conditions, is the
only instrument available here that can *break* an equivalence class (`R1-p(R2,C1)` versus
`p(R1,C1-R2)`), and stays inside the frequency-and-impedance rule because it only adds more
spectra. **That argument is withdrawn, not because it does not work — a full implementation was
built and measured to work (`docs/IMPACT_PLAN.md` §3, gates A1-A4 passing) — but on
reconsideration of where the boundary of this software sits.** A temperature or a bias point is
an experimental condition, not a property of `Z(f)`, and deciding *what physical law* the part's
parameters follow across those conditions (Arrhenius, as opposed to Vogel-Tammann-Fulcher, a
power law, or none) is squarely the analyst's own physics judgement to make outside this
software, not a narrowing this software should offer even as an opt-in candidate — unlike
`pool` and `skeleton`, which narrow *which circuit elements* may appear and leave every physical
interpretation of the fitted numbers to the analyst. This software's job stops at producing the
per-condition circuit and its parameters; relating those parameters across conditions is out of
scope the same way permittivity and geometry are. See `docs/IMPACT_PLAN.md` §3 for what was
built and why it was withdrawn rather than shipped or reworded.

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
   **Implemented, all six steps; gates EV1, EV2, EV3 and EV5 measured, and EV4 shipped with two
   of its three clauses recorded as failed rather than reworded.** The claim this fallback is now
   allowed to make is EV1's, and it is a ratchet with a ceiling: [measured] **5 of 9 truths
   reported and 3 of 9 recommended** on the three 6–7 element references, against a 1/9, 1/9, 0/9
   baseline — which must never be reported in the same breath as the exhaustive stage's 30/30,
   and which leaves one of the three references at 0/3. Its §1 is four measurements saying the
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
   early needs both. **§3.4.3 and §3.4.4 are step 4, and they are the clearest case in this repo
   of a saturated arena ranking nothing.** Step 4 bounded the set the search breeds from at
   `population` — a width nobody had measured, because it was the number already in the argument
   list — and then split it across islands. A ladder run down to zero says the answer is not a
   width at all: `pool_bound=0` and `pool_bound=1` are the *same arm on every seed*, since the
   best-scoring candidate cannot be dominated, so what ships is the Pareto front by itself
   (`BREEDING_EXTRA`, 65/120 against the old rule's 7/120 at an unsaturated budget). The islands
   were **built and then removed**: at the 900-fit budget the round had been using, all eleven
   arms score 120/120 and the islands appear to win — and at 150 fits they lose to a single pool
   of their own width. Two islands survived to 480 seeds before McNemar demoted them (p = 0.216).
   Three separate readings were withdrawn rather than softened, and the paired test that could
   not see a hit-rate difference at all was fixed rather than trusted. **§3.5 is step 5, and
   neither of its two knobs moved a default** — which is the result, not a failure to find one.
   Adaptive parsimony does nothing at any scaling short of the degenerate limit, and its best
   rung looked like 77/120 against 65/120 at p = 0.03 before 480 seeds made it p = 0.32: the same
   counts, control and p as the two-island arm §3.4.4 had already demoted. §3.5.2 is the one to
   read, because it is about the *instrument* rather than the knob. Every arena this round had
   built freezes the **same truth**, and the mutation sweep's strongest arm turned out to win by
   moving weight toward parallel insertion on a truth that is three parallel blocks — it loses by
   the same margin on a series-shaped truth, and the mirror arm reverses both signs. So the sweep's
   answer is that the insert-series and insert-parallel weights must stay **equal**, which the
   shipped tuple already was and nothing had checked; an asymmetric setting is the software
   deciding what kind of part this is from inside the search. A third arena — same truth, same
   data, element cap 6 → 7 — then separated the one remaining candidate (a lower delete weight)
   from the fact that both arenas' truths sat at the cap.

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
   auto`); gates C1–C5 measured; the browser is wired too (§8 of
   that document), with its report measured equal to the CLI's row for row.** Two of its sections are the ones to
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

14. `docs/OBJECTIVE_PLAN.md` — the objective axis, which says what the user wants out and is
   **orthogonal to the mode**. **Implemented in the core, the CLI (`--objective`,
   `autocircuit objectives`) and the browser (`discover_objective`, the Report screen's
   `ObjectivePanel`); gate O1 measured on all three references.** Its §2 is the part that
   matters: the invariant is held *by construction*, since
   `discover()` and `fit()` cannot receive an objective and neither imports the reporting layer
   — a byte comparison passing while the parameter existed would only say the two runs happened
   to agree on those spectra. §4.1 is where the obvious default was wrong (`--objective`
   defaulting to `model` makes "asked for model" and "asked for nothing" the same thing, so two
   contradictory flags were accepted silently), and §4.3 is the one place this layer could
   quietly over-claim — the `model` report's sentence that every equivalent topology agrees is
   licensed only by every readout being marked invariant, so a test asserts that rather than
   trusting the list. §4.5 is a bug the browser's strict-JSON wire had been hiding: a class that
   agrees on a *zero* was reporting infinite disagreement, and that one value made the whole
   response undeliverable rather than merely odd.

15. `docs/AUTOEIS_COMPARISON.md` — the first time this project ran a competing tool instead of
   citing one. **Run and stopped early; the plan beside it is `docs/AUTOEIS_COMPARISON_PLAN.md`.**
   The headline is that there is no headline: on five- and six-element truths at both tools'
   defaults, **neither recovered the circuit** — 2/7 with a truth-equivalent anywhere in this
   project's candidate list and **0/7 as its recommendation**, AutoEIS 0/7 on both, p = 0.50
   against `d` = 6. Four sections are worth the read and only one is about AutoEIS. §2.2 is the
   defect the round found *here*: `generations` is 0 on all forty runs, so **the genetic fallback
   never ran once** — its trigger is a runs test at `z < -3.0` and the measured residuals sit at
   −0.45 to +0.67, because a five-element answer reproduces these spectra to within what 1% noise
   hides. `EVOLVE_SEARCH_PLAN.md`'s 5/9 was never the limit; the trigger's sensitivity is. §1.5c
   is why the arena's small truths could not settle anything — 30 of 40 runs have the truth
   *inside* `complete_up_to`, so below six elements this project does not search for the truth, it
   enumerates it. §1.5d records the user's decision to score only five elements and up, with the
   objections that were put and overruled. And §2.1 records that the round was stopped after its
   result was seen, as a departure from its own stopping rule rather than as a machine-time stop.
   §0 stands on its own whatever happens to the comparison: AutoEIS's vocabulary is `R, C, L, P`
   with **no Warburg**, its default alphabet excludes the ideal capacitor and its filters delete
   any circuit keeping one, its default path **does not honour its seed** (measured, not read off
   the FIXME), its preprocessing **deletes 6–37% of a sweep before its search sees it**, and a
   clean `pip install autoeis` today produces a build whose last stage crashes on `arviz` 1.x.
   §0.3 carries two withdrawn readings, both the same error: a stall diagnosed from the process
   table that was not a stall.

16. `docs/TOPOLOGY_6PLUS_PLAN.md` — six elements and up, which is where the automatic path stops
   working. **Experiments run and recorded; the growth stage is implemented and shipped
   opt-in; X4, X6, X7, X2 and X3 are all complete (§5.9, §5.11, §5.10, §5.12). X3's measurement
   did not produce a trigger worth shipping — see §5.12.**
   Its §2 is the part to read first, because
   it is the reframing the rest depends on: "six elements does not work" is **four** independent
   problems — whether the spectrum distinguishes six elements from five at all (**information**),
   whether the class is reached (**search**), whether it is fitted well enough to *score*
   (**parameters**), and whether it is then recommended (**reporting**) — and fixing one alone
   changes nothing, which is exactly what happened to `EVOLVE_SEARCH_PLAN.md`. The round's five
   most useful measurements, in the order they change what you would otherwise do:
   **(a)** the tier-1 screen's verdict is a **basin lottery** for a minority of topologies and
   *budget does not fix it* — one circuit screens at 0.0141 or 33.78 on the seed alone, and 25x
   the population-generations product moves neither number, while a second draw takes the mean
   penalty across 360 sampled topologies from 37.7x to 1.06x; **(b)** on
   `LARGE_REFERENCES[2]` the **shipped publication budget reaches the truth's own optimum 2 times
   in 12** with the true topology given and noise-free data, and 20 restarts take it to 12/12 —
   so gate EV1's arena is measuring the fitter as much as the search; **(c)** all three
   `LARGE_REFERENCES` carry a parameter whose leverage is *below the noise*, while all three
   small references are clean, and `recommended` is built to reject exactly such a candidate;
   **(d)** the **feasibility filter assumes the measurement window reaches the model's
   asymptote**, and silently deletes a truth whose self-resonance sits at the edge of its own
   sweep — a gap in gate G3 rather than a contradiction of it; **(e)** the rational-approximation
   route (`scipy.interpolate.AAA`, a Loewner pencil, a stabilisation diagram) is **exact without
   noise and useless with it**, 0.04–0.20 exact-recovery at 1% noise, so no production code
   follows from it. What *was* built is a **growth stage**: above the exhaustive limit the search
   stops enumerating and grows — every one-element extension of the best `GROWTH_WIDTH`
   topologies of each completed level — reaching the six-element truth's equivalence class
   [measured] **three screening fits after the five-element enumeration ends**. It ships
   **off by default** (`GROWTH_DEFAULT = 0`, `--growth-width 4` to ask for it) because the search
   evidence is strong and the *report* evidence is not in yet, and because switching it on made
   the web tests alone run longer than the whole suite had. The rule that governs it is §4.7's:
   `complete_up_to` describes the enumeration and growth may never raise it, so `grown_to` is a
   separate field and the coverage line says "That is not a completeness claim" in words. Both
   front ends grow through one `growth_plan` generator; the browser's first version derived
   coverage from a list the growth stage appends to and therefore over-claimed completeness,
   which is the failure the whole §4.7 discipline exists to catch. **X4, run end to end on six
   shapes [measured, §5.9]: growth is not a uniform win.** It recovers `par6`, `mix6`, `par7` and
   `mix7` completely — 12/12 recommended — and it recovers neither `ser6` nor `ser7` (0/6), for a
   topology-shape reason (a near-degenerate extra reactive element, residual already inside the
   noise floor at five elements) rather than a budget one. That is why `GROWTH_DEFAULT` stays `0`
   rather than flipping on: doing so would silently promise a recovery that does not happen for
   series-shaped parts. **X7 [measured, §5.10]** used the same 54 runs to ask what parsimony costs
   when it declines a truth-equivalent that reached the front: only the two `ser6`/`grow` seeds
   qualify, and in both the declined candidate's AICc is 29–34 points better and every one of its
   parameters is resolved (`n_unresolved = 0`) — not the unresolved-extra-parameter case the
   `recommended` docstring describes, and not the "front's top two are indistinguishable" case
   axis R anticipated either. The actual reason is `PARSIMONY_CHI2_FACTOR = 2.0`: both candidates
   sit within that band of the best chi², so `recommended`'s `(complexity, aicc)` tie-break picks
   the simpler one regardless of the AICc gap, and the report's own printed sentence — "better
   numerically, but the extra elements are not supported by the data" next to "0 of them
   unresolved" in the same line — used to say the wrong reason out loud. **Fixed**
   (`docs/IMPACT_PLAN.md` item D1): `DiscoveryResult` now names the real reason
   (`unresolved`/`inside_band`/`outside_band`) and prints a sentence that matches it, with no
   number changed. The rate and size of the cost are what X7 asked for and both are answered.
   **X6 [measured, §5.11]** gave `_evolve` the `workers` parameter `_exhaustive` already had —
   `--workers` under `--mode evolve` silently did nothing before this. With `generations` set
   high enough that `time_limit` binds instead of the iteration cap, eight cores bought 39-48%
   more generations than one at *lower* wall clock on both `par6` and `ser6`, which is a real win
   and nowhere near an 8x one (roughly 5-6% scaling efficiency per core, likely because each
   generation dispatches two sequential batches — polish, then search — each well under
   `population = 40` once the cache-hit majority `EVOLVE_SEARCH_PLAN.md` §1.3 already measured is
   subtracted out). **It changed no recovery outcome**: `par6` was already reported, on the front
   and recommended at `workers=1` given enough generations, and `ser6` stayed off the front and
   unrecommended at `workers=8` despite 48% more generations and 413 distinct topologies fitted —
   the same reading §5.9 and §5.10 already gave that shape, that its obstacle is the residual
   already sitting inside the noise floor rather than search reach. So the asymmetry X6 measured
   (single-threaded evolve against six-way exhaustive) was real and worth fixing, and it was never
   the reason any six-element truth went unrecovered. **X2 [measured, §5.12], the identifiability
   ladder over all 6 truths × 12 (noise, points-per-decade) cells = 72 cells:** `par6`, `mix6`,
   `par7` and `mix7` never approach "not distinguishable" anywhere on the grid (worst cell 24.2x,
   an order of magnitude clear), while `ser6` and `ser7` sit at or near `gain≈1` across most of it
   and cross into "not distinguishable" at or near the project's standard 1%-noise/10-ppd cell
   (`ser6` 1.258x, `ser7` 1.012x) — **shape predicts the crossing far more than element count
   does**, and the seventh element made the series shape's crossing worse rather than better. This
   is why `GROWTH_DEFAULT` stays `0`: the search evidence (X4) and the identifiability evidence
   (X2) agree on which shape growth should not be trusted for. **X3 [measured, §5.12], the
   decision rule that would read this grid and fire only when the extra element is real, is
   complete — and it did not produce a trigger worth shipping.** Scored on a 108-row labelled set
   (X2's 72 real boundaries plus 36 more built the same way from three five-element negative
   controls) against four candidates — the current runs test, a nested F-test between the best
   smaller-size model and its own one-element extensions, a parametric bootstrap of that
   statistic, and X9's pole count read as a margin — **no candidate dominates the incumbent runs
   test on both recovery and false-positive rate**: the runs test is 52.78% recovery / 0.00% false
   positives, the F-test is 80.56% / 16.67%, the bootstrap (which calibrates the F-test's
   boundary-null problem correctly, landing within one event of its own 5% target) is 51.39% /
   5.56% — dominated by the plain runs test — and the pole-count margin is 11.11% / 22.22%,
   dominated on both axes and the fourth independent measurement in this repository finding
   pole-order estimation unreliable under noise. `_is_underfitted` is unchanged and
   `GROWTH_DEFAULT` stays `0` for the reason X4 already gave it, now doubled: no report-side check
   measured here is trustworthy enough to promise the user the sixth element is real, and the
   series shape X2 flagged is where every candidate agrees least — at the project's own standard
   cell, `ser7` is read "no" by all four.

17. `docs/SEARCH_TIME_PLAN.md` — where the topology search spends its time, and the levers on
   it. **§3.1 implemented and shipped, §3.2 measured and its fix rejected, §4.2 measured and
   its flag rejected, §4.1 measured and its own decision rule keeps it a lever rather than a
   default, §4.3 implemented and shipped, §3.3 implemented and shipped in half (the CPE kernel
   substitution ships, the buffer-reuse half measured inside the noise floor and does not), the
   rest is still plan only.** It is deliberately *not* about the 13x F2
   gap `SEARCH_ALGORITHM_SCREENING.md`
   measured: it collects the F1 and F3 levers the earlier rounds set aside — the per-topology
   setup that is 23–33% of a screen and mostly per-*dataset* work recomputed 2,976 times, a
   chunked `Pool.map` whose idle turned out to be 31.7%, the second screening seed whose
   recovery arm is coded and has never been run, and `_evolve`'s two-barrier dispatch behind
   X6's 5–6%-per-core scaling. Its §2 is the list of what is settled and must not be re-tried,
   §5 states the ceiling before anything is built (perhaps 1.5–2x on a screen, not 13x), and
   §6's gates are byte-identical fingerprints for the levers that change no number and
   reported-digit equality for the one that changes bits. **§3.1, the `FitContext` hoist, is
   done and its own gate is where the plan's a priori numbers met a real machine**: the
   byte-identity half held exactly (three references, `ev5_fingerprint.py` before/after,
   identical), but the two numeric targets did not survive contact — `profile_eval.py`'s setup
   bucket cannot move at all because that script calls `screen()` without a `FitContext` and so
   never exercises the hoisted path, and the wall-clock win measured 10.4% at `workers=1`
   against a 15% target and vanished into a 28–36 s run-to-run spread at `workers=8`, on a
   machine this repository already knew ran 2x slower loaded than rested. Both targets are
   revised down to what was measured rather than reworded to look met, and the change ships
   anyway because it is free when unused and a real win on the one path (`workers=1`) the
   browser actually takes. **§3.2 is the sharper lesson**: the idle was real (31.7%, confirmed
   by pid-tagged instrumentation of the dispatch), but the fix the plan itself proposed
   (`Pool.imap`, smaller chunksize) does not touch the actual cause — `Pool.map`'s own
   chunksize heuristic already rebalances *within* a batch, so the barrier is the batch
   *boundary*, and only a bigger batch (`WORKER_CHUNK` 64→256) moves the number (31.7%→13.4%
   idle, confirmed twice). That fix was implemented, and it **fails its own byte-identity
   requirement**: on the skin-effect reference, a bigger batch shares a stale `abandon_above`
   threshold across more candidates, and that measurably changes which candidate reaches the
   tier-2 shortlist on at least one CPE/SKINF pair — disproving `discover.py`'s own
   long-standing, never-tested comment that a stale threshold "can never change a result." The
   change was reverted rather than shipped on the strength of that comment. **§4.2, the
   sub-tree re-screen flag, is the third rejection and the one that also caught a stale
   benchmark**: its own decision rule was "ships only if it catches the majority of >100x
   mis-screens at a flag rate under 50%," and the 360-topology sample that rule was meant to
   run against turned out to be unreproducible with today's code at all — every one of its
   rows' seed-0 cost differs from a fresh `screen()` call by 0.1–0.5%, confirmed **not** caused
   by §3.1's hoist (`core/fit.py` checked out at the commit before it reproduces today's number
   exactly, not the sample's). The measurement was rebuilt fresh and self-consistently instead,
   covering every enumerated topology in the same three arenas (446/446/2171) rather than a
   120-row sample: the flag catches **100%** of the measured >100x mis-screens, and flags
   **70.6–78.7%** of everything, nowhere near "under 50%." No tolerance rescues it — the
   mis-screen rows' own violation ratios against their sub-topology (1.20x–8.17x) fully overlap
   the ordinary-noise rows' ratios (up to 5.8x–8.2x), because the flag compares one single-seed
   draw against another single-seed draw of a *different, smaller* topology, which is exactly as
   exposed to the same basin lottery as the parent it is trying to check. Nothing shipped.
   **§4.1 closes the loop §4.2 opened**: the recovery arm §5.7.2 had deferred (`seeds2` in
   `benchmarks/six_plus/recovery.py`, coded but never run) was finally run on the same nine
   truths and three seeds X4 used, and against the decision rule written before the run —
   "ships as the default only if it moves at least one truth from lost to reported, and
   removes none" — it moved **zero** of the eighteen large-truth recovery cells (0/18 both
   before and after, unchanged by shape). This is not a contradiction of §5.7.2's own basin
   ratio (37.7–41.4x at one seed, 1.06–1.16x at two): that measurement was about the sampled
   landscape's noise, and these nine truths' own screened landscapes were never shown to
   contain a mis-screen for a second seed to repair. `screen_restarts=2` stays an available
   lever, not the shipped default — the fourth item in this section to be measured and not
   ship, after §3.2 and §4.2's rejections and alongside §3.1's more qualified acceptance.
   **§4.3 is the fifth measurement in this section and the second to ship**: `_evolve`'s
   generation loop now proposes children until `population` distinct canonical forms are in
   hand (a duplicate previously spent a slot for nothing, `EVOLVE_SEARCH_PLAN.md` §1.3's 15/40 →
   22/40 cache-hit finding), and its two sequential `executor.map` calls (polish, then a full
   barrier, then search) are merged into one worker function per candidate, because the accept
   decision under `warm_accept = inf` needs only `best_cost` at that complexity — known
   before dispatch, not after. Both halves of gate T4 passed: frozen-landscape hit rate is
   unchanged at 480 seeds on two arenas (McNemar p = 0.63, p = 0.50), and real-fit throughput at
   300 s / `workers = 8` rose far past X6's own 380/413 baseline — `par6` to 1366, `ser6` to
   1095. One thing was measured and recorded rather than smoothed away: at `workers = 1`,
   `ser6`'s `reported` flag flipped `true` → `false` between baseline and post-change despite
   evaluating 2.6x more topologies, which is not part of T4's decision rule and is not a quality
   regression — `recommended` was `false` on that cell both before and after — but is exactly
   the same single-draw RNG sensitivity `TOPOLOGY_6PLUS_PLAN.md`'s basin-lottery finding already
   names for tier-1 screening, now seen once in the fallback's own stream. **§3.3 is the sixth
   measurement in this section and the one that shipped only half of itself.** Its two candidate
   levers were measured independently rather than together, because the plan's own bullets had
   already kept them apart: replacing `ConstantPhaseElement.impedance`'s `(1j*omega)**n` with
   `exp(n * log(1j*omega))`, and reusing the population buffers `to_values_batch`/
   `cost_vectorized` allocate fresh on every one of a screen's ~41 calls. Isolated,
   the CPE substitution cuts `cost_vectorized` 31-33% on CPE-bearing topologies and 0% on a
   non-CPE control — the exact causal fingerprint a real, CPE-specific win should leave — well
   past the quarter-reduction bar §3.3 sets. Buffer reuse alone measured 3-5% on *every*
   topology tried, including the non-CPE control, which is indistinguishable from this
   instrument's own noise floor (±5-8%, visible on that same control, which should show exactly
   0% for an inert change and does not) — it does not clear its own bar and was reverted rather
   than kept for a number the control case cannot tell apart from noise, especially since
   keeping it would also keep a new hazard: the buffer it returns is aliased across calls, so a
   caller retaining a reference past its own use silently reads a later population's values.
   T5's "reported digit" comparison had to be built rather than reused, because the raw
   `--json` payload is full `repr()` precision — the same precision `ev5_fingerprint.py`
   already fingerprints byte-exactly — so it was run instead against `DiscoveryResult.summary()`,
   the text a CLI user actually reads, on all three references: identical before and after
   except the wall-clock line, with the by-product that full exhaustive discovery wall-clock
   fell 18.7-31.7% across all three. The byte fingerprint does differ, as the plan predicted,
   and one difference is worth its own line: on the Randles reference, an exactly-tied
   exact-reparameterisation pair (`p(R1-CPE1,R2)-CPE2` / `p(R1,CPE1)-R2-CPE2`, same score to
   every digit) swapped which member the restart search lands on, R1/R2 fully exchanged rather
   than perturbed — both still reported, still each other's listed equivalent, unchanged in
   `.summary()` — the same basin-lottery family §4.3 already names for the evolve fallback's
   RNG stream, seen here for the first time at the ULP level of one kernel's own arithmetic.
   **§3.4's cheap count is the section's seventh and last measurement, and it closed the order
   of work in the direction the section's own bound did not expect.** Clustering all five
   existing frozen landscape tables by screened cost at the same `1e-6` relative tolerance
   tier 2's own equivalence check uses gives **4.4-5.9x multiplicity over whole tables**, and
   restricting to same-size topologies only — the closer match to the section's own
   `R1-p(R2,C1)` / `p(R1,C1-R2)` example — **3.8-4.9x at each table's largest, most expensive
   size class**, both well past the "under ~1.3x" bound the section said would close the
   question as bounded-small. It closes anyway, because the two reasons already on record for
   not building a dedupe (no cheap predictive test runnable *before* fitting; tier 2 refits
   every equivalence-class member regardless of what tier 1 skipped) do not depend on the size
   of the number — so this is recorded as a larger-than-hoped, still-unbuilt opportunity rather
   than a lever this plan ships. Part of the all-sizes number is a distinct, honestly-separated
   phenomenon and not the section's own example: an over-parameterised superset topology whose
   extra element gets fitted to irrelevance lands on exactly its subset's cost, which the
   same-size breakdown shows is not the whole story — genuine same-size duplication is large on
   its own. All seven steps of section 7's order of work are done.

18. `docs/DISCOVER_UX_PLAN.md` — usability fixes on the Discover path, from two rounds of user
   review of the CLI and web front ends. **Implemented, items A-G; verified by `npm run check`,
   `npm run smoke`, `tests/test_cli.py`, `tests/test_discover.py` and the full `pytest` suite (no
   quantitative gate — these are usability fixes, not a search property to measure).** The CLI's
   `--workers` now defaults to `cpu_count - 1` on the desktop path (`main.py`'s argparse default
   only); the library's own `workers: int = 1` defaults are unchanged, so the Pyodide-safety
   contract `_worker_pool` documents still holds for anything importing `autocircuit.core.discover`
   directly. The Data screen's Example Data panel now collapses each manifest group into a
   `<details>`, open only for the first group, with a count in every closed heading. The Discover
   screen's Pool control is now Auto/Custom only; the named presets (`"component"`,
   `"electrochemical"`) moved into the custom panel as quick-fill buttons that replace the checkbox
   selection rather than a dropdown entry sitting next to `auto` — which is the point, since a named
   pool is the same "what kind of part is this" assertion this project otherwise only allows as an
   opt-in narrowing — and the checkboxes now show the same `SymbolPreview` the Fit screen's
   `ElementPalette.tsx` already draws. And the Discover -> Fit hand-off now auto-runs the fit once
   on arrival, via a one-shot `autoFitToken` counter bumped only by `App.fitCircuit`; the fitted
   *values* still do not travel (`SCREEN_STATE_PLAN.md` section 3, unchanged) — only a request to
   refit does, so the Fit screen still computes its own number rather than displaying the search's.
   **A second review (§ "second review round") raised five more points, and investigating them
   before writing code changed the answer for three of the five.** Loading an Example dataset now
   holds "Loaded ✓" on the clicked button for 2 s and auto-scrolls the loaded-spectra table into
   view — [browser, Playwright] confirmed the group-collapse above was already live, so the actual
   defect was that a successful, correctly-working click produced zero visible change in the
   viewport, not that the panel was showing too much. The Discover screen's Workers control is now
   tucked inside a collapsed "Advanced" `<details>` rather than sitting beside controls that change
   the search's answer — its auto-fill from `navigator.hardwareConcurrency` (`defaultPoolSize()`)
   was already shipped, so only its visual prominence needed fixing. The CLI's `--progress` output
   now announces, once each, the two points a search escalates beyond a plain exhaustive run —
   pool-widening and the genetic fallback — via a new `discover(..., on_stage=...)` parameter that,
   like `on_progress`, is reporting-layer-only and changes no number the search returns; **this
   request did not apply to the browser**, which the code and the smoke test already assert never
   runs the genetic fallback at all (`SearchPanel.tsx`, `smoke.mjs`). The other two points were
   investigated and left alone: the switch to the genetic fallback is already pool-size-sensitive
   as an emergent property of the exhaustive stage's `max_candidates` enumeration ceiling rather
   than a raw element-count threshold, but turning that into a deliberately calibrated two-axis
   rule is an `EVOLVE_SEARCH_PLAN.md`-scale benchmark project and was not attempted; and the
   startup library-loading concern is two already-closed questions —
   `STARTUP_AND_EDITING_PLAN.md` §3's staging and `METRICS_AND_UX_PLAN.md` §1.5's rejected
   prefetch — plus a scipy replacement, which is a different scale of project than anything else
   in this document and was not attempted without being asked for specifically.

19. `docs/CRITERION_SELECTION_PLAN.md` — whether `DEFAULT_CRITERION` (`stats.py:39`) was the
   right default against BIC, CAIC, HQC or AICc, which no document had measured before this.
   **Implemented and measured; `DEFAULT_CRITERION` moved `"aic"` → `"bic"` on 2026-09-04.** Its
   scoping argument is the part worth not re-deriving even now the answer is in:
   `DiscoveryResult.recommended` is built to ignore `criterion` entirely by design
   (`discover.py`, chi2-band parsimony plus an always-AICc tie-break), so the open question was
   narrower than "which criterion is right" — whether the *screening-stage* ranking `criterion`
   does control (`_quota_by_size`/`_screening_score`) ever changes which topologies survive to be
   `recommended`-eligible at all (element count and parameter count diverge once CPE is in the
   pool), and how often the separately reported `by_criterion` value disagrees with `recommended`
   or overfits a small truth. **[measured] It does not change eligibility**: AIC and BIC agreed on
   both `recovered` and `recommended_correct` on all 37 matched cells with zero mismatches
   (`benchmarks/discovery_v2.py`'s `REFERENCES`/`LARGE_REFERENCES`, `benchmarks/six_plus`'s nine
   truths — full grid for two, the project's standard 1%-noise/10-ppd cell for the rest, a
   deliberately scoped-down slice of the plan's full prescribed grid; see that plan's §9 for
   exactly what ran), and all six scored criteria tied truth-by-truth on the nine-truth
   standard-cell check. What moved the default is the fallback axis the plan's own decision rule
   falls back to when eligibility ties: `by_criterion`, the secondary "what the criterion alone
   would pick" line, named something larger than a five-element truth in 15 of 19 negative-control
   cells under AIC and 0 of 19 under BIC — a gap that replicated independently across three
   separate slices of the data, not an artefact of one truth. See that plan's §9-10 for the full
   numbers and exactly what shipped (`stats.py`, a `tests/test_web_light.py` assertion, the
   Discover screen's placeholder default, `METRICS_AND_UX_PLAN.md` §2.6, `README.md`).

20. `docs/IMPACT_PLAN.md` — what would move the project most with effort disregarded, ranked
   against the three purpose points. Five items in order of effect, **D1 and B implemented, A
   built and then withdrawn, the rest still plan only.** **A** multi-condition joint fitting (a
   temperature or bias series fitted to one circuit with a per-parameter-class
   Arrhenius/shared/free law chosen by BIC) was fully implemented and its gates A1-A4 measured
   passing (`core/multicondition.py`, since removed) before being **withdrawn on a scope
   decision, not a technical failure**: relating parameters across experimental conditions via a
   named physical law is the analyst's own physics judgement, not something even an opt-in
   candidate this software offers should decide — see the "Objectives" section above and
   `docs/IMPACT_PLAN.md` §3 for the full reasoning and what was measured before the withdrawal.
   **B** — `weighting="auto"` (`core/noise.py`), a noise scale σ(f) estimated from
   the spectrum itself so `--weighting` stops being a knob the target user cannot set. **Shipped
   as an explicit opt-in only, on no path a default**: gate N1 passes (a GCV-selected local
   quadratic recovers the injected noise to within 0.6–1.1x on all three `REFERENCES`), N4
   passes (a resonance-bearing fit still lands on the truth despite σ being badly over-estimated
   near the pole — the safe failure direction), but a 1-seed slice of gate N2 found the
   recommended candidate changing on two of three references, which is the plan's own
   two-regression bar for "stays a lever, not a default." §2.2 is the part worth reading before
   touching `core/noise.py`'s constants: the estimator went through three designs in one
   session, each replaced only after being measured wrong — a fixed-fraction window tuned until
   the Maxwell-Wagner reference passed (withdrawn as a constant fitted to the test, not a
   mechanism), then a per-spectrum leave-one-out cross-validated window (measured to
   under-smooth the capacitor reference by about half, a documented property of plain LOOCV
   bandwidth selection), then the shipped design: the same cross-validation with the
   generalised (GCV) degrees-of-freedom correction `autocircuit.core.drt` already uses for its
   own regularisation strength, which closed the capacitor gap without disturbing the other two
   references; **C** a measured-data arena, because the repository contains no real spectrum and
   every gate to date is on data generated from the vocabulary being searched; **D** — D1 (the
   `recommended()` sentence naming `unresolved`/`inside_band`/`outside_band` instead of always
   the first) is done; D2 (the genetic fallback running on the user's time budget instead of a
   trigger measured twice not to fire) is not. **E** profile/bootstrap intervals for the three
   quantities the report decides on, not started. §5 lists what was considered and left out with
   the measured reason beside each, §8 gives the order D1 → B → (A, withdrawn) → C → E → D2, and
   §3 records the reversal of an earlier survey correction that had called activation energies
   in scope on geometry grounds alone — true as far as it went, but superseded by the scope
   decision above that relating parameters *across conditions* is not this software's job
   regardless of whether the resulting number needs a geometry.

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
