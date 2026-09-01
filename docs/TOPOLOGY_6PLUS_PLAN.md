# Six elements and up — the plan for the part of discovery that does not work

**Status: experiments run, X4 (§5.9), X7 (§5.10), X6 (§5.11), X2 and X3 (both §5.12) complete; the
growth stage of §6 is implemented and ships opt-in.** X3's measurement did not produce a trigger to
ship: no candidate dominates the incumbent runs test on both recovery and false-positive rate, so
`GROWTH_DEFAULT` stays `0` and `_is_underfitted` is unchanged. Claims marked
**[measured]** carry a number from a script under `benchmarks/`; everything else is a hypothesis
and is labelled as one. Read `docs/EVOLVE_SEARCH_PLAN.md` and
`docs/SEARCH_ALGORITHM_SCREENING.md` first; this document takes their measurements as given and
does not repeat them.

## 0. The question, and why the current answer is not one

`CLAUDE.md`'s point 1 is that the data chooses the topology *and* the values. That holds up to
five elements and stops there:

| truth size | how it is searched | measured recovery |
|---|---|---|
| ≤ 5 | exhaustive enumeration, two-tier fit | **30/30** (gate G1) |
| 6–7 | genetic fallback, called directly, 600 s | **5/9 reported, 3/9 recommended** (gate EV1) |
| 6 | genetic fallback as `discover.py` actually calls it | **1/6 reported, 0/6 recommended** (commit `1db16a2`) |
| 5–6 | `mode="auto"` at defaults — what a user gets | **2/7 reported, 0/7 recommended** (Arena C) |

The bottom row is the product. The gap between it and the top row is not a matter of degree, and
this document exists to find out what it is made of before writing a line of production code.

## 1. What is already measured, and what it forbids

Re-confirmations, each cited. No design below may contradict one without re-running its benchmark.

1. **The exhaustive stage is the reliable half and it ends at five.** 30/30 against the
   fallback's 5/9. The two must never be quoted as one capability (`EVOLVE_SEARCH_PLAN.md` §1).
2. **The fallback is never called at defaults.** `generations` is 0 on all forty Arena C runs.
   Its trigger `_is_underfitted` is a runs test at `z < -3.0`; the measured residual z on the
   six-element truths is −0.45 and +0.67 (`AUTOEIS_COMPARISON.md` §2.2). The trigger asks *"does
   the best model leave structure?"* and at 1% noise a five-element model leaves none.
3. **Calling it anyway does not rescue the round.** `evolve-min6` — `discover.py`'s own fallback
   call, argument for argument — scored 0/6 recommended. The single recovery in twelve runs was
   found at generation 13, ranked 2 of 59, put on the front, and **not recommended**: parsimony
   took an 8-parameter five-element circuit over the 9-parameter truth at ΔAIC 0.86, 1.4639%
   against 1.4768% at a 1% noise floor (commit `1db16a2`).
4. **Bounding the set the search breeds from is the only search change that has ever measured a
   win** — 120/120 against 87/120 — and a compiled kernel cannot be the answer, because the
   impedance kernel is 36–47% of a screen and Amdahl caps it at 1.4–1.7× against a 13× gap
   (`SEARCH_ALGORITHM_SCREENING.md` §4.2, §4.4).
5. **Every frozen arena in this repo carries the same truth.** `SEARCH_ALGORITHM_SCREENING.md`
   §3.5.2: a mutation sweep's strongest arm was winning by moving weight toward parallel
   insertion *on a truth that is three parallel blocks*, and lost by the same margin on a
   series-shaped one. Any result here that rests on one truth is worth nothing.

## 2. The diagnosis: four failures, not one

"Six elements does not work" decomposes into four independent problems, and fixing any one
alone changes nothing — which is exactly what happened to the round that fixed the search
(`EVOLVE_SEARCH_PLAN.md`) and did not move the user-visible number.

- **(I) Information.** Does the spectrum distinguish six elements from five *at all*? Item 3 says
  that on one measured instance it does not. Where it does not, **no search should report the
  truth**, and the deliverable is a report that says so.
- **(S) Search.** Where the data can tell, does the search reach the truth's class? Measured at
  87–120/120 in a frozen arena — against one truth (item 5).
- **(P) Parameters.** Having reached the class, is it *fitted well enough to score*? §5.1 and
  §5.6 are new, and the answer is "usually yes, and on one of the three references this project
  gates on, twice in twelve".
- **(R) Reporting.** Having scored it, does the report recommend it? Item 3 says no, and the rule
  that rejected it is the parsimony rule working correctly.

**An experiment that cannot say which axis it is measuring is not run.**

## 3. What the literature says, and what it leaves open

Surveyed 2026-08-30 (two surveys, `benchmarks/lit/` records the citations). Three findings
change the plan; two gaps are worth claiming.

### 3.1 The identifiability ceiling is established, external, and quantitative

- **Berthier, Diard & Michel, *Electrochim. Acta* 2001** define **two-terminal
  non-distinguishable (TTND)** circuits — distinct topologies with identical impedance at every
  frequency — and give 12 explicit transformation formulae among four TTND topologies for the
  two-CPE/two-resistor case. This is the published form of what this project calls an exact
  reparameterisation, and it says the equivalence classes are a property of the physics, not of
  our search.
- **Schaeffer et al., *J. Electrochem. Soc.* 170:060512 (2023)** — the BatteryDEV/QuantumScape
  benchmark, ~9,300 labelled synthetic spectra over 9 circuit classes. Weighted F1: Random
  Forest 0.38, XGBoost+tsfresh 0.50, **CNN 0.32**. Their own stated failure: the classifiers
  "struggled consistently to distinguish L-R-RCPE, L-R-2RCPE and L-R-3RCPE" — i.e. **machine
  learning on nine thousand spectra cannot count the relaxation blocks either**, and the authors
  attribute it to label identifiability rather than to model weakness. This is independent,
  external corroboration of axis I, and it is the reason axis I is placed first here rather than
  treated as an excuse.
- **Danzer et al., *Energies* 10:90 (2017)** — structural identifiability of 12 battery ECM
  templates; assigning physical meaning to the two resistors of a plain 2-RC network is *not
  possible* without information outside Z(f).

### 3.2 DRT is not the shortcut, and the newest measurement says so louder than ours did

**Orazem & Ulgut, *J. Electrochem. Soc.* (2025)**: a synthetic **two**-time-constant spectrum
decomposed at regularisation width FWHM = 0.3 shows **six easily observable peaks**; at 0.15 it
shows two. And nested, Maxwell and series topologies with *identical* impedance yield
substantially different DRT time constants. `DISCOVERY_V2_PLAN.md` §3.4 already refused to wire
DRT into the search; this is the same conclusion from outside, with a number. **DRT stays out of
the search**, and any use of it here is as a seed generator only, never as a filter.

### 3.3 The rational-approximation route exists, ships in scipy, and has not been tried here

This is the one genuinely new option the surveys turned up.

- **`scipy.interpolate.AAA` has shipped since scipy 1.15 (Jan 2025)** — the AAA algorithm of
  Nakatsukasa, Sète & Trefethen (*SIAM J. Sci. Comput.* 40:A1494, 2018). Barycentric rational
  approximation, **no initial values, order chosen greedily against a tolerance**, with
  `.poles()` and `.residues()`. This machine has scipy 1.17.1 and the browser's Pyodide build
  must be checked (§6 gate). **Zero new runtime dependencies**, so it is admissible under the
  numpy/scipy-only rule.
- **The Loewner framework has already been applied to EIS** — Patel, Sorrentino &
  Vidakovic-Koch, *iScience* 28:111987 (2025), and Sorrentino, Gosea, Patel, Antoulas &
  Vidakovic-Koch, *J. Power Sources* 585:233575 (2023). Build the Loewner and shifted-Loewner
  pencils from the samples, **take the model order from the SVD rank of the pencil**,
  eigendecompose for poles, solve for residues, and read the result as a discrete
  Z = Σ Rᵢ/(1+jωτᵢ) — a Voigt/Foster form. It is a few dozen lines of numpy; **no Python package
  exists**. Their honest limit is the same as ours: it produces a pole-residue decomposition, not
  a topology, and two of their four test circuits stay "nearly impossible" to distinguish.
- **Foster's form is read straight off a pole-residue expansion**, and Cauer's off a continued
  fraction. So a rational fit hands over a realisable network for free — but **only a
  terminal-equivalent one**. The synthesis literature is unambiguous that Foster/Cauer/Brune/
  Bott-Duffin produce *some* network with the prescribed Z(s), chosen for algebraic convenience,
  with no claim to physical meaning; and Hughes (*IEEE TAC* 2017) shows RLC realisations can need
  **more than twice** the reactive elements the McMillan degree suggests, with minimality still
  open. **This maps exactly onto this project's objective split**: synthesis is a legitimate fast
  path for `model`, and is actively misleading for `interpret`.
