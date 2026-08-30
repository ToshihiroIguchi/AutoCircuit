# Comparing Against AutoEIS — Results

Companion to `docs/AUTOEIS_COMPARISON_PLAN.md`, which was written before any of this was known
and which is corrected in place where a measurement contradicted it. **Withdrawn readings are
left here beside the surviving ones rather than deleted.**

Status: **run and stopped early.** §2 has the result: on truths of five and six elements, at
defaults, **neither tool recovered the circuit** — AutoCircuit 2/7 on `reported` and 0/7 on
`recommended`, AutoEIS 0/7 on both, p = 0.50 against a bar of `d` = 6. The round was stopped at 7
of 20 pre-registered pairs **after the result was seen**, which §2.1 records as a departure from
its own stopping rule rather than dressing up as a machine-time stop.

§0 is step 0, the go/no-go, and everything it measured about the other tool still stands
independently of the comparison.

---

## 0. Step 0 — go/no-go

**Outcome: go.** AutoEIS installs and runs on this machine. Four of the five checks answered
differently from what the plan expected, and two of those change what the round can be.

### 0.1 The environment, recorded because otherwise this is not reproducible

Installed **outside** the project, in its own virtual environment
(`C:\Users\toshi\python\autoeis-env`), because AutoEIS pulls Julia, JAX and NumPyro and none of
those may reach `pyproject.toml`. The numpy+scipy rule is about the shipped wheel; a
benchmark-only environment is fine as long as it stays outside the project environment, and it
does.

