# Replacing `differential_evolution` in the parameter fitter's global stage

Status: **measured, not shipped, 2026-09-06.** Ten alternative optimisers were implemented and
measured against the incumbent `scipy.optimize.differential_evolution` for
`core/fit.py`'s `_global_stage`. One of them, L-SHADE, decisively beat the incumbent on both
optimiser-only arenas tested in Phase 1 -- and was withdrawn in Phase 2 after it regressed a known
-hard reference and broke three existing tests on trivial noise-free circuits. Nothing in
`core/fit.py` changed as a result of this round.

## Why this was asked

`docs/SEARCH_ALGORITHM_SURVEY.md` section 3.2 and `docs/SEARCH_ALGORITHM_SCREENING.md` section
4.4 (KPI-3) had already measured CMA-ES, a `rand1bin` DE strategy, and Sobol multi-start against
the incumbent for this exact call, and found CMA-ES lost decisively (16/26 "in basin" against
DE's 24/26). L-SHADE, SHADE and JADE were named as candidates in that survey and never
implemented. This round closes that gap, and -- at the user's request mid-round -- widens it to
PSO, a real-coded genetic algorithm (SBX + polynomial mutation), `scipy.optimize.shgo` /
`dual_annealing` / `basinhopping`, and a from-scratch GP-EI Bayesian optimiser, on the reasoning
that the no-free-lunch theorem argues for testing genuinely distinct search mechanisms (DE-family,
evolution strategies, swarm intelligence, recombination-based GAs, deterministic/annealing
methods, model-based optimisation) rather than more variants of one family. Nature-inspired
"metaphor" metaheuristics (Firefly, Grey Wolf, Whale Optimization, Cuckoo Search, Harmony Search)
were deliberately not added: the optimisation literature (e.g. Sörensen 2015, "Metaheuristics --
the metaphor exposed") documents these as reformulations of PSO/DE without demonstrated
algorithmic novelty, so adding them would not test a mechanism this round had not already covered.

## Phase 1 -- optimiser-only measurement (KPI-3 harness)

Instrument: `benchmarks/screening_round/param_opt.py`, extended with `lshade()` (and its
population-fixed ablation `shade()`), `jade()`, `pso()`, `ga_sbx()`, `dual_annealing_arm()`,
`basinhopping_arm()`, `bayes_opt()`, and `shgo_arm()` (defined but excluded from `ARMS` -- see
below), plus a Wilson 95% confidence interval on the printed table, which the script never had
before this round. Every arm searches the identical `_Problem` (same bounds, weighting, data);
success is landing within 1% of the best cost any arm reached on that topology, at equal cost-
function-evaluation budget (`bayesopt` is the deliberate exception -- see its own note below).

**Decision rule, fixed before running:** a candidate advances to Phase 2 only if, on a non-
overlapping Wilson interval, its in-basin rate is not worse than the incumbent's, and its median
NFE is lower by a clear margin (informally, 15%+, not a few percent).

### RCL arena (`land_rcl6.json`, R/C/L pool, n<=6, no CPE or Warburg)

| arm | in-basin | 95% Wilson CI | median NFE |
|---|---|---|---:|
| de_8x40 (current), 30 seeds (750 samples) | 630/750 | [0.81,0.86] | 2624 |
| **lshade**, 30 seeds | **698/750** | **[0.91,0.95]** | **1641** |
| shade (no population reduction), 30 seeds | 628/750 | [0.81,0.86] | 1710 |
| cmaes / cmaes_half | 430/750, 428/750 | [0.54,0.61], [0.53,0.61] | 1640, 824 |
| sobol_lm (12-start multi-start LM) | 677/750 | [0.88,0.92] | 3816 (mean 11639 -- heavy tail) |
| jade, 3 seeds (75 samples) | 67/75 | [0.80,0.94] | 1710 |
| pso, 3 seeds | 59/75 | [0.68,0.86] | 1640 |
| ga_sbx (real-coded GA, SBX+poly mutation), 3 seeds | 45/75 | [0.49,0.70] | 1640 |
| dual_annealing, 3 seeds | 57/75 | [0.65,0.84] | 1640 |
| basinhopping, 3 seeds | 27/75 | [0.26,0.47] | 2499 (excess 1.17 -- not reaching the good basin) |
| bayesopt (own budget, 200 NFE), 3 seeds | 34/75 | [0.35,0.57] | 200 |

L-SHADE's CI does not overlap the incumbent's: a clear win on both quality and cost. Every other
new arm ties or loses; JADE (67/75) comes closest but is dominated by L-SHADE on both counts.

### CPE arena (`land_rclcpe6.json`, R/C/L/CPE pool, n<=6 -- the harder, more realistic case)

| arm | in-basin | 95% Wilson CI | median NFE |
|---|---|---|---:|
| de_8x40 (current), 15 seeds (375 samples) | 231/375 | [0.57,0.66] | 2624 |
| **lshade**, 15 seeds | 230/375 | [0.56,0.66] | **1968** |
| shade, 15 seeds | 208/375 | [0.50,0.60] | 2052 |

A tie on quality (CIs almost fully overlap), with a 25% NFE saving. Not worse anywhere, which is
what the decision rule needs, though the margin is smaller than on the RCL arena.

`shgo` (deterministic, Sobol sampling) was tried and excluded from the table on its own evidence:
one topology took 361.7 s (against well under 1 s for every other arm) and still landed at cost
0.0451 against a best-known 0.0166 -- the same basin failure as CMA-ES, at a cost that would make
a 25-topology x several-seed run take hours.

**Phase 1 verdict: L-SHADE clears its decision rule outright** -- non-overlapping win on the RCL
arena, a tie-with-NFE-saving on the harder CPE arena, and no other tested arm (ten in total: four
DE variants, CMA-ES x2, Sobol multi-start, SHADE, JADE, PSO, SBX-GA, dual_annealing,
basinhopping, Bayesian optimisation) beat it anywhere.

## Phase 2 -- pipeline-level validation, and where it stopped

L-SHADE was implemented as `src/autocircuit/core/lshade.py` (the same algorithm as the benchmark
arm, generalised to accept a `deadline` for `--time-limit` and an `x0` for `fit(initial=...)`,
with its evaluation budget derived from the caller's existing `popsize`/`maxiter` as
`popsize * n * (maxiter + 1)` -- scipy's own approximate total-evaluation count for that
population multiplier and generation cap, so `screen()`'s cheap budget and `fit()`'s full one keep
the ratio they always had) and wired into `_global_stage`'s single-process branch (the one every
call in this codebase actually takes; the `workers != 1` branch, confirmed unreachable from any
current entry point, was left calling `differential_evolution` unchanged).

**A T5-style `.summary()` comparison** (`docs/SEARCH_TIME_PLAN.md` section 3.3's method) across
`discovery_v2.py`'s three `REFERENCES` and two `LARGE_REFERENCES`, true circuit, seed 0: **5 of 6
references produced identical output.** The sixth, "Randles + ESL + second block"
(`R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)`, a `LARGE_REFERENCES` entry already documented in
`docs/TOPOLOGY_6PLUS_PLAN.md` item (b) as a known hard, multi-modal landscape), regressed:

| | chi2_reduced | RMS \|dZ\|/\|Z\| | AICc |
|---|---:|---:|---:|
| DE (before) | 9.34e-05 | 1.33% | -1678.87 |
| L-SHADE (after) | 2.81e-04 | 2.31% | -1478.65 |

Because this reference is already known to be a basin lottery, a single seed is not enough to
call it a regression by itself, so it was followed up with a 12-seed, `restarts=1` sweep (mirroring
the method `TOPOLOGY_6PLUS_PLAN.md` item (b) used for this exact reference), at the noise level
`.summary()` actually used (1%, not the noise-free landscape):

| | seeds reaching the noise floor (chi2 < 2e-4) |
|---|---|
| DE | 5/12 |
| L-SHADE | **0/12 -- every seed converged to the identical chi2_reduced=0.000280652** |

DE is already weak here (5/12), consistent with the documented difficulty of this reference, but
L-SHADE is measurably weaker still, and the fact that all twelve independently-seeded runs landed
on the exact same value is itself unexplained and worth flagging rather than smoothing over -- it
was not chased further once the decision to withdraw was made.

**The full `pytest tests -q` suite then surfaced a sharper problem**: three failures, all in
`tests/test_discover_skeleton.py`, all on small (2-3 element), noise-free circuits --
`test_truth_is_recovered_under_a_true_skeleton` (the true topology was not even reached),
`test_the_semicircle_twin_is_reported_as_excluded` and `test_a_driven_excluded_pass_is_the_same_pass`
(both: `result.recommended is None` -- nothing was recommended at all). These are not "a hard
multi-modal landscape" cases; they are exactly the small, clean circuits this project's own test
suite uses to check basic correctness. This is a robustness gap, not merely a quality trade-off,
and is the stronger of the two reasons this round stopped.

An `ev5_fingerprint.py`-style comparison on the three main `REFERENCES` (`--mode exhaustive`,
`--limit 4`) showed differences only at the 10th-12th significant digit on the values already
covered by the checks above -- consistent with "the same answer reached by a different optimiser
path" rather than a further disagreement, and was not audited candidate-by-candidate beyond that.

## Decision

**Per the decision rule fixed before Phase 2** ("ships only if no reference/truth regresses"),
this does not clear the bar. `src/autocircuit/core/fit.py` is unchanged from before this round;
the experimental `src/autocircuit/core/lshade.py` module was removed rather than left unused in
the production tree. `benchmarks/screening_round/param_opt.py`'s new arms (`lshade`, `shade`,
`jade`, `pso`, `ga_sbx`, `dual_annealing_arm`, `basinhopping_arm`, `bayes_opt`, `shgo_arm`, and the
`_wilson` confidence interval) are kept: they are a measurement instrument, not production code,
and the same script already carried CMA-ES and Sobol multi-start from the round that rejected
them.

**What would need to happen before reopening this**: the three test failures point at a concrete,
investigable defect (something about this from-scratch L-SHADE handles small, well-conditioned
problems worse than `differential_evolution` does) rather than an inherent limit of the algorithm
family -- JADE, the closest competitor in Phase 1, might be worth a similar Phase 2 pass instead,
or the existing implementation's small-`n` behaviour could be debugged directly. Neither was
attempted here: per this project's own standing rule, a candidate that already failed its
decision rule is not the place to keep tuning until it passes.
