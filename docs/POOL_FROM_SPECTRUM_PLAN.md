# The default pool, and why it may not be a decision about the part

Status: **implemented in the core and the CLI; gates C1-C6 measured; the browser is not
wired.** Written 2026-08-22.

`CLAUDE.md` states the rule this document exists to repair:

> the current default pool `("R","C","L","CPE")` does *not* yet do this and silently excludes
> the diffusion elements, which is an open violation of that rule rather than a
> counter-example to it

The rule is that the automatic path takes the spectrum and nothing else, and that whatever the
search would have gained from knowing what kind of part this is must be **derived from the
spectrum's own shape**. A default pool that omits `W`, `Ws`, `Wo` and `G` is a judgement about
the part -- "this is not an electrochemical cell" -- baked into a default that a non-expert
will never change, which is precisely the expert decision point 3 of the purpose exists to
remove. And it is invisible: the coverage sentence says *every plausible topology from this
pool*, which is true, and says nothing about a family of elements never being on the table.

## 1. The exclusion is real, and it is not small

The first question is whether the omission costs anything at all, because `CPE` spans a whole
band of exponents and might already cover what the diffusion elements do.

[measured] Truth generated at 1% proportional noise on 61 points from 0.01 Hz to 100 kHz, each
model fitted with `restarts=3`; `relerr` is RMS `|Z_model - Z_data| / |Z_data|`, so the noise
floor is about 1.4%.

| truth | truth's own fit | best 4-parameter default-pool form | best 7-parameter default-pool form |
|---|---|---|---|
| `R1-W1`  | 1.334% (AICc -1133.7) | `R1-CPE1` **1.334%** (-1131.6) | 1.314% (-1126.7) |
| `R1-Ws1` | 1.488% (-1105.0) | `R1-p(R2,CPE1)` 7.800% (-698.7) | 1.750% (-1056.7) |
| `R1-Wo1` | 1.420% (-1116.4) | `R1-p(R2,CPE1)` 23.559% (-429.0) | 2.711% (-949.9) |
| `R1-G1`  | 1.452% (-1111.0) | `R1-p(R2,CPE1)` 5.353% (-790.6) | 1.802% (-1049.6) |

Two different answers in one table.

**`W` is already in the pool under another name.** A semi-infinite Warburg *is* a CPE at
`n = 0.5` -- `A/sqrt(j w)` against `1/(Q (j w)^n)` -- and the fit says so to five figures:
1.3344% both ways. Adding `W` buys one parameter of parsimony, worth 2.1 in AICc, and nothing
else. So the code that looks most like the missing feature is the one code there is a measured
reason **not** to add.

**`Ws`, `Wo` and `G` are genuinely unreachable.** Each is a transmission line -- an infinite
ladder -- and no finite tree of R, C, L and CPE reproduces one. The default pool's best
four-parameter answer is 4x to 17x the noise floor, and buying it down to 1.75-2.71% takes
seven parameters against the truth's three, which is a worse model by every criterion in the
project and a nonsense one to read as internal structure.

## 2. Adding them all is not available

Pool size drives the exhaustive stage combinatorially. Topologies up to five elements, before
the feasibility screen:

| pool size | 1 | 2 | 3 | 4 | 5 | total |
|---|---|---|---|---|---|---|
| 4 (`R,C,L,CPE`) | 4 | 12 | 61 | 376 | 2,523 | **2,976** |
| 5 | 5 | 22 | 146 | 1,163 | 10,214 | 11,550 |
| 6 | 6 | 34 | 275 | 2,670 | 28,727 | 31,712 |
| 7 | 7 | 48 | 456 | 5,207 | 66,060 | 71,778 |
| 8 (`+W,Ws,Wo,G`) | 8 | 64 | 697 | 9,136 | 133,251 | **143,156** |

[measured] After the feasibility screen, on an `R1-Ws1` spectrum, at the default
`max_candidates = 20000`:

| pool | screened | `complete_up_to` |
|---|---|---|
| `R,C,L,CPE` | 2,887 | **5** |
| `R,C,L,CPE,Wo` | 9,702 | **5** |
| `R,C,L,CPE,Ws,G` | 2,433 | **4** |
| `R,C,L,CPE,W,Ws,Wo,G` | 6,687 | **4** |

So the naive repair -- make the default pool the electrochemical one -- trades a silent
exclusion of four element types for a loud exclusion of every five-element topology, and the
loud one is bigger. **One** added code is affordable and keeps the fifth level; two are not.
That is the budget this design has to work inside, and it is why "just widen the default"
is not the answer.