- **Positive-realness is a hard precondition, not polish.** A rational fit to noisy data can be
  an excellent numerical approximation of Z(f) and realisable by *no* finite passive network
  (Brune 1931). Synthesis then fails or returns a negative element.

### 3.4 Two gaps worth claiming

Both surveys, independently, failed to find these — which makes them contributions rather than
homework:

1. **No published curve relates noise level to the number of distinguishable relaxations.** Only
   qualitative statements, plus Orazem & Ulgut's negative result on DRT. **X2 below is that
   curve.**
2. **No published recovery-rate-versus-truth-complexity measurement exists above ~5 elements.**
   The AutoEIS paper's own case studies never exceed three Randles blocks and have no ground
   truth to score against. This project's `AUTOEIS_COMPARISON.md` appears to be the only
   controlled measurement of the kind anywhere. **X4 extends it.**

And one thing not to claim: **AAA and classical Vector Fitting appear never to have been
published against EIS data at all** — only the Loewner framework has. That is an opening, and it
is also a warning: if it were easy someone would have done it, so X9 is scored against a
pre-registered bar like everything else.

## 4. The experiment programme

Pre-registered. Each names its question, its instrument, and the decision it feeds. Results in
§5, including the ones that kill the hypothesis that motivated them.

### 4.1 Instruments, all of which already exist

Building a fourth harness would be the mistake. Three exist and each fits one axis.

- **`benchmarks/screening_round/`** — the frozen landscape: every topology in a space screened
  once into a table, so searches are compared in **fits** rather than seconds and the comparison
  does not drift with machine load. `arms.py` holds 40+ arms, McNemar and a sign test. **Axis S.**
- **`benchmarks/autoeis_round/`** — the sampled arena, the three-part identifiability screen
  (`parameter_leverage`), and the `Referee` deciding truth-equivalence by canonical form *or*
  response after an independent refit. **Axes I and R.**
- **`benchmarks/discovery_v2.py evolve-gate`** — end to end on the three `LARGE_REFERENCES`.
  Wall-clock, so it is the last check and never the comparison. **All axes.**

### 4.2 Axis P — the ceiling under everything else

**X8 — with the true topology given and no search at all, does the fitter find the parameters?**
Noise-free data makes this decidable rather than a judgement call: the truth's own values give
cost zero by construction, so "did it get there" has an exact answer. Sweep `restarts`,
`popsize`, `maxiter` against element count. **Run; see §5.1.** *Decision:* if the fitter misses,
every ranking above five elements is ranking under-converged fits and axis-S work is premature.

### 4.3 Axis I — when does a spectrum support a sixth element?

**X1 — the five-element ceiling, read off arenas that already exist.** How much better is the
truth's class than the best five-element circuit? **Run; see §5.2.**

**X2 — the identifiability ladder.** Over (noise) × (points per decade) × (truth), where does a
six-element truth stop being distinguishable from every five-element circuit? Grid, fixed now:
noise ∈ {0.1%, 0.3%, 1%, 3%}, points/decade ∈ {5, 10, 20}, six truths (§4.6). *Decision:* this is
the **domain of applicability** the report must state, and §3.4 says no such curve is published.

**X9 — rational-approximation order estimation as an element-count oracle.** Does the number of
*stable* poles of a rational fit to Z(f) predict how many relaxations the data supports? Three
estimators, all numpy/scipy: (a) `scipy.interpolate.AAA` pole count after clean-up; (b) the SVD
rank of a hand-rolled Loewner pencil (§3.3); (c) a **stabilisation diagram** — fit at orders
1..N and keep only poles whose (τ, weight) stay put as N grows, which is the one criterion in
§3.3 that needs no noise estimate from the user. Scored against known truths over X2's grid.
*Decision:* a winner becomes the growth stopping rule and the search's element budget, replacing
a trigger that measures the wrong quantity (item 2).

**X3 — a decision rule that fires when, and only when, the sixth element is real.** Candidates on
one labelled set: (a) the current runs test — the control, which item 2 says reads ≈0 exactly
when it should fire; (b) an F-test between the best five-element fit and its own one-element
extensions, which are **nested by construction** (an inserted element reduces to its parent at a
boundary of its own range) — the one place in this project where the F-test's nesting assumption
is licensed, and the boundary makes its null non-standard, so (c) a **parametric bootstrap** of
that statistic: resimulate from the fitted smaller model at the estimated noise, refit both, and
read the null off the resimulations rather than off a table; (d) X9's pole count. *Metric:* ROC
over X2's grid, reported as a **pair** — recovery rate and the false-positive rate on
five-element truths (§5.4/§4.5). *Decision:* the winner replaces `_is_underfitted`, or nothing
does and the trigger is **removed** rather than left in place looking like a check.

### 4.4 Axis S — reaching the class

**X4 — beam growth against the incumbent, on more than one truth.** `arm_beam` already exists and
is the strongest unadvanced number in the screening round: **[measured,
`SEARCH_ALGORITHM_SCREENING.md` §4.2] width 4 reaches the truth's class in 86 fits on the small
arena and 220 on the large one, deterministically**, against 256–451 fits for the three GA arms
that beat the incumbent. It was held back for a stated reason — "one run per arena is not a pass
fraction" — and that reason is about the arena, not the arm: a deterministic search cannot be
averaged over seeds, so it must be averaged over **truths**, which is item 5 seen from the other
side. *Instrument:* six new frozen landscapes (§4.6), `arms.py` unchanged, two budgets (§4.5).

**X5 — seed the beam from the complete five-element level.** Untried in any form. `arm_beam`
grows from level 1; the production pipeline has already enumerated level 5 *completely* and
throws that ranking away. *Decision:* if seeding wins, the production search above five elements
is "exhaustive to 5, then grow" — the only design here that can still make a completeness
statement above five, a conditional one (§4.7).

**X6 — the parallelism the fallback does not have.** [measured, commit `1db16a2`] `_evolve` takes
no `workers` where `_exhaustive` does, so every evolve measurement in this repo ran
single-threaded: 194–798 core-seconds against the control's six-way run. And all twelve runs
stopped at `generations = 30`, the library default, having spent 156–818 s of a 600 s allowance —
**the generation cap ended every run and the clock never did.** *Decision:* a correction to every
wall-clock comparison here, whichever way it goes.

### 4.5 Axis R — the report

**X7 — what parsimony costs at six elements.** Over X4's arenas, how often is the truth's class
found and on the front but not recommended, and what is ΔAIC when that happens? Item 3's single
event is not a rate. *Decision:* if the rate is high, the honest fix is on the reporting side —
**say that the front's top two are not distinguishable** — rather than tilting `recommended`
toward larger models, which would trade a measured failure for an unmeasured one.

### 4.6 The truths, and why six of them

Item 5 is the reason. Pre-registered, fixed before any arm runs, three shapes × two sizes, each
drawn to pass `arena.py`'s three-part identifiability screen at the noise it will be used at. A
truth whose parameters the data does not contain measures the screen, not the search.

