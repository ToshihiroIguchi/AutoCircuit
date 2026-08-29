# Shortlisting Search Algorithms — a Cheap Round Before the Plan

Status: **screening round, 2026-08-23. The measurements are real; what they support is a
shortlist, not a design.** Nothing here is implemented.
Prerequisite reading: `docs/SEARCH_ALGORITHM_SURVEY.md` (the twelve candidates this round ranks)
and `docs/EVOLVE_SEARCH_PLAN.md` §1 and §4 (the failure being shortlisted against, and EV1's
1/9 baseline). Scripts and the frozen tables are in `benchmarks/screening_round/`.

This is the round `HANDOFF_PROMPT.md` task E needs before its plan document can be written. The
survey ranked twelve candidates by *expected* benefit over cost; every entry in that ranking is
an expectation, and the instrument that would settle them — `benchmarks/discovery_v2.py
evolve-gate` — costs 2.5–3 hours per arm. Shortlisting twelve candidates that way is not a
budget anyone has.

## 1. Why the gate is the wrong instrument for this question

`evolve-gate` is budgeted in **wall clock** and fits every topology it looks at, so one number
answers three questions at once:

| factor | what it is | which survey candidates own it |
|---|---|---|
| **F1** | seconds per topology evaluation (1.33 s on the six-element reference, 5.4 s on the seven) | a compiled kernel; (h) VARPRO |
| **F2** | how many topologies a search must visit before it reaches the answer | (d) MCTS, (e) MAP-Elites/ALPS, (f) NSGA-II, (g) branch and bound |
| **F3** | whether a visit scores the topology correctly when it happens | (i) L-SHADE / CMA-ES, (j) DIRECT, (h) VARPRO |

Time to the answer is `F1 x F2`, and F3 decides whether F2 is finite at all. A gate that reports
one pass fraction cannot say which of the three moved, which is why EV3 needed ten seeds and two
sides before it was readable at all (`EVOLVE_SEARCH_PLAN.md` §3.3.1). For *shortlisting*, each
factor needs its own instrument, and each instrument can be far cheaper than the gate.

## 2. The instruments

### 2.1 The frozen landscape (F2)

Screen **every** plausible topology in the space `_evolve` searches, once, and keep the table. A
topology-search algorithm then becomes a pure combinatorial search over a lookup table:
milliseconds per run, hundreds of seeds free, and — because the budget is counted in table
misses rather than seconds — a comparison immune to what else is running on the machine. That
last property is not a nicety. `benchmarks/README.md` records three separate occasions where a
wall-clock budget measured the machine rather than the search, and `EVOLVE_SEARCH_PLAN.md` §4
says outright that its own baseline "is a description of the search rather than a fixed point to
diff against" for exactly that reason.

Three arenas were built, all on the same reference and spectrum (§5.2 is why that last clause
turned out to matter, and the two arenas step 5 added to fix it):

| arena | topologies | build |
|---|---:|---|
| `R,C,L` n ≤ 6 | 2,174 | 1.9 min, 8 workers |
| `R,C,L` n ≤ 7 | 11,033 | ~15 min |
| `R,C,L,CPE` n ≤ 6 | 21,057 | 51.9 min |

The incumbent arm is **not a reimplementation**: it drives `discover._next_generation`,
`discover.mutate`, `discover.crossover`, `discover._tournament`, `discover.random_topology` and
`discover._unique_best` directly, with only the evaluator swapped. A reimplementation would
measure the harness.

Four limitations, stated here rather than discovered later:

