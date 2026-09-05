# Impact plan: what would move the project most, effort disregarded

Status: **plan only; nothing in this document is implemented.** Written 2026-09-04 after a
survey of every document in `docs/`, the core modules, the benchmarks and the web front end
(the survey was delegated to three read-only subagents; what they reported is summarised in
section 1, with one correction).

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
| A | **Multi-condition joint fitting** (temperature or bias series fitted to one circuit, with a parametric law across conditions) | 2 — the only instrument that can *break* an equivalence class | §3 |
| B | **A noise model estimated from the spectrum**, replacing the weighting knob's status as a user decision | 3 — a knob the target user cannot set correctly; and it is the prerequisite for A and C | §2 |
| C | **A measured-data arena** — the repository has no real spectrum in it, so every gate to date is on data generated from the model family being searched | 3 — "the same answer" has only ever been shown on synthetic data | §4 |
| D | **The genetic fallback runs on the user's budget, not on a trigger that never fires**, and `recommended()`'s sentence says its real reason | 1 and honest reporting | §6 |
| E | **Uncertainty beyond the linearised standard error** for the quantities the report leans on: `n_unresolved`, τ, and A's activation energies | honest reporting | §7 |

Order of work is D1 → B → A → C → E → D2 (section 8). B goes before A because A compares
chi-squared across spectra measured under different conditions, which is meaningless unless
each spectrum's noise is on a common footing; C goes after A because C's datasets include
temperature series, and A is what makes those worth having.

## 1. What the survey found

Three subagents surveyed the repository read-only. What matters from their reports:

**Open items on record** (`docs/`): multi-condition fitting is named in `CLAUDE.md` and
`docs/OBJECTIVE_PLAN.md` §8 as the one `interpret`-only extension, and is not started. The
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

**One correction to the survey.** The core-audit subagent reported activation energies as
"out of scope per the geometry rule". That is wrong, and the plan depends on it being wrong:
`CLAUDE.md` puts activation energies *inside* scope, because a temperature series adds only
more spectra and an activation energy is a ratio of rates that needs no length or area. The
geometry ban removes permittivity, conductivity and thickness; it does not remove E_a.

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

## 3. Item A — multi-condition joint fitting

### 3.1 Why this is the highest-effect item

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

### 3.2 Design

**Data model.** A `SpectrumSet`: an ordered collection of `Spectrum` with, per spectrum, a
`condition` (float) and a `condition_kind` (`"temperature_K"`, `"bias_V"`, `"replicate"` or
`"index"`). The condition is a *label the user measured alongside the sweep*; it is not
knowledge about the part, and a run with `condition_kind="index"` is legitimate and yields
level 1 below. Readers gain an optional condition column and the CLI an optional
`--condition` list; the Data screen already loads several spectra and gains one column.

**Level 1 — shared topology, free parameters.** `discover()` on a `SpectrumSet` searches one
topology whose parameters are fitted independently per condition, ranked by the *summed*
weighted chi-squared and a parameter count of `k × n_conditions`. This does not break
degeneracy — fitting each spectrum alone and intersecting would give the same class — but it
pools evidence for the topology: a block that carries 2% of the polarisation at one
temperature and 20% at another (`docs/HANDOFF.md` §21 item 5 is the 2% case that is not
recoverable alone) is recoverable from the pair. Screening cost is `n_conditions` times a
single screen; `screen_plan()`'s batches simply carry several spectra.

**Level 2 — parametric laws across conditions.** Each parameter is assigned one of three
statuses: *shared* (one value across conditions), *free* (one per condition), or *lawful*
(`x(T) = x0 · exp(E_a / k_B T)` for temperature; a polynomial in V for bias, degree chosen the
same way). The assignment is **not asked of the user**: for each topology on the front, the
assignment is chosen by BIC over a lattice that is small because it is per parameter *class*
rather than per parameter — all R-type parameters take one status, all C/L-type another, CPE
exponents a third — which is 3³ = 27 assignments per topology, each a joint fit. That is the
"expensive by design" part of this plan, and it is confined to the tier-2 shortlist, never
tier 1.

**What it reports.** Under `interpret`: per lawful parameter, `E_a` with a standard error
propagated through `log_covariance` the way `tau` already is; which equivalence-class members
the series *separated* and by how many BIC points; which remain indistinguishable; and an
Arrhenius table (ln x against 1/T) for the DRT-side peaks, which are invariant. Under `model`:
one subcircuit per condition and nothing about energies, because it buys `model` nothing.

