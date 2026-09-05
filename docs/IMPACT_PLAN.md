# Impact plan: what would move the project most, effort disregarded

Status: written 2026-09-04 after a survey of every document in `docs/`, the core modules, the
benchmarks and the web front end (the survey was delegated to three read-only subagents; what
they reported is summarised in section 1, with one correction, itself later superseded — see
§3). **D1, B and C are implemented (§6.1, §2.4, §4). A was implemented, its gates A1-A4 measured
passing, and then withdrawn on a scope decision (§3) — not reworded, not deleted, kept as the
clearest record in this repository of a feature that worked and was still ruled out. C's own
gates found something neither C nor B anticipated: item B's noise model, gated only on
synthetic data, does not survive contact with a real spectrum (§4.3) — recorded there rather
than smoothed into a passing number.** E and D2 remain plan only.

The question this plan answers is not "what is cheap" but "what would change the answer a
non-expert gets". Every item below is ranked against `CLAUDE.md`'s three purpose sentences
and its consequences, and every item carries a gate written before any code, in the form the
repository already uses: a measurement that can fail, with the decision rule for what happens
when it does. Section 5 lists what was considered and deliberately left out, with the
measured reason beside each, so that nothing here re-opens a question a benchmark has closed.

## 0. The one-paragraph summary

Five items, in order of effect:

| | Item | Purpose point it serves | Section |
|---|------|-------------------------|---------|
| A | ~~**Multi-condition joint fitting**~~ — **built, gates A1-A4 measured passing, then withdrawn on a scope decision (§3)**, not a technical failure | 2 — the only instrument that can *break* an equivalence class | §3 |
| B | **A noise model estimated from the spectrum**, replacing the weighting knob's status as a user decision | 3 — a knob the target user cannot set correctly | §2 |
| C | **A measured-data arena** — **implemented, 7 real datasets; gate R2 found that neither weighting this project has gives a real spectrum's chi2_reduced a usable meaning (§4.3)** | 3 — "the same answer" has only ever been shown on synthetic data | §4 |
| D | **The genetic fallback runs on the user's budget, not on a trigger that never fires**, and `recommended()`'s sentence says its real reason | 1 and honest reporting | §6 |
| E | **Uncertainty beyond the linearised standard error** for the quantities the report leans on: `n_unresolved` and τ | honest reporting | §7 |

Order of work is D1 → B → C → E → D2 (section 8); **A was built, gated and withdrawn** (§3) so
it no longer occupies a slot in that sequence, and dropping it removes the one thing that made
B a hard prerequisite rather than merely a good idea — B stands on its own purpose-3 argument.
**C is done** (§4); it did not close a question so much as open one back up in B, which §4.3
records rather than schedules a fix for.

## 1. What the survey found

Three subagents surveyed the repository read-only. What matters from their reports:

**Open items on record** (`docs/`): multi-condition fitting was named in `CLAUDE.md` and
`docs/OBJECTIVE_PLAN.md` §8 as the one `interpret`-only extension; §3 below records that it was
then built, gated and withdrawn, and both of those documents have been corrected to match. The
Lin-KK test cannot validate a resonator and a pure-noise spectrum still passes
(`docs/KK_RESONANCE_PLAN.md` §5). The genetic fallback's trigger, a runs test at
`RUNS_Z_LIMIT`, was measured never to fire on forty runs (`docs/AUTOEIS_COMPARISON.md` §2.2:
residual z of −0.45 to +0.67 against a −3.0 threshold), and `docs/TOPOLOGY_6PLUS_PLAN.md`
§5.12 then measured four candidate triggers and found none that dominates it. The growth
stage is shipped off by default because it recovers parallel and mixed shapes 12/12 and series
shapes 0/6 (§5.9). `recommended()` prints the wrong reason when it declines a truth-equivalent
that sits inside the chi-squared band with every parameter resolved (§5.10). Gamry `.DTA` and
BioLogic `.mpt` readers wait on real files (`docs/HANDOFF.md` §6 item 4). The
equivalence-class dedupe opportunity (`docs/SEARCH_TIME_PLAN.md` §3.4) is 4.4–5.9x and
unbuilt for a stated structural reason.

**What the core implements** (`src/autocircuit/core/`): twelve elements, all with analytic
tests and SPICE synthesis; `interpret.py` with eight invariant quantities and the
form-dependent ones; DRT as a probe only; DE → TRF with restarts; four weightings, of which
`sigma` requires the user to supply per-point standard deviations and nothing estimates them;
standard errors from the Jacobian with `cov * chi2_reduced`
(`stats.py:450`), which means the *absolute* noise scale is already self-calibrated and only
the *shape* of the weighting across frequency and between real and imaginary parts is a
decision; no multi-spectrum fit of any kind (`fit()` and `screen()` take one `Spectrum`,
`fit.py:569`, `fit.py:713`); `Spectrum.metadata` is a free-form dict with no condition field
(`spectrum.py:61`).

**One correction to the survey, itself later superseded.** The core-audit subagent reported
activation energies as "out of scope per the geometry rule". At the time that was called wrong,
on the reasoning that a temperature series adds only more spectra and an activation energy is a
ratio of rates that needs no length or area. §3.5 supersedes this a second time: the geometry
ban is indeed not why activation energies are out of scope, but they are out of scope anyway,
because computing one requires relating parameters *across* experimental conditions via a named
physical law, which §3.5 argues is the analyst's judgement regardless of what the geometry rule
says about the number itself.

**Measurement infrastructure that can be reused**: `benchmarks/discovery_v2.py`'s three
`REFERENCES` and three `LARGE_REFERENCES`, `benchmarks/six_plus/truths.py`'s nine R/C/L truths
and their 72-cell identifiability grid, `benchmarks/ev5_fingerprint.py` for byte identity,
`benchmarks/o1_objective.py` for the objective invariant, and the 37-cell recovery table that
`docs/CRITERION_SELECTION_PLAN.md` §9 ran. Every one of these is synthetic, at 1% proportional
noise, independent across points — which is section 4's whole argument.

**Web**: the browser exposes pool (auto/custom), skeleton, weighting, seed, criterion and
workers; it does not expose `growth_width`, and it loads several spectra at once but searches
one at a time. The fourteen example datasets are all synthetic.

## 2. Item B — a noise model estimated from the spectrum

### 2.1 Why this is a purpose item and not a numerical nicety

