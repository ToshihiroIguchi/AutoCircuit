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