* The table is **screen-grade** (`fit.screen`, the exhaustive stage's tier 1). `_evolve`'s
  `_Evaluator` runs `fit(restarts=1, ..., local=PUBLISH_LOCAL)`, about 4x dearer. §4.6 is what
  closes this assumption rather than leaving it standing.
* A frozen table cannot express **parameter inheritance**, where a topology's score depends on
  which parent proposed it, so every arm is measured in the `warm_accept=0` world — the control
  arm gate EV3 already uses.
* Early abandon is off, so every entry is comparable.
* **All three arenas freeze the same truth**, and until step 5 the round had never once varied
  the shape of the circuit it was looking for. That is fine for arms that differ in how they
  *select*, and it is a confound for any arm carrying a prior over *structure* — §5.2 is where one
  of those won an arena by knowing the answer's shape, and it is the section to read before
  trusting a single-truth result.
* **Only the easiest of EV1's three references can be put on a landscape at all.** The
  capacitor + interfacial reference has 107,534 topologies at n ≤ 6 on its pool, and the
  Randles + ESL truth has seven elements. Those are the two references where the search scores
  0/3. This round therefore ranks algorithms on the one reference that already works, and the
  transfer to the other two is untested. The mitigation is a scaling check rather than a claim:
  the arms are run on arenas that differ 10x in size and at two element caps, and only a ranking
  that survives those changes is reported as a ranking. §4.2 is where that mitigation earns its
  place — the ranking on the small arena is **not** the ranking on the large one.

### 2.2 Counted function evaluations (F3)

Every parameter-side arm searches the identical `_Problem` — same log-space bounds, same
weighting, same data — with a counting wrapper around the cost function, and is followed by the
identical trust-region polish. The budget is **cost-function evaluations**, so again the machine
is not the thing being measured.

### 2.3 A profile of one evaluation (F1)

`cProfile` over one tier-1 screen, reported as fractions of that process's own time, which is
what makes the reading survive a loaded machine — everything slows together. This is the
measurement that decides whether a compiled kernel (C, C++, Cython, numba) is on the table.

### 2.4 The real search, instrumented (validation)

A cheap instrument that has not been checked against the expensive one is a guess with a table
in front of it. `_Evaluator.evaluate` is wrapped so that every topology the real `_evolve`
actually fits is recorded with its score, and the run is then asked the same question the frozen
model answers: was the truth's equivalence class reached, and did it reach the report?

## 3. The KPIs, for this round only

These are shortlisting instruments. None is proposed as a gate, and none should outlive this
document.

| KPI | definition | unit |
|---|---|---|
| **KPI-0** (gatekeeper) | rank of the truth's equivalence class in the frozen landscape, by tier-1 screening AICc | rank / size |
| **KPI-1** | `E@hit`, table misses until the class is first evaluated (median over seeds); `HR@B`, hit rate within budget B, with a Wilson 95% interval | fits; fraction |
| **KPI-2** | selection pressure — probability the best-known candidate enters a tournament — first generation vs last | ratio |
| **KPI-3** | fraction of (topology, seed) pairs where an optimiser lands within 1% of the best cost any arm reached, at equal NFE | fraction |
| **KPI-4** | share of one evaluation's own time in the impedance kernel, in scipy's DE bookkeeping, and in per-topology setup | percent |

Two rules make the round honest:

* **KPI-0 is a gatekeeper, not a score.** If the tier-1 score does not already point at the
  class, no topology-search algorithm can fix EV1's 1/9 and the whole F2 half of the survey is
  the wrong half to shortlist from. It is one second of arithmetic and it is asked first.
* **An arm advances only on a non-overlapping Wilson interval.** With hundreds of free seeds
  there is no excuse for reading a difference off single events, which is the error
  `EVOLVE_SEARCH_PLAN.md` §3.3.1 records having nearly made. §4.2's decisive run is 120 seeds
  because 30 was not enough to separate the top arms.

## 4. Results

All on the three-block Maxwell-Wagner reference of `EVOLVE_SEARCH_PLAN.md` §3.1
(`p(R1,C1)-p(R2,C2)-p(R3,C3)`, 1% noise, seed 0) — the one of EV1's three references that
recovers anything at all.

### 4.1 KPI-0 — the score points at the truth's class on every arena

| arena | topologies | the truth's rank by screening AICc |
|---|---:|---|
| R,C,L, n ≤ 6 | 2,174 | **1–13** — a thirteen-way exact tie at −1680.986; next best −1550 |
| R,C,L, n ≤ 7 | 11,033 | **10**; by *raw cost* it is 85th, and the parsimony penalty is what puts it back |
| R,C,L,CPE, n ≤ 6 | 21,057 | **17** — the sixteen above it are seven-parameter CPE variants at −1682.511 |

The exact-equivalence class, verified by refitting every candidate within 5% of the truth's
screening cost and comparing responses under `EQUIVALENCE_RTOL` exactly as
`_large_truth_verdict` does:

| arena | within 5% of the truth's cost | **verified exact equivalents** | density |
|---|---:|---:|---:|
| R,C,L n ≤ 6 | 13 | **12** | 0.55% |
| R,C,L n ≤ 7 | 175 | **109** | 0.99% |
| R,C,L,CPE n ≤ 6 | 136 | **18** | **0.085%** |

**The tier-1 criterion is not what loses EV1's recovery.** Even where the strict top of the list
is occupied, it is occupied by the truth's own CPE reparameterisations (a CPE at n = 1 *is* a
capacitor, the phenomenon `benchmarks/README.md`'s excluded-equivalents table already records),
not by something unrelated.

**Within one pool, the class grows with the space; across pools it does not.** Going from n ≤ 6
to n ≤ 7 on R,C,L multiplies the space by 5 and the class by 9, so the density *rises* — which is
what §4.3 turns out to depend on. Adding CPE multiplies the space by 10 and the class by 1.5, so
the density **falls 6.5x**. Those are opposite effects and the second one is half of §4.6's
explanation.

**A correction, recorded rather than replaced.** The right-hand column above is the third answer
this question got. It was first asked of a 1,176-point uniform sample, which returned "not one
sampled topology out-scores the truth" — true of the sample, and too strong an inference, since
the sixteen that do are 0.09% of the n = 6 level and a 400-point sample expects 0.35 of them. It
was then asked with cost proximity standing in for the response test, which over-counted the CPE
arena's class by **7.6x** (136 against 18). Only the full enumeration plus the response test
gives the number, and §4.2's first reading was taken on the proxy.

**A correction, recorded rather than replaced.** This question was first asked of a **1,176-point
uniform sample** of the CPE space, which returned "not one sampled topology out-scores the
truth". That statement is true of the sample and the inference drawn from it was too strong: the
sixteen that do out-score it are 0.09% of the n = 6 level, so a 400-point sample expects 0.35 of
them. The full enumeration is what corrects it, and a sample is not a rank.

### 4.2 KPI-1 and KPI-2 — the ranking on the small arena is not the ranking on the large one

Budget 450 fits, Wilson 95% intervals. `beam` is deterministic, so it gets one run and no
interval.

**Small arena** (`R,C,L n ≤ 7`, 11,033 topologies, 12 verified targets, 30 seeds) — everything
ties:

| arm | cap 6 | median fits | cap 7 | median fits | selection pressure |
|---|---|---:|---|---:|---|
| random (the same proposal distribution, no selection) | 15/30 [0.33,0.67] | 261 | 22/30 [0.56,0.86] | 218 | — |
| current (`_evolve` as it is) | 30/30 [0.89,1.00] | 122 | 30/30 | 109 | 0.123 → 0.007 |
| ga_bounded | 30/30 | 101 | 30/30 | 104 | 0.123 → 0.070 |
| staged (element cap earned, not granted) | 30/30 | 129 | 30/30 | 126 | 0.337 → 0.007 |
| nsga2 | 30/30 | 98 | 30/30 | 108 | 0.029 → 0.025 |
| mapelites (element count as descriptor) | 30/30 | 144 | 30/30 | 152 | 0.043 → 0.025 |
| beam, width 4 | 1/1 | **86** | 1/1 | **86** | — |

**Large arena** (`R,C,L,CPE n ≤ 6`, 21,057 topologies, **18 verified targets at 0.085%**, budget
900 fits, **120 seeds**) — they separate, and by a lot:

| arm | hit rate | 95% CI | median fits | pressure |
|---|---|---|---:|---|
| current (`_evolve` as it is) | 87/120 | **[0.64, 0.80]** | 451 | 0.103 → 0.003 |
| **ga_bounded** (breeding pool stops growing) | **120/120** | **[0.97, 1.00]** | 308 | 0.103 → 0.064 |
| **nsga2** | **120/120** | **[0.97, 1.00]** | **256** | 0.031 → 0.025 |
| **mapelites** | **120/120** | **[0.97, 1.00]** | 418 | 0.037 → 0.023 |
| random | 26/120 | [0.15, 0.30] | 478 | — |
| mapelites + ALPS (30 seeds, cost-proximity targets, budget 450) | 24/30 | [0.63, 0.90] | 282 | 0.037 → 0.006 |
| staged (30 seeds, cost-proximity targets, budget 450) | 27/30 | [0.74, 0.97] | 270 | 0.209 → 0.007 |
| beam, width 4 (cost-proximity targets, budget 450) | 1/1 | — | 220 | — |

**Three arms clear the advancement rule, and they have exactly one thing in common.**
`ga_bounded`, `nsga2` and `mapelites` all reach 120/120 against the incumbent's 87/120, on
intervals that do not touch. What separates them from `current` is not their operators, their
descriptors or their sorting — all three **bound the set they breed from**, and `current` is the
only arm that draws parents from an archive that grows every generation. That is §1.2's
diagnosis, measured.

**This table's first reading was taken on a proxy and it understated the effect.** With cost
proximity standing in for the response test (136 targets rather than 18) and a 450-fit budget,
the same run read `current` 109/120 [0.84,0.95], `ga_bounded` 120/120, `nsga2` 120/120 and
`mapelites` **118/120 [0.94,1.00]** — which put MAP-Elites *inside* the incumbent's
neighbourhood and left it out of the shortlist. On the verified targets it is 120/120 and it
belongs in. The ranking by median fits also inverts at the top: `nsga2` 256 against
`ga_bounded` 308, where the proxy had them at 160 and 145.

**§1.2's pathology is real, and it only bites on the large arena.** The 8.2x pressure collapse
reproduces as 0.103 → 0.007 (15x). On the 11,033-topology arena, bounding the breeding pool
changes *nothing* (30/30 either way) because the class is reached in about three generations,
before the archive has grown enough for the collapse to matter. On the 21,057-topology arena the
search needs longer, the collapse has time to happen, and the same fix is worth eleven seeds in
120. **A round that had stopped at the small arena would have reported "no candidate beats the
incumbent" and been wrong** — the same shape as `screen` versus `screen-rank`
(`benchmarks/README.md`), where a cheaper budget looked free on the easy reference and dropped
the answer on the real space.

**Survey candidate (e) is vindicated in its diagnosis and not in its machinery.** The archive
really is the problem, and every arm that bounds it recovers 120/120. But the *cheapest* way to
bound it wins on change size and comes second on speed: `ga_bounded` is a few lines around
`_next_generation`'s caller, against a MAP-Elites archive (120/120, median 418 — the slowest of
the three) and a non-dominated sort (120/120, median 256 — the fastest). Adding ALPS on top makes
it clearly worse (24/30). What the survey ranked first is right about *why* and wrong about *how
much code*.