`--weighting` is currently a user decision with four values, defaulting to `modulus`
(`1/|Z|` on both components). `CLAUDE.md`'s first consequence says a knob the target user
cannot set correctly is not a feature, and this is such a knob: whether the instrument's error
is proportional to `|Z|`, to each component separately, or has an additive floor is exactly the
kind of thing an analyst with little background does not know. And it is not cosmetic, because
the weighting shape decides three things the report leans on:

1. **Which parameters count as resolved.** With `modulus` weighting on a capacitor, the real
   part carries weight `1/|Z| ≈ 1/|Im Z|`, so a real-part residual of one ESR is scaled by the
   reactance — the ESR is under-weighted by the ratio `|Im Z| / Re Z`, which is Q. That is a
   decision about whether a 10 mΩ ESR on a 10 Ω reactance is "resolved", and it is made by a
   default nobody measured against a noise model.
2. **Which candidates fall inside the parsimony band.** `_well_fitting` compares
   `chi2_reduced` between candidates at `PARSIMONY_CHI2_FACTOR = 2.0`; the absolute scale
   cancels, the shape does not.
3. **Whether a residual is "structure".** The runs test is shape-free, which is why it is the
   only absolute check the search has — and section 6 argues that is why the fallback never
   runs. An estimated σ(f) would give the search a second absolute instrument: the best
   model's chi-squared *against the data's own noise*.

The rule that governs the design is the same one that governed `--pool auto`: whatever the
search would have gained from asking the user must be derived from the spectrum's own shape.

### 2.2 Investigation: four smoothers tried, measured, and three rejected

**This section exists because the first implementation was wrong, and wrong in the way this
project's own methodology exists to catch.** A generic local-quadratic smoother (LOESS in
`log10(f)`) was built with a fixed window of 30% of the spectrum's points. It passed on the
capacitor and Randles references and failed on Maxwell-Wagner — `p(R1,C1)-p(R2,C2)`, two
relaxations four decades apart — by up to 100x at the high-frequency end. The window was then
narrowed to 15% until Maxwell-Wagner passed too. **That narrowing was an error of method, not
only of degree**: a constant picked by sweeping until one named reference passes is a parameter
fitted to the test, and Maxwell-Wagner is not a reference to fit *to* — `CLAUDE.md`'s ceramic
use case (grain versus grain-boundary) *is* a two-relaxation Maxwell-Wagner block, so an
estimator tuned to pass it by accident rather than by mechanism is exactly the failure this
document's own §0 and §5 exist to prevent. What follows is the investigation that should have
come first, run after the fact: four candidate smoothers, each measured on the same four
spectrum shapes — the three `REFERENCES` plus a fourth added specifically because the
investigation needed a genuine pole to be honest about, not only zeros:

| Shape | Circuit | What it tests |
|---|---|---|
| capacitor | `C1-R1-L1-SKINF1` | a *series* LC resonance (a zero of `Z`) plus a fractional (skin-effect) element |
| Maxwell-Wagner | `p(R1,C1)-p(R2,C2)` | two relaxations four decades apart — the shape this document treats as the one that must not be gotten wrong |
| Randles | `R1-p(C1,R2-W1)` | a relaxation plus a Warburg diffusion tail |
| ferrite bead | `R1-p(R2,L1,C1)` | a genuine *parallel* resonance (an anti-resonance, a pole) — added because none of the three references contains one, and every estimator below needed to be shown one to find its real limit |

Pure bias (noise-free data, so the number is the smoother's own error and not noise) and, under
1% proportional noise, the estimate's ratio to the injected σ:

- **Fixed-fraction LOESS, 30% window.** Maxwell-Wagner's pure bias reaches 21.5% of `|Z|` near
  the first relaxation's roll-off — a quadratic cannot represent a full sigmoid transition over
  a window that wide, and the underfit reads as "noise", growing the further the window sits
  past the transition (measured point by point, `benchmarks/noise_estimation.py` §investigation
  log). The other two references are fine at this width.
- **Fixed-fraction LOESS, 15% window (the rejected fix).** Maxwell-Wagner's pure bias falls to
  under 1% almost everywhere. This is a real, mechanistic improvement — a narrower window tracks
  a sigmoid more closely, not numerology — but it is still a constant with no argument for why
  15% rather than 20% or 10% is right on a spectrum this project has not yet seen, and a sweep
  from 5% to 30% (`benchmarks/noise_estimation.py`, run interactively) shows exactly the
  bias-variance tradeoff a fixed constant cannot resolve: below about 10% every reference's
  *median* ratio drops under 0.5 (the window is now flexible enough to fit part of the noise
  itself, under-estimating σ), and above 20% Maxwell-Wagner's tail starts climbing again. There
  is a working range, and no principled reason internal to this method to pick one constant in
  it for every future spectrum.
- **Voigt basis, Lin-KK's own order selection.** Reusing `validate.py`'s fixed-tau Voigt series
  with Schoenleber's mu-criterion (`mu_criterion=0.85`, `lin_kk`'s default) — since a
  Maxwell-Wagner block *is* two Voigt elements, this basis should fit it exactly. On noise-free
  data it does: bias under 0.02% on all three `REFERENCES`, including the capacitor's series
  resonance (a zero, and the Voigt basis's own series-L/C terms represent it exactly — the
  module docstring in `validate.py` already states this: "a series resonance is fine"). **Under
  1% noise it fails on the capacitor**, not on Maxwell-Wagner: the mu-criterion is tuned to stop
  *early* rather than risk fitting noise, which is the right call for Lin-KK's own purpose
  (validating the data) and the wrong one for this purpose (getting the tightest possible
  reference curve) — under noise it selects order 6 for the capacitor where noise-free data
  reached order 65, and at order 6 the skin-effect element's curvature is not represented, so
  the residual is systematic (runs z as low as −5.5, below `RUNS_Z_LIMIT`) on a spectrum that
  has no resonance at all. On the ferrite bead's genuine anti-resonance the same basis fails
  outright regardless of order, as `docs/KK_RESONANCE_PLAN.md` §2 already found for a different
  purpose: median bias 450%, max 8100%, because no sum of real-pole elements can express a
  complex pole pair.
- **DRT (Tikhonov-regularised inversion, GCV-selected λ).** The same basis again, regularised
  instead of order-selected. Rejected outright, not merely imperfect: DRT's own regularisation
  is tuned for peak-count interpretability, not curve-tracking accuracy, and its RMS residual
  under 1% noise is 29–40% on the capacitor and 2–4% on Maxwell-Wagner — several times the
  injected noise level on every reference, including the two with no resonance at all. A
  smoother whose residual is dominated by its own smoothing bias rather than by noise cannot be
  used to measure noise.
