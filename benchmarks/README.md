# Benchmarks

Measurements, not tests. The test suite asserts that things *work*; these scripts say *how
well*, and they are the evidence behind every claim marked **[measured]** in
`docs/IMPLEMENTATION_PLAN.md` and `docs/DISCOVERY_V2_PLAN.md`.

Run with the package on the path (it is not pip-installed on the dev machine):

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
python benchmarks/topology_space.py
python benchmarks/fitting.py accuracy
python benchmarks/fitting.py calibration
python benchmarks/fitting.py restarts
python benchmarks/discovery_v2.py filter
python benchmarks/discovery_v2.py screen
python benchmarks/discovery_v2.py gate --workers 8      # slow: hours
```

Re-run the relevant script after touching the optimizer, the element library or the
discovery filters, and update the numbers below if they move.

## Results as of 2026-08-08

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
budget on — but it is enough to say the budget is not the thing to spend more on.

Full-space screening cost on this machine, single core, after the feasibility filter:
57 ms/topology at n = 3, 86 ms at n = 4, 219 ms at n = 5, i.e. ~22 min for the whole
capacitor sweep on one core and a few minutes with `--workers 8`.

### `fitting.py accuracy`

All five circuits recover their true parameters from clean data with no initial guess
(worst error < 0.01%), and stay within a few percent at 1% noise. Times: 0.3–4.5 s.

### `fitting.py calibration`

Reported standard errors are honest: over 25 noise realisations the z-scores have mean ≈ 0,
standard deviation 0.8–1.1, and 92–96% coverage inside ±2σ.

### `fitting.py restarts`

On the hardest six-parameter case, at 1% noise:

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