**Beam search stays interesting and is not yet decidable.** Growing one element at a time and
keeping the best four of each size reaches the class in 86 fits on the small arena and 220 on the
large one, with **no seed at all**. Widths 1 and 2 miss entirely and width 24 costs 249, so the
width is a measurement rather than a choice — and one deterministic run per arena is not a pass
fraction.

### 4.3 The element cap is not the problem — a hypothesis raised and refuted

`current` spends 48% of its budget in the top size layer, which made "the search drowns in the
largest layer, where the truth is not" the leading explanation. It is wrong. Raising the cap from
6 to 7 changes nothing (30/30 either way, median 122 → 109), and `staged` — which earns the cap
instead of being handed it — is no better on either arena. §4.1 says why: the class grows with
the space at roughly constant density, so a larger layer brings proportionally more right answers
with it.

### 4.4 KPI-3 — the incumbent optimiser is the best arm tried

13 topologies x 2 seeds, budget in cost-function evaluations, every arm followed by the same
polish. "In basin" is within 1% of the best cost any arm reached on that pair.

| arm | in basin | median NFE |
|---|---|---:|
| **`differential_evolution` 8x40 (current)** | **24/26** | 2,624 |
| the same at `strategy="rand1bin"` | 24/26 | 2,624 |
| Sobol multi-start + trust region (12 starts) | 23/26 | 3,190 (mean 15,968 — a bad tail) |
| 8x20 | 20/26 | 1,344 |
| 4x40 | 19/26 | 1,312 |
| CMA-ES (textbook, numpy, restarted) | 16/26 | 1,640 |
| CMA-ES at half the budget | 12/26 | 824 |

