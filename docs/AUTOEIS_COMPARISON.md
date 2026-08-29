# Comparing Against AutoEIS — Results

Companion to `docs/AUTOEIS_COMPARISON_PLAN.md`, which was written before any of this was known
and which is corrected in place where a measurement contradicted it. **Withdrawn readings are
left here beside the surviving ones rather than deleted.**

Status: **step 0 complete (go). Steps 1–5 not started.** Nothing below is a comparison of the two
searches; step 0 only establishes that a comparison can be run at all, and at what price.

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
| arviz | 1.3.0 |
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

**5. Cost: about 21 s per generation iteration, so ~35 min per spectrum at the default budget.**
Ten iterations took 221.7 s, 209.4 s and 205.7 s. The default is `iters=100`, which puts the
generation stage alone at roughly **35 minutes per spectrum**, before filtering and before the
NUTS stage (`num_warmup=2500`, `num_samples=1000` per surviving circuit, not yet timed).

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
is usually instrument artefact rather than sample. It is not a defect. But it means that **for a
truth containing an `L`, AutoEIS's search never sees the evidence for the `L`**, and a miss there
is its preprocessing rather than its search — a distinction the failure taxonomy of the plan's §3
does not yet have a code for, and which is not the same event as `filtered`.

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

### 1.3 Stopping rule, fixed now so that it cannot be chosen later

The seed list (1–20) and the stage boundaries (5, 10, 20 seeds) are written into `arena.py` before
the first run. Extending the round runs more of an already-written list; it never chooses seeds
after seeing a result. **The round stops when the machine time runs out or the seed list is
exhausted — never because a result looked significant.** A stopping rule that depends on the data
is not a stopping rule, and the reason it is recorded here is so that the claim can be checked
rather than believed.
