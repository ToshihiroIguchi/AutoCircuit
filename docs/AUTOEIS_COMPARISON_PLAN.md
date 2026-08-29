# Comparing Against AutoEIS — the Plan, Written Before the Answer Is Known

Status: **step 0 run; steps 1–5 not started.** No number in this file is a result. Where step 0
contradicted this plan the correction is marked **[corrected by step 0]** in place — the original
expectation is left visible beside it, and `docs/AUTOEIS_COMPARISON.md` §0 carries the
measurements.
Prerequisite reading: `CLAUDE.md` (`### Purpose`, especially point 3), `docs/SEARCH_ALGORITHM_SCREENING.md`
§1 and §4.2 (why a wall-clock budget and a cheap arena both mislead), and
`docs/EVOLVE_SEARCH_PLAN.md` §3.3.1 (what happens to a two-sided bar that cannot resolve its own
question).

AutoEIS is cited in four places in this repository — `docs/IMPLEMENTATION_PLAN.md:71,84,289,549`,
`docs/SEARCH_ALGORITHM_SURVEY.md:85,99`, `docs/DISCOVERY_V2_PLAN.md:421` and
`src/autocircuit/core/discover.py:20` — always as prior art or as the source of the post-filtering
and down-selection design. **It has never been run.** There is no arm for it in `benchmarks/`, no
timing, no recovery count. Every comparative statement this project could make today is an
expectation, which is precisely the state `SEARCH_ALGORITHM_SURVEY.md` was in before the screening
round contradicted its top recommendation.

---

## 1. The one comparable claim

AutoEIS and AutoCircuit are not the same product, and a feature table is not a measurement. The
single question both tools answer, and therefore the only one this round scores:

> Given an impedance spectrum and **the tool's own default settings**, does it return the true
> topology and its parameter values, with no user-supplied initial values and no statement of
> what kind of part this is?

That framing is not neutral by accident: point 3 of `CLAUDE.md`'s Purpose is that a non-expert
reaches a defensible answer, and a non-expert runs defaults. Any tuned arm is a separate, labelled
run and never the headline.

**Explicitly out of scope, and not to be scored, tallied or implied:**

- Bayesian posterior quality. AutoEIS has NUTS posteriors; this project has none, by the
  numpy+scipy rule (`SEARCH_ALGORITHM_SURVEY.md:99` — ruled out by the dependency rule, not by
  merit). Absence of a stage is not a measured difference.
- Equivalence-class reporting, the objective axis, skeleton mode, SPICE export, the browser build,
  the element vocabulary beyond the intersection of §2.1. These are things one tool has and the
  other does not. Listing them is documentation; scoring them is an own-goal disguised as a result.
- Real-sample interpretation. There is no truth on a real ceramic, so a real spectrum can only show
  agreement or disagreement, never correctness. See §7.

---

## 2. Fairness constraints, fixed before any run

Each of these exists because the opposite choice would produce a flattering number that means
nothing.

### 2.1 The arena is built in the *intersection* of the two vocabularies

`REGISTRY` here holds twelve codes (`R, C, L, CPE, W, Ws, Wo, G, ColeCole, HN, SKINF, SKINR`).
EquivalentCircuits.jl — the generator underneath AutoEIS — is expected to offer `R`, `C`, `L`, `P`
(CPE) and `W`; **step 0 must confirm this from the installed version rather than from this
sentence.**

Consequence: two of the three `LARGE_REFERENCES` in `benchmarks/discovery_v2.py` contain `SKINF`,
and one contains `Wo`. Those elements are **out of AutoEIS's vocabulary**. A truth the other tool
cannot express is scored **N/A, never 0**. Reporting an out-of-vocabulary reference as a failure
would be the same move as scoring an absent posterior stage, pointed the other way.

The arena is therefore built from topologies in the confirmed intersection. That shrinks the usable
part of the existing fixtures to the two Maxwell-Wagner references plus the Randles one (`W`,
if confirmed), and is the reason §5 builds a third, neutral set.