**The invariant it must not break.** The objective still never reaches a number. The joint fit
is triggered by the *data* having several conditions, not by the objective; both objectives on
the same `SpectrumSet` produce a byte-identical `DiscoveryResult`, and `benchmarks/o1_objective.py`
extends to a `SpectrumSet` input to say so.

### 3.3 Gates

- **A1 (the degeneracy breaks when it should):** `R1-p(R2,C1)` simulated at five temperatures
  between 300 K and 400 K with `E_a(R1) = 0.3 eV`, `E_a(R2) = 0.8 eV`, C1 shared, 1% noise, ten
  seeds. Level 2 on the pair of forms must rank the true form ahead of its equivalent by more
  than 10 BIC points on 9 of 10 seeds, and the report's class line must say which form the
  series selected.
- **A2 (and does not when it should not):** the same with `E_a(R1) = E_a(R2)`. The two forms
  must be reported as **still equivalent** — same score to within the class tolerance — on 10
  of 10 seeds. A plan that passes A1 and fails A2 has built a machine that picks a form the
  data cannot support, which is worse than what exists now, and ships nothing.
- **A3 (energies are recovered):** on A1's data, `E_a` for each resistance within 3 standard
  errors of the generating value on 9 of 10 seeds, and the standard error itself within a
  factor of 2 of the seed-to-seed scatter (the calibration item E measures more generally).
- **A4 (level 1 pools evidence):** `p(R1,C1)-p(R2,C2)` at the 100/5000 Ω split that
  `docs/HANDOFF.md` §21 records as unrecoverable from one spectrum, simulated at two
  temperatures chosen so the small block's share rises to 20% at the second. Level 1 must
  report the two-block truth on the front where single-spectrum discovery on either sweep alone
  does not. If a two-temperature pair does not do it, the gate records the number of
  temperatures that does, and if none under ten does, the section's level 1 claim is withdrawn.
- **A5 (O1 still holds):** byte-identical `DiscoveryResult` under both objectives on a
  `SpectrumSet`, structural half included — `discover()` and `fit()` still import nothing from
  the reporting layer.

### 3.4 What this does not claim

It does not break a degeneracy that temperature does not touch: two forms whose parameters all
share one energy stay a class, and the report says so. It does not identify *which* mechanism
an energy belongs to — 0.8 eV is reported as a number, not as "grain boundary", because that
step is the expert judgement `CLAUDE.md` point 3 exists to remove and this software does not
know what kind of part it has.

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

### 4.2 Design

Collect a set of publicly available measured spectra with licence and citation recorded
beside each — the candidates to verify are the example data shipped with `impedance.py`,
DearEIS and pyimpspec, Zenodo battery EIS releases, and the vendor sample files Gamry and
BioLogic publish for their formats. Each dataset carries: the instrument and its format, the
published circuit *if the source fitted one* (as a reference, never as a truth), the
temperature or bias if it is a series, and the reason it is in the arena (which of §4.1's
artefacts it exhibits). Ten to twenty datasets, at least three of them temperature series so
that item A has something real to run on, and at least two from the ceramic literature because
that is the use case named in `CLAUDE.md`.

Because there is no truth, the gates are stability gates, and each is written so it can fail:

- **R1 (the readers):** every file is read by its format's reader with the same point count the
  vendor's own software shows. This closes `docs/HANDOFF.md` §6 item 4 with the real files it
  was waiting on.
- **R2 (the pipeline finishes and its numbers mean something):** on every dataset, Lin-KK
  produces a verdict, `--pool auto --weighting auto` produces a front, and the recommended
  model's `chi2_reduced` under item B's σ(f) lies in [0.5, 3]. Outside that band the pipeline
  is over- or under-claiming and the dataset becomes a named open item.
- **R3 (split-half stability):** the recommended *class* on the odd-indexed frequency points is
  the same class as on the even-indexed points, on at least 80% of datasets. This is the
  nearest thing to "the same answer" that is measurable without a truth.
- **R4 (agreement with the literature, reported, not scored):** for each dataset with a
  published circuit, whether that circuit or an exact equivalent is on the front, is
  recommended, or is absent — as a table, with no pass fraction, because the published circuit
  was chosen by the expert this project is trying to replace and may itself be wrong.
- **R5 (the site):** at least three measured datasets join the example panel, marked
  "measured" and carrying their citation, so that the first spectrum a visitor tries can be a
  real one.