| | version |
|---|---|
| AutoEIS | 0.0.44 (the current release) |
| EquivalentCircuits.jl | 0.3.1, `git_revision = master` — **AutoEIS pins a branch, not a tag** (`version.py`: `__equivalent_circuits_jl_version__ = "master"`), from the fork `ma-sadeghi/EquivalentCircuits.jl` |
| Julia | 1.10.12, fetched by `juliapkg` (its `juliapkg.json` requires `~1.10.0`; this machine's own Julia 1.12.6 does not satisfy that and was not used) |
| jax / jaxlib | 0.6.2 / 0.6.2 |
| numpyro | 0.19.0 |
| juliacall / juliapkg | 0.9.35 / 0.1.26 |
| pyimpspec | 5.1.3 |
| arviz | **0.23.4, pinned by hand — see below** |
| numpy / scipy / pandas (AutoEIS env) | 2.5.2 / 1.18.1 / 3.0.5 |
| Python (AutoEIS env) | 3.12.10 |
| Python / numpy / scipy (project env) | 3.13.14 / 2.5.1 / 1.17.1 |
| this repository | `523ed20` |
| machine | Intel Core 7 150U, 10 physical cores / 12 logical, Windows 11 |

Two installation facts worth keeping, because both cost time to find:

- **Python 3.13 cannot run current AutoEIS.** `autoeis` 0.0.44 declares
  `requires_python = ">=3.10,<3.13"`, so on this machine's Python 3.13 `pip` silently offers
  0.0.35 as the newest candidate. Comparing against a release eight versions behind would be a
  worse round than installing an interpreter, so Python 3.12.10 was installed (winget, user
  scope) and the environment built on that.
- **A clean `pip install autoeis` today produces a build whose last stage crashes.** AutoEIS
  0.0.44 requires `arviz` with no upper bound, pip resolves it to 1.3.0, and arviz 1.x no longer
  has `az.waic` — so `compute_fitness_metrics` dies with
  `AttributeError: module 'arviz' has no attribute 'waic'`. That is the stage the tool's *own*
  ranking rule comes from, so it cannot be skipped. Fixed by pinning `arviz==0.23.4`, the last
  release that has `waic`; stages 4 and 5 then complete. This is recorded rather than quietly
  repaired because "the other tool at its defaults" has to mean a build that runs, and the next
  person to install it will hit the same wall.
- **`perform_full_analysis()` raises `NotImplementedError`.** There is no single end-to-end call.
  The supported path, and therefore the definition of "AutoEIS at its defaults" for this round,
  is the documented step-by-step pipeline: `generate_equivalent_circuits` →
  `filter_implausible_circuits` → `perform_bayesian_inference` → `compute_fitness_metrics`, each
  at its own default arguments.

### 0.2 The five checks

**1. The quickstart runs.** Import takes 42 s; the first touch of the Julia runtime takes a
further 147 s, which installs Julia 1.10.12 and precompiles EquivalentCircuits.jl. That cost is
paid **once per process**, not once per spectrum, which is a constraint on how the producer script
of step 1 must be written: one process, many spectra.

**2. The element vocabulary is `R`, `C`, `L`, `P` — and there is no Warburg.**
`parser.validate_circuit()` accepts exactly `["R", "C", "L", "P"]`. The plan's §2.1 expected
`R, C, L, P` **and `W`**; `W` does not exist in this version. Worse for arena A, the default
`terminals` argument of `generate_equivalent_circuits` is **`"RLP"`** — an ideal capacitor is not
in the default alphabet at all — and `filter_implausible_circuits` then runs a
`capacitance_filter` that **drops every surviving circuit containing an ideal `C`**. AutoEIS's
default position is that a capacitor is a CPE.

**3. Programmatic access: yes.** `generate_equivalent_circuits(freq, Z, ...)` returns a
`pandas.DataFrame` with columns `circuitstring` and `Parameters` (a `dict[str, float]`). No
notebook is involved.

**4. Seed control: the argument exists and the default path does not honour it.** This was
measured rather than read. `core.py` carries the comment
`# FIXME: This doesn't work when multiprocessing` above the seeding line of
`_generate_ecm_parallel_julia`, which is the function `parallel=True` — the default — selects.
Three runs on identical data, 10 iterations each:

| run | seed | circuits returned |
|---|---|---|
| 1 | 1 | `R1-[P2-P3,R4]`, `[L1-R2,R3-P4]`, `[P1,R2]-R3`, `[[P1-L2,R3]-[L4,R5],R6]-R7` |
| 2 | **1** | `P1-R2-[P3,R4]` |
| 3 | 2 | `R1-[P2,[P3,L4]-R5]` |

Runs 1 and 2 are the same seed and share nothing. The comparison can see a difference (runs 1 and
3 differ too), so this is not a broken instrument reporting equality — it is a genuine
irreproducibility. Per the plan's §5 step 0 item 4, this is recorded rather than worked around,
and **every AutoEIS run in this round is an independent draw**. Consequences:

- Pairing for McNemar (§4 of the plan) survives, because the pairing is on the *spectrum* — both
  tools read the same CSV with the same noise realisation — not on the tool's internal RNG.
- The round is **not exactly reproducible on the AutoEIS side.** A re-run gives different
  answers. This must appear next to any number the round reports.
- A seeded arm is available (`parallel=False` takes the `_generate_ecm_serial` path, which sets
  `Random.seed!` in-process), but it is not the default and it is roughly ten times slower. If it
  is used at all it is a separate, labelled arm, never the headline.
- Unrelated but in the same function: `seed = seed or time.time_ns() % 2**32`, so **`seed=0` is
  not a seed** — it falls back to the clock. Seeds start at 1.

**5. Cost: about 40 minutes per spectrum, and the generation stage is nearly all of it.**
Ten generation iterations took 221.7 s, 209.4 s and 205.7 s, and the default is `iters=100`, so
the generation stage alone is roughly **35 minutes per spectrum**. The Bayesian stage was then
measured separately at its defaults (`num_warmup=2500`, `num_samples=1000`), on two circuits fitted
to one spectrum: **35.7 s per circuit on one run and 52.7 s on another** — the spread is this
machine's own drift, which `docs/HANDOFF.md` §4 documents at 2× — with both circuits converged and
zero divergences. `compute_fitness_metrics` costs about 2 s. So the total is the generation stage
plus roughly 40 s per circuit that survives the filters, and the fear that a single run might take
hours is not borne out.

### 0.3 A reading that was withdrawn, kept here because the mistake is the useful part

**Withdrawn: "setting `PYTHON_JULIACALL_THREADS` deadlocks the default path."** AutoEIS never sets
Julia's thread count, so it is 1, and giving Julia the machine's ten physical cores looked like
the obvious first improvement. With `PYTHON_JULIACALL_THREADS=10` the run appeared to stall — no
progress for twelve minutes, and the Python process accumulating 0.03 s of CPU per 45 s of wall
clock — and that was reported as a deadlock.

It was not. `circuit_evolution_batch` parallelises through Julia's **`Distributed`**, not through
threads: it spawns one `julia.exe` worker process per physical core
(`nprocs = psutil.cpu_count(logical=False)`). Ten workers were present, each parented to the
Python process and each saturating a core. The parent shows no CPU **because the parent does no
work**, and the instrument — CPU time of one process — could not see the computation at all.
`PYTHON_JULIACALL_THREADS` was never relevant to this code path in either direction.

Two things to keep from it. Measuring the wrong process looks exactly like measuring a stalled
one. And the parallelism here is fixed at the physical core count with no argument exposed, so
"how many cores AutoEIS uses" is not a knob this round can set or report as a choice.

**Withdrawn, the same mistake a second time: "stage 4's multiprocessing is broken under the
venv."** `perform_bayesian_inference` at its default `parallel=True` spawns a worker for each
circuit, and on Windows that worker appears as the *base* interpreter
(`...\Programs\Python\Python312\python.exe`) rather than the virtual environment's. That looked
like a child that could not import `autoeis`, and the run it was diagnosed from was indeed sitting
still. It was reported as broken and it is not: the same call, left alone, completed in 71.4 s
with both chains converged. A venv's spawned child is launched from the base executable by design
and inherits the environment's paths.

Twice now a stall has been diagnosed from the process table and twice it was wrong. The rule this
round now follows is that **a run is judged when it finishes or fails, not from a snapshot of what
its processes look like** — process inspection can say what is running, never that nothing is
progressing.

### 0.4 What step 0 changes in the plan

**§2.1 was wrong about the vocabulary, and the consequence is larger than the correction.** The
plan expected the intersection to shrink arena A to "the two Maxwell-Wagner references plus the
Randles one". Against the vocabulary and the default filters that actually shipped, **arena A is
empty**:

| reference (`benchmarks/discovery_v2.py`) | AutoEIS at its defaults |
|---|---|
| `C1-R1-L1-SKINF1` | `oov` — `SKINF` is not in the vocabulary; also series-only, so `series_filter` would drop it |
| `p(R1,C1)-p(R2,C2)` | `filtered` — no series ohmic resistor (`ohmic_resistance_filter`); `C` is also outside the default `terminals` and killed by `capacitance_filter` |
| `R1-p(C1,R2-W1)` | `oov` — no `W` in this version |
| `p(R1,C1)-p(R2,C2)-p(R3,C3)` | `filtered` — same as the two-block case |
| `C1-R1-L1-SKINF1-p(R2,CPE1)` | `oov` — `SKINF` |
| `R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)` | `oov` — `Wo` |

Six of six. This does not make arena A worthless — an `oov`/`filtered` census *is* a result, and
it is the one the plan's §6 predicted — but it removes arena A as a source of any recovery
number. **Arena C is no longer merely the arena whose result is quotable without a caveat; it is
the only arena in which a recovery rate exists at all.** Its sampler is correspondingly
constrained: truths must be expressible in `R`, `L`, `CPE`, must contain a series ohmic
resistance and at least one parallel route, and must not contain an ideal capacitor — and the
fraction of the shared vocabulary that those constraints exclude is itself a number this round
should report rather than quietly design around.

**§5 step 1 gets easier in one place.** The CPE definitions are identical —
`Z = 1/(Q·(jω)^n)` here (`core/elements.py`), `Z = 1/(P·w·(jω)^(P·n))` there
(`parser.replace_components_with_impedance`). `Pw` maps to `Q` and `Pn` to `n` with no unit
conversion, which removes a whole class of silent scoring bug from `translate.py`.

**§3's `recommended` metric has a definition on the AutoEIS side, and it is theirs, not ours.**
`visualization.py` ranks the result table by `WAIC (sum)` ascending. Using that as AutoEIS's
single top answer is reading the tool's own rule rather than imposing one.

### 0.5 The other tool deletes data before its search sees it, and an inductor is what it deletes

Read from `utils.preprocess_impedance_data`, which is the first call of AutoEIS's documented
pipeline and runs at its defaults (`tol_linKK=5e-2`, `high_freq_threshold=1e3`). Three heuristics
run in order, and all three remove points:

1. Among frequencies above 1 kHz, find the point of minimum `|Im Z|` and **discard everything
   above it**. On a spectrum with no inductive tail the minimum sits at the top of the sweep and
   nothing is lost. On a spectrum with an ESL, the minimum is the self-resonance, and **the whole
   inductive region above it is deleted.**
2. Then delete any remaining point above 1 kHz with `Im Z > 0` — the inductive tail again.
3. Then run Lin-KK and delete every point whose real or imaginary residual reaches 5%.

On AutoEIS's own bundled test dataset this removed 7 of 67 points (10%), and it warned about it.

This is a defensible position for a tool aimed at electrochemical cells, where an inductive tail
is usually instrument artefact rather than sample. It is not a defect. Where a spectrum does have
an inductive tail, the evidence for the `L` is gone before the search starts, and a miss there is
the preprocessing rather than the search — a distinction the failure taxonomy of the plan's §3 does
not yet have a code for, and which is not the same event as `filtered`.

**Corrected by measurement.** This section first said that *for a truth containing an `L`,
AutoEIS's search never sees the evidence for it.* That is too strong, and the arena's own spectra
say so. Each of the eight truths was put through `preprocess_impedance_data` at its defaults:

| truth | L | circuit | kept | points with `Im Z > 0` |
|---|---|---|---|---|
| c3_0 | no | `p(CPE1,CPE2)-R1` | 88.9% | 8 |
| c3_1 | yes | `p(R1,L1)-R2` | 72.8% | 47 |
| c4_0 | yes | `p(R1,L1)-R2-L2` | **63.0%** | 58 |
| c4_1 | yes | `p(L1,CPE1)-R1-CPE2` | **100.0%** | 0 |
| c5_0 | yes | `p(CPE1-CPE2,CPE3)-R1-L1` | 97.5% | 2 |
| c5_1 | yes | `p(R1-L1,CPE1)-R2-L2` | 90.1% | 30 |
| c6_0 | no | `p(p(R1,CPE1)-p(R2,CPE2),R3)-R4` | 98.8% | 0 |
| c6_1 | yes | `p(p(L1-CPE1,CPE2)-L2,L3)-R1` | **63.0%** | 56 |

[measured] Mean kept: **80.7% across the six `L` truths, 90.3% across the two without** — but the
mean is the least informative number on the table. What the preprocessing responds to is whether
the spectrum actually *has* an inductive tail in the window, which is a property of the topology
and its parameters, not of the presence of an `L`: `c4_1` carries an inductor, has no point with
`Im Z > 0`, and loses nothing at all, while `c4_0` and `c6_1` lose more than a third. And an
`L`-free truth loses points too — `c3_0` gives up 11% — which is the Lin-KK residual filter rather
than either inductive heuristic.

So the split the report needs is **not only** `L` against no-`L`. `L` is the cheap proxy that was
pre-registered, and it is kept; but the producers record `n_points_in` and `n_points_used` per run,
so the honest secondary reading is against **how much of the spectrum that run's search actually
received**. A recovery rate on 63% of a sweep is not comparable to one on all of it, and neither is
comparable to a claim about the search.

Two consequences for arena C, both of which have to be decided in the open rather than absorbed:

- Excluding `L` from the sampler would build an arena around the other tool's weakness in one
  direction; including it without saying so would build one in the other. So `L` is included, and
  results are reported **split into `L`-containing and `L`-free truths**, with the number of
  points the preprocessing removed recorded per run.
- "Both tools read the same file" stays true, and is no longer the same as "both searches saw the
  same data". The scorer records both counts, because a recovery rate against a spectrum that lost
  a third of its points is not comparable to one against the whole sweep.

### 0.6 What step 0 did *not* measure

- The NUTS stage has not been run or timed, so the per-spectrum cost above is a **lower bound**.
- `filter_implausible_circuits` was exercised once and the generation run it was given returned
  **zero** circuits, so it filtered 0 → 0. That is a vacuous observation, not a measurement of the
  filter, and it is recorded here as vacuous. The filter's behaviour above is read from its
  source, not from a run.
- Nothing has been scored. There is no arena, no truth, and no comparison in this document.

---

## 2. The result, and why it stops at seven pairs

**Neither tool recovered a five- or six-element circuit from its spectrum, at defaults. That is
the finding, and it is a statement about both.**

[measured, 2026-08-30] Arena C, truths of five elements and up (§1.5d), one referee applied to
both sides:

| | AutoCircuit | AutoEIS |
|---|---|---|
| `reported` — truth or an exact equivalent anywhere in the candidate list | **2/7** | **0/7** |
| `reported`, judged on each tool's own parameter values | 2/7 | 0/7 |
| on the Pareto front / in the post-filter surviving set | **0/7** | **0/7** |
| **`recommended` — the single answer the tool puts forward** | **0/7** | **0/7** |

| by size | AutoCircuit | AutoEIS |
|---|---|---|
| 5 elements | 2/5 | 0/5 |
| 6 elements | 0/2 | 0/2 |

Paired: 2 discordant runs, both this project's way, 0 the other. **p = 0.50 against `d` = 6.**
The pre-registered verdict applies and is not reworded: **indistinguishable at this seed count.**

Two things are worth separating in that table. AutoEIS returned nothing truth-equivalent on any of
the seven runs, across all four truths. And **this project recommended the truth zero times out of
seven** — it put a truth-equivalent circuit *somewhere* in its candidate list twice, and never on
its own front, and never as its answer. A reader looking for a winner here will not find one.

Every AutoEIS run lost points to its own preprocessing (81 → 60–74), and the failure taxonomy is
`ok` on all fourteen runs: no crash, no `filtered`, no empty result on either side. These are
searches that finished and returned the wrong circuit.

### 2.1 The round was stopped early, and not for the reason the rule allows

**Stopped at 7 of the 20 pre-registered pairs, on the user's decision, after seeing the result.**
§1.6 says the round stops on machine time and never because of what a result looks like. This stop
was because the result looked null, which is a different direction from the one that rule was
written against but **the same mechanism**, and calling it a machine-time stop would make every
other self-imposed limit in this document unverifiable. So it is recorded as what it is.

The reasoning, such as it is: after four runs on one truth showed nothing, three more runs were
added — one seed each of the three truths that had no AutoEIS data at all — specifically to test
whether the zero was that truth's property or general. It was general: 0/7 across four truths.
With `reported` running at 2/7 for this project and 0/7 for AutoEIS, completing all twenty pairs
projects to roughly 6/20 against 0/20, which sits exactly on `d` = 6 — so nine more hours would
most likely have bought either "indistinguishable, add seeds" or a result balanced on a single
run. The pre-registered answer to that is more seeds, and more seeds is another twenty hours.

What this costs the round, stated rather than glossed: **seven pairs cannot resolve a difference
that twenty might have**, and the 2/7 versus 0/7 gap on `reported` is left unresolved rather than
shown to be absent. The data, the arena and the scripts are all in place; `run_round.ps1` with
`-MaxSeeds 5` continues from where it stopped and costs nothing already spent.

### 2.2 What this side did wrong, which the round found and the comparison did not need

The more useful half of the result is about this project, and it is not about the genetic search's
quality. [measured] **`generations` is 0 on all forty runs — the genetic fallback never ran once.**
`mode="auto"` falls back only when the best exhaustive fit leaves a systematic residual, tested as
a runs-test `z < -3.0`. The recorded values on the six-element truths are **−0.45, +0.67, −0.45,
+0.67** and on the five-element ones **0.00, +0.22**: nowhere near it. A five-element answer
reproduces these spectra to within what 1% noise hides, so the trigger never fires and the search
stops one completeness level below the truth.

So `docs/EVOLVE_SEARCH_PLAN.md`'s measured 5/9 for the fallback is not what limited this round —
the fallback was never asked. The limit is the **sensitivity of the trigger**, and that is a
defect this comparison surfaced which no amount of tuning the genetic search would have touched.

A second observation from the same records, unresolved: on `c6_0` the pool chooser reported a
**5.7–6.9 decade 45-degree branch** and set `triggered: yes`, then widened nothing because the
measured low-frequency exponent `[-0.90, -0.17]` admitted none of `W`, `Ws`, `Wo`, `G`. The truth
`p(L1-CPE1,R1)-p(CPE2,CPE3)-R2` has three CPEs, so the long 45-degree branch is real and is not
diffusion. Whether that is the detector working correctly or getting the right answer for the
wrong reason is not established here.

---

## 1. Arena C — how it is built, written before it is run

`benchmarks/autoeis_round/arena.py`. Everything it fixes is in the pre-registered block at the top
of that file with the reason beside it; the two decisions worth repeating here are that **`L` stays
in the pool** even though the other tool's preprocessing deletes the evidence for it (§0.5), and
that **sizes run to 6**, one past the point where this project's exhaustive stage stops being
complete and its measurably weaker genetic fallback takes over. Stopping at five would hand this
side its strongest configuration and call the result a comparison. Results are reported per size
and split by whether the truth contains an `L`, so neither half is averaged away.

### 1.1 The structural filters were reproduced and then checked against the original

Two of AutoEIS's four default post-filters decide whether a truth can be returned by it at all: it
must have a bare resistor in the top-level series chain (`ohmic_resistance_filter`, via
`parser.find_ohmic_resistors`) and it must contain a parallel route (`series_filter`). The sampler
has to apply the same two rules, and a subtly different reading of them would quietly change the
arena — which is a score with no symptom, the same failure mode `translate.py` is tested against.

So they were not reasoned about; they were **run**. All 1020 topologies of sizes 2–5 in the pool
`("R", "L", "CPE")` were translated into AutoEIS syntax and put to AutoEIS's own functions in its
own environment. [measured] **1020 cases, 0 errors, 0 disagreements on either filter.** The check
is not vacuous: the ohmic predicate is true for 164 of the 1020 and false for 856, the parallel
predicate true for 1004 and false for 16, so a disagreement had ample opportunity to appear. It
also put `translate.py`'s outbound direction through 1020 circuits without an error.

### 1.2 Most of the shared space is unreachable by the other tool's defaults

A by-product of the same census, and a number worth having on its own:

| size | topologies in pool | admissible | rejected: no series R | rejected: no parallel route |
|---|---|---|---|---|
| 3 | 32 | 4 | 26 | 2 |
| 4 | 156 | 24 | 130 | 2 |
| 5 | 824 | 128 | 694 | 2 |
| 6 | 4664 | 692 | 3970 | 2 |

The requirement of a series ohmic resistance alone removes about **85%** of the shared vocabulary's
topology space. That is a statement about the other tool's default assumptions rather than about
its search, and it is why arena C samples inside the admissible set instead of sampling freely and
reporting a landslide of `filtered` events that would say nothing about either search.

### 1.3 The arena as it came out, including the bias the sampler was not designed to avoid

[measured] Eight truths, two per size, from 4 / 24 / 128 / 692 admissible topologies at sizes
3–6. The census: **4820 draws rejected for having no series ohmic resistance**, 8 for no parallel
route, and **132 parameter draws rejected as unidentifiable** before any tool ran.

| id | circuit | L? |
|---|---|---|
| c3_0 | `p(CPE1,CPE2)-R1` | no |
| c3_1 | `p(R1,L1)-R2` | yes |
| c4_0 | `p(R1,L1)-R2-L2` | yes |
| c4_1 | `p(L1,CPE1)-R1-CPE2` | yes |
| c5_0 | `p(CPE1-CPE2,CPE3)-R1-L1` | yes |
| c5_1 | `p(R1-L1,CPE1)-R2-L2` | yes |
| c6_0 | `p(p(R1,CPE1)-p(R2,CPE2),R3)-R4` | no |
| c6_1 | `p(p(L1-CPE1,CPE2)-L2,L3)-R1` | yes |

**Six of the eight contain an inductor.** Uniform sampling over a pool of `R`, `L`, `CPE` makes
`L` common — foreseeable, and not foreseen when the sampler was written. It matters because
AutoEIS's default preprocessing deletes the inductive tail before its search sees it. How much it
actually deletes on *these* spectra is measured in §0.5 and is not uniform: it ranges from nothing
at all to more than a third, and it tracks whether the spectrum has an inductive tail rather than
whether the circuit has an inductor.

**The arena was not re-drawn.** Changing a pre-registered sampler after seeing its draw is the
move this plan exists to forbid, and it would be no less a selection for having been made on the
arena rather than on a score. What is done instead is stated here in advance of any result: the
**`L`-free subgroup is the search comparison and the `L`-containing subgroup is the preprocessing
effect**, they are reported separately, and the `L`-free subgroup is **thin** — two truths, so ten
pairs at the first stage and forty only if the round reaches twenty seeds. A difference inside the
`L`-free group at five seeds cannot be resolved (`d = 6` against ten pairs is possible but only
for a near-total split), and saying so now is cheaper than discovering it afterwards.

### 1.4 Is this a fair comparison? Written before the result, because afterwards it would look
like a rationalisation

**One narrow claim can be compared fairly. The two tools cannot, and no sentence in this document
may be read as ranking them.**

What was actually done to make the narrow claim fair, each of it measured rather than intended:
both sides read the same files with the same noise realisations, so the pairing is real; one
referee — numeric equivalence at `EQUIVALENCE_RTOL` — is applied to both candidate lists through
the same code, verified on a fixture where the other tool's exact reparameterisation of the truth
had to score as a hit and did; the two structural filters the sampler reproduces were checked
against AutoEIS's own functions on 1020 topologies with zero disagreements; out-of-vocabulary
truths leave that tool's denominator instead of scoring zero; a refusal and a wrong answer are
separate rows; and `d` and the stopping rule were fixed before any run.

What remains unfair or limited, listed in full because a limitation discovered later reads as an
excuse:

1. **The arena is defined by the other tool's constraints but built by our machinery** — our
   enumerator, our parameter ranges, our notion of a plausible topology.
2. **The identifiability screen is *our* fitter's verdict.** 132 draws were discarded because a
   fit of ours left a parameter unresolved, so the arena is shaped toward circuits our fitter
   handles well. This is the largest single hole and it was not accounted for when the sampler was
   written. §1.5 closes it as far as it can be closed without re-drawing the arena.
3. **The two searches do not see the same data even from the same file.** AutoEIS preprocesses and
   we do not: between 63% and 100% of each sweep survives (§0.5).
4. **We change regime at six elements and they do not.** Above five, this project falls back to a
   genetic search measured at 5/9 against the exhaustive stage's 30/30. Reporting per size shows
   it; it does not remove it.
5. **The plan wanted an arena "authored by neither" and this one is authored by our sampler.**
   Pre-registration limits the damage; it does not undo the authorship.
6. **Only one of the two products is being asked about.** AutoEIS's Bayesian posteriors are its
   distinguishing output and are deliberately unscored, so what is compared is "topology and
   values from defaults", not which tool is better at what it is for.
7. **Their side is unseeded** (§0.2), so their runs are independent draws while ours are
   reproducible. The round is not exactly repeatable on their side.

### 1.5 Asking the other tool whether it agrees the truths are identifiable

Hole 2 above can be partly answered rather than only declared. AutoEIS is put to the *same*
question about the same eight truths with its own instrument: infer the true circuit's parameters
with `perform_bayesian_inference` at its defaults, and count a parameter unresolved when its
posterior coefficient of variation reaches 1 — its own convention, not ours mapped onto it.

**The arena is not re-drawn on the answer.** Changing a pre-registered sampler after seeing its
draw is what §1.3 refuses, and it would be no less a selection here. Truths the two instruments
disagree about carry a caveat wherever they appear.

**What the answer was, and why it mostly is not about the arena.** [measured] AutoEIS calls 3 of
the 8 identifiable where our screen calls 8 of 8. That looked like the arena bias hole 2
describes, and it is almost entirely something else. Running the leverage test — *our*
deterministic instrument — on **the sweep AutoEIS actually receives after its own preprocessing**
lines the two up almost exactly:

| truth | below the noise floor on *their* data | AutoEIS called unresolved | |
|---|---|---|---|
| c3_0 | — | — | agree |
| c3_1 | — | — | agree |
| c5_0 | — | — | agree |
| c4_0 | `L1.L`, `L2.L`, `R1.R` | `L2`, `L4`, `R1` | **same three** |
| c4_1 | `CPE1.Q`, `L1.L` | `P2w`, `L1` | **same two** |
| c5_1 | `CPE1.Q`, `CPE1.n`, `L1.L`, `R1.R` | `P3w`, `R4` | subset |
| c6_1 | `CPE2.Q`, `CPE2.n`, `L1.L`, `L2.L` | `P2w`, `L1` | partial |
| c6_0 | — | `L1`, `P2w` | disagree |

The magnitudes say it plainly: `c4_0`'s `R1` has 1.14% leverage on the full sweep and **0.00%** on
the 51 points AutoEIS keeps; `c5_1`'s `CPE1.Q` goes 2.75% → 0.01%. The parameters AutoEIS cannot
resolve are, with one exception, exactly the parameters its own preprocessing removed the evidence
for.

So hole 2 is much smaller than it looked. The arena is fair *to the data as generated* — every
parameter of every truth is above the noise floor on the full sweep — and AutoEIS's handicap on
these truths is one its defaults impose on themselves. That is a legitimate part of "the other
tool at its defaults" and is to be **reported, not corrected**: the round would be measuring
something else entirely if the spectra were trimmed to suit it. `c6_0` is the one real
disagreement and carries a caveat.

### 1.5b An interim look, recorded because hiding it would be the problem

[2026-08-30] With this project's side complete (40 of 40) and AutoEIS's at 9 of 40, the scorer was
run on the 9 pairs that existed. **This is not a result and must not be quoted as one.** It is
recorded here for two reasons: the look happened, and concealing it would make "the round stopped
on machine time" unverifiable afterwards.

What it showed: AutoCircuit 9/9 reported and 9/9 recommended, AutoEIS 3/9 and 1/9, six discordant
runs all in one direction, p = 0.0312. That formally reaches `d`, and it is still not the round's
answer:

- The 9 pairs are **two truths out of eight**, both the smallest size and both `L`-free — the
  first two in arena order, which is a non-random subset of the arena rather than a sample of it.
- The truths not yet run include the 5- and 6-element ones, which are where **this project is
  weakest**: above five elements its exhaustive stage gives way to the genetic search, measured at
  5/9 against the exhaustive stage's 30/30 (`docs/EVOLVE_SEARCH_PLAN.md`). The gap should be
  expected to narrow.
- The round continues to the pre-registered end of the seed list. **Stopping here because the
  number looked good is exactly what §1.6 forbids**, and the fact that it currently looks good is
  the reason to say so explicitly rather than quietly.

The look was worth taking for a different reason, and that part *is* a finding. AutoEIS's misses
on `c3_0` were audited candidate by candidate: all 16 of its post-filter circuits translated and
fitted without error, and the closest reached a residual of 4.3e-2 against the referee's 1e-6
threshold, at 2–3.6% relative error on 1% noise data. So they are genuinely unexplained fits
rather than near-equivalents the referee mishandled — and, more importantly for the round's
validity, **the translator and the referee work on real data**. The silent failure this round is
most exposed to, where the other tool's candidates fail to translate and are scored as misses,
is not happening.

### 1.5c Three quarters of the arena sits inside this side's completeness guarantee

[measured] Of the 40 AutoCircuit runs, **30 have the truth inside the exhaustive stage's
completeness guarantee** — `complete_up_to` comes back as 4 or 5, and the truths at sizes 3, 4 and
5 are at or below it. On those runs the truth was *enumerated and fitted by construction*: the
question was only whether the two-tier screen and the ranking kept it, not whether a search found
it. Only the ten size-6 runs are outside the guarantee.

That is a different kind of achievement from a stochastic search arriving at the same circuit, and
it means **the aggregate across sizes is close to a foregone conclusion and must never be the
headline.** `arena.py` says results are reported per size and gives this as the reason; the
statement was too quiet for how much it matters. The informative rows are the size-6 ones, where
enumeration cannot reach and both tools are searching.

It is not a pure tautology — a screening budget that keeps the truth but drops it from the
shortlist is a failure this project has measured on itself (`DISCOVERY_V2_PLAN.md` §3.3) — but it
is close enough that a reader who quotes the pooled number will be quoting the arena's design
rather than a comparison.

One further observation from the same records, which will matter when the size-6 rows are read:
**`generations` is 0 on every run**, so the genetic fallback never ran. `mode="auto"` only falls
back when the best exhaustive fit still shows systematic residuals, and on these spectra it did
not — including at size 6, where a 5-element answer apparently explained the data well enough to
stop. If this side misses the six-element truths, that is where it will come from, and it is a
statement about the fallback trigger rather than about the fallback.

### 1.5d The analysis set was cut to five elements and up — the user's decision, after an interim

**On 2026-08-30 the user decided that the round scores only truths of five elements or more, and
asked for the decision to be recorded as theirs.** It is implemented as `MIN_ELEMENTS` in
`score.py`, the report names the excluded truths on every run, and nothing is deleted — the runs
for `c3_0`, `c3_1`, `c4_0` and `c4_1` remain in the tables and can be scored at any time with
`--min-elements 3`.

**Their argument**, which §1.5c had just measured: below five elements AutoCircuit does not search
for the truth, it enumerates it, so a comparison there is decided by the arena's construction
rather than by the two searches.

**The objections put to them before they decided**, recorded so a reader can weigh the same things
rather than take the outcome on trust:

1. The completeness guarantee covers sizes 3, 4 **and 5** — `complete_up_to` is 4 or 5 on every
   run — so a cut at five still keeps ten runs the argument would exclude, and the cut matching
   the argument is six.
2. Changing the analysis set after seeing a result is the mechanism this round refuses everywhere
   else (§1.3, §1.6). That the change is *unflattering* to this project does not change the
   mechanism, and a document that allows the exception here cannot claim the rule elsewhere.
3. The discarded rows carry a real measurement **of AutoEIS** — 3 of 9 at three elements, on
   spectra where its own preprocessing removed almost nothing — which someone choosing between the
   tools would want. Cutting them removes information about the other tool, not only about this
   one.

The alternative offered was to keep every row and delete the *pooled* figure instead, since the
pooled figure is what misleads and the rows themselves are measurements.

The user considered these and chose five. **This section exists so that the choice is visible
rather than absorbed**, and any reader who prefers a different cut has both the data and the
argument to make it.

One consequence to keep in view: at five and above the arena is four truths, so a five-seed stage
is twenty pairs and `d` is 6. That is reachable but thin, and the response to it is the
pre-registered seed list — ten seeds, then twenty — not a further change to what is scored.

### 1.6 Stopping rule, fixed now so that it cannot be chosen later

The seed list (1–20) and the stage boundaries (5, 10, 20 seeds) are written into `arena.py` before
the first run. Extending the round runs more of an already-written list; it never chooses seeds
after seeing a result. **The round stops when the machine time runs out or the seed list is
exhausted — never because a result looked significant.** A stopping rule that depends on the data
is not a stopping rule, and the reason it is recorded here is so that the claim can be checked
rather than believed.