**[corrected by step 0]** The estimate in the paragraph above was wrong in the unfavourable
direction. The installed version's vocabulary is `R`, `C`, `L`, `P` and **contains no `W`**, the
default `terminals` is `"RLP"` so an ideal capacitor is not even in the default alphabet, and
`capacitance_filter` deletes any surviving circuit that contains one. Together with
`ohmic_resistance_filter` (a series ohmic resistance is required) this leaves **none** of this
repository's six reference truths scorable — three `oov`, three `filtered`. Arena A therefore
yields an `oov`/`filtered` census and no recovery number, and **arena C is not merely the
quotable arena but the only one in which a recovery rate exists.** The table is in
`docs/AUTOEIS_COMPARISON.md` §0.4, together with what those filters force on arena C's sampler.

### 2.2 Our own references are home turf, and the source comments prove it

`LARGE_REFERENCES` carries measurements in its comments showing the fixtures were *tuned until
identifiable*: `f_max` widened from 1e5 to 1e7 because an ESL was unidentifiable below it, `R2`
lowered from 5 kΩ to 5 Ω because 3 of 8 parameters were unresolved above it. That was correct for
their purpose — a gate must not ask a search for something the data does not contain — and it makes
them a biased arena for a cross-tool round. A comparison run only on them measures who wrote the
fixtures.

Three arenas, therefore, and the neutral one is the one that counts:

| arena | truths from | what it can show |
|---|---|---|
| **A** | this repo's references, restricted to §2.1 | continuity with every existing gate number |
| **B** | AutoEIS's own bundled/published examples | the same courtesy in reverse |
| **C** | pre-registered random sampling in the shared vocabulary, authored by neither | the only arena whose result is quotable without a caveat about its author |

If A and C disagree, **C is the finding and A is the home-field measurement of it.**

### 2.3 One referee decides what counts as a hit, and it is ours for both sides

A hit is: the returned topology's `canonical_form()` equals the truth's, **or** it is an exact
reparameterisation of the truth, judged by this repo's numeric equivalence at `EQUIVALENCE_RTOL`.
`R1-p(R2,C1)` and `p(R1,C1-R2)` fit the same data to 1.2e-15 (`IMPLEMENTATION_PLAN.md:86`), so a
tool that returns the second when the truth is the first has found the truth.

Applying our equivalence detector to our own output and a string comparison to theirs would be
scoring the referee, not the searches. The same referee, run on both tables, in the same process.

### 2.4 Budget parity is not achievable, so it is not claimed

Fits-count parity cannot be enforced across a Python search and a Julia one that does not report
comparable counts. Wall clock measures the machine — `benchmarks/README.md` records three separate
occasions in this project alone where it did exactly that, and `EVOLVE_SEARCH_PLAN.md` §4 says its
own baseline is "a description of the search rather than a fixed point to diff against" for that
reason.

So: **recovery at defaults is the headline; time is a description.** Time is reported with the
machine, its load state, and Julia's precompilation excluded and stated as its own number. No
speed-up ratio appears in any conclusion.

---

## 3. Metrics, pre-registered

**Per (arena, reference, seed), for each tool:**

1. `reported` — a truth-equivalent (§2.3) anywhere in the tool's returned candidate list, after its
   own filters.
2. `on_front` — for this project, on the reported Pareto front; for AutoEIS, in its post-filter
   surviving set. These are *not* the same object and the table says so in a footnote rather than
   pretending otherwise.
3. `recommended` — the tool's single top answer. Ours: `DiscoveryResult.recommended`. AutoEIS: its
   top-ranked model.

The three-way split is `Verdict`'s and exists because they are different questions: a capacitor
whose ESR is barely resolvable at 1% noise can legitimately be *recommended* as a simpler model
with the truth on the front beside it.

**Parameter accuracy, only on runs where `reported` is true:**

- Worst per-parameter relative deviation, **matched by value, never by name.** Three parallel RC
  blocks in series carry a permutation symmetry, so a name-by-name comparison is meaningless — the
  three-block reference's own comment says so.
- Unresolved-parameter count. Ours: `stats.unresolved_mask` (stderr ≥ value). AutoEIS: posterior
  coefficient of variation ≥ 1. **These are different instruments** and the mapping is an
  approximation, labelled as one wherever it appears — the same treatment `METRICS_AND_UX_PLAN.md`
  §2.3 gave WAIC.

**Failure taxonomy** — a wrong answer and a refusal are not the same event, and collapsing them is
how a round produces a number nobody can act on:

| code | meaning |
|---|---|
| `oov` | truth outside the tool's vocabulary → excluded from that tool's denominator |
| `filtered` | the tool's physics filters removed the truth (e.g. a truth with no series R) |
| `crash` | the run raised |
| `timeout` | exceeded the per-run cap fixed in step 0 |
| `wrong` | completed, returned candidates, none truth-equivalent |