### 4.3 What R2 is likely to find, and what to do about it

The expectation, stated so it can be contradicted, is that R2 fails first on lead inductance
and on drift: a real capacitor sweep carries a fixture's inductance that the exhaustive stage
will spend an element on, and a real low-frequency electrochemical sweep drifts in a way
Lin-KK will flag and the search will then fit with a spurious element. Neither is a search
problem. The first is a *reporting* one — an L in series at the terminals is a fact about the
measurement and the report can say so once it can compare the fitted ESL against what the
frequency window can resolve. The second is a data-screen one — the trim panel exists, and the
Lin-KK residual per point can tell the user *which* points fail rather than that the sweep
fails. Both are listed here as the follow-ups R2 would generate, not as work this plan
schedules.

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
  decision, `CLAUDE.md`, and this plan adds nothing that needs them: a temperature is a label
  on a sweep, not a property of the part.
- **A Maxwell-Wagner named template.** The topology falls out of the grammar and
  `p(R1,C1)-p(R2,C2)` is already a reference; the dielectric-oriented readouts it would carry
  are item A's E_a and `interpret.py`'s existing per-block quantities. Nothing separate to build.

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
`chi2_reduced`. Three quantities are reported to a non-expert on that basis and each is used
to *decide* something: `n_unresolved` (which decides `recommended`), `tau` and its
`sigma_tau` (the `interpret` headline), and, after item A, `E_a`. For a CPE exponent near its
bound or a pair of strongly correlated parameters, a linearised interval is known to be wrong
in the direction of over-confidence.

Design: profile likelihood on the tier-2 shortlist for the parameters that feed those three
quantities, and a parametric bootstrap — the one X3 already measured as calibrated to within
one event of its 5% target — for the derived quantities. Both stay in the reporting layer;
`recommended` reads `n_unresolved` from whichever interval the gate below picks.

Gate **E1 (measure the linearised one first)**: on the three `REFERENCES` and the six
`six_plus` truths at 1% noise, 200 draws each, the coverage of the linearised 95% interval for
every parameter. If it covers 90–98% everywhere, this item ships nothing except the
measurement, recorded in this document. Gate **E2**: where E1 shows under-coverage, the profile
interval covers 90–98% on the same draws and `recommended` on the 37-cell table is no worse.

## 8. Order of work, and why

1. **D1**, because it is a sentence that is wrong today and costs nothing to fix.
2. **B**, because A and C both need a σ(f) that comes from the data, and because it is the
   only item that changes what a single-spectrum user gets.
3. **A**, the highest-effect item, on synthetic series first (A1–A5).
4. **C**, so that A has real series to run on and the readers have real files.
5. **E**, once A has added `E_a` to the list of numbers that need an interval.
6. **D2**, last, because its one new measurement needs B and its budget semantics are
   independent of everything else.

Each item lands with its gates recorded in this document in the form the repository uses:
[measured], with the number, and with a withdrawn reading left in place beside the correction
rather than reworded.

## 9. Files this plan expects to touch

| Area | Files |
|------|-------|
| Noise model (B) | `core/weighting.py` (new `"auto"`), a new `core/noise.py`, `core/validate.py` (expose per-point KK residual), `core/spectrum.py` (`sigma_re`, `sigma_im` fields), `cli/main.py`, `web/bridge.py`, the Data screen's `KKPanel.tsx` |
| Multi-condition (A) | `core/spectrum.py` (`SpectrumSet`), `core/fit.py` (joint residual and Jacobian), `core/discover.py` (`screen_plan` over a set; level 2 lattice on the shortlist), `core/interpret.py` (`E_a`, series-separated class line), `core/objective.py`, readers in `io/`, `cli/main.py`, `web/bridge.py`, `DataScreen.tsx`, `ReportScreen.tsx` |
| Measured arena (C) | `benchmarks/measured/` (new), `io/gamry.py`, `io/biologic.py` (new), `web/public/samples/` |
| Fallback and sentence (D) | `core/discover.py` (`recommended`, `_evolve` budget), `core/objective.py`, `SearchPanel.tsx` |
| Uncertainty (E) | `core/stats.py`, `core/interpret.py`, `benchmarks/fitting.py` |

Nothing here adds a runtime dependency; every estimator and interval above is numpy and
scipy, which is the hard rule that keeps the same wheel running in the browser.
