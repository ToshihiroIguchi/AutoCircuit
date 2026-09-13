# Small-sample review — three verdicts revisited, one left alone on purpose

A pass over this repository's own decision record, looking for a specific failure shape: a
change rejected, or a default left unmoved, on a negative reading drawn from very few seeds or
very few real datasets, while every other reading for the same change was healthy. This project
has already measured this failure shape happening in both directions — a small sample that
looked *good* and did not replicate (`docs/EVOLVE_SEARCH_PLAN.md` §§3.4.4, 3.5: 120-seed
"significant" results demoted at 480 seeds), and a small sample that looked *decisive* and
turned out to have no statistical power at all (`docs/DE_KERNEL_PLAN.md` clause 3: 5/12 vs 2/12,
exact McNemar p=0.25 on three discordant pairs, resolved by a 120-seed re-run finding no
difference). Three candidates for the same treatment were found; two are re-measured here, one
is deliberately not.

## What was not re-run, and why (near-misses already caught in their own round)

Recorded so a later reader does not re-derive these:

- **`docs/DE_KERNEL_PLAN.md` clause 3** — caught and resolved inside its own round (12 seeds →
  120 seeds), not a standing rejection. Nothing to re-run.
- **`docs/PARAM_OPTIMIZER_PLAN.md`'s L-SHADE withdrawal** — 5/12 → 0/12 on a known-hard reference
  *plus* three independent test failures on small, noise-free circuits in
  `tests/test_discover_skeleton.py`. Convergent evidence across two different kinds of check,
  not a single lucky-looking draw — not a small-sample-illusion candidate.

## A-1. `params7` vs `grow` on `ser6`/`ser7` (`docs/PARAM_BUDGET_PLAN.md` item 5)

**What was decided on what.** Item 5 asked whether a parameter budget (`--max-params 7`)
supersedes the growth stage (`docs/TOPOLOGY_6PLUS_PLAN.md`). Its pre-registered rule: beat
`grow` on `reported` for the 6/7-element truths **on every shape**. Four shapes tied 3/3 = 3/3.
The rule fired on `ser6`'s `reported`: `grow` 2/3 against `params7` **0/3**, at **n=3 seeds**.
The document itself named the likely cause — the tier-1 screening lottery
(`docs/TOPOLOGY_6PLUS_PLAN.md` §2(a)), already caught flipping this exact truth's `reported`
flag between otherwise-identical runs (`docs/SEARCH_TIME_PLAN.md` §4.3) — and did not chase it
further, "because the rule does not need the mechanism resolved."

**The ship verdict does not depend on the outcome here.** Full parameter-axis enumeration to
seven elements measured 2.3–2.8× more expensive than growth for a tied-at-best recovery rate,
and that cost leg alone already decides item 5. What this re-measurement settles is narrower:
whether the recorded reason is true, at a sample size that can resolve it.

**Method.** `benchmarks/six_plus/recovery.py --arms grow,params7 --truths ser6,ser7 --seeds
4,...,33 --workers 8 --pair grow,params7`, appending to the existing seeds 1–3 in
`x4_recovery.json`/`x4_params7.json` (new rows written to `a1_ser_seeds.json`). Exact McNemar via
the new `benchmarks/paired_stats.py::mcnemar_exact` (the same two-sided exact binomial as
`benchmarks/screening_round/arms.py::_sign_test`, factored out so this round did not re-derive
it or edit the module that backs published 480-seed numbers).

**Pre-registered rule**, exact McNemar on paired-by-seed `reported`, two-sided α = 0.05:

| outcome | what is written down |
|---|---|
| significant, `params7` worse on `ser6` | item 5's recorded reason is confirmed; the "most likely" hedge is replaced with a measured rate |
| not significant | the recorded reason is withdrawn; item 5's verdict stands on the cost leg alone |
| fewer than 10 discordant pairs at n=33 | the test cannot resolve its own question yet; extend to n=63 rather than reading the p-value |

`ser7` gets the same test as a secondary reading; its `recommended` was 0/3 on both arms at
n=3, so nothing the report says changes whichever way `reported` moves.

**Result — [measured, n=33, 2026-09-14]: the recorded reason was wrong. This is not
screening-lottery noise; it is a real, large, and opposite-signed effect on the two truths.**
Combining the original seeds 1-3 (`x4_recovery.json`/`x4_params7.json`) with the new seeds 4-33
(`a1_ser_seeds.json`), paired exact McNemar on `reported`:

| truth | `grow` hits | `params7` hits | discordant pairs | p |
|---|---:|---:|---:|---:|
| `ser6` | **17/33 (51.5%)** | **0/33 (0%)** | 17 | **< 0.0001** |
| `ser7` | **0/33 (0%)** | **12/33 (36.4%)** | 12 | **0.0005** |

Both truths are now decisively significant, in *opposite directions*: `grow` reaches `ser6`'s
truth-equivalence class routinely and `params7` never does across 33 seeds; on `ser7` the roles
flip completely — `params7` reaches it over a third of the time and `grow` never does. This is
the opposite of what the original small-sample reading suggested: the effect did not wash out
with more seeds, it sharpened into two clean, opposite, highly significant results. **The
`docs/PARAM_BUDGET_PLAN.md` item 5 text attributing the `ser6`/`ser7` swing to "the tier-1
screening lottery" is therefore wrong and is corrected there** — this looks instead like a real
structural difference in how growth (adding one element to the best exhaustive candidates) and a
parameter-axis re-enumeration (widening the search axis itself) each interact with a series-only
truth as its element count crosses from 6 to 7. The mechanism was not investigated further, per
this round's own scope (re-measure the sample size, not chase the cause), but the *existence* of
a real, shape/size-dependent effect is now established rather than hypothesised.