## 3. The obvious detector works on the easy half and fails on the half that matters

If only one or two codes can be afforded, something has to choose them, and by the rule that
something may only read `f` and `Z`.

The signature to look for is a constant-phase region at -45 degrees. Two corrections were
needed before it measured anything:

1. **The phase of `Z` is the wrong quantity, because a series resistance masks it.** `Ws`,
   `Wo` and `G` are all 45-degree at their *high*-frequency end, which is exactly where a
   series R dominates the total. A first detector built on `arg Z` and the local log-log slope
   of `|Z|` found `R1-W1` and `R1-Ws1` and **missed `R1-Wo1` and `R1-G1` entirely**. The fix is
   to differentiate: an additive constant vanishes from `dZ/d ln w`, so the quantity is the
   local Nyquist angle `atan2(dIm/dln w, -dRe/dln w)`, which is 45 degrees for a diffusion
   branch whatever is in series with it.
2. **The sign is the direction of travel.** A Nyquist plot is traversed towards *decreasing*
   frequency; with the derivative taken the other way every case reported no branch at all.

[measured] Longest contiguous run within 12 degrees of 45, in decades, over 3 seeds x 2 noise
levels (0.5%, 2%) x 4 frequency grids:

| truth | min | median | max |
|---|---|---|---|
| `R1-W1` | 3.20 | 5.15 | 7.30 |
| `R1-Ws1` | 1.60 | 3.43 | 5.02 |
| `R1-Wo1` | 1.60 | 3.33 | 4.90 |
| `R1-G1` | 1.00 | 3.33 | 4.90 |
| `R1-p(R2,C1)-Ws1` | **0.40** | 0.97 | 1.10 |
| `R1-p(R2,CPE1)-Wo1` | **0.20** | 0.40 | 0.60 |
| --- no diffusion --- | | | |
| `R1` | 0.00 | 0.05 | 0.20 |
| `R1-C1` | 0.00 | 0.00 | 0.35 |
| `R1-p(R2,C1)` | 0.00 | 0.10 | 0.35 |
| `R1-p(R2,C1)-p(R3,C2)` | 0.10 | 0.20 | 0.35 |
| `C1-R1-L1` | 0.00 | 0.00 | 0.00 |
| `p(R1,C1)-p(R2,C2)` | 0.10 | 0.20 | 0.30 |
| `R1-p(R2,CPE1)` | 0.20 | 0.35 | **0.50** |
| `R1-L1` | 0.00 | 0.00 | 0.40 |

On a spectrum that is *only* diffusion the separation is total: 1.00 against 0.50. On a
spectrum where a relaxation sits on top of the diffusion branch -- which is what a real cell
looks like -- `R1-p(R2,CPE1)-Wo1` lies **entirely inside** the no-diffusion range, and
`R1-p(R2,C1)-Ws1` straddles it. There is no threshold that admits the composite cases and
rejects a depressed arc, because the arc's own tangent sweeps through 45 degrees on its way
round and a second process in the same decade blends the two.

This is a negative result about the detector, not about the data: section 1 measured that the
information *is* present, since the truth beats every default-pool form by a wide margin on the
same spectra. A local shape statistic is simply not the instrument that reads it.

**Read this together with section 6, which gives the detector back.** What is rejected here is
the shape run as the *sole* trigger, and that judgement stands unaltered. The residual test
that replaces it in section 5 then turned out not to be a sole trigger either, and the two fail
on different spectra -- so the shape reading survives as one half of a union, at a threshold
this section's table is what sets. Nothing above is retracted; the conclusion "therefore use
the residual instead" is what section 6 corrects.

## 4. Which codes, once something has decided to widen

Whatever fires the widening, the choice of *which* diffusion codes to spend the pool slots on
is a separate question, and there the spectrum does answer. `Ws`, `Wo` and `G` are
indistinguishable at high frequency -- all three are exponent -0.5 there -- and differ only in
their DC limit: 0, -1 and 0. `EndpointBehaviour.low_band` already measures the interval of
low-frequency exponents the data admits, widened by tolerance plus three standard errors, and
the feasibility screen already trusts it to *drop* topologies. Asking it which codes are worth
a slot is the same question one step earlier.

[measured] Over the same 3 seeds x 2 noise levels x 4 grids, the set of codes whose
`dc_exponent` overlaps the measured band:

| truth | codes admitted (count of 24) |
|---|---|
| `R1-W1` | `W` 24 |
| `R1-Ws1` | `W,Ws,G` 17 / `Ws,G` 7 |
| `R1-Wo1` | `W,Wo` 12 / `W,Ws,Wo,G` 6 / `Wo` 6 |
| `R1-G1` | `W,Ws,G` 18 / `Ws,G` 6 |
| `R1-p(R2,C1)-Ws1` | `Ws,G` 18 / `W,Ws,G` 6 |
| `R1-p(R2,CPE1)-Wo1` | `W,Wo` 12 / `Wo` 6 / **`W,Ws,G` 6** |
| `R1-C1`, `C1-R1-L1` | `Wo` 24 |
| `R1`, `R1-p(R2,C1)`, `p(R1,C1)-p(R2,C2)`, `R1-p(R2,CPE1)`, `R1-L1` | `Ws,G` 24 |

The true code is in the admitted set in 138 of the 144 diffusion trials. The six misses are all
`R1-p(R2,CPE1)-Wo1` on the grids whose lowest frequency sits above the blocking region, where
the data simply does not reach the DC limit that identifies `Wo` -- a limit of the window, not
of the rule.

Two consequences.

**`W` is never worth a slot.** Section 1 measured that a CPE reproduces it exactly, so the one
code the band admits most often is the one code with a measured reason to leave out. On an
`R1-W1` spectrum the rule therefore adds *nothing*, and that is the right answer rather than a
failure: the pool already contains the element under another name.

**`Ws` and `G` are not substitutes, so admitting both costs the fifth level.** The tempting
saving is to keep only one, since both have the same asymptotes. [measured] Swapping them
costs 3.3x to 3.6x in relative error -- truth `R1-Ws1` fits at 1.333% and `R1-G1` at 4.334% on
the same data; truth `R1-G1` fits at 1.333% and `R1-Ws1` at 4.802% -- so the data does tell
them apart and dropping either one would exclude a distinguishable answer. Section 2's table
then applies: `Ws,G` is a six-code pool and `complete_up_to` falls from 5 to 4. The `Wo` case
costs nothing, because it is a single code.

### A fitting risk this widening brings with it

[measured] `R1-p(R2,C1)-G1` at 1% noise, fitted with its own generating topology, returns
15.055% relative error at `restarts=5, seed=1` and 1.313% at `restarts=20` for both seeds
tried -- and at 5 restarts the *wrong* topology `R1-p(R2,C1)-Ws1` scored better (2.599%) than
the right one. Five is `discover`'s `final_restarts` default. This is an ordinary
global-optimisation miss rather than a defect in the element, but it lands exactly where the
widened pool puts new five-parameter candidates, so a widened search that reports a diffusion
topology needs its refit budget checked rather than assumed.

## 5. Asking the search instead, and the trap beside it

The question the descriptor could not answer -- *does this spectrum need an element the pool
does not have* -- has an instrument that answers it directly, and `discover` already carries it.
`_is_underfitted` runs a Wald-Wolfowitz runs test on the sign pattern of the best fit's
residuals, and `mode="auto"` already consults it to decide whether to fall back to the genetic
search. A pool too narrow to express the data leaves the same fingerprint as a topology too
small: residuals that are large *and smooth in frequency* rather than large and random.

[measured] Full exhaustive search on the default pool, `exhaustive_limit=4`, 1% noise, 61
points; `runs_z` is the smaller of the two halves and the threshold is `RUNS_Z_LIMIT`:

| truth | best default-pool topology found | relerr | runs z | underfit |
|---|---|---|---|---|
| `R1-W1` | `p(R1-CPE1,C1)-L1` | 1.295% | +0.00 | **False** |
| `R1-Ws1` | `p(R1-C1-CPE1,R2)` | 2.522% | -4.91 | True |
| `R1-Wo1` | `p(CPE1-CPE2,R1)-C1` | 2.545% | -4.39 | True |
| `R1-G1` | `p(R1-C1-CPE1,R2)` | 1.615% | -3.10 | True |
| `R1-p(R2,C1)-Ws1` | `p(R1,L1)-p(CPE1,CPE2)` | 10.727% | -6.20 | True |
| `R1-p(R2,CPE1)-Wo1` | `p(R1-CPE1,CPE2)-C1` | 2.797% | -4.39 | True |
| --- no diffusion --- | | | | |
| `R1` | `p(L1,CPE1)-R1-L2` | 1.273% | -0.26 | False |
| `R1-C1` | `R1-C1-L1-CPE1` | 1.283% | -0.52 | False |
| `R1-p(R2,C1)` | `p(R1-C1,R2)-L1` | 1.297% | -0.26 | False |
| `R1-p(R2,C1)-p(R3,C2)` | `p(L1-CPE1,CPE2)-R1` | 24.191% | -6.20 | **True** |
| `C1-R1-L1` | `p(R1,L1)-CPE1` | 1.304% | -1.29 | False |
| `p(R1,C1)-p(R2,C2)` | `p(p(R1,C1)-C2,R2)` | 1.297% | -0.26 | False |
| `R1-p(R2,CPE1)` | `p(L1-CPE1,R1)-R2` | 1.296% | -0.77 | False |
| `R1-L1` | `p(R1-L1,C1-L2)` | 1.304% | -1.81 | False |

