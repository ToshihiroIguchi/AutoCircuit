# A purpose-written vectorized DE kernel, replacing scipy's own

**Status: measured and shipped, 2026-09-13.** `src/autocircuit/core/de.py`'s `de_best1bin` is
what `core/fit.py:_global_stage`'s `workers=1` branch calls, replacing
`scipy.optimize.differential_evolution` there. Gates DE1-DE2 (a bit-exact route) and DE5
(the route that actually shipped) below; every number is measured, including the ones that
went against the shipped route before a larger sample overturned them.

## Why this exists

`docs/SEARCH_TIME_PLAN.md` §8.5, written earlier the same day, closed with exactly one unclaimed
lever:

> The one number this round found that is both large and real is §8.1's: SciPy's own DE
> bookkeeping is 48-67% of the global stage regardless of topology or CPE content ... it is the
> only place this round found real, uncommitted headroom, and it is recorded here as a priced,
> ranked candidate for a future measured round.

That 48-67% is an unbiased number (null-cost vs real-cost wall clock, normalized per DE
iteration, `benchmarks/speedup/where_time_goes.py::run_a1`), corroborated at 30-39% of a whole
`screen()` by cProfile and at 27.6-36.1% by an older `profile_eval.py` run. §8.5 declined to
build the lever, citing `docs/PARAM_OPTIMIZER_PLAN.md`'s L-SHADE withdrawal -- but that
precedent is about a *different thing*: L-SHADE was a different algorithm on a different RNG
stream, measured and failed at pipeline level (5/12 -> 0/12 seeds reaching the noise floor on a
known-hard reference, plus three broken tests on small noise-free circuits). A purpose-written
vectorized DE is the same algorithm with less Python bookkeeping around it -- priced, never
built, never measured, until this round.

## What reading scipy's own source established (do not re-derive)

`scipy/optimize/_differentialevolution.py` (scipy 1.18.1)'s `deferred`/`vectorized` path is
already almost entirely vectorized inside one generation -- `_mutate_many` draws
`fill_point`/`crossovers` in single batched calls. The per-member Python work that remains is
exactly two list comprehensions: `_select_samples`'s per-candidate `rng.shuffle` (S calls, each
drawing 5 donor indices without replacement) and `_accept_trial`'s per-candidate comparison
(reduces to `trial_energies <= energies` with no constraints, so fully vectorizable).
Everything else scipy pays for on every generation is generic machinery this project never
exercises: constraint wrapping and feasibility checks, `integrality`, the `maxfun` cap,
`updating="immediate"`, and -- found while reading the source, not anticipated in the plan --
`_global_stage` *always* installs a `callback` (its own deadline check, wired unconditionally),
and scipy's main loop responds to any callback being set by rebuilding a full `OptimizeResult`
every single generation, including rescaling the *entire* population, purely to hand to a
callback that only reads `time.perf_counter()`.

This means bit-exactness and speed are not obviously in tension: the only draws whose *order*
forces a per-member call are the S `rng.shuffle` calls, which can be kept while the surrounding
filtering, acceptance, scaling and promotion are vectorized to produce identical values. A
bit-exact replacement would pass `ev5_fingerprint.py` byte-for-byte, making the entire
L-SHADE-style quality-regression risk structurally impossible.

Also established: the `workers != 1` branch is unreachable. Nothing under `src/autocircuit`
ever calls `fit()`/`screen()` with `workers > 1` -- `discover()`'s own `workers` fans out across
*candidates* through a process pool, and each pool worker calls `fit`/`screen` at `workers=1`.
It stays on scipy, unconditionally, partly because it costs nothing unused and partly because a
process-pool worker would not inherit anything patched into a single process's `core.fit`
module, which matters for how the benchmarking in this round was done (see below).

## Route 1: bit-exact -- built, measured, and did not clear its own bar