**This does not change item 5's ship verdict.** Full parameter-axis enumeration to seven elements
still costs 2.3-2.8x more than growth (§ item 5's own F6/G1 timing), and `recommended` was 0/33
under `params7` on *both* truths (only `reported`/`on_front` moved) — so nothing the actual
report says changes. What changes is the *reason recorded* for the `ser6`/`ser7` split, from an
unreplicated guess to a measured, opposite-signed effect worth its own investigation later if
this project ever revisits `max_params` vs `growth_width` as the mechanism for reaching past
`complete_up_to`.

## A-2. Real-data split-half stability, `docs/PARAM_BUDGET_PLAN.md` E.2

**What was decided on what.** E.2 tripped its own stop rule (e) when split-half stability (R3)
fell 2/7 → 0/7 under `--max-params 6`, blocking phase 8 (moving the default). Seven datasets, a
swing of two, no repetition.

**A sharper possibility than sample size.** `benchmarks/measured/measured.py`'s `run_split_half`
hard-coded `discover(seed=0)` on both halves with no seed axis, so with `--time-limit` unset it
is deterministic — but E.2 was run at `--time-limit 60`, and a wall-clock limit makes the evolve
path's stopping points machine-dependent. **The 2/7 → 0/7 swing may not be reproducible at all**,
independent of sample size, and that is cheap to check first.

**Method**, added to `measured.py` (`--seeds`, `--out`, and a new `compare-split-half` gate,
all confirmed working against a one-dataset smoke test before the real run):

1. Reproducibility: run the element-axis baseline twice, identical arguments (`--time-limit 60`,
   seed 0), and diff.
2. The 7×k grid: both axes (element, `--max-params 6`), `--seeds 0,1,2,3,4`, `--time-limit 60`
   throughout (never unbounded — one dataset's `mode="auto"` fallback ran ~2h of CPU with no
   output the last time this was tried unbounded, `docs/PARAM_BUDGET_PLAN.md` phase 2).
3. Paired exact McNemar on `stable` by (dataset, seed) via `compare-split-half`.

**Pre-registered rule**, exact McNemar on paired (dataset, seed) `stable`, two-sided α = 0.05:

| outcome | what is written down |
|---|---|
| step 1 disagrees between two identical runs | reported first; both the 2/7 and the 0/7 already on record are re-labelled as carrying run-to-run variance |
| significant fall under P≤6 | stop rule (e) confirmed at a real sample; item 8 stays blocked, with a measured rate replacing a 2-of-7 swing |
| not significant | the trip is withdrawn as under-powered; item 8's *blocker* from E.2 is removed — but the default still does not move on this alone, since R3's absolute level (0–29% either axis) fails the 80% bar regardless |

**Result, step 1 (determinism check) — [measured, 2026-09-13]: the command is NOT
reproducible, and the one dataset E.2's whole R3 result rests on is exactly where it broke.**
Two literally identical invocations (`measured.py split-half --time-limit 60 --seeds 0`, no
code path difference, same machine) disagree on `impedancepy-zplot`: run 1 reports `stable =
False` (`[L-p(CPE,[R-p(C,R)])]` vs `p(R,[CPE-L-p(C,R)])`), run 2 reports `stable = True`
(`[L-p(C,R,[CPE-R])]` on both halves). The other six datasets agree between the two runs.
**`impedancepy-zplot` is the one dataset `docs/IMPACT_PLAN.md` §4's R3 (1/7, 14%) was ever
stable on** — so the previously-reported 1/7 is not a reproducible measurement of this pipeline,
it is one wall-clock-dependent draw that happened to land on "stable." Mechanism: `--time-limit`
bounds the evolve fallback's stopping point in real seconds
(`discover.py:3030`,`:3073`,`:3123`), so two runs with an identical RNG seed can still explore a
different amount of the search space depending on machine timing at the moment each call ran.
Files: `benchmarks/measured/a2_determinism_run1.json`, `a2_determinism_run2.json`,
`a2_determinism_compare.log`. This is reported first, per the pre-registered rule, and the 2/7
and 0/7 numbers already on record in `docs/PARAM_BUDGET_PLAN.md` E.2 are re-labelled below as
carrying this run-to-run variance rather than being read as a clean measurement of the parameter
budget's effect.

**Result, step 2 (the 7×5 seed grid) — [measured, 2026-09-14]: not significant, and the
direction reverses.** `measured.py split-half --time-limit 60 --seeds 0,1,2,3,4` on both axes
(35 (dataset, seed) pairs each):

| axis | stable | rate |
|---|---:|---:|
| element (baseline) | 8/35 | 22.9% |
| `--max-params 6` | 14/35 | **40.0%** |

Paired McNemar: both stable = 3, only-elements = 5, only-params6 = 11, neither = 16 — **16
discordant pairs, exact p = 0.2101.** Sixteen discordant pairs is enough for this test to have
real power (contrast the 0-3 discordant pairs in the two single-draw numbers this is replacing),
and the result is unambiguous: no significant difference, and what signal there is points the
opposite way from the original 2/7 → 0/7 reading — `--max-params 6` is numerically *more* stable
here, not less. Per-dataset detail shows why a single seed was never going to settle this:
`zenodo-21700-id15` is 5/5 stable under the element axis but only 3/5 under the parameter axis;
`zenodo-21700-id34` is the mirror image, 0/5 vs 4/5 — the same seed-to-seed basin-lottery
variance this project has already measured for tier-1 screening, now visible directly in this
real-data gate. Files: `benchmarks/measured/a2_grid_elements.json`,
`a2_grid_params6.json`, `a2_grid_compare.log`.

**Conclusion for `docs/PARAM_BUDGET_PLAN.md` E.2 / item 8**: the stop-rule trip recorded there
(2/7 → 0/7) is **withdrawn as under-powered — confirmed, not merely suspected**. It was one
wall-clock-dependent draw per axis, on a command already shown non-reproducible in step 1, read
as a clean measurement. At a sample size with real power, there is no significant effect in
either direction. This does **not** unblock promoting `max_params` to a default — R3's absolute
level (23–40%, either axis) still fails the 80% bar by a wide margin, for reasons this round did
not investigate further — but the *specific* objection E.2 raised against `max_params` is
retracted. `docs/PARAM_BUDGET_PLAN.md` is updated accordingly.

## A-3. `weighting="auto"` N2 — deliberately not run

Recorded in `docs/IMPACT_PLAN.md` §2.4 directly (the load-bearing document for this lever): the
37-cell grid would only resolve whether N2's 1-seed, 2-of-3-reference regression is mechanistic
or a coincidence of noise draws. It would not remove the actual block, which is independent —
§4.3's gate R2 already measured `weighting="auto"`'s `chi2_reduced` at 1.6–3.1e4 on seven real
spectra (six of seven 1000×–30000× outside the band N2's rule assumes) while `relative_error`
stays normal, meaning the σ estimate itself fails on real data regardless of what a synthetic
37-cell re-run would show. Running it would answer a question that no longer gates the decision.
**No run scheduled.** Reopens if a σ estimator is built that survives a real 43–72-point sweep.

## Order of work

A-2's reproducibility check (step 1) ran first, cheapest and potentially the most consequential
single result here. A-1 and A-2's grid then run as independent background jobs; this document is
updated with their numbers once both land, and `docs/PARAM_BUDGET_PLAN.md` item 5 / E.2 are
updated to point here rather than duplicate the numbers.