- **LOESS with the window chosen by leave-one-out cross-validation (LOOCV), not fixed —
  measured, and itself replaced.** For each spectrum, predict every point from its neighbourhood
  *with that point excluded*, at each of a handful of candidate window widths (roughly 8% to
  50% of the spectrum, log-spaced), and keep the width with the lowest total held-out error.
  On Maxwell-Wagner and Randles this worked well on its own account: 0.78–1.12x the injected σ
  across three seeds, arrived at from the data (it independently chose widths of 10–20%,
  bracketing the constant the rejected fixed-window version had used, without being told to).
  **On the capacitor it under-estimated by about half, consistently across seeds (0.41–0.54x)**
  — this is not the same failure as the fixed-window version's, and it is not a coincidence:
  leave-one-out error alone rewards a narrower window for the variance it removes without
  charging it for the degrees of freedom spent getting there, a documented tendency of LOOCV
  bandwidth selection to under-smooth. This was caught before it shipped, not after: gate N1's
  own decision rule (§2.4) is what flagged the capacitor's ratio as a borderline fail.
- **The fix: generalised cross-validation (GCV), not plain LOOCV.** Same candidate widths, same
  local quadratic, but the score is now the in-sample mean squared residual divided by
  `(1 - tr(H)/n)^2` — the hat-matrix-trace correction that charges a window for its own
  flexibility, computed per point from the local weighted normal equations rather than one
  `n x n` matrix. This is the identical principle `autocircuit.core.drt` already uses GCV for
  (selecting its regularisation strength), applied here to a bandwidth instead. **Measured**:
  the capacitor's median ratio moves from 0.41–0.54 (failing) to 0.57–0.71 (passing) across the
  same three seeds, while Maxwell-Wagner (0.62–0.89) and Randles (0.73–0.89) — already fine
  under plain LOOCV — are not made worse. On the ferrite bead's anti-resonance GCV still fails,
  choosing the widest candidate and landing 21–140x over the injected σ across seeds and noise
  families — expected, and carried forward to gate N4 rather than treated as a defect of this
  step specifically.

**What ships is GCV-selected LOESS**, and the reason to prefer it over the fixed-fraction
smoother is not that its numbers happen to be better — it is that its width is a function of
*this* spectrum's own cross-validated fit quality rather than a constant this document would
otherwise have to keep re-justifying every time a new reference shape shows the last constant
wrong. Plain LOOCV was one step closer than a fixed window and still not far enough; GCV is kept
because it is what was actually measured to close the gap, not because it was the first idea
that looked more principled.

**The anti-resonance failure is not fixed, and is not being hidden.** Every method tried fails
on a genuine pole, for the same reason Lin-KK's own basis does (`docs/KK_RESONANCE_PLAN.md`):
smoothing a curve to find its noise cannot distinguish "the fit is bad because of noise" from
"the fit is bad because the true response has a feature this family of curves cannot express."
What makes shipping this defensible despite that is the direction of the failure for *this*
consumer specifically: an inflated σ near an unmodelled resonance down-weights that region in a
least-squares fit rather than over-trusting it, which is the safe side of the two possible
errors here (the dangerous side — σ too *small*, over-trusting noisy points — was not observed
in any of the four shapes at any candidate width). This is recorded as a directional argument to
be checked, not assumed: gate N4 below asks whether a resonance-bearing circuit (the ferrite
bead) still fits correctly under `weighting="auto"` despite the local inflation, because
"the failure mode is safe" is exactly the kind of claim this project does not get to make
without measuring it.

### 2.3 What changes downstream, and what must not