**Every one of the five truths the pool provably cannot express fires, including both
composite cases the shape descriptor lost.** And `R1-W1` -- the one diffusion truth the pool
*can* express, because a CPE is a Warburg -- does not fire, landing at the noise floor with
`runs_z` exactly 0.00. Section 1 predicted that from the fits and section 4 predicted it from
the band; the search agrees. The instrument that failed at reading the shape succeeds at
reading what the shape was evidence *for*.


### The element limit is a second cause of the same symptom, and it had to be measured out

`R1-p(R2,C1)-p(R3,C2)` fires at 24.191% with no diffusion anywhere in it. It is a five-element
truth searched to four: the test is right that the model is underfitted and wrong about why.
**A systematic residual has two causes -- the pool is too narrow, or the element limit is too
low -- and the runs test cannot tell them apart.** That matters because the two remedies pull
against each other: section 2 measured that widening the pool *costs* an element level, so
answering a size-starved search by widening its vocabulary makes the real problem worse.

[measured] At the production limit of five, where that truth is inside the enumerated space,
the false positive is gone -- and so is most of the trigger:

| truth | best default-pool topology found | relerr | runs z | fires at -3.0 |
|---|---|---|---|---|
| `R1-p(R2,C1)-p(R3,C2)` | `p(R1-C1,R2)-p(R3,CPE1)` | 1.299% | -0.26 | no |
| `p(R1,C1)-p(R2,C2)` | `p(p(R1,C1)-C2,R2)` | 1.297% | -0.26 | no |
| `R1-W1` | `p(L1-CPE1,L2)-R1-CPE2` | 1.260% | +0.00 | no |
| `R1-Ws1` | `p(p(R1-CPE1,CPE2)-C1,R2)` | 1.497% | **-2.07** | **no** |
| `R1-p(R2,C1)-Ws1` | `p(R1-C1,CPE1-CPE2,R2)` | 1.735% | **-2.58** | **no** |
| `R1-p(R2,CPE1)-Wo1` | `p(R1,CPE1,CPE2)-C1-CPE3` | 2.526% | -5.42 | yes |

The three that must not fire are all at -0.26 or better. The three that must fire are all
below -2.0. **The instrument separates them cleanly; the threshold is what is wrong.** -3.0 is
`RUNS_Z_LIMIT`, chosen for the Kramers-Kronig validator, where a false positive tells a user
their *measurement* is bad -- an expensive mistake that deserves a strict bar. Here a false
positive costs a second search and nothing else, so the same number is the wrong one.

Two things that changed with the limit are worth keeping separate. The first is the false
positive disappearing, which is the element-limit ambiguity resolving itself at the default.
The second is `R1-Ws1` and `R1-p(R2,C1)-Ws1` sliding from -4.91 and -6.20 up to -2.07 and
-2.58: given five elements the default pool builds an eight-parameter CPE stack
(`p(p(R1-CPE1,CPE2)-C1,R2)`) that reaches 1.497% against a 1.4% noise floor. The residual stops
being evidence not because the pool got better but because it got *bigger*, and the truth it is
standing in for has three parameters. That is the failure mode this whole document is about:
under the `model` objective an eight-parameter stand-in is merely inelegant, and under
`interpret` it is a fabricated mechanism.

### The asymmetry that decides where the bar goes

A false negative and a false positive are not comparable costs here, and the implementation is
what makes that true. The widening keeps the base pool's candidates and merges them with the
wider pool's, so:

* **A false positive costs time and a more careful sentence.** The reported ranking is
  unchanged, because the diffusion candidates simply lose on the criterion; `complete_up_to`
  drops for the wide pool while `base_complete_up_to` still records that every topology up to
  five elements from `R,C,L,CPE` was evaluated. Nothing that was true stops being true.