`filtered` is the interesting one and must not be folded into `wrong`. A filter that deletes the
right answer from a search still calling itself complete is a failure mode this project has already
measured on itself twice (`HANDOFF.md` §3, `DISCOVERY_V2_PLAN.md` §3.4).

**Lin-KK cross-check, reported, not scored.** Both tools implement the Boukamp/Schönleber test.
Run both on identical data and print an agreement table. A disagreement is worth knowing about for
`core/validate.py`'s sake and has nothing to do with which search is better.

---

## 4. The bar, written now so it cannot be reworded later

**This round is a description, not a gate. No default in this repository changes on its result.**
What it may change is what `IMPLEMENTATION_PLAN.md` and `SEARCH_ALGORITHM_SURVEY.md` are allowed to
say about prior art, and — if AutoEIS wins on arena C — what the next search-side plan document is
about.

- The paired comparison is **McNemar's exact test on per-seed `reported`**, tool against tool, on
  identical spectra (same reference, same seed, same noise realisation). Unpaired hit-rate
  comparison is not used: `EVOLVE_SEARCH_PLAN.md` §3.4.4 records a paired table in this repo that
  could not see a hit-rate difference at all and had to be fixed rather than trusted.
- **Resolution is declared before the run.** At S seeds per reference and R references, the round
  can only resolve a difference of `d` discordant pairs; step 4 writes `d` into the results file
  from the arena size actually affordable. If the outcome lands inside `d`, the finding is
  *"indistinguishable at this seed count"* and the response is more seeds or nothing — never a
  reworded bar. Two islands survived to 480 seeds before McNemar demoted them at p = 0.216; a
  five-seed impression would have shipped them.
- **Pre-registered outcomes.** If AutoEIS reports more truths on arena C, that is the finding, it
  goes into `IMPLEMENTATION_PLAN.md` marked `[measured]`, and the diagnosable reason (its filters?
  its GEP operators? its Bayesian ranking?) becomes the next plan document. If this project reports
  more, the same, with §7's limits attached. If they tie, that is also a result and is written as
  one.

---

## 5. Steps

### Step 0 — go/no-go, ≤ 1 h, and a legitimate place for the round to die

Install AutoEIS in an **isolated environment** — its own conda env or venv, outside this project's,
because it pulls Julia (via `juliacall`/`EquivalentCircuits.jl`) and a JAX/NumPyro stack that must
never reach `pyproject.toml`. The numpy+scipy rule is about the shipped wheel; a benchmark-only env
is fine, and it stays out of the project env entirely.

Then, in this order:

1. Run AutoEIS's own quickstart to completion on its own example data.
2. **Confirm the element vocabulary** from the installed version (§2.1).
3. **Confirm programmatic access** — a function call that returns the candidate list, not a
   notebook that plots it.
4. **Confirm seed control** over both the GEP stage and NUTS. If the run is unseedable, say so in
   the results file and treat every run as an independent draw.
5. **Time one spectrum end to end.** This number sizes every arena below. If one run is hours, the
   seed count collapses and §4's resolution `d` must be recomputed before anything else is built.

**[corrected by step 0]** All five checks were run and the outcome is **go**; the numbers are in
`docs/AUTOEIS_COMPARISON.md` §0.2. Three of them landed differently from the expectations above.
There is no single end-to-end call — `perform_full_analysis()` raises `NotImplementedError`, so
"at its defaults" means the documented step-by-step pipeline at each function's own defaults.
**The default path is not seedable**: two runs at the same seed returned disjoint circuit sets,
so every AutoEIS run in this round is an independent draw and the round is not exactly
reproducible on that side. And one spectrum costs roughly 35 minutes in the generation stage
alone, which is the number that sizes every arena and `d`. §0.3 of the results file records a
reading that was published and then withdrawn.

If the install does not complete on this machine within the hour, **stop and write that down**.
"AutoEIS could not be installed on the development machine on <date>, at versions <x>" is a real
outcome, it is the honest replacement for the comparison, and the current statement in the docs —
that no head-to-head exists — stays as it is. Do not substitute a literature comparison presented
as if it were a measurement. Note also that WSL may be the path of least resistance for the Julia
and JAX toolchain; the Bash tool must not call `wsl` (`HANDOFF.md` §4), so that route needs the user
to run it.