| id | shape | elements |
|---|---|---|
| `par6` | three parallel blocks in series (the incumbent arena's truth) | 6 |
| `ser6` | series-dominant | 6 |
| `mix6` | nested / mixed | 6 |
| `par7` | parallel-dominant | 7 |
| `ser7` | series-dominant | 7 |
| `mix7` | nested / mixed | 7 |

Plus, for §4.7's negative control, **three five-element truths** of the same three shapes.

### 4.7 Verification — the part that is harder than the search

- **A hit is truth-*equivalence*, never a string match.** Reused unchanged from `score.py`:
  canonical form, or a response agreeing to `EQUIVALENCE_RTOL` after an independent refit.
  `R1-p(R2,C1)` and `p(R1,C1-R2)` fit the same data to 1.2e-15 and both are right.
- **Three readings, never pooled**: `reported`, `on_front`, `recommended`. Axis S owns the first
  two, axis R the third; pooling them cannot say which axis moved.
- **The negative control, which nothing here has yet had.** Every recovery rate is reported
  beside a **false-positive rate** on five-element truths: how often does the method report six
  elements when five generated the data? A method that always grows scores perfectly on recovery
  and is worthless, and no measurement in this repo would currently catch it.
- **What a growth-based search may claim.** A beam above five elements is **not** complete at
  six and the report must not imply it is. The sentence it licenses is narrower and still worth
  having: *"every topology up to five elements was evaluated; above five, every one-element
  extension of the best W of them."* Same obligation `PARTIAL_TOPOLOGY_PLAN.md` §3 places on a
  skeleton, met the same way — in the coverage line, not a footnote.
- **Two budgets, always.** [measured, `SEARCH_ALGORITHM_SCREENING.md` §4.2] a budget every arm
  clears ranks nothing: at 900 fits all eleven arms scored 120/120 and the islands appeared to
  win; at 150 they lost. One of the two budgets must be low enough that the incumbent misses.
- **Pre-registration.** Seed counts and stopping rules fixed before the first run; a round
  stopped early says so as a departure (`AUTOEIS_COMPARISON.md` §2.1).

## 5. Results

### 5.1 X8 (pilot) — a nine-parameter fit the shipped budget does not reliably reach [measured]

`benchmarks/six_plus/oracle.py` (pilot: scratchpad, folded into the benchmark in step 1). True
topology given, no search, noise-free data, so the optimum is exactly zero.

Reference `R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)` — 7 elements, 9 parameters, 71 points, **noise = 0**:

| restarts | popsize | maxiter | relative error | seconds |
|---:|---:|---:|---|---:|
| — | truth's own values, local polish only | | **1.7e-14 %** | — |
| **5** | **20** | **400** | **0.228 %** | 3.6 |
| 20 | 20 | 400 | 0.228 % | 14.8 |
| 50 | 20 | 400 | **0.0 %** | 40.1 |
| 5 | 40 | 400 | 2.081 % | 8.6 |
| 20 | 40 | 800 | **0.0 %** | 37.8 |
| 5 | 60 | 1500 | **0.0 %** | 32.1 |

> **Read §5.6 with this.** This table is one fitter seed per cell, which cannot separate a
> budget that is too small from a basin a draw sometimes misses. The twelve-seed rerun says the
> mechanism is the second — and that on *this* case the shipped publication budget converges
> **2 times in 12**, so the reading above is right about this reference and does not generalise
> to the other seven. The three consequences below stand, with the second amended: raising
> `restarts` is not merely "not reliably the fix", it is the *only* thing measured to work here
> (20 restarts → 12/12), while four times the population-generations product changes nothing.

**The shipped default (`restarts=5, popsize=20`) misses the global optimum of a nine-parameter
fit to its own noise-free data**, and reaching it costs about 10× the time. HANDOFF §3 records
`restarts=5, popsize=20` as "the measured optimum (0/25 failures)" — that measurement was taken
at ≤ 5 elements. Three consequences, in order of how much they hurt:

1. **0.228% is invisible.** Under 1% noise that fit looks perfect. Nothing in the report would
   say the number is wrong — only that the topology scored worse than it should have.
2. **Raising `restarts` alone is not reliably the fix.** 20 restarts landed in the *same* basin
   as 5. What separated the successes was total global-stage work (`popsize × maxiter`), not the
   restart count, and the cheapest success here was `popsize=60, maxiter=1500` at one restart per
   five.
3. **The tier-1 screen is far below all of these** (`popsize=8, maxiter=40, restarts=1`). If a
   *publication* budget misses, the screen that decides the shortlist is ranking seven-element
   topologies on noise. This is a candidate explanation for the whole 6+ failure that costs
   nothing to test, and it is tested in step 1 rather than assumed.

Also measured, same run: **the six-element references do not show this.** `p(R1,C1)-p(R2,C2)-p(R3,C3)`
(6 params) and `C1-R1-L1-SKINF1-p(R2,CPE1)` (8 params) both reach relative error 0.0% at the
default budget on noise-free data, and ~1.25–1.50% at 1% noise, which is the noise floor. So this
is a defect that appears **between six and seven elements**, or between eight and nine parameters
— which of the two is a step-1 question, and the answer changes what the fix is indexed on.

A method note recorded rather than buried: the pilot's first parameter-deviation metric compared
recovered to generating parameters **by name**, and read 2400% deviation on a perfect fit of
`p(R1,C1)-p(R2,C2)-p(R3,C3)`. Three interchangeable parallel blocks are a permutation symmetry,
so only a value-matched comparison means anything — `benchmarks/autoeis_round/deviation.py`
already does this and the benchmark uses it.

### 5.2 X1 — whether the sixth element is visible at all depends on the pool, not just the noise [measured]

Read off the frozen landscapes that already exist (`benchmarks/screening_round/land_*.json`),
which hold one screening cost per topology against a 1%-noise reference. Best cost at each size:

| arena | pool | best at 4 | best at 5 | best at 6 | 5→6 gain |
|---|---|---:|---:|---:|---:|
| `land_rcl6` | R,C,L | 0.04540 | 0.04534 | **0.01656** | **2.74×** |
| `land_rclcpe6` | R,C,L,**CPE** | 0.03448 | 0.02084 | **0.01620** | **1.29×** |

Same truth (`p(R1,C1)-p(R2,C2)-p(R3,C3)`), same data, same noise. **Adding CPE to the pool cuts
the evidence for the sixth element from 2.74× to 1.29×**, because a five-element circuit with two
CPEs has seven parameters and buys most of the residual back. `SEARCH_ALGORITHM_SCREENING.md`
already records CPE costing 2× per fit and 6.5× in class density; this is a third cost, and it is
on axis I rather than axis S: **widening the pool does not merely make the search harder, it
makes the truth less distinguishable.**

For contrast, the same table on a five-element truth (`land_series_rcl6`, truth
`C1-R1-L1-p(R2,C2)`) reads 0.01320 at five and 0.01311 at six — a 1.007× gain, i.e. nothing.
That is what "the data does not support another element" looks like, and it is the shape any
X3/X9 rule has to separate from the 1.29× row above. **The two are only a factor of 1.3 apart,
which is the measurement that sets the difficulty of this whole document.**

### 5.3 Every large reference carries a parameter the data does not contain [measured]

Found while building X8, and it is about the *arena*, not the search. The screen is
`benchmarks/autoeis_round/arena.py`'s `parameter_leverage`: bump each parameter by 10% and take
the largest relative change it produces in |Z| anywhere in the sweep. Below the noise level, the
data does not contain that parameter. Run at each reference's **own** frequency window, 10 points
per decade, against the 1% noise those references are used at:

| reference | elements | weakest parameter | its leverage | below 1% noise |
|---|---:|---|---:|---:|
| capacitor `C1-R1-L1-SKINF1` | 4 | `R1.R` | 1.551% | **0 of 5** |
| Maxwell-Wagner `p(R1,C1)-p(R2,C2)` | 4 | `C2.C` | 8.754% | **0 of 4** |
| Randles `R1-p(C1,R2-W1)` | 4 | `W1.A` | 5.146% | **0 of 4** |
| three-block MW `p(R1,C1)-p(R2,C2)-p(R3,C3)` | 6 | `C3.C` | **0.700%** | **1 of 6** |
| capacitor + block `C1-R1-L1-SKINF1-p(R2,CPE1)` | 6 | `R1.R` | **0.634%** | **1 of 8** |
| Randles + ESL + block `R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)` | 7 | `C1.C` | **0.758%** | **1 of 9** |

**All three small references are clean and all three large ones are not.** The three that gate
the exhaustive stage at 30/30 have a worst-case leverage of 1.55%; the three that gate the
genetic fallback at 5/9 each carry exactly one parameter whose effect on the spectrum is smaller
than the noise on it.

This is not a small bookkeeping point, because of what it does to the rule that picks the answer.
`DiscoveryResult.recommended` prefers, among candidates that fit as well as the best, those with
`n_unresolved == 0`. A truth carrying a parameter the data does not contain is therefore the
kind of candidate that rule is *built to reject* — so on these references the parsimony rule
disprefers the truth by design, and item 3 of §1 (the truth found, ranked 2 of 59, and not
recommended) stops looking like bad luck.

Three things follow, and the first two are corrections to claims this repo already makes:

1. **Gate EV1's 5/9 is measured on an arena that is partly unrecoverable by construction**, and
   its bar was set from a completed baseline of 1/9 on that same arena. The ratchet is still a
   ratchet — both arms saw the same arena — but "5 of 9 truths reported" must not be read as
   "the search misses 4 of 9 findable truths".
2. **The references predate the screen.** `arena.py`'s three-part screen was written for the
   AutoEIS round, months after `LARGE_REFERENCES`, and was never turned on them.
   `AUTOEIS_COMPARISON.md` already records that the screen "took three versions and the first
   two passed truths nothing could recover"; this is the same lesson arriving from the other
   side — the third version works, and nothing had asked it about the references.
3. **The nine truths of §4.6 must pass it before any arm is run**, which is why that requirement
   was written into §4.6 before this was found rather than after.

What this does *not* say: that the large references are worthless. Five of six, eight of nine and
five of six of their parameters are well inside the data, and a truth with one weak parameter is
a realistic case rather than a broken one — real parts have them. The defect is that no report
and no gate said so.

### 5.4 X9 — rational-approximation order estimation is exact without noise and useless with it [measured]

`benchmarks/six_plus/order.py`. Four estimators, all numpy/scipy, asked one question: how many
relaxations does this spectrum support? Ground truth is a set of RC ladders whose pole count is
known, plus two fractional truths (CPE, Warburg) that have no finite order at all.

**On dense noise-free data (40 points/decade) the answer is exact**, which is worth stating
because it says the implementations are right and the failure below is not a bug:

| truth | true relaxations | AAA | Loewner (threshold) | Loewner (gap) | stabilisation |
|---|---:|---:|---:|---:|---:|
| `p(R1,C1)` | 1 | **1** | 2 | **1** | **1** |
| `p(R1,C1)-p(R2,C2)` | 2 | **2** | **2** | **2** | 3 |
| three blocks | 3 | **3** | **3** | **3** | 5 |
| four blocks | 4 | **4** | **4** | **4** | 4 |
| `R1-p(R2,CPE1)` | none (fractional) | 27 | 40 | 1 | 0 |
| `R1-p(C1,R2-W1)` | none (fractional) | 22 | 23 | 2 | 1 |

**At 0.1% noise — ten times finer than the 1% these spectra are measured at — three of the four
collapse completely.** The raw estimates, 5 seeds, 10 points/decade, on the one-relaxation truth
whose answer is 1:

| estimator | noise 0 | noise 0.1% | noise 1% |
|---|---|---|---|
| AAA | 1 | 34, 32, 26, 22, 23 | 23, 24, 28, 24, 35 |
| Loewner (threshold) | 1 | 30, 32, 28, 25, 32 | 23, 20, 17, 13, 20 |
| Loewner (gap) | 1 | 101, 92, 94, 90, 95 | 101, 92, 94, 90, 95 |
| stabilisation | 1 | 3, 1, 1, 1, 2 | 1, 3, 2, 1, 2 |

Exact-recovery rate at 1% noise and 10 points/decade, averaged over the four finite-degree
truths: **AAA 0.12, Loewner-threshold 0.04, Loewner-gap 0.20, stabilisation 0.16.**

**The mechanism is the one the literature predicts** (§3.3): AAA is an *interpolant*, so it
places poles on noise, and the Loewner pencil's singular values stop dropping once noise fills
the tail — its "largest ratio gap" rule then lands at the very end of the spectrum and returns
essentially the full rank, 90–101 out of a 91-point sweep, identically at both noise levels
because the gap is in the noise floor rather than in the data. The stabilisation diagram is the
one qualitatively different result: it is the only estimator that does not explode, staying at
1–3 where the others go to 20–100, which is exactly what its cross-order-consistency criterion
is for. It is also the only one that *under*-counts, returning 1–3 on a three-relaxation truth.

**Decision: the rational route does not size this search, and no production code follows from
it.** Not a near miss to be tuned — 0.16 against a usable ~0.9. What survives is one thing worth
keeping and one thing worth saying:

- **A fractional element announces itself loudly.** On noise-free data AAA needs 22–27 poles for
  a CPE or a Warburg and 1–4 for any RC ladder. §3.4 records that the literature has no
  calibrated rule for detecting a fractional element from a growing pole count; this is a
  10x separation on the noise-free case and it is **not yet measured under noise**, which is the
  next question and not this one.
- **What was not tried, and why not.** AAA's tolerance is relative to the largest |Z| in the
  sweep, so on a spectrum spanning decades of magnitude the low-|Z| end is effectively unweighted
  — a modulus-weighted vector fit would be the principled repair, and it is ~200 lines of numpy.
  It is not being written, because the gap to close is a factor of five rather than a few percent,
  and because the published Loewner-for-EIS work (Patel et al. 2025) reports the same
  noise-driven extra poles and stops at DRT extraction rather than at a topology. Recorded so
  that a later reader knows this was a decision and not an oversight.

### 5.5 X5 — a first signal: after the enumeration production already runs, the truth is three fits away [measured, one truth]

`benchmarks/screening_round/arms.py` gained two arms for this document, and this is their first
run — on the **incumbent** arena (`land_rcl7`, the six-element three-block truth, 11,033
topologies, 109 verified targets, budget 900 fits, `--max-elements 7`). One truth and one run, so
this is a signal and not a result; §4.6's nine truths are what turn it into one.

| arm | growth operator | seed | hit | fits to hit |
|---|---|---|---|---:|
| `beam4` (on record) | attachment only, width 4 | single elements | 1/1 | **86** |
| `beamf1` | complete (`_insertions`), width 1 | single elements | 0/1 | — |
| `beamf2` | complete, width 2 | single elements | 0/1 | — |
| `beamf4` | complete, width 4 | single elements | 1/1 | 93 |
| `beamf8` | complete, width 8 | single elements | 1/1 | 133 |
| `beams5w2` | complete, width 2 | **complete level 5** | 0/1 | — |
| `beams5w4` | complete, width 4 | **complete level 5** | 1/1 | 452 |
| `beams5w8` | complete, width 8 | **complete level 5** | 1/1 | 452 |

Two readings, and the second is the one that matters.

- **Closing the operator's hole changes almost nothing here.** `arm_beam` grows by *attaching* an
  element at a position, and [measured, `enumerate._insertions`] that reaches only 7 of the 16
  four-element topologies containing `R1-C1-L1` and 58 of 139 at five — so the 86-fit number on
  record was set by a search that cannot reach most of its own level. Using the library's
  complete operator costs 93 fits instead of 86. The hole was real and, on this truth, harmless;
  whether that survives a truth of another shape is X4.
- **Seeding from the complete five-element level reaches the class 3 fits after the enumeration
  ends.** The R,C,L pool has 449 topologies at five elements or fewer, and `beams5w4` hits at
  452. The arena charges those 449 like any other lookup, which is why the column reads 452 and
  not 3 — but **the production pipeline has already paid them**: `_exhaustive` enumerates and
  screens exactly that level and then throws the ranking away. The marginal cost of the sixth
  element, given what discovery already does, is three screening fits.

Also measured and needed before any of this is designed on: **width 2 is not enough and width 4
is** — `beamf2` and `beams5w2` both miss where their width-4 siblings hit. A one-truth run cannot
set that threshold, but it can say the parameter matters.

### 5.6 X8 at twelve seeds — the axis is the draw, not the budget [measured]

The seeded rerun of §5.1, twelve independent fitter seeds per cell rather than one, because a
single draw cannot separate a budget that is too small from a basin the search only sometimes
reaches. Noise-free convergence, so the target is exactly zero:

| case | circuit | r1/p8/m40 (the tier-1 screen) | r5/p20/m400 (**the shipped default**) | r20/p20/m400 |
|---|---|---|---|---|
| 4 el / 4 par | `p(R1,C1)-p(R2,C2)` | 12/12 | 12/12 | 12/12 |
| 5 el / 5 par | `C1-R1-L1-p(R2,C2)` | 12/12 | 12/12 | 12/12 |
| 6 el / 6 par | `p(R1,C1)-p(R2,C2)-p(R3,C3)` | 12/12 | 12/12 | 12/12 |
| 7 el / 7 par | `R4-p(R1,C1)-p(R2,C2)-p(R3,C3)` | **10/12** | 12/12 | 12/12 |
| 8 el / 8 par | four blocks | 12/12 | 12/12 | 12/12 |
| 6 el / 8 par | `C1-R1-L1-SKINF1-p(R2,CPE1)` | **9/12** | 12/12 | 12/12 |
| 6 el / 9 par | `p(R1,CPE1)-p(R2,CPE2)-p(R3,CPE3)` | 12/12 | 12/12 | 12/12 |
| **7 el / 9 par** | `R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)` | **1/12** | **2/12** | **12/12** |

**The last row is the finding, and it arrived after the other seven had been read as an
all-clear.** On seven of eight cases the shipped publication budget converges 12 times in 12,
which is what the note in §5.1 above was written from. On the eighth it converges **twice in
twelve** — and that case is not an oddity chosen to make a point, it is
`LARGE_REFERENCES[2]`, one of the three references gate EV1 is measured on. With the true
topology handed to it and noise-free data, the fitter this project ships finds the right answer
one time in six.

**Four times the restarts fixes it and four times the population does not.** `r20/p20/m400` is
12/12; `r5/p40/m800` and the rest of the population-generations sweep in §5.1 never reached it.
That is the same bimodality §5.7.2 measures on the screen, at the publication budget and with a
much worse win probability: reading 1/12 at one restart as a per-draw success probability of
about 0.08 predicts 35% at five restarts and 82% at twenty, against 17% and 100% measured — the
right shape, and enough to say the axis is **draws**.

Three consequences:

1. **Gate EV1's arena has a second problem.** §5.3 found one parameter below the noise in each
   of the three large references; this finds that on one of them the fitter reaches the truth's
   own optimum in 2 runs of 12. Both are properties of the arena rather than of the search, and
   both push EV1's 5/9 in the same direction: it is not a measure of how often the search misses
   a findable truth.
2. **It is indexed on neither element count nor parameter count.** 8 elements passes where 7
   fails; 6 elements with 9 parameters passes where 6 with 8 fails; and the 9-parameter case that
   fails and the 9-parameter case that passes differ only in their vocabulary. So the remedy
   cannot be "scale the budget with N".
3. **The screen is worse than the publication budget on the same case, in the same direction**
   (1/12 against 2/12), which is what §5.7.2 then measures across the space rather than on one
   circuit.

### 5.7 Two defects in the *existing* pipeline, found by running the new truths through it

Building the nine truths of §4.6 meant running `discover()` on circuits whose shape no arena in
this repository had ever carried. Two things fell out immediately, and neither is about growth.

#### 5.7.1 The feasibility filter assumes the measurement window reaches the asymptote [measured]

`ser5` — `C1-R1-L1-p(R2,C2)`, five elements, weakest leverage 9.09%, fitted to its own 1% data
with a worst value-matched deviation of 0.7% — is **deleted before any fitting** by
`enumerate.is_feasible` at the default degeneracy budget. A search on that spectrum cannot find
that truth however good the search is.

The filter compares a model's *asymptotic* endpoint exponents against the *measured* edge slope.
For this truth the reachable high-frequency band is (0, +1) — resistive to inductive — and the
measured high-frequency slope is **−1.15**, still capacitive, because the shunt capacitance is
falling faster than the series inductance is rising right up to the top of the window. So the
filter concludes, correctly on its own terms, that the two cannot be reconciled, and drops the
circuit that generated the data. It survives at `feasibility_budget=2`; the default is 1.

Two separate things are true and both are worth writing down:

- **The instance is partly the tuner's doing.** §4.6's values are chosen to maximise the weakest
  parameter's leverage and nothing else, so nothing stopped it from putting the self-resonance
  at the edge of the window. `benchmarks/screening_round/landscape.py`'s own `series` reference
  is the same circuit with hand-picked values and it survives.
- **The assumption is real and was not previously written down.** Gate G3 of
  `DISCOVERY_V2_PLAN.md` — "the truth and every known exact equivalent survive the feasibility
  filter" — was measured on references whose windows do reach their asymptotes. A real sweep that
  stops short of its own asymptote sits exactly where `ser5` sits, and nothing in the report says
  so: the truth is simply not in the candidate list.

What was done about it here: `truths.py` gained a **fourth** admission check, that the pipeline's
own filter keeps the truth (`survives_feasibility`). A truth the filter deletes measures the
filter, not the search. What was *not* done: the filter itself is unchanged, because raising the
default budget costs its power everywhere to fix a case whose frequency is not yet known, and
that is a measurement (how often does a real window stop short?) rather than a judgement call.

#### 5.7.2 The tier-1 screen's verdict is a basin lottery, and more budget does not fix it [measured]

`mix5` — `p(p(R1,C1)-R2,C2)-R3`, five elements, which the enumeration does reach — screens at
cost **33.78** and ranks **150 of 244**, while the best five-element circuits screen at 0.0141.
Its full-budget fit reaches χ²_red 7.96e-05, i.e. it fits the data essentially perfectly. So the
screen is wrong about it by a factor of 2400, and the shortlist never sees it.

The obvious explanation is that the screening budget is too small. It is not:

| screen budget | best of 5 seeds | worst of 5 seeds |
|---|---:|---:|
| popsize 8, maxiter 40 (**shipped**) | 0.0140861 | 33.7751 |
| popsize 12, maxiter 60 | 0.0140861 | 33.7751 |
| popsize 20, maxiter 100 | 0.0140861 | 33.7751 |
| popsize 20, maxiter 400 | 0.0140861 | 33.7751 |
| popsize 40, maxiter 400 | 0.0140861 | 33.7751 |

*(the truth's own parameters give 0.0140861, so the good basin is the right answer)*

**Twenty-five times the population-generations budget changes nothing, and the seed changes
everything.** The distribution is bimodal: a seed lands in the right basin or in one 2400× worse,
and which it is does not move with budget. The control `par5` behaves identically — best
0.0140983, worst 30.7231 — it merely happens that seed 0 draws the good basin there and the bad
one for `mix5`.

`_screen_all` calls `screen(text, spectrum, seed=seed)` **once per topology, with one seed for
the whole run**. So for a topology whose landscape is bimodal, its place on the shortlist is
decided by a coin flip, and the report cannot show it: a mis-screened candidate is not a bad fit,
it is an absence.

**How often, across the space rather than on two circuits** — 120 topologies sampled uniformly
from each of three enumerated spaces, screened at five seeds each, seed 0 compared against the
best of the five:

| | `par5` | `mix5` | `par6` |
|---|---:|---:|---:|
| seed 0 worse by > 1.01× | 20.0% | 28.3% | 25.8% |
| worse by > 2× | 8.3% | 11.7% | 1.7% |
| worse by > 10× | 2.5% | 1.7% | 0.0% |
| worse by > 100× | 1.7% | 1.7% | 0.0% |
| **mean ratio to best-of-5, 1 seed** | **37.7** | **41.4** | 1.07 |
| mean ratio, 2 seeds | 1.06 | 1.16 | 1.04 |
| mean ratio, 3 seeds | 1.06 | 1.04 | 1.01 |

The median ratio is 1.0000 in every column: **the typical topology is screened correctly and the
damage is entirely in the tail.** One to two percent of topologies are mis-screened by more than
a hundredfold, and because the truth is one specific topology, that is also roughly the
probability that a given truth is thrown away before tier 2 ever sees it. `mix5` is a case of
exactly that happening — it is not a coincidence discovered separately, it is the tail.

A second seed removes almost all of it: mean 37.7 → 1.06, 41.4 → 1.16. A third buys little more.
That is the shape of a bimodal landscape and not of an under-converged one, and it is why the
remedy is **another draw rather than a longer one**.

**What was done: the lever, not the default.** `fit.screen(..., restarts=)`,
`ScreenBudget.restarts`, `discover(screen_restarts=)`, and `SCREEN_RESTARTS = 1` — unchanged, so
no number recorded anywhere in this repository moves. The screen is the dominant cost of an
exhaustive run and raising this doubles the whole search; the case for paying that is a
*recovery* measurement — does a second seed put truths on the shortlist that one seed lost — and
that is X4, below. A 2% mis-screening rate is an argument for measuring, not for spending.

### 5.8 The growth stage, implemented [measured, end to end]

`discover(growth_width=...)` and `--growth-width`; `growth_plan` in `core/discover.py`, driven by
`_grow_all` exactly as `screen_plan` is driven by `_screen_all`, so the browser can fan the same
batches across Web Workers without a second copy of the decisions. Growth runs **between** the
two tiers — it needs the tier-1 ranking of a completed level, which is what `_exhaustive` used to
compute and discard — and both stages then feed one shortlist under one per-size quota.

End to end on `par6` (`p(R1,C1)-p(R2,C2)-p(R3,C3)`, six elements, 1% noise, pool R,C,L,
`exhaustive_limit=5`, `max_elements=7`, 8 workers):

| `growth_width` | wall clock | topologies evaluated | `complete_up_to` | `grown_to` |
|---:|---:|---:|---:|---:|
| 0 | 23 s | 303 | 5 | — |
| 4 | 46 s | 548 | 5 | 7 |

**The truth was not recovered in either arm**, which is why §5.7.2 is above this section rather
than below it: on this spectrum the search never gets a fair chance at the answer, because the
screen that ranks it is a lottery. Growth doubles the work and reaches two sizes further; whether
it reaches the *truth* is X4, and X4 cannot be read until 5.7.2 is settled.

What is verified is the claim discipline. The coverage line now reads, in full:

> Coverage: every plausible topology with up to 5 elements from this pool was evaluated. Above 5
> elements the search grew rather than enumerated: every one-element extension of the best 4
> topologies of each completed size was evaluated, up to 7 elements. That is not a completeness
> claim — a topology of 6 elements or more that is not one insertion away from those is absent
> because it was never considered, not because it did not fit.

`tests/test_discover_growth.py` holds that to it: `complete_up_to` may not move when growth runs,
`grown_to` is absent when it does not, growth is skipped under a skeleton, the beam is
deterministic, and a wider beam never evaluates fewer topologies.

### 5.9 X4 — growth changes what the report says, and one shape shows why a global default is wrong [measured, complete]

**All 54 runs complete.** The round was interrupted once, for a machine shutdown, and resumed
from `benchmarks/six_plus/x4_recovery.json` exactly where it left off (the partial reading that
used to stand here — "growth measured on one six-element truth of one shape" — is superseded by
the table below).

**The negative control passes, which had to be checked first.** On `par5`, `ser5` and `mix5` both
arms score **3/3 reported, on the front, and recommended**, and `grow` reaches seven elements
without ever recommending one: `over_grown` is false on all 18 runs. A method that answers "six
elements" to a five-element spectrum would have scored perfectly on recovery below and been
worthless, and nothing previously measured in this repository would have caught it.

**On the six- and seven-element truths, growth is not one effect but two, and the second is the
one that decides the default:**

| truth | arm | reported | on the front | **recommended** | best relative error | seconds |
|---|---|---:|---:|---:|---:|---:|
| `par6` | `base` | 0/3 | 0/3 | **0/3** | 30.23–30.34% | 21–26 |
| `par6` | `grow` | 3/3 | 3/3 | **3/3** | 1.24–1.44% | 52–59 |
| `ser6` | `base` | 0/3 | 0/3 | **0/3** | 1.43–1.66% | 11–44 |
| `ser6` | `grow` | 2/3 | 2/3 | **0/3** | 1.24–1.49% | 53–78 |
| `mix6` | `base` | 0/3 | 0/3 | **0/3** | 30.23–30.35% | 14–15 |
| `mix6` | `grow` | 3/3 | 3/3 | **3/3** | 1.24–1.44% | 34–36 |
| `par7` | `base` | 0/3 | 0/3 | **0/3** | 33.63–33.72% | 17–23 |
| `par7` | `grow` | 3/3 | 3/3 | **3/3** | 1.24–1.46% | 37–58 |
| `ser7` | `base` | 0/3 | 0/3 | **0/3** | 28.62–28.65% | 31–42 |
| `ser7` | `grow` | 0/3 | 0/3 | **0/3** | 1.26–1.49% | 45–74 |
| `mix7` | `base` | 0/3 | 0/3 | **0/3** | 33.76–33.85% | 11–18 |
| `mix7` | `grow` | 3/3 | 3/3 | **3/3** | 1.24–1.46% | 30–34 |

Aggregated: **base 0/18 reported (0/18 recommended) against grow 14/18 reported, 12/18
recommended**, median seconds 20 against 46. By shape, `reported`: parallel 9/9, mixed 9/9,
**series 5/9** (all five from `ser5`, the negative control — `ser6` and `ser7` contribute zero
between them).

**Parallel and mixed are the `par6` result repeated four more times.** `base`'s zero is
structural rather than unlucky — the enumeration stops at five elements and the truth has six or
seven — and the residual names why: the best five-element fit sits at 28–34% of |Z| against a 1%
noise floor, and the sixth or seventh element takes it to 1.2–1.5%. That is not a marginal
preference parsimony had to be argued into; it is a model that does not fit being replaced by one
that does. The recommendations `grow` returns are strings like `p(p(R1-p(C1,R2),C2)-R3,C3)`, not
the truth's own text; they are exact reparameterisations accepted by the referee's response test
at `EQUIVALENCE_RTOL`, which is the equivalence-class machinery doing its job. This also names the
next experiment: X3's trigger should be a statement about the residual's **magnitude**, since §1
item 2 measured the current sign-based runs test at z = −0.45 to +0.67 on exactly these spectra.

**`ser6` and `ser7` are a different failure, and it is informative rather than a bug.** Their
`base` residual is not 30% — it is 1.4–1.7%, already close to the 1% noise floor, on a circuit
with *one fewer element than the truth*. In series topologies built from an inductor next to a
parallel RC branch, the extra reactive element the truth adds is close enough to redundant at
this sweep's frequencies that a five-element circuit already explains the data to within noise.
`grow` finds six- and seven-element fits that are numerically better (1.2–1.5%) but a residual
that is already inside the noise floor gives parsimony no evidence to prefer the larger model —
so `ser6` never recommends it (0/3) and `ser7` does not even put it on the front (0/3 reported).
This is the sixth element being **genuinely unresolved by this spectrum**, which is exactly the
state point 3 of this project's mandate says the report must show rather than paper over — a
result the negative control did not test for, because `par5`/`ser5`/`mix5` were tuned to have no
such near-degeneracy.

**This settles the question §1 item 5 raised before X4 ran.** Growth is not a uniform win: it
recovers `par6`, `mix6`, `par7`, `mix7` completely (12/12 recommended) and it recovers neither
`ser6` nor `ser7` (0/6), for a topology-shape reason rather than a budget one. Flipping
`GROWTH_DEFAULT` on for every user would silently promise a recovery that does not happen for
series-shaped parts, which is worse than the status quo's honest silence — so **`GROWTH_DEFAULT`
stays `0`**. The lever (`--growth-width`) stays available for a user who asks for it, and the
report's own `_with_growth_note()` sentence ("not a completeness claim") is what protects a user
who does turn it on and lands on a `ser6`-shaped part: they see a `grown_to` of 7 and a residual
that did not move, not a false claim of completeness.

### 5.10 X7 — what parsimony costs at six elements [measured]

X4's own data already contains every instance the question needs: across all 54 runs, a
truth-equivalent sits on the front but is *not* the recommendation in exactly two of them —
`ser6`/`grow`, seeds 2 and 3 (§5.9's table: 2/3 on the front, 0/3 recommended). No new run was
required; the two cases were re-run only to read out `aicc` and `n_unresolved`, which
`x4_recovery.json` does not store.

**The cost is not small, and it is not what the report's own sentence says it is.** In both
cases the truth-equivalent's AICc is far better than the recommendation's — Δaicc = −33.9 (seed
2) and −29.0 (seed 3), against a rule of thumb (already used elsewhere in this file, `discover.py`
line ~260) that front rows differing by *tens* of AICc are not close calls. And in both cases the
six-element candidate's parameters are all resolved (`n_unresolved = 0`, std. errors 0.2–7% of
value) — this is not the unresolved-extra-parameter case `recommended`'s docstring describes.
`_well_fitting()` is why: `PARSIMONY_CHI2_FACTOR = 2.0` admits any front candidate within 2x the
best chi², and both recommendations sit at only 1.24–1.28x — comfortably inside a threshold wide
enough that a chi² improvement large enough to move AICc by 30 still does not exclude the simpler
model. Once both are "well fitting," `recommended` breaks the tie on `(complexity, aicc)`, so
complexity wins outright and the 30-point AICc gap never gets a vote.

**This makes the report's canned explanation wrong on the two cases where it fires.** `summary()`
prints, verbatim: `"Lowest AIC: <circuit> (6 parameters, 0 of them unresolved) -- better
numerically, but the extra elements are not supported by the data."` The sentence and the
parenthetical it is attached to contradict each other — "0 of them unresolved" *is* the data
supporting them. The real reason `recommended` differs from `by_criterion` here is not
axis-R's anticipated one ("front's top two are not distinguishable," §4.5) either: a Δaicc of 30
is the opposite of indistinguishable. The reason is specifically the chi²-threshold width in
`_well_fitting()`, and the report does not currently say that. Fixing the sentence is future
work, not done here; what X7 asked for — the rate and the size of the cost — is answered: **rate
2/54 overall (2/18 of `grow` runs at 6–7 elements, 2/14 of the runs where a truth-equivalent
reached the front at all), and the cost when it happens is a two-to-three-dozen-point AICc gap
conceded to a model whose extra elements the data does resolve.** Both events are `ser6`, the
same shape §5.9 already flagged as the one growth does not recover — consistent with, not
independent evidence for, that section's reading that this shape sits closer to a genuine
five-versus-six-element ambiguity than the other five.

### 5.11 X6 — the fallback's missing parallelism, wired and measured [measured]

Section 4.4's note (commit `1db16a2`) is a finding made in passing while measuring something
else, and it is not the whole of X6: `_evolve` took no `workers` where `_exhaustive` does, so
every evolve run in this repo before this section ran single-threaded, and all twelve of those
runs stopped at `generations = 30` — the library default — having spent 156–818 s of a 600 s
allowance. **The generation cap ended every one of those runs, not the clock.** That fact alone
does not settle X6's decision ("a correction to every wall-clock comparison here, whichever way
it goes"), because it is a statement about the default configuration, not about the search: a
run that is not time-limited gains nothing from finishing its iterations faster, but a run that
*is* time-limited might gain everything from it. Which one a user's run is depends only on
whether `generations` is set high enough to let `time_limit` bind first, and the shipped default
was not.

**What was built.** `_evolve` now takes `workers`, plumbed through `discover()` exactly as
`_exhaustive` already receives it — the CLI's `--workers` flag silently did nothing under
`--mode evolve` before this and now does. Two tiers are parallelised, each the same way its
`_exhaustive` counterpart already is: the per-generation population evaluation
(`_Evaluator.evaluate_all`, new) fans the warm polish and the reduced-budget global search across
a process pool a generation at a time, and the shortlist's tier-2 refit (`_refine`) fans its
independent full-budget fits the same way `_refit_shortlist` does. `workers=1` (the default)
creates no pool at all and calls the original per-item `evaluate()` in the original order, so it
is byte-identical to the loop it replaces — confirmed by the existing `test_discover*` suite (82
tests) passing unchanged, and by `mypy --strict`. `workers>1` accepts one documented staleness:
a lookup inside `evaluate_all` sees the cache and `best_cost` as of the *start* of the
generation rather than updated as each tree is resolved, which is the same trade
`_screen_parallel` already makes within a chunk and cannot change which fit is reported, because
tier 2 always refits the shortlist at full budget regardless of which tier-1 path a topology
took.

**The measurement.** `benchmarks/six_plus/x6_workers.py` calls `mode="evolve"` directly (as gate
EV1 does) on `par6` and `ser6` — one shape growth recovers completely, one it recovers not at
all (§5.9) — with `generations` set to 100,000, far above what either arm can reach, so
`time_limit` (300 s) is the only thing that stops a run rather than the cap. `workers=1` against
`workers=8`, one noise seed each:

| truth | workers | wall seconds | generations | topologies evaluated | reported | on front | recommended |
|---|---:|---:|---:|---:|---|---|---|
| `par6` | 1 | 358 | 198 | 295 | yes | yes | yes |
| `par6` | 8 | 336 | 275 | 380 | yes | yes | yes |
| `ser6` | 1 | 464 | 103 | 365 | no front | no | no |
| `ser6` | 8 | 440 | 152 | 413 | no front | no | no |

Two readings, and they point in different directions on the two things X6 could have said.
**Parallelism is a real, measured win once `generations` is not the binding constraint**: eight
cores bought 39% more generations on `par6` and 48% more on `ser6`, at *lower* wall clock in both
cases (300 s nominal budget, and the per-generation overshoot the loop already documents landed
lower with more workers rather than higher). **It is nowhere near an 8x win** — roughly 5–6%
scaling efficiency per core, well short of the six-way exhaustive control the X6 note in §4.4
compared against. The likely reason is structural rather than a defect to fix here: each
generation dispatches two *sequential* batches (polish, then search), and
`EVOLVE_SEARCH_PLAN.md` §1.3 already measured that over half of a late generation's proposals are
cache hits needing no fit at all, so the batch actually reaching the pool most generations is
well under `population = 40` split two ways — small enough that per-task dispatch and IPC
overhead eat into an 8-way split before it can show up as wall clock. That is a hypothesis, not
re-measured further here.

**And it changes no recovery outcome.** `par6` was already reported, on the front and
recommended at `workers=1` given enough generations — the direct `mode="evolve"` call recovers
this shape without either growth (§5.8) or parallelism, consistent with gate EV1's own 5/9. `ser6`
stayed off the front and unrecommended at `workers=8` despite 48% more generations and 413
distinct topologies fitted, which is the same shape and the same reading §5.9 and §5.10 already
gave it: this truth's obstacle is not search reach, it is the residual already sitting inside the
noise floor at five elements. More parallelism cannot buy an answer the data does not contain.

So the correction X6 asked for is this: **every prior wall-clock or core-second comparison
between the evolve arm and the exhaustive control in this repository (§4.4, `1db16a2`,
`EVOLVE_SEARCH_PLAN.md`) was comparing a single core against six, and that was a real asymmetry
worth fixing** — `_evolve` had no principled reason to run single-threaded when the search it
falls back from does not — **but the asymmetry was never the reason any six-element truth went
unrecovered.** `par6` did not need it and `ser6` is not helped by it. `workers` ships wired for
the fallback because a search this document calls a fallback should not carry an arbitrary
handicap the exhaustive stage does not, not because it was found to close any of the four gaps
§2 names.

### 5.12 X2 and X3 (both complete)

**X2 — the identifiability ladder, complete: 6 of 6 truths, 72 of 72 cells [measured].**
`benchmarks/six_plus/identifiability.py` operationalises section 4.3's grid exactly as section
5.2's own method: simulate the truth at `(noise, points_per_decade)`, enumerate every R,C,L
topology up to the truth's own element count, screen all of them (`fit.screen`, tier-1, seed=0),
and read `gain = best(n−1) / best(n)`. Noise ∈ {0.1%, 0.3%, 1%, 3%}, points/decade ∈ {5, 10, 20},
one data seed (1, distinct from the arenas' 0).

Four truths never approach "not distinguishable" at any cell on the grid:

| truth | noise | ppd=5 | ppd=10 | ppd=20 |
|---|---:|---:|---:|---:|
| `par6` | 0.1% | 77182.6 | 59312.0 | 51868.8 |
| `par6` | 0.3% | 8575.1 | 6591.3 | 5765.8 |
| `par6` | 1% | 772.0 | 594.1 | 520.3 |
| `par6` | 3% | 86.3 | 66.8 | 58.8 |
| `mix6` | 0.1% | 77210.6 | 59325.8 | 51879.3 |
| `mix6` | 0.3% | 8578.2 | 6592.9 | 5766.9 |
| `mix6` | 1% | 772.3 | 594.3 | 520.4 |
| `mix6` | 3% | 86.4 | 66.8 | 58.8 |
| `par7` | 0.1% | 29687.6 | 23723.0 | 20882.8 |
| `par7` | 0.3% | 3299.0 | 2638.8 | 2321.6 |
| `par7` | 1% | 297.6 | 239.0 | 209.9 |
| `par7` | 3% | 33.9 | 27.6 | 24.2 |
| `mix7` | 0.1% | 29618.9 | 23771.6 | 20989.9 |
| `mix7` | 0.3% | 3291.4 | 2644.4 | 2333.5 |
| `mix7` | 1% | 296.9 | 239.6 | 211.0 |
| `mix7` | 3% | 33.8 | 27.7 | 24.3 |

**Worst cell across all four is still 24.2x** (`par7`, 3% noise / 20 ppd), an order of magnitude
above section 5.2's own "nothing" reading (1.007x on a genuinely five-element truth). That is not
a surprise this late: every truth here is `tune()`-maximised (section 4.6), so each one's extra
element is, by construction, the most identifiable member of its topology's parameter family. And
**`mix6` tracks `par6` cell for cell, `mix7` tracks `par7` cell for cell** — every pair agrees to
within 0.1% at every one of the 12 cells — which says the "mix" truths' extra structure does not
change which element is hardest to see; the sixth (seventh) element is the same kind of easy
regardless of what else the circuit contains.

The two series-shaped truths are the opposite story:

| truth | noise | ppd=5 | ppd=10 | ppd=20 |
|---|---:|---:|---:|---:|
| `ser6` | 0.1% | **1.010** | 28.6 | 25.7 |
| `ser6` | 0.3% | **1.017** | 3.9 | 3.7 |
| `ser6` | 1% | **1.012** | 1.258 | 1.239 |
| `ser6` | 3% | **1.107** | 1.036 | 1.026 |
| `ser7` | 0.1% | **1.874** | 1.536 | 1.378 |
| `ser7` | 0.3% | **1.067** | 1.063 | 1.043 |
| `ser7` | 1% | **1.034** | 1.012 | 1.014 |
| `ser7` | 3% | **1.037** | 1.012 | 1.014 |

**`ser6` crosses it twice, for two different reasons, and only one of them is noise.** At 5
points/decade, `gain` sits at 1.01–1.12 across the *entire* noise range — sparse sampling alone
holds this truth at the boundary regardless of how clean the data is, which section 5.2's
noise-only framing cannot express. At 10 or 20 points/decade the ladder is visible and behaves as
expected — 28.6x at 0.1% noise, falling roughly as `1/noise²` (0.1%→0.3% is a 3x noise increase
and a 7.3x `gain` drop, close to the 9x a pure square law predicts) — until it reaches **1.24–1.26
at exactly the configuration (1% noise, 10 points/decade) every other experiment in this document
uses as its default**, which is the quantitative form of section 5.9's qualitative reading that
`ser6`'s five-element residual already sits inside the noise floor.

**`ser7` never clears roughly 1.9x anywhere on the grid, and it is the one truth where more points
per decade makes the extra element *harder* to see, not easier.** Its best cell is not its
cleanest — 1.874x at 0.1% noise sampled at only 5 points/decade — and `gain` *falls* as
`points_per_decade` rises at every noise level (0.1%: 1.874 → 1.536 → 1.378; 0.3%: 1.067 → 1.063 →
1.043), the opposite of `ser6`'s behaviour, where more points always helped or was neutral. At the
project's standard configuration (1% noise, 10 ppd) `ser7` reads 1.012x — indistinguishable from
"nothing" to three digits, and worse than `ser6`'s 1.258x at the same cell. This direction reversal
is measured, not explained; a plausible reading is that `ser7`'s extra element affects the spectrum
over a narrower band than `ser6`'s did, so added points mostly land off that band and dilute rather
than sharpen the signal, but that has not been checked and should not be assumed of any other
truth. `points_per_decade=20` never differs materially from `10` for either series truth (25.7 vs
28.6 for `ser6`; 1.378 vs 1.536 for `ser7`) — the third rung of the density axis does little work
across the whole grid, six-element and seven-element alike.

**Reading, all 72 cells: shape predicts the crossing far more than element count or size does.**
Both series-shaped truths cross into "not distinguishable" at or near the standard 1%-noise/10-ppd
configuration, and every non-series shape — parallel or mixed, six or seven elements — stays one to
three orders of magnitude clear of that boundary at every cell tried. Adding a seventh element made
the series shape's crossing *more* severe (`ser6`'s 1.258x at the default cell fell to `ser7`'s
1.012x) while leaving the non-series shapes' margin roughly where it was in kind, if not in exact
size (`par6`'s 594x at the default cell vs `par7`'s 239x — both still far from 1). The full grid is
`benchmarks/six_plus/x2_ladder.json`, 72 of 72 cells.

- **X3 (a trigger that fires when the sixth element is real) — complete, and it did not produce a
  trigger to ship.** `benchmarks/six_plus/trigger.py` scores the four candidates section 4.3
  named — (a) the current runs test, (b) a nested F-test between the best model at the smaller
  size and its own one-element extensions (`enumerate._insertions`, so the comparison is nested
  *by construction* rather than by picking the independently-best topology of the larger size),
  (c) a parametric bootstrap of (b)'s statistic (needed because the inserted element's parameter
  sits at a boundary of its range under the null, which breaks the asymptotic F-distribution's
  regularity conditions), and (d) X9's `stabilisation_order`, read as a margin over the same
  estimator's reading on a clean, noise-free simulation of the smaller model's own fitted circuit
  — against a **108-row labelled set**: X2's own 72 cells (six truths × 12 grid cells, where
  growing one element is always correct) plus 36 more built the same way from `par5`/`ser5`/
  `mix5` at the boundary (5 → 6), where it never is. [measured, `benchmarks/six_plus/x3_trigger.json`]

  | candidate | recovery (real=True) | false-positive rate (real=False) |
  |---|---:|---:|
  | (a) runs test | 52.78% (38/72) | **0.00%** (0/36) |
  | (b) F-test | **80.56%** (58/72) | 16.67% (6/36) |
  | (c) bootstrap | 51.39% (37/72) | 5.56% (2/36) |
  | (d) pole margin | 11.11% (8/72) | 22.22% (8/36) |

  **No candidate dominates the incumbent on both axes, so nothing replaces it.** Of the four,
  only (a) and (b) sit on the recovery/false-positive Pareto front; (c) is dominated by (a)
  outright (52.78%/0.00% beats 51.39%/5.56% on both numbers), and (d) is dominated by (a) on both
  axes too — it is the fourth independent measurement in this repository finding pole-order
  estimation unreliable under noise, after X9 itself. Per section 4.3's own decision rule ("the
  winner replaces `_is_underfitted`, or nothing does, and the trigger is removed rather than left
  in place looking like a check"), the honest reading is that **nothing wins outright**: (b) would
  roughly triple recovery (52.78% → 80.56%) but at a false-positive rate more than three times the
  nominal 5% the bootstrap was built to hold to, and accepting that trade is a choice this
  measurement can inform but not make. `_is_underfitted` is therefore left as it stands, and
  `GROWTH_DEFAULT` stays `0` for the same reason X4 already gave it: no report-side check
  measured here is trustworthy enough to promise the user "the sixth element is real."

  **The bootstrap did exactly the job it was built for, and it cost recovery to do it.** At 100
  replicates per cell (screen-grade refits of both the smaller model and its extension on data
  resimulated from the smaller model's own fit), (c)'s false-positive rate lands at 5.56% against
  a nominal alpha of 0.05 -- 2 false positives on 36 negative cells is within one event of the 1.8
  the calibration target predicts. All six of (b)'s false positives sit at `p` between 0.026 and
  0.042 -- just inside the 0.05 line, not by orders of magnitude -- and the bootstrap disagrees
  with four of the six, reading the identical fit as not significant (`boot_p` 0.06-0.16) rather
  than as a coin-flip's difference from the asymptotic answer. The clearest case: `mix5` at 0.3%
  noise, 5 points/decade extends its own best fit `p(R1-C1,R2-C2,R3)` with an inductor,
  `p(R1-C1,p(R2-C2,R3)-L1)`, and the asymptotic test calls that significant at `p = 0.026`
  (`f = 5.15`) where the bootstrap on the same pair reads `p = 0.059` -- not quite. That is the
  boundary-null problem section 4.3 predicted, measured rather than assumed: the inserted
  element's parameter can go to zero (or infinity) at the null, which is exactly the condition
  under which a plain extra-sum-of-squares F-test is known to be anti-conservative, and here the
  effect is real but modest -- a handful of borderline calls near the 5% line, not a test that is
  wrong by many orders of magnitude.

  **The shape-dependence X2 measured in cost ratios reappears here in fire/no-fire terms, cell for
  cell, and (d) never clears the project's default operating point at all.** Over the whole grid
  (a) is 0/12 on both `ser6` and `ser7` against 100% and 58.33% on `par6`/`par7`, the parallel-
  shaped truths at the same two sizes -- the same asymmetry X2 already read off cost ratios. At
  the project's standard configuration (1% noise, 10 points/decade) -- the one cell every other
  measurement in this document reports at -- **(d) reads "no" on every one of the six real
  boundaries**, `par6`/`mix6`/`par7` included, so at this cell it recovers nothing at all; its
  11.11% overall recovery comes entirely from other cells. `ser7` is where every candidate agrees:
  (a), (b), (c) and (d) all read "no" there, (b)'s own asymptotic `p = 0.876` nowhere near
  significant, so *no* candidate here would have grown `ser7` at the pipeline's own default
  operating point. `ser6` is not as absolute -- (a) and (d) read "no" but (b) and (c) both
  correctly fire (`p = 2.5e-08`, `boot_p = 0.0198`) -- so the standard cell alone understates how
  much of the series shape a trigger can reach; it is `ser7`, not the shape in general, that
  nothing here recovers at the project's default settings. The reading X2 already made still
  holds: a trigger tuned on `par6`/`mix6`/`par7`/`mix7` alone, exactly the four truths section 4.3
  named as the design lead, would have looked reliable while missing part of the series-shaped
  case a trigger has to get right.

X7 is answered, in §5.10: on `par6`, `mix6`, `par7` and `mix7`, parsimony recommended the larger
truth as soon as the search put it on the front, so the reporting axis was not the obstacle
there. On `ser6` it is a mixed picture rather than the clean "correctly declined" reading a
first pass might expect — §5.10 measures two of `ser6`'s three seeds landing the truth on the
front with a Δaicc in the tens and every parameter resolved, and the parsimony rule still
declining it, purely on chi²-threshold width rather than on any unresolved-parameter finding.

## 6. Implementation plan

*Written from §5, and the growth stage of it is built. See §5.8 for what shipped, `GROWTH_DEFAULT`
for why it is off, and §5.10 and §5.12 for what the default is waiting on.*