* **A false negative returns a wrong topology that fits.** `p(p(R1-CPE1,CPE2)-C1,R2)` for
  `R1-Ws1` is not flagged by any statistic in the report.

So the bar belongs low, in the measured gap, and biased towards widening. Placing it needs the
*distribution* rather than one sample per case, and section 6 is what happened when that was
measured.

## 6. The residual is not reliable either, and section 3 gets its detector back

The threshold above was written from one seed per case. Repeating `R1-Ws1` at three noise seeds
is what the whole design turned on.

[measured] Same truth, same production limit, same best topology found; only the noise
realisation differs:

| seed | best default-pool topology | relerr | runs z |
|---|---|---|---|
| 0 | `p(p(R1-CPE1,CPE2)-C1,R2)` | 1.497% | -2.07 |
| 1 | `p(p(R1-CPE1,CPE2)-C1,R2)` | 1.385% | **-0.77** |
| 2 | `p(p(R1,CPE1)-R2-C1,R3)` | 1.577% | **-1.03** |

One of three falls below -1.5. **The residual reading is not a reliable trigger for this
truth**, and no threshold fixes it: at -0.77 the pool that cannot express a Warburg is leaving
residuals indistinguishable from noise. The reason is section 5's other half -- given five
elements the default pool builds an eight-parameter CPE stack that explains the data to within
noise, so the sign pattern of what is left carries almost nothing. What distinguishes the
models there is parsimony (three parameters against eight), not residual structure, and the
runs test does not see parsimony.

### The two instruments have opposite domains

Section 3 rejected the shape detector *as the sole trigger* and that judgement stands. What the
measurement above adds is that the residual is not a sole trigger either. Run properly -- every
truth at three noise seeds, at the production element limit -- the two readings do not merely
disagree, they **partition the problem**:

| truth | residual runs z, three seeds | fires at -1.5 | shape fires |
|---|---|---|---|
| `R1-Ws1` | -2.07, -0.77, -1.03 | 1/3 | **24/24** |
| `R1-Wo1` | -0.77, -2.07, -1.29 | 1/3 | **24/24** |
| `R1-G1` | -0.77, **+0.77**, -0.26 | **0/3** | **24/24** |
| `R1-p(R2,C1)-Ws1` | -2.58, -2.07, -2.07 | **3/3** | 17/24 |
| `R1-p(R2,CPE1)-Wo1` | -5.42, -4.39, -3.87 | **3/3** | **0/24** |
| eight diffusion-free truths | -0.26, -0.26, +0.00 | -- | 0/24 each, 192 trials |
| `R1-W1` (the pool already has it) | +0.00 | -- | 24/24, adds nothing |

**The residual reading works on the composite truths, 6 of 6, and fails on the single-element
ones, 2 of 9. The shape reading is the exact mirror image**, 24/24 on the single-element truths
and degrading to 17/24 and then 0/24 as the diffusion branch gets more obscured. `R1-G1` is the
sharpest case: its three residuals, -0.77, +0.77 and -0.26, sit *inside* the diffusion-free
distribution, so no residual threshold whatever could separate it -- and the shape reading calls
it 24 times out of 24.

That is not two noisy instruments averaging out. It is two instruments looking at different
things: the shape reading sees an unobstructed diffusion branch, and the residual reading sees
the misfit a diffusion branch causes *when something else obscures it*. Exactly what hides one
is what reveals the other, which is why the union covers a set neither one does, and why a
version of this feature with either instrument removed passes every other gate here and
silently loses a class of answer. Gate C6 pins one failure case from each side for that reason.

The union is affordable because the errors are asymmetric (section 5): a spurious widening
costs a second search and changes no reported number, since the base pool's candidates are kept
and `base_complete_up_to` still records what the narrow pool covered. So the right bias is
towards firing, and both bars are set on that side of their measured gaps.

### The two thresholds

**`DIFFUSION_RUN_DECADES = 0.75`.** Diffusion-free truths reach at most 0.50 decades over 192
trials and a depressed arc at `n = 0.80` at most 0.60; `R1-Ws1`, `R1-Wo1` and `R1-G1` never fall
below 1.00. The measured false-positive rate at 0.75 is **0 of 192**. Pushing an ordinary arc
over the line is the regression to watch: a sweep of the CPE exponent puts the boundary at `n`
around 0.75 (max 1.05 over 24 trials), so heavily depressed arcs will widen -- which is the
search doing its job on a genuinely ambiguous shape rather than an error.