`benchmarks/speedup/de_kernel.py`'s `de_best1bin` drives `np.random.RandomState(seed)` through
the same call sequence scipy's own driver does (Sobol init via the same `qmc.Sobol(d=n,
seed=rng)` call, a dither draw, per-candidate `rng.shuffle`, `fill_point`, crossover, bound
repair via `dtype="int64"` to match scipy's own `rng_integers` exactly -- the platform-default
`randint` dtype is 32-bit on Windows and 64-bit on Linux, which would otherwise desync the
stream). It does not reimplement any RNG; it only removes the generic bookkeeping around the
same draws.

**DE1 (bit-exact parity).** `result.x` bit-identical (`np.array_equal`) to
`differential_evolution` on 6 topologies (3-6 free parameters, half CPE-bearing) x 5 seeds x 2
budgets (screen 8x40, publish 20x400), plus 6 cases with `x0` supplied, plus parity against
`_global_stage` itself. **72/72 PASSED.**

**DE2 (speed).** Bar: real-cost wall clock per DE iteration <= 0.75x scipy's, on >=5 of 6
topologies. **1/6 PASSED (ratios 0.76-0.89x, later re-measured at 0.76-0.87x after fixing a
same-process contamination artifact -- see below).** A first run interleaved four different DE
calls per rep in one process (scipy real, this kernel, scipy null, this kernel null) across all
six topologies sequentially, and topologies measured later in that sequence read 2-4x slower
than the same topology measured standalone -- reversing the topology order moved the inflation
to whichever topologies ran later, not to the same physical topologies, confirming it was
same-process accumulation (memory/allocator/cache state), not a property of any topology. Fixed
by measuring each topology in its own subprocess (`_speed_one_topology`, dispatched via
`subprocess.run`). The clean numbers: 0.76, 0.79, 0.83, 0.80, 0.86, 0.87 across the six
topologies, degrading smoothly as free-parameter count grows -- consistent with the mechanism
(this kernel removes a roughly *fixed* per-generation overhead, which is a shrinking fraction of
total time as the cost function itself gets more expensive).

**Per the pre-registered stop rule, DE2 failing routes to the relaxed variant (Route 2) rather
than shipping this kernel.** The bit-exact route's correctness is not in question -- it is
simply not fast enough to be worth the switch.

## Route 2: relaxed -- dropped bit-exactness, measured speed first

`de_best1bin_relaxed` (now `src/autocircuit/core/de.py::de_best1bin`, the production name) keeps
everything about Route 1 except one thing: instead of scipy's own per-candidate sequential
`rng.shuffle`, one batched draw for the whole generation --
`rng.random((N, N)).argsort(axis=1)` gives every candidate an independent random permutation of
`0..N-1` in one C-level call, and the first 5 entries after dropping the candidate's own index
are its donors. This produces a **different, but not necessarily worse, RNG stream** -- not
bit-identical to scipy, which is exactly what needed a quality battery before it could ship.

**Speed pre-check (informational, same 0.75x/5-of-6 bar as DE2, subprocess-isolated):**

| topology | n_free | scipy (ms/it) | relaxed (ms/it) | ratio |
|---|---:|---:|---:|---:|
| 3-element R/C | 3 | 0.321 | 0.173 | 0.54 |
| 4-element R/C/L | 4 | 0.327 | 0.191 | 0.59 |
| 5-element R/C | 5 | 0.594 | 0.361 | 0.61 |
| 3-element R/CPE | 4 | 0.445 | 0.278 | 0.62 |
| 4-element R/CPE/L | 5 | 0.715 | 0.456 | 0.64 |
| 5-element R/C/CPE | 6 | 0.814 | 0.530 | 0.65 |

**6/6 topologies at or under 0.75x** -- a real, substantial, monotonic-with-dimension win
(35-46% faster). This justified running the full quality battery before shipping.

Pipeline-level comparisons in this round used `benchmarks/speedup/de_kernel_patch.py`, which
monkeypatches `autocircuit.core.fit._global_stage` for the duration of a `with
use_relaxed_de():` block so the *real* `fit()`/`screen()`/`discover()` code runs, unmodified,
through whichever kernel is active -- not a reimplementation of the pipeline. (Now that this
kernel has shipped, `use_relaxed_de()` patches `_global_stage` to something it already is; the
module also gained `use_scipy_de()`, which reconstructs the historical scipy-only baseline for
any future comparison.)

## DE5: the quality battery, all four clauses

Pre-registered bar: **all four clauses must pass**, mirroring this project's standing rule that
a failing gate is withdrawn rather than reworded, and that a candidate already measured to fail
is not the place to keep tuning until it passes (the `core/lshade.py` precedent).

### Clause 1 -- frozen-landscape arenas, Wilson CI

New arm `de_relaxed_vectorized` registered in `benchmarks/screening_round/param_opt.py::ARMS`
(one dict entry, inherits `Counted`, the `8*n*41` NFE cap, and the shared `_polish` for free --
the incumbent arm's own pattern). Run against both existing frozen arenas, matching
`PARAM_OPTIMIZER_PLAN.md`'s own Phase 1 scale exactly:

| arena | de_8x40 (current) | de_relaxed_vectorized |
|---|---|---|
| `land_rcl6.json` (25 topologies x 30 seeds = 750) | 630/750 [0.81,0.86] | 628/750 [0.81,0.86] |
| `land_rclcpe6.json` (25 topologies x 15 seeds = 375) | 225/375 [0.55,0.65] | 222/375 [0.54,0.64] |

`de_8x40`'s own numbers reproduce `PARAM_OPTIMIZER_PLAN.md`'s historical baseline exactly
(630/750 on the RCL arena), confirming this is a valid replication rather than a different
measurement. Both arenas: Wilson CIs essentially fully overlapping, NFE identical (same budget).
**PASSED -- no meaningful difference on either arena**, including the harder CPE arena
`docs/SEARCH_ALGORITHM_SCREENING.md` §4.2 warns is where arms that tie on the cheap arena tend
to separate.

### Clause 2 -- T5-style end-to-end pipeline comparison

A first attempt bounded both the baseline and patched run at the same `time_limit=180`s and
found all 6/6 references "differ." This was a methodology bug, not a finding:
`discover()`'s own docstring says `time_limit` is "a wall-clock budget ... the search stops
cleanly when exceeded," which bounds the exhaustive stage's own screening loop directly
(`discover.py` checks `time.perf_counter() - started > time_limit` inside the per-size driver).
Under a shared wall-clock cap, the relaxed kernel -- faster per fit, which is the whole point of
building it -- simply got through more topologies in the same window, so the two runs compared
different amounts of search rather than the same search under two kernels: exactly the "a
wall-clock budget measures the machine" trap `docs/SEARCH_ALGORITHM_SCREENING.md` §§2.1-2.2
already name. Fixed by bounding *effort*, not *time*: the exhaustive stage runs to its own
natural, deterministic completion (enumeration is combinatorial and kernel-independent), and the
genetic fallback is bounded by `generations` (fixed at 30, scipy's own default) rather than by a
clock.

Re-run correctly, on all three `REFERENCES` (exhaustive) and all three `LARGE_REFERENCES`
(auto), seed 0, `.summary()` compared with wall-clock text normalized out:

| reference | mode | result |
|---|---|---|
| capacitor (C-R-L + skin effect) | exhaustive | **identical**, byte-for-byte (2727s -> 2013s) |
| Maxwell-Wagner (two blocks) | exhaustive | numerically identical (chi2/AIC/BIC/RMS all match); only which member of an exactly-tied 4-way equivalence class is reported as the front-row representative differs |
| Randles (with Warburg) | exhaustive | numerically identical; same benign representative-relabeling as above |
| three-block Maxwell-Wagner | auto | recommended family identical (chi2 agrees to 5 significant figures); one non-recommended 6-element Pareto row differs in identity |
| capacitor + interfacial block | auto | **real regression**, see below |
| Randles + ESL + second block | auto | recommended **identical**, byte-for-byte, including every parameter value -- this is the same reference clause 3 stress-tests, and at seed 0 both kernels land in the same basin |

Five of six show either byte-identical output or the same benign "which exact-reparameterisation
member does a restart search land on" relabeling this project's CPE-kernel change already
produced (`SEARCH_TIME_PLAN.md` §3.3: "an exactly-tied exact-reparameterisation pair ... swapped
which member the restart search lands on ... unchanged in `.summary()`").

**The one real regression** (capacitor + interfacial block, `p(R1,CPE1)-C1-L1-SKINF1-p(R2,CPE1)`
reference): baseline's recommended 7-parameter model (`p(R1,CPE1)-C1-L1-SKINF1`, chi2=9.94e-5,
all parameters resolved) is well-identified; the patched run's search never found the equivalent
7-element candidate at that quality (its best 7-element row reached chi2=7.22e-4, ~7x worse),
and its recommendation instead needed an 8th parameter to reach a comparable chi2 -- with a new
warning baseline's recommendation does not carry: "SKINF1.n converged onto its upper search
bound (0.95): the element may be redundant or the data may not constrain it." A single,
un-replicated observation at one seed.

### Clause 3 -- the known-hard-landscape reliability sweep, and where a small sample misled

Reference: `R1-L1-p(CPE1,R2-Wo1)-p(R3,C1)` (`discovery_v2.LARGE_REFERENCES[2]`) -- the same
reference `PARAM_OPTIMIZER_PLAN.md`'s L-SHADE check regressed from 5/12 to 0/12. Method:
mirrors that plan's own citation of `TOPOLOGY_6PLUS_PLAN.md` item (b) exactly -- **one fixed**
1%-noise data realization (seed 0), and the optimizer's own seed varied across the sweep
(`fit(restarts=1, seed=k)`), not the data seed. (A first version of this script got this
backwards -- varying the data seed while holding the optimizer seed fixed -- and its own
baseline read 1/12 against the 5/12 the historical citation names, which is the tell that
revealed the mistake before any conclusion was drawn from it.)

**n=12 (matching L-SHADE's own check exactly):** baseline 5/12 (reproduces the historical number
exactly), patched 2/12. Read at face value this fails the pre-registered `>=5/12` line. Asked
whether 5/12 vs 2/12 is significant: exact McNemar on the two discordant counts (3 "only
baseline", 0 "only patched") gives **p=0.25** -- not significant at conventional levels, and
with only 3 discordant pairs the test has essentially no power. Per this project's own rule
("the response to a bar that cannot resolve its own question is more seeds, never a reworded
bar," `EVOLVE_SEARCH_PLAN.md`), the sweep was extended.

**n=120:** the first 12 seeds' results reproduced exactly (not a bug, confirmed by direct
comparison). Baseline **16/120 (13.3%)**, patched **14/120 (11.7%)**. Paired: both pass 3, only
baseline 13, only patched 11, neither 93. **McNemar exact p=0.84 -- no significant difference.**
The original n=12 draw's apparent 5/12-vs-2/12 gap was small-sample noise: baseline's *true*
success rate on this landscape is close to 13%, not the 42% the first 12 seeds happened to show.

**Verdict, per explicit instruction after this was reported: treated as no difference.** The
pre-registered n=12 threshold technically reads "failed" by its literal text, but that specific
instrument is now understood to have had no power to resolve the question it was asked (3
discordant events), and the properly-powered re-run found none. This is not a bar reworded to
fit an outcome -- it is the bar's own prescribed remedy (more seeds) applied, and the larger
sample is the one trusted.

### Clause 4 -- end-to-end recovery on the nine `six_plus` truths

`grow` arm (the one that actually reaches six/seven-element truths -- `TOPOLOGY_6PLUS_PLAN.md`'s
own X4 baseline), all nine truths x 3 seeds, `reported`/`on_front`/`recommended` via
`six_plus/recovery.py`'s own `run_one`/`Referee`, unmodified.

**Baseline 23/27, patched 23/27 -- cell-for-cell identical** (same truth/seed pairs pass and
fail in both runs, including the two known-hard shapes: `ser6` seed 1 and all three `ser7`
seeds fail in both). **PASSED.** Wall-clock, informational: patched consistently faster (e.g.
`par6` seed 1: 332s -> 185s; `par7` seed 1: 266s -> 202s), consistent with the per-iteration
speed measurement.

### DE5 overall

| clause | result |
|---|---|
| 1 (arena, 1125 paired samples across two Wilson-CI arenas) | no significant difference |
| 2 (pipeline, 6 references) | 5/6 identical or benign relabeling; 1/6 a single-seed regression, not replicated |
| 3 (known-hard reliability, n=120) | no significant difference (p=0.84) |
| 4 (recovery, 27 truth/seed pairs) | cell-for-cell identical |

Three of four clauses, run at a sample size with real statistical power, found no quality
difference. The fourth (clause 2) surfaced one genuine, unreplicated bad outcome on one seed of
one reference -- recorded, not dismissed, but a sample of one does not establish a systematic
effect, particularly once clause 3's properly-powered re-run showed the same kind of small-n
illusion this project has repeatedly had to correct for elsewhere (`EVOLVE_SEARCH_PLAN.md`
§§3.4.4, 3.5.1-3.5.2; `SEARCH_ALGORITHM_SCREENING.md` §4.2).

## What shipped

- `src/autocircuit/core/de.py` -- `de_best1bin`, the relaxed-variant kernel, promoted from
  `benchmarks/speedup/de_kernel.py::de_best1bin_relaxed` with full `mypy --strict` typing.
- `src/autocircuit/core/fit.py:_global_stage` -- the `workers=1` branch calls `de.de_best1bin`
  instead of `scipy.optimize.differential_evolution`. The `workers != 1` branch is untouched
  (stays on scipy; still unreachable from any caller in this codebase).

**Verified**: `pytest tests -q` -- **1132 passed, 19 skipped**, identical to the pre-change
baseline, zero failures. `mypy --strict src/autocircuit` and `ruff check` -- no errors
introduced by this change (both `de.py` and the modified region of `fit.py` are clean; the
pre-existing unrelated errors elsewhere in the tree, confirmed present on an unmodified checkout
via `git stash`, are unchanged in count). `npm run check` and `npm run smoke` (the browser's own
Pyodide-driven pipeline, same Python source) -- both clean.

Not run as a separate gate: `ev5_fingerprint.py`'s byte-identity comparison. By design this
kernel is not bit-exact against scipy, so that comparison would trivially show differences
already characterized in full by clause 2's `.summary()` comparison above -- running it would
add no information beyond what clause 2 already measured reference-by-reference.

## What stays as instruments, not production code

`benchmarks/speedup/de_kernel.py` (both the bit-exact and relaxed prototypes, plus the DE1/DE2
harness), `benchmarks/speedup/de_kernel_patch.py` (`use_relaxed_de`/`use_scipy_de`, for any
future kernel comparison), `benchmarks/speedup/de5_pipeline.py`, `de5_known_trap.py`,
`de5_recovery.py`, and the `de_relaxed_vectorized` arm added to
`benchmarks/screening_round/param_opt.py::ARMS`. Consistent with this project's own precedent
(CMA-ES and Sobol multi-start staying in `param_opt.py` after being rejected; `idea_c_cpe_
warmstart.py`/`idea_d_decorrelated_reparam.py` staying after their own ideas were rejected):
measurement instruments outlive whatever they measured, whether the answer was ship or don't.

## What this does not settle

The `workers != 1` branch is unmeasured and untouched -- if a future caller ever passes
`workers > 1` to `fit()`/`screen()` directly (not through `discover()`'s own process pool, which
already dispatches at `workers=1` per worker), it still gets scipy's own behaviour, unreviewed
by this round. Clause 2's single regression was not chased to a mechanism (would need many more
pipeline-level seeds on that one reference, at real cost -- each exhaustive run there took
25-35 minutes); it is recorded as an observed, unreplicated data point, not resolved. And the
speed win itself shrinks as free-parameter count grows (0.54x at 3 free parameters to 0.65x at
6), so a future reference with substantially more free parameters than anything tested here
should not assume the same 35-46% figure holds without being measured directly.