### Step 1 — the wire, before any arena (≈ 2 h)

`benchmarks/autoeis_round/`, built as two producers and one scorer so the environments never meet:

- `run_autoeis.py` — runs **in the AutoEIS env**, imports nothing from `autocircuit`, reads spectra
  from CSV files written by step 2, emits `results_autoeis.json`.
- `run_autocircuit.py` — runs in the project env, same JSON schema.
- `score.py` — project env, reads both frozen tables, applies §2.3's referee and §3's metrics, emits
  the report. It never imports AutoEIS.

Both result files record **versions of everything**: AutoEIS, EquivalentCircuits.jl, Julia,
numpyro/jax, numpy, scipy, this repo's git SHA. Without that the round is not reproducible and
therefore is not a measurement.

**`translate.py` is the part that can silently become a score.** AutoEIS's circuit strings are
expected to use `-` for series and `[a,b]` for parallel, with `P` for the CPE — *confirm in step 0*
— and must be parsed into this repo's `p(...)` grammar. A translation bug turns into a hit or a miss
with no visible symptom. It gets its own unit tests with hand-checked cases in both directions,
including at least one nested parallel and one CPE, and a round-trip test on every truth in every
arena.

### Step 2 — arena A (≈ 3 h wall clock, mostly unattended)

Our references from §2.2, restricted to the confirmed intersection, at the seed count step 0's
timing allows (target 10). Spectra are generated **once**, written to CSV, and both tools read the
same files. Neither tool regenerates data.

### Step 3 — arena B (≈ 2 h)

AutoEIS's own bundled examples. Where a truth is published, score it as in §3. Where there is none,
report only cross-tool agreement — which topologies each returned and whether they are equivalent
under §2.3 — and score nothing.

### Step 4 — arena C, the neutral one (≈ 4 h)

Sample truths from the shared vocabulary with a **pre-registered sampler**: element count range,
pool, parameter ranges and frequency window fixed and written into the script before the first run,
and chosen so the truth is identifiable at the noise level used (check by fitting the truth to its
own data and requiring 0 unresolved parameters — the same screen `LARGE_REFERENCES` applied to
itself, but applied here *before* seeing any tool's score, and applied identically to every sampled
truth rather than by hand).

Truths that fail that screen are discarded before either tool runs, and the discard count is
reported: an arena that silently drops a third of its draws is a different arena from the one the
sampler describes.

Write `d` (§4) into the results file from the arena size that was actually affordable.

### Step 5 — write it up (≈ 2 h)

`docs/AUTOEIS_COMPARISON.md`, with the withdrawn readings left in place beside the surviving ones.
Then update: `IMPLEMENTATION_PLAN.md`'s prior-art paragraph, `SEARCH_ALGORITHM_SURVEY.md`'s row 85,
a new `HANDOFF.md` section, and — only once results exist — item 15 of `CLAUDE.md`'s "Start here".

---

## 6. What can kill this round, listed now rather than discovered later

- **The Julia toolchain on Windows.** Most likely single point of failure. Step 0 exists for it.
- **AutoEIS's physics filters rejecting our truths.** `p(R1,C1)-p(R2,C2)` has no series resistance;
  if the filters require one, several arena-A references never reach its search. That is a `filtered`
  event, is worth reporting on its own, and is not a search failure.
- **Cost per run.** If a single AutoEIS run is hours, arena C shrinks to a size that resolves
  nothing. Then the round reports the timing and declines the comparison, rather than running three
  seeds and calling it a result.
- **Stochasticity without seeds.** Handled by declaration, not by hoping.
- **Version drift.** Pinned and recorded in the results files.

---

## 7. What this round may not say, even if every step succeeds

- Synthetic truths are not parts. A recovery rate on generated spectra says nothing about a real
  ceramic, where no truth exists and the equivalence classes are the whole difficulty.
- It compares **two tools' defaults, at two versions, on one machine**. It is not a comparison of
  gene-expression programming against exhaustive enumeration; the algorithms are only one of several
  differences between the two programs.
- It cannot compare posterior quality, and the absence of a posterior stage here must not appear in
  any sentence that also contains a score.
- Arena A cannot be quoted without its §2.2 caveat. Arena C can.
- A tie is not a validation of either tool. It is a statement about what this arena, at this seed
  count, could resolve.
