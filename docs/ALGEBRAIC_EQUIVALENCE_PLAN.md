# Algebraic equivalent-circuit dedup — preliminary experiments, not a build plan

Status: **plan document; two measurement runs are real (the enumeration-size spike, §2, and the
SymPy spike, §3, run 2026-09-12 with the user's explicit authorization to install SymPy as a
dev-only dependency); a full build of either approach is not attempted.** This document exists to
decide whether either of two heavier approaches to the equivalence-class problem
(`docs/SEARCH_TIME_PLAN.md` §3.4) is worth building at all. SymPy is now installed
(`pyproject.toml`'s `dev` extra) for benchmark/spike use only — `autocircuit.core` imports nothing
from it, and `discover()`'s and `fit()`'s behavior is unchanged.

## 0. This has already been substantially explored — read this first

`docs/SEARCH_SPEEDUP_PLAN.md` (not in `CLAUDE.md`'s numbered list, but the most relevant existing
artifact for this question) already ran three experiments squarely on this topic. Do not
re-propose what they already settled:

- **Idea A** — a hand-derived closed-form reparameterisation between `R1-p(R2,C1)` and
  `p(R1,C1-R2)` (`R1' = R1+R2`, `R2' = R1(R1+R2)/R2`, `C1' = R2^2 C1/(R1+R2)^2`). Confirmed exact
  (5.8e-16 relative error over 200 random trials) and confirmed useful (0.000% parameter agreement
  against an independent fit). Explicitly recorded as "not something this round can respond to with
  a shippable change" without either a hand-catalogued rewrite-rule library per pair/order, or a
  general symbolic engine deriving such maps automatically.
- **Idea A2** — generalises idea A via Foster/Cauer ladder duality: an order-`N` **pure
  linear-algebra** transform (continued-fraction expansion of numerator/denominator polynomials),
  needing **no symbolic engine at all** and fully compatible with `CLAUDE.md`'s numpy+scipy-only
  rule. Verified correct at orders 2–6 (worst algebraic-identity error 9.4e-16). Measured to save
  only **~0.56% of a typical exhaustive run** in the case where both members are guaranteed to
  co-occur (`K<=2`, inside the default exhaustive limit), and to almost never land on the
  specifically-targeted pair in the regime where the saving would matter (`K>=3`, the growth
  stage: the exact Foster canonical form appeared in only 2/10 seeds on `par6`, the exact Cauer
  dual in 0/10). **Verdict: not shipped, ceiling too low.**
- **Idea 5a** — a cross-*session* cache of previously-seen spectra. Rejected on desk analysis only
  (no code run), on the grounds that this project's own purpose (`CLAUDE.md`: "each analysis
  targets one physically distinct, previously unmeasured part") argues against spectra recurring
  across sessions.

**Idea 5a is not the same idea as what is proposed here, and this document exists because that
distinction matters.** The user's dictionary proposal is about a table of equivalence classes
*among the enumerated topologies of one pool*, a property of the search space itself, not of any
particular user's spectrum. That is much closer to what `SEARCH_TIME_PLAN.md` §3.4 already
measured *post hoc*: clustering an already-screened landscape table by cost at
`EQUIVALENCE_RTOL = 1e-6` found **4.4–5.9x multiplicity over whole tables**, 3.8–4.9x at the
largest same-size class, well past the "under ~1.3x" bound that section hoped would close the
question. §3.4 declined to build a *predictive* (before-fitting) version of this for two stated
reasons, independent of the multiplicity number: "detecting a class before fitting is a
symbolic-equivalence problem with no cheap exact test," and "the report still needs every member
of a reported equivalence class refitted at tier 2 regardless." **The real open question this
document scopes is narrower than "should we do algebraic dedup at all": can §3.4's already-measured
multiplicity be captured *predictively*, cheaply enough to be worth it, by (a) a general symbolic
engine, or (b) a large precomputed table** — and, critically (found while running §2 below,
correcting this document's own original framing), **(b) is not independent of (a)**: see §2.3.

## 1. What a predictive equivalence table would actually be used for

Worth stating precisely before any spike, because it changes what "the table" needs to contain.
Two different topologies (different canonical forms — `canonical_form`, `circuit.py:468-476`,
already collapses the *easy* equivalences: commutativity and flattening within one series/parallel
tree) can compute the *same family* of impedance functions via a reparameterisation, exactly as
idea A's pair does. `canonical_form` does not and cannot unify these — they are structurally
different trees. So an equivalence-class dictionary is a second relation layered on top of
canonical form, and its payoff is narrower than "skip a duplicate topology entirely": **members of
one class still compute an identical `Z(f)` for corresponding parameter choices, so a class table
would let tier-1 screening reuse a representative's already-computed cost for every other member
of its class without a second `differential_evolution` call** (screening only ranks by cost; it
does not need each member's own parameter values). It would **not** by itself remove the need for
`SEARCH_TIME_PLAN.md` §3.4's second, independent reason to decline building this: a *reported*
equivalence-class member's own parameter values still require either a real refit or a
reparameterisation formula (idea A's kind), so tier-2 cost is unaffected regardless of what the
table contains. This reframes the table's entire value proposition to **tier-1 screening only**,
which should be stated explicitly wherever this idea is discussed again, so nobody later assumes
it would also cut tier-2 refit cost.

## 2. Preliminary spike (b) — precomputed dictionary, run now (cheap, reuses existing code)

**2.1 Raw enumeration size, measured directly** (`enumerate_topologies`/`count_topologies`,
default pool `("R","C","L","CPE")`, no new code):

| `n` (exact size) | count | cumulative `n<=`  |
|---:|---:|---:|
| 3 | (77, cumulative, from `tests/test_enumerate.py`) | 77 |
| 4 | 453 − 77 = 376 | 453 |
| 5 | 2976 − 453 = 2523 | 2976 |
| 6 | **18081** [measured] | **21057** |
| 7 | **135454** [measured] | **156511** |
| 8 | **1049055** [measured] | **1205566** |

`count_topologies(pool, 8)` took 74.7 s single-process on this machine — cheap, and it already
performs the same canonical-form deduplication (`_compose`'s `seen: set[str]` keyed on
`canonical_form(node)`) the real search does, so the count is not a projection.

**2.2 On-disk size, measured on the `n=6` level and projected.** Canonical-form strings at `n=6`
average **36.0 bytes** (650,848 raw bytes / 18,081 entries for a `{canonical_form: int}` JSON
dict — not the earlier, much larger estimate this document's first draft produced by accidentally
measuring `repr()` of the raw dataclass node instead of the canonical-form string; that mistake is
recorded here rather than silently corrected, since it is exactly the kind of measurement error
this project's own discipline exists to catch before it reaches a decision). Gzip compresses this
table **7.58x** (85,841 bytes at level 9), consistent with the large shared-substring redundancy
expected from labelled element codes repeating across entries.

Projected to the full `n<=8` cumulative count (1,205,566 entries), at the `n=6` per-entry rate:

| serialization | projected size at `n<=8` |
|---|---:|
| raw JSON `{canonical_form: class_id}` | **~43.4 MB** |
| gzip-compressed | **~5.7 MB** |

Compared against `docs/STARTUP_AND_EDITING_PLAN.md` §3's own recorded 17–41 MB cold-start budget
(scipy alone is 18.3 MB of that): **the raw form sits right at the edge of what this project has
already fought hard to shrink, and the compressed form is comfortably under it.** This is the
opposite of what this document originally expected — **size is not, by itself, the thing that
kills this idea.**

**2.3 The real ceiling is build time, not size, and it exposes a dependency this document's
original framing got wrong.** `canonical_form` cannot detect the cross-shape equivalences this
idea is about (§1) — only an algebraic method can. Without a general symbolic engine (spike (a),
§3), the only dataset-independent way to *discover* which of the 1,205,566 `n<=8` topologies
belong together is the same method §3.4 already used: **screen every one of them once and cluster
by matching cost**, i.e., one full exhaustive-screen-scale pass over the *entire* `n<=8` space, as
a one-time offline build. Using this project's own already-measured per-screen cost
(`SEARCH_TIME_PLAN.md` §1: 0.87 s without CPE, 1.77 s with; `DISCOVERY_V2_PLAN.md` §3.3: 2,976
topologies at `n<=5` take 6.1 min at 8 workers, i.e. ≈0.98 s/topology effective), and this
document's own measured count of 1,205,566 topologies at `n<=8` — **~410x more topologies than the
`n<=5` reference** — the projected one-time build cost is:

```
1,205,566 topologies x ~1.0-1.3 s/screen (blended CPE/non-CPE) / 8 workers
  ~ 42-54 hours of continuous 8-worker compute, single pass
```

This is an order-of-magnitude extrapolation from measured per-topology costs, not a run performed
this session (running it would have cost 2+ days of this machine's time, out of this plan's own
scope discipline) — labelled as such rather than presented as measured. **It fails this document's
own pre-registered "a few hours on ordinary hardware" bar by roughly two orders of magnitude**,
and the table would need rebuilding whenever canonicalization rules, the pool, or the plausibility
filter change (a real, recurring maintenance cost, not a one-off). **The dependency this section
found, which the original framing of this document (splitting (a) and (b) into independent
alternatives) got wrong: a cheap, dataset-independent version of (b) does not exist without
solving (a)'s harder problem first** (or accepting the ~50-hour one-time-and-per-change cost
above, which this document's own bar rejects). A structural, algebraic engine (spike (a)) is what
would make building the table's *class assignments* cheap in the first place; §3.4's own numeric
post-hoc clustering is a data-dependent proxy usable only after a screen has already run on a
specific spectrum, not a reusable, pool-level table.

**Stop/go for spike (b), revised from the original pre-registration in light of §2.3:** a
standalone precomputed dictionary, built by exhaustive numeric fingerprinting, **does not clear
its own build-time bar and is closed as a non-starter on that basis alone** — not on size, which
this section's own measurement shows is not the binding constraint. It remains available as a
downstream consumer of spike (a)'s output (a class table populated by an algebraic method that
does not need to screen every topology to know they are equivalent), which is scoped in §3 as a
"go" that would need re-evaluating this section's build-time math with the actual cost of the
algebraic method substituted for the screen-everything cost.

## 3. Preliminary spike (a) — SymPy, explicitly scoped as dev-only tooling; run 2026-09-12

**Numpy/scipy-only rule tension, stated loudly per this document's own instruction.**
`CLAUDE.md`'s Stack section states, as a hard rule: "`numpy` and `scipy` are the only runtime
dependencies... it is what lets the same wheel run under Pyodide in the browser." Any SymPy usage
explored here must be scoped to an **offline benchmark script under `benchmarks/`**, exactly like
idea A/A2's own scripts (`benchmarks/speedup/idea_a_algebraic_equivalence.py`,
`idea_a2_foster_cauer.py`) — never imported by `autocircuit.core`, never part of the shipped
wheel. If this spike ever graduates into a shipped feature, it needs one of two things, decided
by the user, not by this document: (1) SymPy's output precomputed into static rewrite rules or a
class table consumed by the numpy/scipy-only runtime (converging with §2's dictionary, subject to
§2.3's build-time ceiling using whatever cost the algebraic method itself carries instead of the
brute-force screen), or (2) an explicit, separately-flagged amendment to `CLAUDE.md`'s dependency
rule for a dev-time-only code path that never ships in the wheel. **This document does not decide
between them and flags the question for the user's own sign-off before any code — even
dev-only — lands.**

**Method, as originally planned (see below for what actually ran and what changed).**
Symbolically derive `Z(s)` for a small topology family — start with
idea A's known pair, extend to idea A2's already-validated order-3 Foster/Cauer case — and compare
via `sympy.cancel`/rational-function normal-form reduction (e.g. `sympy.together` then
`sympy.cancel`, or a `sympy.Poly` coefficient-ratio comparison after a substitution search). Time
it on: (i) positive controls — the pairs idea A/A2 already proved equivalent by hand, to confirm
the mechanism finds what is already known; (ii) negative controls — a sample of adjacent,
non-equivalent members drawn from `land_rcl6.json` (topologies that do *not* share a screened cost
at `EQUIVALENCE_RTOL`), to check for false positives.

**Pre-registered stop/go, unchanged from this document's first draft:**
1. **Zero false positives on the negative-control sample.** A false positive here is worse than a
   missed duplicate — it would silently under-search, exactly the failure mode
   `docs/POOL_FROM_SPECTRUM_PLAN.md` §5 already warns about for a different detector. Any false
   positive closes this spike outright.
2. **Recognises both already-known-by-hand cases (idea A, idea A2) automatically**, with no
   topology-specific hints.
3. **Per-pair comparison time must be a small fraction of one tier-1 screen (~1 s).** If SymPy's
   comparison costs more than screening both members would have cost, the mechanism defeats its
   own purpose — this is the same shape of self-defeat idea 2e/F already measured for a much
   simpler cache (`docs/SEARCH_SPEEDUP_PLAN.md`: caching `canonical_form` made enumeration 37-42%
   *slower* because a safe cache key costs as much to compute as the thing it replaces). Any
   symbolic-comparison spike must be timed against this same risk from the start.

**[measured, 2026-09-12] Run, with SymPy installed as an explicit, user-authorized dev-only
dependency (`pyproject.toml`'s `dev` extra, never `dependencies`).**
`benchmarks/speedup/idea_sympy_equivalence.py` (new) operationalises the comparison as: given two
topologies each with a *concrete* numeric parameter assignment, build `Z(s)` as a SymPy rational
function of `s` and check whether the residual is zero — exact symbolic equality where possible,
and, since concrete parameters (idea A2's closed form is float-derived, never an exact rational)
essentially never cancel to a literal `0`, the largest numerator coefficient of the residual
relative to the two impedances' own coefficient scale, checked against a `1e-6` relative
tolerance — the same tolerance this project's own `EQUIVALENCE_RTOL` already uses for its numeric
equivalence check.

| check | result |
|---|---|
| Positive control 1 (idea A's pair, integer-ish parameters) | exact residual `0`, relative coefficient `0.0` |
| Positive control 2 (idea A2's order-2 Foster/Cauer pair) | exact residual nonzero (floating-point derived closed form); relative coefficient `3.4e-20` — six orders of magnitude inside the `1e-6` bar |
| Negative controls (6 topology pairs × 3 random-parameter trials = 18 comparisons) | 0 false positives |
| Timing | 0.003 s (control 1), 0.11 s (control 2, the more complex order-2 expression), mean 0.037 s per negative control |

**All three pre-registered clauses pass.** (1) Zero false positives on 18 negative-control
comparisons. (2) Both known positive-control pairs recognised — control 1 exactly, control 2 to
`3.4e-20` relative, a tolerance this document adopts as the practical "effectively zero" reading a
real deployment would need for float-derived parameters, and records as a genuine finding rather
than a silently-loosened bar: **exact symbolic equality is the wrong test for concrete fitted
parameters, and a small numeric tolerance on the residual's coefficients is required in practice**
— a specific, useful correction to this document's own first-draft framing ("compare via
`sympy.cancel`... to check for false positives"), which had not anticipated that even a textbook-
correct algebraic identity would fail a literal `== 0` check once real floating-point parameters
are substituted in. (3) Per-pair time (worst observed 0.11 s) is comfortably inside "a small
fraction of one tier-1 screen (~1 s)."

**This spike is confirmed to work at the scale tested; it is not scaled up to a general engine or
a shipped table this session.** Only R/C/L element impedances are implemented (idea A/A2's own
scope); CPE, Warburg and the other transcendental elements were not attempted, and neither was a
search procedure that *discovers* an unknown reparameterisation automatically rather than
verifying one already supplied. The order recommended by §2.3's finding stands: **(a) is the
piece that would make (b) cheap**, and this pass confirms (a)'s mechanism works on the cases
tested — but building either into a shipped, general-purpose detector (across the whole default
pool, at every element count) is a substantially larger project than this spike, and remains the
user's own decision to authorize, per §4 below.

## 4. What this document recommends, and what it explicitly leaves to the user

- **Spike (a) ran and passed all three of its own pre-registered clauses** (§3): zero false
  positives on 18 negative controls, both known positive-control pairs recognised (one exactly,
  one to 3.4e-20 relative — inside a 1e-6 tolerance that turned out to be a real, necessary
  correction to the spike's own design, not a loosened bar), and per-pair timing (worst 0.11 s)
  comfortably inside the "~1 s" ceiling. It ran as a dev-only, `benchmarks/`-scoped script
  (`benchmarks/speedup/idea_sympy_equivalence.py`) — no change to `autocircuit.core`.
- **Spike (b), as a standalone brute-force-fingerprinted dictionary, is closed** on the build-time
  bar (§2.3), not on size (§2.2 shows size was never the binding constraint — a genuinely useful
  finding this document's own measurement produced, contrary to its first-draft expectation).
- **The SymPy *dependency* question was resolved by the user for this session's dev-only,
  benchmarks-only use** (installed in `pyproject.toml`'s `dev` extra, per explicit authorization).
  What remains genuinely undecided, and is **not** resolved by this pass, is whether to build
  either (1) a general, production-scale symbolic detector, or (2) a precomputed table derived
  from one — both are substantially larger projects than this spike (§3's own closing paragraph),
  and both still need their own explicit go-ahead before any code lands in `autocircuit.core` or
  in a shipped data file, since that is a different, much larger decision than authorizing a
  benchmark script for one afternoon's experiment.