`weighting="auto"` is added as an explicit, opt-in value everywhere (`fit`, `discover`,
`validate`, `drt`, the CLI's `--weighting` choices) and does **not** become the default on any
path yet — that is gated on N2 below, unchanged from the original plan. The four existing
weightings are untouched: `resolve_weights` forwards to the existing
`weight_vectors` unmodified for every value but `"auto"`, so
`benchmarks/ev5_fingerprint.py` still holds byte-for-byte for anyone passing `--weighting
modulus` explicitly — gate N0.

`_well_fitting`'s chi-squared band stays exactly as it is regardless of what N2 finds; nothing
in this item is licensed to touch the parsimony rule. (An earlier draft of this section proposed
making the band statistical *if* N2 showed a clean ratchet; that coupling is dropped; the two
questions — does a better σ estimate exist, and is the parsimony band the right shape — do not
need each other's evidence and conflating them was scope creep this revision removes.)

### 2.4 Gates

- **N0 (byte identity, must hold):** with any explicit weighting, `ev5_fingerprint.py` before
  and after is identical on all three references.
- **N1 (the estimator recovers the truth) — measured, passes.** On the three `REFERENCES`, at
  1% proportional noise and a matched absolute-noise level, three seeds each, under the shipped
  GCV design: median ratio of estimated to injected σ is 0.57–0.71 (capacitor), 0.65–0.85
  (Maxwell-Wagner), 0.75–0.88 (Randles) — every one inside [0.5, 2.0]. The ferrite bead is
  carried as an informational row (21–140x over, as §2.2 predicts) rather than held to this
  bound; it is gated instead by N4. This replaces the original wording's "within a factor of 1.5
  at 90% of points", which the first implementation was never actually checked against; the
  median-based form is what §2.2's investigation used throughout.
- **N2 (ratchet on recovery) — measured on a 1-seed slice, fails; stays an opt-in lever.** The
  full plan is the 37 matched cells of `docs/CRITERION_SELECTION_PLAN.md` §9 re-run under
  `auto`, not yet run. A 3-reference, 1-seed slice was run instead as a fast first read (`--n2
  -seeds 1`, ~7 discover() calls, ~20 minutes single-threaded): `recovered` held on all three
  (the truth's equivalence class always reached the front), but **`recommended_correct` flipped
  from `True` to `False` on two of three references** — the capacitor and Randles both changed
  which candidate the parsimony rule picked, though not whether the truth was reachable. Two
  regressions is exactly the threshold this section's own rule names ("two or more and the
  default does not flip"), so the rule is doing its job: **`weighting="auto"` ships as an
  explicit opt-in only, on no path does it become a default**, pending the wider grid. One seed
  per reference is too little to say whether this is a real, mechanistic sensitivity (the
  reweighted chi² shifting which candidate falls inside `_well_fitting`'s band) or a coincidence
  of these particular noise draws; that question is exactly what the deferred 9-seed/37-cell run
  would answer; the deferred 37-cell grid is union, not replaced, with this 1-seed reading.
- **N3 (the capacitor's ESR) — re-measured after the GCV fix; now mixed rather than uniform,
  withdrawn either way.** The prediction was that `auto` reports a *smaller* relative standard
  error than `modulus` for the capacitor's ESR, because `modulus` under-weights it by a factor
  of Q (§2.1). Under the shipped GCV estimator, three seeds give 10.7% vs 7.4% (larger), 6.7% vs
  7.6% (smaller), 15.6% vs 7.7% (larger) — not the uniformly-larger result the pre-GCV estimator
  gave, but still no consistent improvement either. The withdrawal in §2.1 stands: the test data
  is generated under `simulate`'s own proportional-noise model, so a correctly-estimated `auto`
  weighting converges close to `modulus`'s own shape (both near `1/|Z|`) on exactly this data,
  which is why the sign of the difference is dominated by noise-realisation detail rather than
  by the mechanism §2.1 proposed. Untested, not disproven, on data whose true noise is *not*
  proportional.
- **N4 (the safe-failure-direction claim for a resonance) — measured, passes.** On the ferrite
  bead reference, `fit()` of the true topology to 1% noisy data under `weighting="auto"`
  recovered every parameter within 1% of truth and `relative_error` under 1.4% on all three
  seeds tried, despite σ being over-estimated 21–140x near the anti-resonance (N1's
  informational row). The safe-direction argument in §2.2 holds on this reference: an inflated
  local σ down-weighted the unmodelled region without preventing the fit from finding the true
  parameters elsewhere. This is one reference, not a proof that every resonance-bearing topology
  behaves the same way, and is recorded as such rather than generalised.

**N1-N4 above are, and were always, scoped to `simulate()`'s synthetic references — item C's
gate R2 gives that scope a measured reason rather than a caveat nobody had tested.** On seven
real spectra (43-72 points, not the denser synthetic sweeps N1 used), `weighting="auto"`'s
`chi2_reduced` is `1.6` to `3.1e4` -- six of seven land 1000x to 30000x above the [0.5, 3] band
N2's own decision rule assumed -- while `relative_error` stays a normal 0.16-12.5% throughout,
meaning the *fits* are fine and the *sigma estimate* is not. See §4.3 for the full measurement
and why `weighting="modulus"` fails the same check in the opposite direction. Nothing here
changes what N1-N4 measured; it changes what a reader is licensed to conclude from them about
real data, which was never demonstrated either way until §4.3 ran.

## 3. Item A — multi-condition joint fitting (built, gated, withdrawn)

**This section is kept in full rather than deleted, because the reason it is not shipped is not
that it failed.** Every gate below was measured and passed. §3.5 is why it was withdrawn anyway,
and it is the part worth reading before anyone reopens this question: the objection is not to
any number here, it is to what kind of judgement this software should be making at all.

### 3.1 Why this looked like the highest-effect item

`CLAUDE.md` says it in one sentence: several sweeps at different temperatures or DC bias,
fitted to one circuit simultaneously, is "the only instrument available here that can actually
*break* a degeneracy". Everything the project has built so far reports the equivalence class
honestly and then stops, because a single `Z(f)` genuinely contains no more. `R1-p(R2,C1)`
and `p(R1,C1-R2)` fit the same data to 1.2e-15 (`docs/HANDOFF.md` §3, gate I1), and whether
R2 is a grain boundary or an electrode interface is exactly the question a ceramic
measurement is taken to answer.

The mechanism is arithmetic, not hope. The exact correspondence between those two forms is

    R1' = R1 + R2        R2' = R1(R1+R2)/R2        C1' = R2^2 C1 / (R1+R2)^2

If R1 and R2 are each Arrhenius in temperature with *different* activation energies, then R1'
is a sum of two exponentials and is not Arrhenius, and neither is R2'. A model that says
"every resistance follows one Arrhenius law" is therefore satisfiable by one form and not by
its equivalent, and a temperature series decides between them. If the two energies are equal,
both forms remain Arrhenius and the class stays unbroken — which is the negative control, and
the report must say "still indistinguishable" in that case rather than pick.

### 3.2 Design (as built)

**Data model.** A `SpectrumSet`: an ordered collection of `Spectrum` with, per spectrum, a
`condition` (float) and a `condition_kind` (`"temperature_K"`, `"bias_V"`, `"replicate"` or
`"index"`). The condition is a *label the user measured alongside the sweep*; it is not
knowledge about the part, and a run with `condition_kind="index"` is legitimate and yields
level 1 below.

**Level 1 — shared topology, free parameters.** One topology fitted independently per
condition, ranked by the *summed* weighted chi-squared and a parameter count of
`k × n_conditions`. This does not break degeneracy — fitting each spectrum alone and
intersecting would give the same class — but it pools evidence for the topology: a block whose
share of the response is too small to see in one spectrum can still show up once a second
condition where it carries more weight is fitted alongside it.

**Level 2 — parametric laws across conditions.** Each parameter *class* — resistive, reactive,
or everything else — is assigned one of three statuses: *shared* (one value across
conditions), *free* (one per condition), or *lawful* (an Arrhenius law across temperature). The
assignment is chosen by BIC over a lattice that is per parameter *class* rather than per
parameter (at most `3³ = 27` assignments per topology), each a genuine joint least-squares fit.

**What it would have reported**, had this shipped: under `interpret`, per lawful parameter an
activation energy with a standard error, which equivalence-class members a temperature series
*separated* and by how many BIC points, and which remain indistinguishable. This report was
never built (§3.5 explains it does not need to be, now).

### 3.3 Gates — all measured, all passing

Implemented as `core/spectrum.py`'s `SpectrumSet` and a new `core/multicondition.py`
(`discover_set` for level 1, `fit_joint`/`select_level2` for level 2), both since removed along
with their tests and benchmark (`git revert` of the commit that added them; the revert is the
only trace left in the repository's history, this section is the trace kept in its documentation).

- **A1 (the degeneracy breaks when it should) — PASS, 10/10 seeds.** `R1-p(R2,C1)` simulated at
  five temperatures 300-400 K with `Ea(R1) = 0.3 eV`, `Ea(R2) = 0.8 eV`, C1 shared, 1% noise.
  Level 2 ranked the true form ahead of its exact equivalent `p(R1,C1-R2)` by 43.1-61.3 BIC
  points on all ten seeds (bar: > 10), always via the assignment
  `{"resistive": "lawful", "reactive": "shared"}` against the equivalent's best-available
  `{"resistive": "free", "reactive": "free"}` — the equivalent's transformed resistances
  (`R1' = R1+R2`, `R2' = R1(R1+R2)/R2`) are sums of two exponentials and cannot be fitted by a
  single Arrhenius law when the two source energies differ.
- **A2 (and does not when it should not) — PASS, 10/10 seeds.** The same scenario with
  `Ea(R1) = Ea(R2) = 0.3 eV`. `|BIC gap|` stayed under 1.4 points on all ten seeds
  (0.000-1.327), far inside the 10-point band A1 uses to call a separation real.
- **A3 (energies are recovered) — PASS, 10/10 seeds.** On A1's data, both `Ea` estimates landed
  within 3 standard errors of truth on every seed (`Ea(R1)` to 0.2998-0.3003, stderr ~0.0001;
  `Ea(R2)` to 0.7987-0.8012, stderr ~0.0010-0.0011), and the calibration check held: seed-to-seed
  scatter over the ten runs was 1.47x the mean reported stderr for `Ea(R1)` and 0.87x for
  `Ea(R2)`, both inside the factor-of-2 band set in advance.
- **A4 (level 1 pools evidence) — PASS at 2 conditions, on a recalibrated scenario.** The plan's
  first design (a 100 Ω / 5000 Ω split, share 2% to 20%) turned out to be a trivial pass once
  investigated: 20% share alone was already enough for single-spectrum discovery to recommend
  the truth's equivalence class, so pooling with the 2% spectrum was shown to hurt nothing but
  not shown to help — and the naive "is the truth's own topology string on the front" check
  first read `False` even at 20% share, because an exact equivalence-class tie under a
  *different* topology string (`p(p(R1,C1)-R2,C2)`) occupied the literal slot, the same
  literal-string-match trap `docs/HANDOFF.md` warns about. Both were fixed: the check was
  rewritten to use the search's own `equivalents_of()`, and the scenario was rebuilt around two
  shares (2%, 5%) that both fail *individually* (single-spectrum `discover()` recommends the
  reduced 2-element `p(R1,C1)` model at either alone) so that the pooled result — the exact
  4-element truth, recommended once both spectra are fitted together — is attributable to
  pooling rather than to one condition already being sufficient.
- **A5 (O1 still holds) — not run.** No `SpectrumSet`-aware objective report was ever built
  (nothing to fingerprint for byte-identity); the structural half of the invariant (no
  `Objective` parameter anywhere in the module) held by inspection.

### 3.4 What this would not have claimed, even had it shipped

It would not have broken a degeneracy that temperature does not touch: two forms whose
parameters all share one energy stay a class. It would not have identified *which* mechanism an
energy belongs to — 0.8 eV is a number, not "grain boundary" — because naming the mechanism is
exactly the expert judgement `CLAUDE.md` point 3 exists to remove.

### 3.5 Why this was withdrawn despite passing every gate

**Passing A1-A4 answers "does the mechanism work", not "should this software be the one doing
it".** On review, the answer to the second question is no, for a reason distinct from every
other rejection in this document (§5's rejections are all "it does not work" or "it is not
worth the cost"; this one is "it works, and it is still the wrong thing to build"):

A temperature or a bias voltage is an experimental condition, not a value `Z(f)` contains —
unlike `pool` and `skeleton`, which narrow *which circuit elements* a search may use while
leaving every physical reading of the result to the analyst, level 2's `"lawful"` status asks
the software to decide *which law of nature* governs how the part's parameters move with that
condition (Arrhenius, here, chosen because `CLAUDE.md` named it — never Vogel-Tammann-Fulcher,
a power law, or "none, because the two conditions probe different physics"). Offering that
choice as a BIC-selected candidate rather than forcing it does not remove the judgement, it only
launders it: a non-expert reading a report that says "Ea(R1) = 0.3 eV, lawful" has been handed a
physical interpretation this software chose to test in the first place, on the analyst's data,
without being asked whether Arrhenius was ever the right family to test. That is a narrower
version of exactly the thing `CLAUDE.md`'s consequence "the software must not ask what kind of
part this is" already rules out for topology — extended here to *temperature response*, which
the original design of this item did not recognise as the same kind of question.

The corollary is where this software's job actually stops: producing the per-condition circuit
and its parameters (which `fit()`/`discover()` already do, one call per spectrum, with no
change needed) is in scope: relating those parameters *across* conditions via a named physical
mechanism is not, the same way permittivity and conductivity are out of scope even though they
would be a one-line calculation from a fitted capacitance if geometry were supplied. An analyst
who wants the Arrhenius plot can already get everything they need from this software's existing
per-spectrum output; drawing the conclusion is theirs to do, in whatever tool and with whatever
physical law they judge appropriate for their part.

**What survives, and what would need to be true before this is reopened.** The technical
result — a joint least-squares engine with a correct Arrhenius reparameterisation, a
parameter-class lattice selected by BIC, and level 1's evidence-pooling argument for *topology*
alone (§3.3, A4) — is not itself in question, and §3.6 records the one real numerical bug it
surfaced so it is not rediscovered by a future attempt. What would need to change is not a
number: it would be a reason this software should make a physical-law judgement it does not
make anywhere else, which nothing in this session's discussion supplied.

### 3.6 A numerical bug the gates caught before any of them passed

The first working version of the Arrhenius law used the textbook form,
`x(T) = x0 · exp(Ea/(kB·T))`, with `x0` bounded the same way a `"shared"`/`"free"` parameter is
(the data-derived per-parameter interval already used elsewhere). On A3's own scenario
(`Ea(R2) = 0.8 eV`) this put the true `x0` at ~1.06e-10 Ω — because `exp(0.8/(kB·300 K)) ~
2.8e13` while the *observed* R2 is a few thousand ohms, so the `T -> infinity` prefactor is many
orders of magnitude smaller — which sits below the resistor element's own hard lower bound of
1e-9 Ω. The optimizer could not reach it at any starting point: a direct comparison on one seed
gave `chi2_reduced ~ 1244` for `"lawful"` against `~1.28` for `"free"` on identical data, and the
lattice search consequently never chose `"lawful"` even though the data was generated by exactly
that law. The fix was a different parameterisation, not a wider bound (a wider bound only moves
the same problem to a different activation energy): anchoring the law at the *first observed
condition's own temperature* — `x(T) = x_ref · exp(Ea · (1/(kB·T) − 1/(kB·T_ref)))` — keeps the
fitted reference value inside the bounds `"shared"`/`"free"` already use, because it *is* one of
the values either status would report. The same seed then recovered `chi2_reduced ~ 1.27`
(matching `"free"`) with `Ea` accurate to four decimal places.

## 4. Item C — a measured-data arena

### 4.1 The gap

There is no measured impedance spectrum anywhere in this repository. Every gate — G1's 30/30,
EV1's 5/9, X4's 12/12, the 37-cell criterion table, the fourteen example datasets on the site —
is on data generated from a circuit in the vocabulary being searched, with 1% proportional
noise, independent across points, at 10 points per decade. That is the right way to *build* a
search, because a truth is needed to score recovery. It is not evidence for the claim on the
front of `CLAUDE.md`, that a non-expert with an instrument gets a defensible answer, because
an instrument produces things the generator never does: a noise floor that is additive at high
`|Z|` and proportional at low, a lead inductance that is not in the part, a low-frequency drift
that violates KK, points that are simply wrong, and a spectrum that the vocabulary does not
contain at all.

`docs/AUTOEIS_COMPARISON.md` §0 records that AutoEIS's preprocessing deletes 6–37% of a sweep
before its search sees it. That number came from real-shaped data; this project has never
found out what its own pipeline does to such data, and it has no reader that has been run
against a real `.DTA` or `.mpt` file.

### 4.2 Design (as built)

**Implemented at 7 datasets, not the ten-to-twenty planned, and with zero from the ceramic
literature despite that being the use case `CLAUDE.md` names — both recorded as shortfalls,
not rounded away.** The candidate sources named above were searched (two rounds, one for
Gamry/BioLogic format specs and real sample files, one for open-licence real spectra more
broadly: impedance.py, pyimpspec, DearEIS, Zenodo). What survived a real check on the licence
and on whether the file is actually a *measurement* rather than a synthetic test fixture:

| id | system | licence | source |
|---|---|---|---|
| `impedancepy-generic` | unnamed cell (impedance.py's own tutorial fit target) | MIT | impedance.py |
| `impedancepy-gamry` | unnamed cell, REF3000 potentiostat, -50 mV bias | MIT | impedance.py |
| `impedancepy-biologic` | LSC thin film near OCV, SP-150 potentiostat | MIT | impedance.py |
| `impedancepy-zplot` | unnamed cell, ZPlot 3.2c sweep | MIT | impedance.py |
| `zenodo-21700-id15` | 21700 NMC811 Li-ion cell, 30% SoC | CC-BY-4.0 | Zenodo 15422339 |
| `zenodo-21700-id34` | a second, nominally identical 21700 cell | CC-BY-4.0 | Zenodo 15422339 |
| `zenodo-kendall-electrode` | Kendall Ag/AgCl reference electrode | CC-BY-4.0 | Zenodo 17691812 |

`benchmarks/measured/datasets.py` carries this table plus each dataset's `artefact` (which of
§4.1's real-instrument effects it was chosen to show) and, for `impedancepy-generic` alone,
`published_circuit` (impedance.py's own tutorial fit, `R_0-p(R_1,C_1)-p(R_2,C_2)-Wo_1` — a
notebook demonstration, not a peer-reviewed source, kept as exactly that kind of citation).
Two more real, real-licenced datasets were found and are **not** in the arena: a Mg-alloy
corrosion series (CC0) and a PEO-KTFSI solid electrolyte temperature series (CC-BY), both
excluded because their frequency axis is not in the file — it would have to be *reconstructed*
from a stated sweep recipe (points-per-decade, start/end frequency), which is exactly the
generated-not-measured character this arena exists to get away from. A vendor Autolab export
and a spatially-resolved PEM fuel-cell file were also found and set aside for parsing reasons
specific to their own text layout, not for anything to do with licence or authenticity.

New readers were required and are shared, general-purpose code, not arena-only glue:
`io/gamry.py` and `io/biologic.py`, closing `docs/HANDOFF.md` §6 item 4. Both are verified
against the real vendor files above, not only hand-built fixtures — the Gamry reader is
exercised against a file whose `ZCURVE` impedance table sits *after* an unrelated `OCVCURVE`
table, and the BioLogic reader against both sign conventions its format uses for the imaginary
column (`-Im(Z)/Ohm`, negated, and the less common already-signed `Im(Z)/Ohm`).

Because there is no truth, the gates are stability gates, each written so it can fail --
`benchmarks/measured/measured.py`:

- **R1 (the readers) — [measured] PASS, 7/7.** Every file is read by its format's reader
  without error; `f`, `|Z|` range and point count are reported. There is no vendor software on
  this machine to compare the point count against — recorded as a real limitation of the check
  rather than silently worked around — so what R1 actually confirms is narrower than planned:
  every reader terminates and produces a spectrum shaped like the file, not that the vendor's
  own tool would report the same count.
- **R2 (the pipeline finishes and its numbers mean something) — [measured] FAIL, 1/7, and the
  reason is the more important result than the count.** See §4.3.
- **R3 (split-half stability) — [measured] FAIL, 1/7 (14%), bar was 80%.** The recommended
  candidate's canonical topology on the odd-indexed points matched the even-indexed points'
  exactly once, on `impedancepy-zplot` (the dataset with the smallest chi2 divergence in R2).
  This check is deliberately the strict, literal-string version — it does not know two runs'
  exact reparameterisations are the same model, unlike `DiscoveryResult.equivalents_of` within
  one run — so 14% is a *ceiling* on how often a genuinely equivalence-class-aware version would
  pass, not a measurement of it; that weaker, harder check was not built (§4.4).
- **R4 (agreement with the literature, reported, not scored) — [measured], the one dataset that
  qualifies.** `impedancepy-generic`'s tutorial-fitted `R1-p(R2,C1)-p(R3,C2)-Wo1` is **absent**
  from this project's own candidate list for that spectrum entirely -- not on the front, not
  evaluated as an exact equivalent, not present under any canonical form. Exactly one data
  point, reported as the table format promises: no pass fraction, because the published circuit
  was chosen by the expert this project exists to replace and may itself be wrong, and this
  project's own search may just as easily be the one missing something on real, drifting data.
- **R5 (the site) — done.** Three of the seven join the Data screen's example panel
  (`impedancepy-generic`, `impedancepy-biologic`, `impedancepy-gamry`), marked "measured" with
  their citation and licence rendered in place of a circuit/noise line, and no "show the
  command" row, because nothing generated them. [measured, in Chrome via a Playwright session]
  loading `impedancepy-gamry` end to end -- 72 points, 15.9 mHz .. 200 kHz, matching the CLI's
  own `read()` exactly -- runs Lin-KK (FAIL, systematic, runs z = -6.76) and draws all four
  plots with no console error. The other four arena datasets are not on the site: two need a
  `reader_hints` positional-column override the browser's upload path has no way to carry (only
  a filename crosses into Pyodide's filesystem, per `bridge.worker.ts`'s `upload()`), so they
  stay Python-only rather than being force-fit through sniffing that would guess wrong.

### 4.3 What R2 actually found, and it is not what §4.1 predicted

The prediction on record before this ran was that R2 would fail on lead inductance and drift.
Both effects are visible -- two of seven datasets fail Lin-KK outright, one with a systematic
runs z of -6.76 -- but they are not why R2 fails. **What actually happens is that
`chi2_reduced` has no usable meaning on real data under either weighting this project has, in
opposite directions, while the fit quality underneath is fine:**

[measured] on `impedancepy-generic` (a 3-element fit, `R1-CPE1-p(R2,CPE2)`) and
`zenodo-21700-id15` (`CPE1-L1-p(C1,R1)`), `relative_error` -- the weighting-independent,
percent-scale number -- is essentially unchanged between weightings (12.22% vs 12.46%; 2.35%
vs 2.58%), while `chi2_reduced` moves by **six to eight orders of magnitude**:

| weighting | `impedancepy-generic` chi2_reduced | `zenodo-21700-id15` chi2_reduced |
|---|---|---|
| `modulus` | 0.0078 | 0.00029 |
| `auto` | 30690 | 16010 |

Run across the whole arena, the pattern is total and consistent, not a property of those two
picks: under `weighting="auto"` every one of the seven real datasets' `chi2_reduced` is
`1.6` to `3.1e4` (six lie between 1242 and 30690; only `impedancepy-biologic` at 1.56 falls
inside the planned [0.5, 3] band), while `relative_error` stays a normal-looking 0.16% to
12.5% throughout. Under `weighting="modulus"` every single one of the seven instead lands
between `1.3e-6` and `9.8e-4` -- three to six orders of magnitude *below* 0.5, the opposite
failure direction, on every dataset with no exception.

That symmetry is the finding. `weighting="auto"`'s GCV-LOESS sigma(f) estimator (item B) was
gated only against `simulate()`'s synthetic proportional-noise spectra (§2.4's N1-N4), which
have far more points per decade and a noise process the estimator's cross-validated bandwidth
was built around; on a 43-72 point real sweep it is not merely imprecise, it is wrong by many
orders of magnitude, driving `chi2_reduced` far *above* any usable band. `weighting="modulus"`
was never fit to an absolute noise scale at all -- its apparent chi2_reduced near 1 on this
project's *synthetic* references was always a coincidence of `simulate()`'s injected noise
level lining up with `1/|Z|`'s shape, not a property that says anything about a real
instrument's noise floor, and on real data that coincidence does not hold, so chi2_reduced
collapses far *below* any usable band instead. **Neither weighting this project has gives R2's
originally-specified [0.5, 3] chi2 criterion a number worth reading on measured data.** This is
not a search failure and not evidence the recommended topologies are wrong -- `relative_error`
says the curves track the data about as well under either weighting -- it is evidence that an
absolute goodness-of-fit threshold calibrated on synthetic noise does not transfer to an
instrument, which is exactly the kind of thing this arena exists to find and was never visible
in any gate run before it.

**What follows, recorded rather than fixed here:** item B's own N1-N4 gates are unaffected --
they were always scoped to the synthetic `REFERENCES`, and that scope now has a concrete,
measured reason to stay explicit rather than be read as "how the estimator behaves." A revised
R2 would have to either drop the chi2-band criterion in favour of `relative_error` plus the
Lin-KK verdict (both of which behave sensibly here), or estimate sigma(f) from something a
43-72 point real sweep can actually support -- neither is attempted here, both are named as
what a future pass at item B or at this arena would need to try. §4.2's R2 row above reports
FAIL because the plan's own criterion was FAIL as written; softening the number after seeing it
would be exactly the failure mode this document's own culture exists to catch.

### 4.4 Two things this round did not build

The lead-inductance and drift follow-ups §4.1 anticipated are still real, still visible in two
of seven Lin-KK verdicts, and still not attempted: an L in series at the terminals is a
*reporting* question once the fitted ESL can be compared against what the frequency window can
resolve, and the Lin-KK per-point residual already exists to tell a user *which* points in a
drifting sweep fail rather than that the whole sweep does. Separately, R3's 14% is measured
under the strict literal-topology comparison stated in §4.2 on purpose; an equivalence-class-
aware version -- checking whether the *even*-half recommendation, refit to the *odd* half's
data, reaches the same score as the odd half's own recommendation -- would answer the sharper
question and was not built for this round.

## 5. Considered and not included, with the reason

- **A Kramers-Kronig test that validates a resonator.** `docs/KK_RESONANCE_PLAN.md` §2 built
  the obvious fix and measured it destroying the test; §5 says the remaining fix is a different
  order-selection design. Not re-opened here, because item B's estimator (iii) is a way to get
  σ(f) that does not go through the KK basis, which removes the one new reason this plan would
  have had to touch it.
- **Equivalence-class dedupe before fitting** (`docs/SEARCH_TIME_PLAN.md` §3.4, 4.4–5.9x).
  Effort is not the objection; the two structural reasons on record are — no cheap exact test
  runnable before a fit, and tier 2 refits every class member regardless. A plan that
  disregards effort still cannot buy a test that does not exist.
- **Streaming tier-1 dispatch** (§3.2). Measured to fail byte identity through a stale
  `abandon_above`. Not a purpose item.
- **A statistical trigger for growth** (`docs/TOPOLOGY_6PLUS_PLAN.md` §5.12). Four candidates
  measured on 108 labelled rows; none dominates. Section 6 replaces the trigger's *role* with a
  budget rather than proposing a fifth candidate — with one exception noted there, which is a
  new instrument (item B's absolute chi-squared) and gets one measurement, not a promise.
- **Pyodide cold start, offline, `file://`.** Closed by measurement in
  `docs/STARTUP_AND_EDITING_PLAN.md` §8.3 and `docs/WEB_UI_PLAN.md` §2.8; not purpose items.
- **Permittivity, conductivity, thickness, "what kind of part is this".** Out of scope by
  decision, `CLAUDE.md`, and this plan adds nothing that needs them.
- **A Maxwell-Wagner named template.** The topology falls out of the grammar and
  `p(R1,C1)-p(R2,C2)` is already a reference; `interpret.py`'s existing per-block quantities
  already read it. Nothing separate to build.
- **Multi-condition joint fitting (activation energies across a temperature or bias series).**
  Built and gated (§3, A1-A4 all passing), then withdrawn: relating parameters across
  experimental conditions via a named physical law is the analyst's own judgement to make
  outside this software, not a narrowing this software should offer even as an opt-in candidate
  — see §3.5 for the full argument, which is the one rejection in this list based on what kind
  of judgement the software should make rather than on a measurement of whether it works.

## 6. Item D — the fallback runs on the budget, and `recommended()` tells the truth

### 6.1 D1: the sentence (small, first) — **done**

`docs/TOPOLOGY_6PLUS_PLAN.md` §5.10 measured the case: a truth-equivalent reaches the front
with `n_unresolved = 0` and an AICc 29–34 points better, and is declined because it sits
inside `PARSIMONY_CHI2_FACTOR`'s band and loses the `(complexity, aicc)` tie-break — while the
report prints "the extra elements are not supported by the data" beside "0 of them
unresolved". **Implemented**: `DiscoveryResult._decline_reason` names which of `unresolved`,
`inside_band` or `outside_band` applies, `summary()` renders a matching sentence for each, and
`by_criterion_decline_reason` carries the same value on the wire (`to_dict()`, and
`web/src/core/types.ts` for the browser, though nothing in the UI reads it yet).
`tests/test_discover.py::test_by_criterion_decline_reason_distinguishes_unresolved_from_inside_band`
constructs the §5.10 case directly (hand-picked scores, not a live search) and checks the
reason is `inside_band`; a second test checks the original `unresolved` sentence is untouched
when the reason really is that. **Gate held**: `benchmarks/ev5_fingerprint.py` before/after is
identical except for the new `by_criterion_decline_reason` key itself — no existing number
moved. See `docs/TOPOLOGY_6PLUS_PLAN.md` §5.10's added note.

### 6.2 D2: growth on the budget

The fallback's trigger has been measured twice not to work as a trigger — never firing on
forty real-shaped runs (`docs/AUTOEIS_COMPARISON.md` §2.2), and with no measured replacement
that dominates it (§5.12). `CLAUDE.md` says budget-shaped controls are the user's; "how
thorough" is one. So the proposal is that when the user has given a `--time-limit` and the
exhaustive stage finishes inside it, the remainder goes to the growth stage at `GROWTH_WIDTH`,
and the coverage line reports `complete_up_to` and `grown_to` exactly as §4.7 already
requires. `GROWTH_DEFAULT` stays `0` for a run with *no* time limit, so nothing changes for
anyone who did not ask. The browser gains the same control in the Advanced panel.

One measurement with the new instrument item B provides, run once and not promised: the best
five-element model's absolute `chi2_reduced` under the estimated σ(f), on the 108-row X3 set.
X3's four candidates were all relative statistics; an absolute one has not been tried. If it
does not dominate the runs test on both axes, it is recorded beside the other four and not
shipped.

Gate **D2a**: on X4's six shapes at a 300 s budget, `par6`/`mix6`/`par7`/`mix7` recommended
12/12 as before, and `ser6`/`ser7` reported as grown-to-six-nothing-better rather than as
complete. Gate **D2b**: with no time limit, `ev5_fingerprint.py` is byte-identical.

## 7. Item E — uncertainty the report can stand on

The standard errors come from a linearised covariance at the optimum, scaled by
`chi2_reduced`. Two quantities are reported to a non-expert on that basis and each is used
to *decide* something: `n_unresolved` (which decides `recommended`) and `tau` with its
`sigma_tau` (the `interpret` headline). (`E_a` would have been a third had item A shipped;
it did not — see §3.5.) For a CPE exponent near its bound or a pair of strongly correlated
parameters, a linearised interval is known to be wrong in the direction of over-confidence.

Design: profile likelihood on the tier-2 shortlist for the parameters that feed those two
quantities, and a parametric bootstrap — the one X3 already measured as calibrated to within
one event of its 5% target — for the derived quantities. Both stay in the reporting layer;
`recommended` reads `n_unresolved` from whichever interval the gate below picks.

Gate **E1 (measure the linearised one first)**: on the three `REFERENCES` and the six
`six_plus` truths at 1% noise, 200 draws each, the coverage of the linearised 95% interval for
every parameter. If it covers 90–98% everywhere, this item ships nothing except the
measurement, recorded in this document. Gate **E2**: where E1 shows under-coverage, the profile
interval covers 90–98% on the same draws and `recommended` on the 37-cell table is no worse.

## 8. Order of work, and why

1. **D1**, because it is a sentence that is wrong today and costs nothing to fix. **Done.**
2. **B**, because it is the item that changes what a single-spectrum user gets. **Done, opt-in
   only.**
3. ~~**A**~~ — built and gated (§3), then withdrawn on a scope decision (§3.5); no longer part
   of this sequence.
4. **C**, so the readers have real files and the pipeline has a spectrum it did not generate.
   **Done** (§4) — 7 real, licensed datasets, new Gamry/BioLogic readers, and a gate (R2) that
   found item B's noise model does not generalise past the synthetic data it was gated on.
5. **E**, uncertainty beyond the linearised standard error for `n_unresolved` and τ.
6. **D2**, last, because its one new measurement needs B and its budget semantics are
   independent of everything else.

Each item lands with its gates recorded in this document in the form the repository uses:
[measured], with the number, and with a withdrawn reading left in place beside the correction
rather than reworded.

## 9. Files this plan expects to touch

| Area | Files |
|------|-------|
| Noise model (B) | `core/weighting.py` (new `"auto"`), a new `core/noise.py`, `core/validate.py` (expose per-point KK residual), `core/spectrum.py` (`sigma_re`, `sigma_im` fields), `cli/main.py`, `web/bridge.py`, the Data screen's `KKPanel.tsx` |
| Multi-condition (A) | **Withdrawn (§3.5); nothing to touch.** Was `core/spectrum.py` (`SpectrumSet`) and a new `core/multicondition.py`, both built, gated and removed by `git revert` -- see §3.3's note on where the trace of that work now lives. |
| Measured arena (C) | **Done.** `benchmarks/measured/` (`datasets.py`, `measured.py`, `data/`), `io/gamry.py`, `io/biologic.py` (new readers, registered in `io/__init__.py`), `web/scripts/measured-samples.mjs` (new), `web/scripts/build-assets.mjs`, `web/src/core/samples.ts`, `web/src/components/SamplePanel.tsx` |
| Fallback and sentence (D) | `core/discover.py` (`recommended`, `_evolve` budget), `core/objective.py`, `SearchPanel.tsx` |
| Uncertainty (E) | `core/stats.py`, `core/interpret.py`, `benchmarks/fitting.py` |

Nothing here adds a runtime dependency; every estimator and interval above is numpy and
scipy, which is the hard rule that keeps the same wheel running in the browser.