Survey candidate (i) is demoted, with a caveat that keeps it open: this is a from-scratch CMA-ES
at standard hyper-parameters, and L-SHADE was not implemented at all. What is measured is that
**halving the incumbent's own budget beats CMA-ES at comparable cost** (20/26 at 1,344 against
16/26 at 1,640), which is not what a replacement is supposed to look like.

### 4.5 KPI-4 — a compiled kernel cannot buy the order of magnitude

`cProfile` over one tier-1 screen, as fractions of that process's own time:

| | three-block MW | a topology with a CPE |
|---|---:|---:|
| impedance kernel (`elements.py`, `circuit.py`, the residual arithmetic) | 36.1% | 46.3% |
| scipy's differential-evolution bookkeeping | 27.6% | 26.3% |
| per-topology setup (`_Problem`, bounds, parsing) | 33.1% | 25.4% |
| trust-region polish | 3.2% | 2.0% |

`cost_vectorized` costs 306 µs at population 1 and 19–44 µs per individual at population 120, so
the population evaluation is already amortised and what remains is genuine array arithmetic.
**Amdahl bounds a compiled kernel at roughly 1.4–1.7x overall**, against a gap that needs an
order of magnitude. C++, Cython or numba is therefore *not* the lever — and it would cost the
"the same wheel runs under Pyodide" rule that `CLAUDE.md` makes a hard one. The one line in that
table worth a second look is **setup at 23–33%**: a quarter of every screen is spent building
`_Problem` and deriving bounds, which is neither the kernel nor the optimiser and is plain Python.

