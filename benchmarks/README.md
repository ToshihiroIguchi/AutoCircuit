# Benchmarks

Measurements, not tests. The test suite asserts that things *work*; these scripts say *how
well*, and they are the evidence behind every claim marked **[measured]** in
`docs/IMPLEMENTATION_PLAN.md`, `docs/DISCOVERY_V2_PLAN.md` and
`docs/PARTIAL_TOPOLOGY_PLAN.md`.

Run with the package on the path (it is not pip-installed on the dev machine):

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
python benchmarks/topology_space.py
python benchmarks/fitting.py accuracy
python benchmarks/fitting.py calibration
python benchmarks/fitting.py restarts
python benchmarks/discovery_v2.py filter
python benchmarks/discovery_v2.py screen
python benchmarks/discovery_v2.py screen-rank --workers 8   # slow: ~1 h
python benchmarks/discovery_v2.py gate --workers 8      # slow: hours
python benchmarks/discovery_v2.py skeleton --workers 8       # gate P1, ~20 min
python benchmarks/discovery_v2.py wrong-skeleton --workers 8 # gate P2, ~20 min
python benchmarks/discovery_v2.py evolve-gate --seeds 3 --time-limit 600   # gate EV1, ~2.5 h
python benchmarks/discovery_v2.py evolve-gate --only Maxwell --seeds 10 --warm 0,inf     --time-limit 600                                          # gate EV3, ~3 h
python benchmarks/kk_resonance.py                       # gates K1-K4, seconds
python benchmarks/pyodide/bench.py                      # CPython baseline for the web numbers
```

`benchmarks/pyodide/` additionally needs Node; see its own README.

`evolve-gate` is the slow one and it is budgeted in **wall-clock**, which changes how it must be
run. Three rules, each of them a measurement that was lost before it was learned:

- **One at a time.** This machine has 2 performance cores and 8 efficient ones, so a second
  concurrent run lands on a much slower core and evaluates fewer topologies in its 600 s — and
  reports that as a property of the search. [measured] The fast test subset went 4 s → 118 s
  with two evolve runs going.
- **Detach it, one invocation per reference.** A backgrounded shell command is killed after ten
  minutes. `Start-Process ... -RedirectStandardOutput` survives; splitting by reference means a
  machine restart costs one reference rather than the run.
- **Compare arms with `--warm`, never against a number from another day.** `--warm 0,inf`
  interleaves the arms seed by seed, which is the only way the comparison is not measuring the
  machine. `--seed-start` resumes a chunked run.

Re-run the relevant script after touching the optimizer, the element library or the
discovery filters, and update the numbers below if they move.

## Results as of 2026-08-13

### `topology_space.py` (a) — search space

Distinct series-parallel topologies with exactly n elements, before and after the
redundancy (`simplify`) and plausibility (`is_plausible`) filters.

| pool | ≤ 3 elements | ≤ 4 | ≤ 5 | ≤ 6 |
|------|-------------:|----:|----:|----:|
| R, C | 8 | 20 | 56 | 170 |
| R, C, L | 25 | 100 | 449 | 2,174 |
| R, C, L, CPE | 77 | 453 | 2,976 | 21,057 |
| R, C, L, CPE, SKINF | 173 | 1,336 | 11,550 | 107,534 |

(Cumulative, after filters.) **This is why discovery v2 is exhaustive-first**: a few
thousand candidates at ≤ 5 elements is an enumeration problem, not a search problem, and
enumeration comes with a completeness guarantee that a genetic search never has.

### `topology_space.py` (b) — distinguishability

Fitting *every* same-size topology to noise-free data from a known circuit:

| true circuit | topologies of that size | reaching 1e-9 |
|--------------|------------------------:|--------------:|
| `C1-R1-L1` | 56 | **1** (unique) |
| `R1-p(R2,C1)` | 20 | 2 |
| `p(R1,C1)-p(R2,C2)` | 80 | 4 |

Exact degeneracy is real but bounded — a handful of circuits, not dozens. Note this counts
*exact algebraic* equivalence on clean data; with real noise, more circuits become
practically indistinguishable, which is what the Pareto front and AICc are for.

### `discovery_v2.py gate` — acceptance gate G1

`mode="exhaustive"`, element limit 5, 1% noise, 10 seeds per reference, 8 workers on a
12-core machine. "Reported" is gate G1 as written — the true topology, or an exact equivalent
of it, present in the reported equivalence classes.

| reference | pool | candidates screened | reported | on the front | is the recommendation | time / run |
|-----------|------|--------------------:|---------:|-------------:|----------------------:|-----------:|
| capacitor `C-R-L-SKINF` | R,C,L,CPE,SKINF | 6,598 | **10/10** | 10/10 | 9/10 | 3.8–5.8 min |
| Maxwell-Wagner `p(R,C)-p(R,C)` | R,C,L,CPE | 2,581 | **10/10** | 10/10 | 10/10 | 1.1–1.2 min |
| Randles `R-p(C,R-W)` | R,C,CPE,W | 3,713 | **10/10** | 10/10 | 9/10 | 1.4–1.6 min |

**G1 passes 30/30.** Every run reported `complete_up_to = 5`.

Two things in this table are worth more than the pass count.

*The two runs where the truth is not the recommendation are the parsimony rule working, not
the search failing.* On capacitor seed 3 the recommendation was `C1-L1-SKINF1`: the true ESR
is 10 mΩ and at 1% noise that seed could not resolve it, so the simplest model fitting within
a factor 2 of the best chi² drops it. The four-element truth is still on the front next to it.
Randles seed 7 is the same story with a different near-tie.

*The Maxwell-Wagner recommendation cycles between `p(p(R1,C1)-C2,R2)`, `p(R1-C1,R2,C2)`,
`p(p(R1,C1)-R2,C2)` and `p(R1,C1)-p(R2,C2)` from seed to seed* — which is precisely the set of
four exact equivalents measured independently by `topology_space.py` (b). The data cannot
separate them and the tool does not pretend otherwise; which one comes out on top is a coin
toss, and that is why the deliverable is the equivalence class rather than a single circuit.

The plan's time budget was ≤ 3 min per run with 8 workers. The capacitor case misses it at
~4.8 min, because the feasibility filter removes 1.75× rather than the 3× the budget assumed.
Single core it is ~22 min of screening for that reference, over the plan's 15 min figure.
`benchmarks/README.md` records what was measured rather than what was hoped for; the budget
line in `docs/DISCOVERY_V2_PLAN.md` has been corrected to match.

### `discovery_v2.py skeleton` — acceptance gate P1

The same three references, with the *true* skeleton asserted: the part of each circuit a user
of that kind of sample would already know. Element limit 5, 1% noise, 10 seeds, 8 workers.

| reference | skeleton | candidates | vs unconstrained | reported | on the front | it is the recommendation | time / run |
|-----------|----------|-----------:|-----------------:|---------:|-------------:|-------------------------:|-----------:|
| capacitor `C-R-L-SKINF` | `C1-R1-L1` | 534 | 12.4× fewer | **10/10** | 10/10 | 10/10 | 0.8 min |
| Maxwell-Wagner `p(R,C)-p(R,C)` | `p(R1,C1)` | 972 | 2.7× fewer | **10/10** | 10/10 | 10/10 | 0.7 min |
| Randles `R-p(C,R-W)` | `R1-p(C1,R2)` | 241 | 15.4× fewer | **10/10** | 10/10 | 10/10 | 0.4 min |

**P1 passes 30/30**, and the constrained run is 1.7–6× faster in wall clock (the candidate
reduction is larger than the time reduction because the levels a skeleton removes are the
cheap small ones). Recovery is the gate; the speed-up is an observation.

One row is worth more than the pass count. *Unconstrained, the capacitor truth is the
recommendation 9/10 — with the true skeleton it is 10/10.* The seed that dropped it was the
one where the 10 mΩ ESR is not resolvable at 1% noise, so the parsimony rule preferred the
three-element model. Asserting `C1-R1-L1` says the ESR is there, and parsimony can no longer
drop it. A skeleton is not only a way to search less; it puts prior knowledge where the
model-selection rule can use it.

Measured with `--compare` on the capacitor reference (5 seeds, and the unconstrained side is
what makes that mode slow): 534 candidates in 0.4–0.8 min against 6,598 in 5.4–7.9 min.

### `discovery_v2.py wrong-skeleton` — acceptance gate P2

The same references under a skeleton the truth does *not* contain. Same budget and seeds.
"Structure" is the runs test on the best fit's residual signs — the criterion `mode="auto"`
uses; "unresolved" counts seeds where the recommendation carried a parameter whose standard
error exceeds its own value; chi² is against what the truth itself achieves on that data.

| reference | wrong skeleton | residual structure | recommendation unresolved | nothing identifiable | chi² vs the truth |
|-----------|----------------|-------------------:|--------------------------:|---------------------:|------------------:|
| capacitor | `R1-p(R2,C1)` | 0/10 | **9/10** | 9/10 | 1.0× |
| Maxwell-Wagner | `p(R1,CPE1)-p(R2,C1)` | 0/10 | 0/10 | 0/10 | 1.0× |
| Randles | `R1-p(CPE1,R2)` | 0/10 | 0/10 | 0/10 | 1.0× |

**A wrong skeleton is invisible in the residuals. 0/30, and the chi² is the truth's own to two
figures in every seed.** The escape valve §3.2 of `docs/PARTIAL_TOPOLOGY_PLAN.md` proposed —
screen a small unconstrained sample and report when something outside the skeleton fits
materially better — is dead on this evidence: nothing outside fits better, because the
constrained best already fits as well as the generating circuit does.

Reading the recommendations explains why, and splits the three cases into two kinds:

*Two of the three "wrong" skeletons are not falsifiable at all.* `p(R1,CPE1)` is a **strict
generalisation** of `p(R1,C1)` — a CPE with n = 1 *is* a capacitor — so the Maxwell-Wagner and
Randles skeletons contain the truth's behaviour even though `contains_skeleton` correctly says
they do not contain its topology. Both return the skeleton itself with every parameter
resolved, chi² equal to the truth's, and a fitted exponent sitting at n ≈ 1. Nothing is wrong
with that report; the fitted exponent is the finding. **Wrong at the level of element codes is
not the same as wrong at the level of what the data can express**, and this measurement is
where that distinction was learned.

*The capacitor case is a genuinely different topology, and there the report does say
something* — 9/10 seeds with an unresolved parameter, and `unresolved_everywhere` true on the
same 9. The reason is visible in the recommendation `R1-p(R2,C1-L1-SKINF1)`: sending R2 to an
open turns it back into the truth, so the fit neutralises the asserted parallel branch and the
element it had to neutralise is exactly the one that will not resolve. **A wrong skeleton the
data can refute announces itself as an asserted element the fit had to switch off** — not as a
worse fit. That is the signal P2 should be written on, and it is not the one anyone guessed.

### `discovery_v2.py excluded` — what the skeleton removed that fits identically

With the *true* skeleton asserted, every same-size topology outside it is screened against the
reported model's own (noise-free) response; those reaching `PERFECT_COST` are exact
reparameterisations the constraint removed. Four elements, seed 0, 8 workers.

| reference | skeleton | excluded / all at that size | screened in | exact equivalents excluded |
|-----------|----------|----------------------------:|------------:|----------------------------|
| capacitor | `C1-R1-L1` | 1,132 / 1,163 | 43 s | `R1-L1-CPE1-SKINF1` |
| Maxwell-Wagner | `p(R1,C1)` | 273 / 376 | 22 s | `p(R1,CPE1)-p(R2,CPE2)`, `p(p(R1,CPE1)-CPE2,R2)` |
| Randles | `R1-p(C1,R2)` | 510 / 527 | 13 s | `p(R1-W1,CPE1)-R2`, `p(R1-CPE1,CPE2)-R2` |

**Every excluded equivalent, on every reference, is a CPE standing in for an ideal element** —
a capacitor at n = -1, an inductor at n = +1, a Warburg at n = -0.5. That is what a skeleton
actually costs: not a lost topology the data preferred, but a commitment to an *ideal* element
where a distributed one fits the same points exactly. It is also the same phenomenon gate P2
ran into from the other side, where a CPE-flavoured wrong skeleton could not be falsified.

The cost is why the feature is opt-in rather than part of every report: 1,132 screens is 137 s
on one core (121 ms each) and 43 s across eight, against a search that takes about a minute,
and a five-element pass is ~20 min single-core. The yield is why it exists at all — one or two
circuits per run, named, that the user's assertion chose against on evidence the data does not
contain.

The list is a floor. A tier-1 budget that misses an exact equivalent under-reports it, so this
says "these were excluded", never "only these were".

### `discovery_v2.py filter` — structural feasibility filter

How much of the enumerated space the endpoint-behaviour screen removes before any fitting,
and whether the true topology survives it. Reduction is over the cumulative n ≤ 5 space.

| reference | pool | n ≤ 5 | kept | reduction | truth kept |
|-----------|------|------:|-----:|----------:|------------|
| capacitor `C-R-L-SKINF` | R,C,L,CPE,SKINF | 11,550 | 6,598 | 1.75× | yes |
| Maxwell-Wagner `p(R,C)-p(R,C)` | R,C,L,CPE | 2,976 | 2,581 | 1.15× | yes |
| Randles `R-p(C,R-W)` | R,C,CPE,W | 4,395 | 3,713 | 1.18× | yes |

Identical at 0% and 1% noise — the tolerance band is wide enough that noise does not move it.
The plan guessed 2–5×; that is only reachable with `feasibility_budget=0`, which forbids any
element from being treated as degenerate and can therefore reject a model whose corner
frequency merely fell outside the measured window. Completeness is the point of this mode, so
the default budget is 1 and the reduction is smaller. See `docs/DISCOVERY_V2_PLAN.md` §3.2 for
the budget sweep (7.7×/3.1×/2.3× at budget 0). The screen itself costs ~0.3 s for 11,550
candidates, so even 1.75× is free money.

### `discovery_v2.py screen` — tier-1 screening budget

54 topologies sampled from the capacitor reference space, ranked by screening cost alone. The
true topology comes first at every budget tried:

| popsize | maxiter | ms/topology | rank of the truth |
|--------:|--------:|------------:|------------------:|
| 4 | 20 | 80 | 1 of 54 |
| **8** | **40** | **126** | **1 of 54** |
| 12 | 60 | 164 | 1 of 54 |
| 20 | 100 | 259 | 1 of 54 |

The library default stays at 8/40. A 54-topology sample is not enough evidence to halve the
budget on — but it is enough to say the budget is not the thing to spend more on. **The
`screen-rank` mode below is the experiment that settles it, and this one is superseded for
that purpose**: it ranks by cost alone and globally, which is not what the shortlist does.

Full-space screening cost on this machine, single core, after the feasibility filter:
57 ms/topology at n = 3, 86 ms at n = 4, 219 ms at n = 5, i.e. ~22 min for the whole
capacitor sweep on one core and a few minutes with `--workers 8`.

### `discovery_v2.py screen-rank` — the same budget question, asked properly

Every feasible candidate screened, at every budget, on all three references × 3 seeds, scoring
what the pipeline actually does with the result: the rank of the truth *and of every known
exact equivalent* within its own element count, by screening AICc, against the per-size refit
quota. Kept = `_shortlist` selected it.

| budget | tier-1 time (8 workers) | vs 8×40 | worst rank/quota | truth + equivalents kept |
|--------|------------------------:|--------:|-----------------:|-------------------------:|
| **8×40 (default)** | **6.1 min** | **1.00×** | **0.67** | **15/15** |
| 8×20 | 3.5 min | 0.56× | 13.5 | 12/15 |
| 4×40 | 4.0 min | 0.64× | 38.3 | 13/15 |
| 4×20 | 2.5 min | 0.41× | 72.3 | 9/15 |

Times and counts are the Maxwell-Wagner and Randles references. **The budget cannot be cut.**
At 8×20 the Maxwell-Wagner truth screens to 1452× the best cost of its size, falls to rank 19
of 330 and misses the shortlist — while its three exact equivalents stay at ranks 1–3, so
nothing in the report looks wrong.

The capacitor reference is tabulated apart because it disagrees completely: its truth screens
to **rank 1 of 657 at every budget**, margin 0.14, with 4×20 finishing in 0.9–1.9 min against
8×40's 3.6–4.9. That reference is the one whose runtime motivated cutting the budget in the
first place, and measured alone it says the cut is free. It is free only there. Same shape as
the `_shortlist` bug: invisible on the easy case, expensive on the real space.

### `fitting.py accuracy` — re-measured 2026-08-22

All **seven** circuits recover their true parameters from clean data with no initial guess
(worst error < 0.01%), and stay within 9% at 1% noise. Times 0.6–4.9 s clean, 0.2–2.2 s noisy.

| case | n | worst error, 1% noise |
|------|--:|----------------------:|
| capacitor C-ESR-ESL | 3 | 1.64% |
| capacitor + skin effect | 5 | 6.33% |
| Randles | 4 | 0.30% |
| Maxwell-Wagner, 2 blocks | 4 | 0.47% |
| brick layer + CPE | 6 | 8.53% |
| **Voigt ladder, 4 blocks** | **8** | **1.26%** |
| **piezo resonator (BVD)** | **4** | **0.16%** |

The last two are new. They were added to answer two questions the first five do not: whether
the fitter carries *eight* parameters without an initial guess, and whether it handles a
*resonance* rather than a relaxation. Both answer yes, and neither leaves a parameter
unresolved — 0/8 and 0/4 with standard errors below their own values, over 5 seeds.

Two things about them are worth more than the error column.

*The eight-parameter case is the easy kind of eight.* Its four RC time constants are ~2
decades apart, so every block is separately resolvable and 1.26% is a statement about the
optimizer, not about the data. The deliberately hard version — three blocks with two of them
0.6 decades apart — is `LARGE_REFERENCES[0]` in `discovery_v2.py`, where the same measurement
reads 24.1%. Keeping them apart keeps "can the fitter carry eight parameters" from being
reported as "can the data separate two relaxations".

*The resonator's sweep is part of the reference.* A resonance of quality factor Q is about 1/Q
wide, so it needs ~`8·ln(10)·Q` points per decade — 1500 at Q = 100 — and a window of 0.2
decades rather than the several decades every other case uses, because a log sweep cannot both
span a wide band and resolve a Q = 100 peak at any sane point count. **The first version of
that note claimed the case would be unmeasurable at the suite's 10 points per decade, and the
measurement disagreed.** It is measurable: the three points a 10-per-decade sweep leaves in
this window recover all four parameters exactly from noise-free data and leave none unresolved
at 1% noise. What the sweep buys is precision — worst deviation over 10 seeds 0.29% at 1500
points per decade against 9.9% at 10. `tests/test_fit.py::test_the_resonator_earns_its_sweep`
pins that ratio, so the claim cannot drift back to the stronger one.

### `fitting.py calibration` — re-measured 2026-08-22

Reported standard errors are honest on all four cases in `CALIBRATION`: over 25 noise
realisations the z-scores have mean within ±0.55, standard deviation 0.72–1.34, and 88–100%
coverage inside ±2σ.

Those ranges are wider than the "mean ≈ 0, 0.8–1.1, 92–96%" recorded here before, and only
partly because two cases were added. Re-running the *original* pair on the same seeds now
reads 88% coverage at its lowest (`CPE1.Q` and `CPE1.n` on the brick layer) rather than 92%.
The earlier line is left contradicted rather than quietly replaced: this table is the current
reading, and where the previous summary came from is not recoverable from it.

The two new cases are the ones with a shape the covariance estimate had not been checked on.
The eight-parameter ladder is the best-behaved case in the table (std 0.72–1.17, coverage
92–100%). The resonator carries a mild bias the relaxation cases do not — mean z +0.54 on C0
and +0.45 on the motional C1, the two parameters the anti-resonance ties together — with
standard deviations 0.73–1.06 and coverage 92–100%. Worth knowing before quoting a capacitance
ratio to three figures; not enough to call the errors dishonest.

### The two 2026-08-22 additions — what they measured beyond recovery

Neither circuit was added to `discovery_v2.py`'s `REFERENCES`: every mode in that file
iterates that list, so appending to it invalidates each table above and costs hours to
restore. Both are `fitting.py` cases (mode 1, topology given) and both are shipped as web
examples. Two things turned up on the way, and they are here because they are the reason
somebody should think before promoting either one to a discovery reference.

**The BVD resonator has a near-degenerate rival, and it is not an exact equivalent.** Screened
against the whole R/C/L space, `C1-p(C2,L1,R1)` — the dual, a series capacitance with a
parallel R-L-C — fits the resonator's noise-free data to 1.1% relative RMS. That is not a
reparameterisation (the exact equivalents in `topology_space.py` (b) reach 1e-9), but at the
project's standard 1% noise it is indistinguishable, and it has the same element count. Ad-hoc
`mode="exhaustive"` runs on the resonator, pool R/C/L, 4 workers: at limit 4 (100 candidates,
10 s) the truth was the recommendation on the one seed run; at limit 5 (449 candidates, ~34 s)
it was 2 of 3 seeds, the third recommending the dual and dropping the truth off the front
entirely. **A gate written as "the truth is the recommendation" would be flaky on this
reference at 1% noise.** Four seeds across two limits is an observation and not a measurement:
there is no `discovery_v2.py` mode for these runs, so nobody can re-run them by name, and the
counts are far too small to be a pass fraction.

Two follow-ups that look obvious and are not. Raising Q makes it *worse*, not better: the
dual's misfit falls 1.52% → 1.12% → 0.67% → 0.37% at Q = 50, 100, 300, 1000, because at high Q
both circuits are dominated by the same pole pair and the difference lives in the off-resonance
shape. Widening the window makes it worse too — 1.1% on the 0.2-decade reference window against
0.30% over 3 decades. The narrow, lossy case is the *most* separable one, which is the opposite
of the intuition.

**The resonator broke the Lin-KK test, and the test blamed the data.** The example is
KK-compliant by construction — it is the exact response of a passive circuit plus i.i.d. noise
— and `validate` returned FAIL with "the data is not consistent with a linear, causal,
stationary system". The cause is basis incompleteness, not order selection: a Voigt series has
only real poles and a resonance is a complex pole pair, so [measured] the residual sits at
96.8% of |Z| at **every** order from M = 3 to M = 317, flat to four figures. The order scan and
its mu criterion were working correctly; there was nothing to select.

The discriminator is clean in both directions and is now in the code as
`validate.MODEL_FAILURE_RMS`:

| spectrum | best RMS residual | gain from M=3 to best | what it means |
|----------|------------------:|----------------------:| --------------|
| Randles, 1% noise | 0.99% | 22.6× | passes |
| Randles + 40% drift across the sweep | 1.77% | 11.5× | a real KK violation |
| piezo resonator | 48.7% | **1.24×** | the model, not the data |

A genuine violation is *tracked* — the model follows the curve and the verdict comes from the
residual's systematic pattern at a small magnitude. An unreachable shape is not tracked at all,
and nothing about the data's causality has been tested. Above 25% RMS the outcome is a third
state, `verdict == "inconclusive"`: the summary says the test could not be applied and names
both possibilities, `validate` exits 2 rather than 1, and the web badge reads NO VERDICT.
**`passed` is unchanged**, so no verdict, threshold or number in any table above moves — only
what the failure is allowed to blame.

Making that a user-visible state meant widening the evidence, and three of the extra
measurements changed the design rather than confirming it.

*`passed` has to be asked first.* Noise inflates the residual without being a violation at all:
KK-compliant Randles data at 30% and 50% noise reads 28.1% and 43.7% RMS — over the threshold —
while passing correctly on the runs test. A badge that asked the residual question first would
have reported healthy noisy data as untested. `KKResult.verdict` is the one place that order
lives, and the browser takes it over the wire rather than rebuilding it.

*The drift family never comes near the line.* 40%, 100%, 300% and 1000% multiplicative drift
give 2.5%, 4.1%, 8.0% and 15.0% RMS. Two orders of magnitude of drift, and the margin holds.

*A series resonance is representable, and the first version of this note said otherwise.* A
series R-L-C **is** the basis's three series terms, and it passes at 0.98%. It is the complex
*pole* — the anti-resonance — that is unreachable, not resonance as such.

**And the residual magnitude only covers the gross case.** The same resonator at mechanical
Q = 2, 3, 5, 10, 15 leaves 1.3%, 2.6%, 4.6%, 17.6% and 24.5% RMS — all under the threshold —
with runs z from −5.7 to −17.3. That band is closed by the resonance probe instead; see
`kk_resonance.py` below.

### `kk_resonance.py` — gates K1–K4, the Lin-KK resonance probe

The plan is `docs/KK_RESONANCE_PLAN.md`, and its section 2 is the part worth reading: the
obvious fix was built and measured, and the measurement rejected it. Giving the basis complex
poles keeps the solve linear and does fix the resonator — and **destroys the test**. [measured]
A 200-column resonant bank fits a 61-point Randles spectrum drifting 1000% to **0.00% residual
with random residual signs**, because 122 real equations cannot constrain 223 unknowns. Budget
the bank against the same `2 * len(spectrum)` the Voigt elements are counted against and the
trade-off comes back, but sizing it then becomes a two-dimensional order scan that moves every
Lin-KK number in this file — and a prototype allocating a third of the budget to relaxations
was measured to *fail clean Randles data* at 14.1% residual, by starving the part the existing
scan already sizes correctly.

So the bank is a **probe**, not a basis: it asks one further question of spectra that have
already failed, at 15% of 2N columns, and can only turn `fail` into `inconclusive`.

| family | rows | without the probe | with it |
|--------|-----:|-------------------|---------|
| drift 40–1000%, at 10, 30, 50 points/decade | 12 | `fail` | **`fail` 12/12** |
| Butterworth-Van Dyke, Q = 2, 5, 15 | 3 | `fail` | **`inconclusive`** |
| Butterworth-Van Dyke, Q = 100, 300 | 2 | `inconclusive` | `inconclusive` |
| Randles clean at 10, 30, 50 points/decade; series L-C-R | 4 | `pass` | `pass`, untouched |
| Randles with Im sign flipped | 1 | `inconclusive` | `inconclusive` |

**All gates pass.** The probe's own residual on the rescued resonators is 0.93% at runs z
+0.90 to +1.46; on the drift family it is 2.0–11.9% at runs z −5.0 to −15.3, which is the
separation the acceptance rule is built on. A first version of that rule also demanded a
threefold improvement in residual magnitude and was measured to drop the Q = 2 resonator, whose
plain residual is already 1.3% — the runs test does the work alone.

What is *not* fixed: this test still cannot validate a resonator. `inconclusive` is the honest
verdict, not a workaround for one.

### `fitting.py restarts`

On the hardest six-parameter case (`brick layer + CPE`, now pinned by label rather than as
`SUITE[-1]`, so that appending a case cannot move this sweep onto a different circuit while
still printing this heading), at 1% noise:

| restarts | popsize | failures | mean time |
|----------|---------|----------|-----------|
| 3 | 20 | 1/25 | 0.56 s |
| **5** | **20** | **0/25** | **0.99 s** |
| 8 | 20 | 0/25 | 1.64 s |
| 3 | 40 | 3/25 | 1.27 s |
| 5 | 40 | 2/25 | 2.23 s |

Hence the library default `restarts=5, popsize=20`. A larger population is *worse* per unit
time — and worse outright at 40. Failures are not silent: a run that lands in a local minimum
reports a chi² an order of magnitude worse.

(The failure counts are unchanged from the first time this was measured; the times are ~3×
lower because batched element evaluation landed afterwards. Any time estimate elsewhere in the
docs derived from the earlier numbers is conservative.)

### `pyodide/bench.py` — how much slower is the browser?

Full table and the phase-6 conclusions in `benchmarks/pyodide/README.md`. The short version:
**WASM costs 1.3–1.8× on the numerical work**, not the "minutes-not-seconds" the plan feared,
because the expensive part is numpy and scipy compiled to WASM rather than interpreted Python.
The interpreter-bound import pays 3.9×, once, for 1.6 s.

| operation | CPython | Pyodide | ratio |
|-----------|--------:|--------:|------:|
| `fit`, 6 parameters | 0.704 s | 0.906 s | 1.3× |
| `screen`, 4 elements | 32.2 ms | 45.1 ms | 1.4× |
| `discover`, component pool, n ≤ 4 (741 screened) | 127.5 s | 169.1 s | 1.33× |

So `exhaustive_limit=4` is a usable web default at 2.8 min single-threaded — which makes
progress streaming mandatory rather than optional — `exhaustive_limit=5` is a ~30 min opt-in,
and the fitter needs no separate web budget.

`pyodide/run_orchestrated.mjs` then runs the whole two-tier search across four Pyodide workers
with the orchestration still in Python, and reproduces the CLI's report exactly: same 741
candidates screened, same 37 refitted, same AICc to a difference of 0.0, same Pareto front, same
recommendation. **[measured] 123 s**, of which the tier-1 screen is 37 s and the tier-2 refit
86 s. That refit stage was 232 s of a 287 s run until `FitResult.to_wire()` let a whole fit --
covariance and restart spread included -- cross a worker boundary losslessly; `tests/test_wire.py`
pins the transport and `docs/WEB_UI_PLAN.md` §2.2 records why the CLI's `--json` shape could not
serve as it.