**`POOL_WIDENING_RUNS_Z = -1.5`.** [measured] Fifteen runs on five truths the default pool
covers exactly, three noise seeds each, at the production element limit:

| truth | runs z, three seeds |
|---|---|
| `R1-W1` | +0.00, +0.00, +0.52 |
| `R1-p(R2,C1)` | -0.26, -0.26, +0.52 |
| `R1-p(R2,C1)-p(R3,C2)` | -0.26, +0.26, +1.03 |
| `C1-R1-L1` | **-1.29**, -0.77, +0.26 |
| `R1-p(R2,CPE1)` at `n = 0.80` | -0.77, +1.29, +0.52 |

**0 of 15 fire.** The closest approach is the resonator at -1.29, which leaves 0.21 of margin;
the nearest value that must fire is -2.07, 0.57 the other way. So the bar sits deliberately
nearer the side whose error is cheap -- it is readier to widen spuriously than to miss --
which is the asymmetry section 5 argues for, now placed against a measured distribution rather
than a single sample.

The theoretical rate is worth keeping beside that, because it is what would happen if fitted
residuals behaved like the null. The Wald-Wolfowitz z is standard normal when the signs are
random and the smaller of two halves is taken, so a correctly fitted spectrum would fire with
probability `1 - (1 - Phi(t))^2`: **12.9%** at -1.5, 4.5% at -2.0, 0.27% at -3.0. The measured
0 of 15 is far below the 12.9% that predicts, and the reason is visible in the table -- eight of
the fifteen values are *positive*. Fitting absorbs structure and pushes the signs towards
alternating, so a well-fitted spectrum is not a null draw. **Do not "correct" the threshold back
towards -3.0 on the strength of the 12.9% figure**; it is an upper bound that the measurement
has already beaten by an order of magnitude.

**What -1.5 buys over -3.0 is exactly one case, and it is the weakest one.** `R1-p(R2,C1)-Ws1`
reads -2.58, -2.07 and -2.07 -- three of three below -1.5, none of three below -3.0 -- and it
is the only truth the shape reading fails to cover completely, at 17 of 24. Raise the bar to
-3.0 and that case falls through both instruments on the 7 of 24 realisations the shape misses.
That is the whole justification for a second constant, and it is one case wide.

### What the report has to carry as a result

Both readings, always, whichever fired. A reader shown only the instrument that fired cannot
tell a spectrum the two agreed on from one where they disagreed, and they disagree often --
that being the entire reason there are two. `PoolChoice` therefore stores `diffusion_decades`
and `residual_runs_z` and *derives* the verdict from them, rather than storing a verdict of its
own: an earlier version carried the flag as a field and a test promptly constructed a `"yes"`
whose two readings both said no, so the sentence and the flag described different runs.

`"unasked"` wins over a firing shape reading, on purpose. It is the genetic search, which never
completes a pool; half the evidence is missing whatever the other half says, and the sentence
reports the shape reading separately, so a spectrum that looks like diffusion under a search
that could not check says exactly that.

## 7. What is not done

- **The browser.** `web/bridge.py` and `web/job.py` take a concrete pool and default to
  `DEFAULT_POOL`, so the deployed site still commits the exact violation this document repairs.
  Wiring it means the two-stage flow inside `DiscoveryJob`, which is resumable and cancellable,
  so it is not a one-line change.
- **`R1-p(R2,C1)-Ws1` is the weakest case in the table and the one the whole second threshold
  exists for.** The shape reading covers it 17/24 and the residual 3/3, but only between -1.5
  and -3.0, so it is the single case standing between the two bars. If this feature ever needs a
  third instrument, build it against this spectrum.
- **The resonator is the nearest false positive.** `C1-R1-L1` reads -1.29 against a -1.5 bar,
  0.21 of margin and the smallest in the diffusion-free set. That is not a diffusion signal, it
  is the default pool struggling with a resonance -- the same shape `docs/KK_RESONANCE_PLAN.md`
  records the Lin-KK basis as unable to express at all. If a future change moves it past the
  bar, the finding is "the residual reading misfires on resonance", not "the threshold is
  wrong".
- **The other element families.** `CC`, `HN`, `SKINF` and `SKINW` are outside
  `WIDENING_CANDIDATES` because nothing has measured whether the default pool already expresses
  them. That is the same unmeasured guess this document exists to remove, one level up, and it
  is named here rather than left implicit.
- **`final_restarts=5` is not always enough once diffusion is in the pool** (section 4).