### 4.6 The cheap instrument agrees with the expensive one — and names the real cause

Everything above is the frozen model. This is `_evolve` itself, instrumented, on the same
reference, at a 180–200 s budget, `warm_accept=0`.

| pool | cap | space | real fits | s / fit | class reached | class **reported** |
|---|---:|---:|---:|---:|---|---|
| R,C,L | 7 | 11,033 | 290, 339 | 0.87 | **2/2**, rank 1 of all fits | **2/2** (4 and 12 members) |
| R,C,L | 9 | 313,607 | 270, 331 | ~1.0 | **2/2**, rank 1 | **1/2** |
| R,C,L,CPE | 7 | ~156,000 | 207 | 1.77 | **0/1** | 0/1 |

**The frozen landscape's prediction transfers.** Where it says 30/30, the real search reaches the
class in 2/2 seeds and ranks it first among everything it fitted. The instrument is sound.

**And EV1's 1/9 becomes attributable — to CPE, in two ways at once.** Doubling the space beyond
the CPE pool's size, at R/C/L fit cost, costs nothing: 2/2 still reach the class. Adding CPE at a
*smaller* space costs everything. Volume alone is therefore not the constraint, and what CPE
changes that volume does not is a product of two measured factors:

* **1.77 s against 0.87 s per fit**, so the same wall clock buys 207 fits instead of ~300; and
* **the class's density falls from 0.55% to 0.085%** (§4.1) — 6.5x rarer, because CPE multiplies
  the space by 10 and the truth's exact equivalents by only 1.5.

Together that is roughly a **13x** harder search bought with 0.7x the fits, against an incumbent
whose median requirement on that arena §4.2 measures at 451 fits with a third of seeds never
arriving. EV1's 1/3 on this reference is what those numbers predict.

**One row of that table is a defect rather than a measurement.** At cap 9, seed 0, the class was
visited nine times and **ranked 1 of 270 fits by screening AICc, and not one of the nine reached
`candidates`.** The search found the answer, scored it best, and the report did not contain it.
That is `EVOLVE_SEARCH_PLAN.md` §1.4's family — a loss inside the reporting path rather than the
search — and confirming it comes before any search work, because no search improvement is worth
anything while the shortlist can drop a first-ranked candidate.

#### 4.6.1 Confirmed, and it was the third stage rather than either of the two suspected

`evolve_probe.py` can see that the class was visited and not reported; it cannot see which stage
lost it. `report_probe.py` wraps `_shortlist_candidates` and `_refine` and prints, for the same
run, the archive rank of every verified class member, its position in the shortlist, and where
the deadline cut fell.

**The shortlist kept it. The refit never got to it.** Four of the six class members in the
archive were shortlisted, including the rank-1 member, and the deadline cut fell at 40 of 73:

```
shortlist sizes in the order _refine walked them:
  3,3,3,3,3,3,3,3,3,3, 2,2,2,2,2, 1,1,1, 5,5,5,5,5,5,5,5,5,5, 4,4,4,4,4, 9,9,9,9,9,9,9 | 9,9,9, 7×10, 6×10, 8×10
                                                                        cut at 40 ────┘
  rank    1 of 270  size 6  shortlist position 53  -- PAST THE CUT  reported=False
  rank    4 of 270  size 7  shortlist position 43  -- PAST THE CUT  reported=False
  rank    5 of 270  size 7  shortlist position 44  -- PAST THE CUT  reported=False
  rank    7 of 270  size 7  shortlist position 46  -- PAST THE CUT  reported=False
```

`_quota_by_size` returns its selection **grouped by element count, the groups in whatever order
the archive first mentioned them**. That is right for the exhaustive stage, which refits all of
them, and it is not an order at all for a tier that stops when the clock runs out: sizes 6 and 8
were never attempted, so the report contained no six-element row while the best thing the search
had found was one. Neither of the two candidates the handoff named was to blame — the per-size
quota did its job and `REFIT_HEADROOM` did its job. The missing piece was that nobody had said
what order a *bounded* tier 2 should walk in.

`_refine` now walks `_refit_order`: a round robin over the size groups, best of every size before
any size's second, ordered within a round by score. On the same run, same seed, same 40 fits:
**4 of 4 shortlisted class members reported**, the rank-1 member refitted first. Two tests in
EV2's shape pin it, both shown to fail against the previous code, and `benchmarks/ev5_fingerprint.py`
(now committed, where the EV5 probe used to be rebuilt by hand) says the exhaustive path is
byte-identical across the change.

### 4.7 One measurement that was nearly lost, and how

The first version of the instrumented probe reported "class members visited: **0**" on runs whose
best screening AICc was **−1680.99** — the class's own value to two decimals. It was feeding
`Circuit.canonical_form()` (which is `[p(C,R)-p(C,R)-p(C,R)]`, a normalised label and not a
circuit string) to `fit`; every call raised, and a bare `except Exception: continue` swallowed
all forty. An empty result that looks like an answer is this project's characteristic failure
(`docs/HANDOFF.md` §3), and it was caught only because a *different* number in the same printout
contradicted it. The probe now counts its own refit failures and prints them beside the result.

A second one is worth the same warning. A 51-minute landscape build was declared killed on the
strength of a log file whose last line was stale; the run had in fact completed, and the arena it
produced is the one §4.2's conclusion rests on. **Both the small-arena "everything ties" reading
and the sampled KPI-0 would have stood as this round's answer had that file not been noticed.**

## 5. What this round decides, and what it does not

**Advances — 120/120 against the incumbent's 87/120, on intervals that do not touch.** All three
do the same thing (bound the breeding set) and differ only in how much code it takes; the order
is by change size, not by median, because the medians are close and the risk is not.

| candidate | evidence |
|---|---|
| **bounding the breeding pool** (`EVOLVE_SEARCH_PLAN.md` step 4's first half; the minimal reading of survey (e)) — **adopted; it is `discover._breeding_pool`** | 120/120 [0.97,1.00], median 308 fits against 451. A few lines around `_next_generation`'s caller. Re-measured against the shipped rule (the arm now calls it rather than restating it) and unchanged: 120/120, median 308. **Since superseded on its width** — see §5.1 |
| **(f) NSGA-II** | 120/120 [0.97,1.00], median **256** — the fastest arm measured, for a selection rewrite |
| **(e) MAP-Elites archive** (without ALPS) | 120/120 [0.97,1.00], median 418 — clears the bar, and is the slowest and largest of the three |

**Do not adopt, on this evidence:**

| candidate | verdict |
|---|---|
| ALPS age layering on top of MAP-Elites | 24/30 against MAP-Elites' 120/120; the one addition measured to make things worse |
| (i) CMA-ES | loses to the incumbent, and to the incumbent at half budget. L-SHADE remains unmeasured |
| a compiled kernel (C/C++/Cython/numba) | 1.4–1.7x ceiling against a 13x gap, and it costs the Pyodide rule |
| raising or staging the element cap | measured to change nothing on either arena |

**Still worth a plan:**

| candidate | why it survived |
|---|---|
| (g) branch and bound / beam growth | deterministic, 86 fits on the small arena and 220 on the large one, with bounded cost per level — the shape a completeness sentence needs. One run per arena is not a pass fraction, so it needs a stochastic variant before it can be gated |
| (h) VARPRO | untested here, and the one candidate that attacks the factor §4.6 identifies as binding: seconds per fit |
| pool staging inside `_evolve` | not a survey entry at all. `descriptors.choose_pool` already stages widening for the exhaustive stage; §4.6 measures the fallback going 0/1 → 2/2 when CPE is out of the pool |
| the 23–33% spent in per-topology setup (§4.5) | neither kernel nor optimiser, plain Python, and nobody has looked at it |

### 5.1 A later round, on the same instruments: how wide the bound should be

The round above measured *bounded against unbounded* and stopped there. The width it adopted was
`population`, which was the number already in `_breeding_pool`'s argument list rather than a
measured one. A later ladder — `ga_tight20`, `ga_tight10`, `ga_tight5`, `ga_tight3`, `ga_tight1`,
`ga_front`, plus `arm_islands` — ran it down to zero. `docs/EVOLVE_SEARCH_PLAN.md` §3.4.3 and
§3.4.4 carry the tables; three things belong here, because they are about the instrument rather
than about the search.

**The 900-fit budget this round used is saturated for every one of those arms.** All eleven reach
120/120, so the ladder can only be read as median fits, and read that way the islands arms beat
the incumbent. Drop the budget to 150 and the ranking is different and the reason is visible: the
islands lose to a single pool of their own width. §4.2 of this document says the cheap arena
ranked nothing; this says a *saturated* one does the same thing, and the check is the same —
confirm the arena still has somewhere to fail before believing a ranking it produces.

**The paired table in `arms.py` could not see a hit-rate difference at all.** It compares
fits-to-hit and drops every seed either arm missed, which at an unsaturated budget is the entire
signal. An exact McNemar on the discordant seeds is now printed above it, and it changed a
verdict: two islands read 77/120 against a single pool's 65/120, and at 480 seeds that is
302/480 against 282/480, p = 0.216. The response to a bar that cannot resolve its own question
is more seeds.

**A cache hit costs no budget and does cost wall time.** `Table.evaluate` returns a known
topology without incrementing the fit counter, so the tighter arms re-propose what they already
know and take far longer in wall clock while spending fewer fits. Budget in fits is the right
unit for the comparison and the wrong unit for an ETA; a tight arm that looks hung is not.

### 5.2 A later round again: the round had only ever asked about one circuit

§2.1's fourth limitation says this round ranks algorithms on the one reference whose space can be
enumerated, and that the transfer to the other two is untested. That is true and it understates
the problem, which step 5 of `docs/EVOLVE_SEARCH_PLAN.md` found by walking into it.

All three arenas above — `land_rcl6`, `land_rcl7`, `land_rclcpe6` — are three *spaces* around one
**truth**: `p(R1,C1)-p(R2,C2)-p(R3,C3)`, five of whose six elements are joined in parallel. Every
mitigation §2.1 offers varies the space (10x in size, two element caps) and none of them varies
the answer. For the arms this round compared — operators, archives, breeding pools — that is
probably harmless. For anything carrying a **prior over structure** it is not.

[measured, `EVOLVE_SEARCH_PLAN.md` §3.5.2, `results_mutation_weights.txt`] The mutation-weight arm
that shifts weight from insert-series to insert-parallel reaches the truth's class in 308/480
against the incumbent's 282, McNemar p = 0.018 — a clean win on every reading this round has, on
its largest arena, at 480 seeds. On a truth of the opposite shape it loses by a comparable margin
(281/480 against 306, p = 0.0001) and the mirror arm reverses both signs; the reversal survives
raising the element cap from six to seven. **The arm was not searching better. It knew the answer's
shape.**

So the round now has a second truth, and the instrument is cheap: `landscape.py --reference series`
freezes `C1-R1-L1-p(R2,C2)` — `LARGE_REFERENCES[1]` with the CPE and the skin-effect element
replaced by their plain counterparts, the same physics in a pool small enough to enumerate — at a
cost of one landscape build and one `targets.py` run. Nothing in §4 is re-opened by this: no arm
there varies a structural prior, and the two that came closest (`arm_beam`'s growth operator and
`arm_map_elites`' cells) were rejected on other grounds. But **any future arm that biases *what
kind of circuit* gets proposed has to be run on both truths before its number means anything**,
and a single-truth win is now known to be a thing this round can produce.

Two smaller instrument notes from the same step:

**A new arena needs its budget calibrated before it can rank anything.** The series arena is 12x
denser in targets than the CPE one (1.06% against 0.085%), so the 150 fits that leave the CPE
arena at 59% leave this one saturated at 40/40. §5.1's rule — check the arena still has somewhere
to fail — turns out to apply to the arena as well as to the ladder.

**`targets.py --max-checks` could silently drop the truth.** It truncates the cost-sorted band
from the cheap end and the truth sits at that band's expensive end by construction, so an arena
whose band exceeds the cap returned a target set not containing the answer — indistinguishable
from an arena with no equivalents. The n ≤ 7 series arena has a band of 761 against a default cap
of 400. The truth row is now appended unconditionally and a truncated band prints a warning.

**What this round cannot decide:**

- Anything about the two references where `mode="evolve"` scores 0/3. Their spaces cannot be
  enumerated, so §2.1's limitation stands unrelieved.
- Whether pool staging is safe on a truth that genuinely needs a CPE. It is precisely the
  capacitor + interfacial reference that would say, and it is the one this round could not build
  an arena for.
- Whether a ranking measured at screening grade holds at publication grade — though §4.6 is
  evidence that it does for the quantity that matters here.
- L-SHADE, MCTS, RJMCMC and the group-LASSO ladder, none of which were implemented.
