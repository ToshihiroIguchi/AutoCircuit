# X9 -- rational-approximation order estimation

## Noise-free dense reference (ppd=40, band 1e-04-1e+07 Hz)

| truth | expected (finite-degree truths only) | aaa | loewner (threshold) | loewner (gap) | stabilisation |
|---|---|---|---|---|---|
| 1relax | 1 | 1 | 2 | 1 | 1 |
| 2relax | 2 | 2 | 2 | 2 | 3 |
| 3relax | 3 | 3 | 3 | 3 | 5 |
| 4relax | 4 | 4 | 4 | 4 | 4 |
| rcl_relax | 2 finite poles / 3 states (see note) | 1 | 1 | 1 | 1 |
| cpe | none (fractional) | 27 | 40 | 1 | 0 |
| randles_warburg | none (fractional) | 22 | 23 | 2 | 1 |

## Headline: exact-recovery rate at 1% noise, 10 points/decade
(averaged over the four finite-degree RC-ladder truths)

| estimator | exact-recovery rate |
|---|---|
| aaa | 0.12 |
| loewner_threshold | 0.04 |
| loewner_gap | 0.20 |
| stabilisation | 0.16 |

## Full grid: recovery buckets by (truth, estimator, noise, ppd)

| truth | estimator | noise | ppd | reference | exact | +1 | -1 | further |
|---|---|---|---|---|---|---|---|---|
| 1relax | aaa | 0.0 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | loewner_threshold | 0.0 | 5 | 2 | 0.00 | 0.00 | 1.00 | 0.00 |
| 1relax | loewner_gap | 0.0 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | stabilisation | 0.0 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | aaa | 0.001 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.001 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.001 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.001 | 5 | 1 | 0.40 | 0.20 | 0.00 | 0.40 |
| 1relax | aaa | 0.003 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.003 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.003 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.003 | 5 | 1 | 0.60 | 0.20 | 0.00 | 0.20 |
| 1relax | aaa | 0.01 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.01 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.01 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.01 | 5 | 1 | 0.00 | 0.60 | 0.00 | 0.40 |
| 1relax | aaa | 0.03 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.03 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.03 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.03 | 5 | 1 | 0.40 | 0.00 | 0.20 | 0.40 |
| 1relax | aaa | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | loewner_threshold | 0.0 | 10 | 2 | 0.00 | 0.00 | 1.00 | 0.00 |
| 1relax | loewner_gap | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | stabilisation | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | aaa | 0.001 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.001 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.001 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.001 | 10 | 1 | 0.60 | 0.20 | 0.00 | 0.20 |
| 1relax | aaa | 0.003 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.003 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.003 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.003 | 10 | 1 | 0.00 | 0.60 | 0.00 | 0.40 |
| 1relax | aaa | 0.01 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.01 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.01 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.01 | 10 | 1 | 0.40 | 0.40 | 0.00 | 0.20 |
| 1relax | aaa | 0.03 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.03 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.03 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.03 | 10 | 1 | 0.00 | 0.20 | 0.40 | 0.40 |
| 1relax | aaa | 0.0 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | loewner_threshold | 0.0 | 20 | 2 | 0.00 | 0.00 | 1.00 | 0.00 |
| 1relax | loewner_gap | 0.0 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| 1relax | stabilisation | 0.0 | 20 | 1 | 0.00 | 1.00 | 0.00 | 0.00 |
| 1relax | aaa | 0.001 | 20 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| 1relax | loewner_threshold | 0.001 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.001 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.001 | 20 | 1 | 0.40 | 0.40 | 0.00 | 0.20 |
| 1relax | aaa | 0.003 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.003 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.003 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.003 | 20 | 1 | 0.40 | 0.40 | 0.00 | 0.20 |
| 1relax | aaa | 0.01 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.01 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.01 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.01 | 20 | 1 | 0.20 | 0.20 | 0.20 | 0.40 |
| 1relax | aaa | 0.03 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_threshold | 0.03 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | loewner_gap | 0.03 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| 1relax | stabilisation | 0.03 | 20 | 1 | 0.40 | 0.40 | 0.00 | 0.20 |
| 2relax | aaa | 0.0 | 5 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | loewner_threshold | 0.0 | 5 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | loewner_gap | 0.0 | 5 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | stabilisation | 0.0 | 5 | 3 | 0.00 | 0.00 | 1.00 | 0.00 |
| 2relax | aaa | 0.001 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.001 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.001 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.001 | 5 | 3 | 0.60 | 0.00 | 0.40 | 0.00 |
| 2relax | aaa | 0.003 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.003 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.003 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.003 | 5 | 3 | 0.20 | 0.00 | 0.80 | 0.00 |
| 2relax | aaa | 0.01 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.01 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.01 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.01 | 5 | 3 | 0.40 | 0.00 | 0.60 | 0.00 |
| 2relax | aaa | 0.03 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.03 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.03 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.03 | 5 | 3 | 0.40 | 0.00 | 0.20 | 0.40 |
| 2relax | aaa | 0.0 | 10 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | loewner_threshold | 0.0 | 10 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | loewner_gap | 0.0 | 10 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | stabilisation | 0.0 | 10 | 3 | 0.00 | 0.00 | 1.00 | 0.00 |
| 2relax | aaa | 0.001 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.001 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.001 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.001 | 10 | 3 | 0.60 | 0.00 | 0.40 | 0.00 |
| 2relax | aaa | 0.003 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.003 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.003 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.003 | 10 | 3 | 0.00 | 0.00 | 1.00 | 0.00 |
| 2relax | aaa | 0.01 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.01 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.01 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.01 | 10 | 3 | 0.20 | 0.40 | 0.20 | 0.20 |
| 2relax | aaa | 0.03 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.03 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.03 | 10 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.03 | 10 | 3 | 0.20 | 0.00 | 0.20 | 0.60 |
| 2relax | aaa | 0.0 | 20 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | loewner_threshold | 0.0 | 20 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | loewner_gap | 0.0 | 20 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | stabilisation | 0.0 | 20 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 2relax | aaa | 0.001 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.001 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.001 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.001 | 20 | 3 | 0.60 | 0.00 | 0.40 | 0.00 |
| 2relax | aaa | 0.003 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.003 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.003 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.003 | 20 | 3 | 0.40 | 0.20 | 0.20 | 0.20 |
| 2relax | aaa | 0.01 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.01 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.01 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.01 | 20 | 3 | 0.20 | 0.00 | 0.40 | 0.40 |
| 2relax | aaa | 0.03 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_threshold | 0.03 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | loewner_gap | 0.03 | 20 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| 2relax | stabilisation | 0.03 | 20 | 3 | 0.40 | 0.00 | 0.20 | 0.40 |
| 3relax | aaa | 0.0 | 5 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | loewner_threshold | 0.0 | 5 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | loewner_gap | 0.0 | 5 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | stabilisation | 0.0 | 5 | 5 | 0.00 | 0.00 | 1.00 | 0.00 |
| 3relax | aaa | 0.001 | 5 | 3 | 0.00 | 0.20 | 0.00 | 0.80 |
| 3relax | loewner_threshold | 0.001 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.001 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.001 | 5 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.003 | 5 | 3 | 0.00 | 0.20 | 0.00 | 0.80 |
| 3relax | loewner_threshold | 0.003 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.003 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.003 | 5 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.01 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.01 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.01 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.01 | 5 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.03 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.03 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.03 | 5 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.03 | 5 | 5 | 0.00 | 0.00 | 0.20 | 0.80 |
| 3relax | aaa | 0.0 | 10 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | loewner_threshold | 0.0 | 10 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | loewner_gap | 0.0 | 10 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | stabilisation | 0.0 | 10 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.001 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.001 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.001 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.001 | 10 | 5 | 0.00 | 0.00 | 0.20 | 0.80 |
| 3relax | aaa | 0.003 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.003 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.003 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.003 | 10 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.01 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.01 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.01 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.01 | 10 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.03 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.03 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.03 | 10 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.03 | 10 | 5 | 0.00 | 0.00 | 0.20 | 0.80 |
| 3relax | aaa | 0.0 | 20 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | loewner_threshold | 0.0 | 20 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | loewner_gap | 0.0 | 20 | 3 | 1.00 | 0.00 | 0.00 | 0.00 |
| 3relax | stabilisation | 0.0 | 20 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.001 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.001 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.001 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.001 | 20 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.003 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.003 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.003 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.003 | 20 | 5 | 0.00 | 0.00 | 0.20 | 0.80 |
| 3relax | aaa | 0.01 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.01 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.01 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.01 | 20 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | aaa | 0.03 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_threshold | 0.03 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | loewner_gap | 0.03 | 20 | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| 3relax | stabilisation | 0.03 | 20 | 5 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | aaa | 0.0 | 5 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | loewner_threshold | 0.0 | 5 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | loewner_gap | 0.0 | 5 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | stabilisation | 0.0 | 5 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | aaa | 0.001 | 5 | 4 | 0.20 | 0.20 | 0.00 | 0.60 |
| 4relax | loewner_threshold | 0.001 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.001 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.001 | 5 | 4 | 0.00 | 0.00 | 1.00 | 0.00 |
| 4relax | aaa | 0.003 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.003 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.003 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.003 | 5 | 4 | 0.00 | 0.00 | 0.40 | 0.60 |
| 4relax | aaa | 0.01 | 5 | 4 | 0.20 | 0.00 | 0.00 | 0.80 |
| 4relax | loewner_threshold | 0.01 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.01 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.01 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | aaa | 0.03 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.03 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.03 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.03 | 5 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | aaa | 0.0 | 10 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | loewner_threshold | 0.0 | 10 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | loewner_gap | 0.0 | 10 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | stabilisation | 0.0 | 10 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | aaa | 0.001 | 10 | 4 | 0.00 | 0.20 | 0.00 | 0.80 |
| 4relax | loewner_threshold | 0.001 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.001 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.001 | 10 | 4 | 0.00 | 0.00 | 1.00 | 0.00 |
| 4relax | aaa | 0.003 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.003 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.003 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.003 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | aaa | 0.01 | 10 | 4 | 0.00 | 0.20 | 0.00 | 0.80 |
| 4relax | loewner_threshold | 0.01 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.01 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.01 | 10 | 4 | 0.00 | 0.00 | 0.60 | 0.40 |
| 4relax | aaa | 0.03 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.03 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.03 | 10 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.03 | 10 | 4 | 0.00 | 0.00 | 0.20 | 0.80 |
| 4relax | aaa | 0.0 | 20 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | loewner_threshold | 0.0 | 20 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | loewner_gap | 0.0 | 20 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | stabilisation | 0.0 | 20 | 4 | 1.00 | 0.00 | 0.00 | 0.00 |
| 4relax | aaa | 0.001 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.001 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.001 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.001 | 20 | 4 | 0.00 | 0.00 | 0.60 | 0.40 |
| 4relax | aaa | 0.003 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.003 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.003 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.003 | 20 | 4 | 0.00 | 0.00 | 0.20 | 0.80 |
| 4relax | aaa | 0.01 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.01 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.01 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.01 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | aaa | 0.03 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_threshold | 0.03 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | loewner_gap | 0.03 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| 4relax | stabilisation | 0.03 | 20 | 4 | 0.00 | 0.00 | 0.00 | 1.00 |
| rcl_relax | aaa | 0.0 | 5 | 1 | 0.00 | 1.00 | 0.00 | 0.00 |
| rcl_relax | loewner_threshold | 0.0 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | loewner_gap | 0.0 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.0 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | aaa | 0.001 | 5 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.001 | 5 | 1 | 0.20 | 0.60 | 0.00 | 0.20 |
| rcl_relax | loewner_gap | 0.001 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.001 | 5 | 1 | 0.20 | 0.20 | 0.60 | 0.00 |
| rcl_relax | aaa | 0.003 | 5 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.003 | 5 | 1 | 0.20 | 0.60 | 0.00 | 0.20 |
| rcl_relax | loewner_gap | 0.003 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.003 | 5 | 1 | 0.20 | 0.20 | 0.60 | 0.00 |
| rcl_relax | aaa | 0.01 | 5 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.01 | 5 | 1 | 0.20 | 0.60 | 0.00 | 0.20 |
| rcl_relax | loewner_gap | 0.01 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.01 | 5 | 1 | 0.20 | 0.20 | 0.60 | 0.00 |
| rcl_relax | aaa | 0.03 | 5 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.03 | 5 | 1 | 0.20 | 0.60 | 0.00 | 0.20 |
| rcl_relax | loewner_gap | 0.03 | 5 | 1 | 0.80 | 0.00 | 0.00 | 0.20 |
| rcl_relax | stabilisation | 0.03 | 5 | 1 | 0.20 | 0.20 | 0.60 | 0.00 |
| rcl_relax | aaa | 0.0 | 10 | 1 | 0.00 | 1.00 | 0.00 | 0.00 |
| rcl_relax | loewner_threshold | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | loewner_gap | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | aaa | 0.001 | 10 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.001 | 10 | 1 | 0.20 | 0.00 | 0.00 | 0.80 |
| rcl_relax | loewner_gap | 0.001 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.001 | 10 | 1 | 0.40 | 0.00 | 0.40 | 0.20 |
| rcl_relax | aaa | 0.003 | 10 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.003 | 10 | 1 | 0.20 | 0.00 | 0.00 | 0.80 |
| rcl_relax | loewner_gap | 0.003 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.003 | 10 | 1 | 0.20 | 0.20 | 0.40 | 0.20 |
| rcl_relax | aaa | 0.01 | 10 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.01 | 10 | 1 | 0.20 | 0.00 | 0.00 | 0.80 |
| rcl_relax | loewner_gap | 0.01 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.01 | 10 | 1 | 0.20 | 0.00 | 0.60 | 0.20 |
| rcl_relax | aaa | 0.03 | 10 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| rcl_relax | loewner_threshold | 0.03 | 10 | 1 | 0.20 | 0.00 | 0.00 | 0.80 |
| rcl_relax | loewner_gap | 0.03 | 10 | 1 | 0.80 | 0.00 | 0.00 | 0.20 |
| rcl_relax | stabilisation | 0.03 | 10 | 1 | 0.20 | 0.00 | 0.60 | 0.20 |
| rcl_relax | aaa | 0.0 | 20 | 1 | 0.00 | 1.00 | 0.00 | 0.00 |
| rcl_relax | loewner_threshold | 0.0 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | loewner_gap | 0.0 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.0 | 20 | 1 | 0.00 | 1.00 | 0.00 | 0.00 |
| rcl_relax | aaa | 0.001 | 20 | 1 | 0.60 | 0.00 | 0.20 | 0.20 |
| rcl_relax | loewner_threshold | 0.001 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| rcl_relax | loewner_gap | 0.001 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.001 | 20 | 1 | 0.20 | 0.40 | 0.00 | 0.40 |
| rcl_relax | aaa | 0.003 | 20 | 1 | 0.60 | 0.00 | 0.20 | 0.20 |
| rcl_relax | loewner_threshold | 0.003 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| rcl_relax | loewner_gap | 0.003 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.003 | 20 | 1 | 0.20 | 0.40 | 0.00 | 0.40 |
| rcl_relax | aaa | 0.01 | 20 | 1 | 0.60 | 0.00 | 0.20 | 0.20 |
| rcl_relax | loewner_threshold | 0.01 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| rcl_relax | loewner_gap | 0.01 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| rcl_relax | stabilisation | 0.01 | 20 | 1 | 0.20 | 0.40 | 0.00 | 0.40 |
| rcl_relax | aaa | 0.03 | 20 | 1 | 0.60 | 0.00 | 0.20 | 0.20 |
| rcl_relax | loewner_threshold | 0.03 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| rcl_relax | loewner_gap | 0.03 | 20 | 1 | 0.80 | 0.00 | 0.00 | 0.20 |
| rcl_relax | stabilisation | 0.03 | 20 | 1 | 0.00 | 0.40 | 0.20 | 0.40 |
| cpe | aaa | 0.0 | 5 | 27 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | loewner_threshold | 0.0 | 5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.0 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | stabilisation | 0.0 | 5 | 0 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | aaa | 0.001 | 5 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.001 | 5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.001 | 5 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | stabilisation | 0.001 | 5 | 0 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | aaa | 0.003 | 5 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.003 | 5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.003 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | stabilisation | 0.003 | 5 | 0 | 0.40 | 0.00 | 0.00 | 0.60 |
| cpe | aaa | 0.01 | 5 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.01 | 5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.01 | 5 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | stabilisation | 0.01 | 5 | 0 | 0.40 | 0.00 | 0.00 | 0.60 |
| cpe | aaa | 0.03 | 5 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.03 | 5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.03 | 5 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | stabilisation | 0.03 | 5 | 0 | 0.40 | 0.40 | 0.00 | 0.20 |
| cpe | aaa | 0.0 | 10 | 27 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | loewner_threshold | 0.0 | 10 | 40 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | loewner_gap | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | stabilisation | 0.0 | 10 | 0 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | aaa | 0.001 | 10 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.001 | 10 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.001 | 10 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | stabilisation | 0.001 | 10 | 0 | 0.80 | 0.00 | 0.00 | 0.20 |
| cpe | aaa | 0.003 | 10 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.003 | 10 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.003 | 10 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | stabilisation | 0.003 | 10 | 0 | 0.20 | 0.00 | 0.00 | 0.80 |
| cpe | aaa | 0.01 | 10 | 27 | 0.20 | 0.00 | 0.00 | 0.80 |
| cpe | loewner_threshold | 0.01 | 10 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.01 | 10 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | stabilisation | 0.01 | 10 | 0 | 0.60 | 0.00 | 0.00 | 0.40 |
| cpe | aaa | 0.03 | 10 | 27 | 0.00 | 0.00 | 0.40 | 0.60 |
| cpe | loewner_threshold | 0.03 | 10 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.03 | 10 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | stabilisation | 0.03 | 10 | 0 | 0.20 | 0.40 | 0.00 | 0.40 |
| cpe | aaa | 0.0 | 20 | 27 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | loewner_threshold | 0.0 | 20 | 40 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | loewner_gap | 0.0 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | stabilisation | 0.0 | 20 | 0 | 1.00 | 0.00 | 0.00 | 0.00 |
| cpe | aaa | 0.001 | 20 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.001 | 20 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.001 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | stabilisation | 0.001 | 20 | 0 | 0.60 | 0.20 | 0.00 | 0.20 |
| cpe | aaa | 0.003 | 20 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.003 | 20 | 40 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | loewner_gap | 0.003 | 20 | 1 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | stabilisation | 0.003 | 20 | 0 | 0.40 | 0.00 | 0.00 | 0.60 |
| cpe | aaa | 0.01 | 20 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.01 | 20 | 40 | 0.20 | 0.00 | 0.20 | 0.60 |
| cpe | loewner_gap | 0.01 | 20 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | stabilisation | 0.01 | 20 | 0 | 0.40 | 0.40 | 0.00 | 0.20 |
| cpe | aaa | 0.03 | 20 | 27 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_threshold | 0.03 | 20 | 40 | 0.00 | 0.00 | 0.00 | 1.00 |
| cpe | loewner_gap | 0.03 | 20 | 1 | 0.00 | 0.20 | 0.00 | 0.80 |
| cpe | stabilisation | 0.03 | 20 | 0 | 0.80 | 0.00 | 0.00 | 0.20 |
| randles_warburg | aaa | 0.0 | 5 | 22 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | loewner_threshold | 0.0 | 5 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.0 | 5 | 2 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | stabilisation | 0.0 | 5 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | aaa | 0.001 | 5 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.001 | 5 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.001 | 5 | 2 | 0.80 | 0.00 | 0.00 | 0.20 |
| randles_warburg | stabilisation | 0.001 | 5 | 1 | 0.80 | 0.00 | 0.00 | 0.20 |
| randles_warburg | aaa | 0.003 | 5 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.003 | 5 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.003 | 5 | 2 | 0.80 | 0.00 | 0.00 | 0.20 |
| randles_warburg | stabilisation | 0.003 | 5 | 1 | 0.60 | 0.00 | 0.20 | 0.20 |
| randles_warburg | aaa | 0.01 | 5 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.01 | 5 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.01 | 5 | 2 | 0.60 | 0.00 | 0.20 | 0.20 |
| randles_warburg | stabilisation | 0.01 | 5 | 1 | 0.20 | 0.00 | 0.80 | 0.00 |
| randles_warburg | aaa | 0.03 | 5 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.03 | 5 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.03 | 5 | 2 | 0.00 | 0.00 | 0.20 | 0.80 |
| randles_warburg | stabilisation | 0.03 | 5 | 1 | 0.80 | 0.00 | 0.20 | 0.00 |
| randles_warburg | aaa | 0.0 | 10 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.0 | 10 | 23 | 0.00 | 0.00 | 1.00 | 0.00 |
| randles_warburg | loewner_gap | 0.0 | 10 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | stabilisation | 0.0 | 10 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | aaa | 0.001 | 10 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.001 | 10 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.001 | 10 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | stabilisation | 0.001 | 10 | 1 | 0.60 | 0.20 | 0.00 | 0.20 |
| randles_warburg | aaa | 0.003 | 10 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.003 | 10 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.003 | 10 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | stabilisation | 0.003 | 10 | 1 | 0.20 | 0.20 | 0.60 | 0.00 |
| randles_warburg | aaa | 0.01 | 10 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.01 | 10 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.01 | 10 | 2 | 0.60 | 0.00 | 0.40 | 0.00 |
| randles_warburg | stabilisation | 0.01 | 10 | 1 | 0.20 | 0.00 | 0.80 | 0.00 |
| randles_warburg | aaa | 0.03 | 10 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.03 | 10 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.03 | 10 | 2 | 0.00 | 0.00 | 0.80 | 0.20 |
| randles_warburg | stabilisation | 0.03 | 10 | 1 | 0.20 | 0.20 | 0.60 | 0.00 |
| randles_warburg | aaa | 0.0 | 20 | 22 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | loewner_threshold | 0.0 | 20 | 23 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | loewner_gap | 0.0 | 20 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | stabilisation | 0.0 | 20 | 1 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | aaa | 0.001 | 20 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.001 | 20 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.001 | 20 | 2 | 1.00 | 0.00 | 0.00 | 0.00 |
| randles_warburg | stabilisation | 0.001 | 20 | 1 | 0.00 | 0.20 | 0.40 | 0.40 |
| randles_warburg | aaa | 0.003 | 20 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.003 | 20 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.003 | 20 | 2 | 0.80 | 0.00 | 0.20 | 0.00 |
| randles_warburg | stabilisation | 0.003 | 20 | 1 | 0.20 | 0.00 | 0.80 | 0.00 |
| randles_warburg | aaa | 0.01 | 20 | 22 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_threshold | 0.01 | 20 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.01 | 20 | 2 | 0.00 | 0.00 | 1.00 | 0.00 |
| randles_warburg | stabilisation | 0.01 | 20 | 1 | 0.60 | 0.00 | 0.40 | 0.00 |
| randles_warburg | aaa | 0.03 | 20 | 22 | 0.00 | 0.20 | 0.00 | 0.80 |
| randles_warburg | loewner_threshold | 0.03 | 20 | 23 | 0.00 | 0.00 | 0.00 | 1.00 |
| randles_warburg | loewner_gap | 0.03 | 20 | 2 | 0.00 | 0.00 | 0.80 | 0.20 |
| randles_warburg | stabilisation | 0.03 | 20 | 1 | 0.20 | 0.00 | 0.60 | 0.20 |

## Fractional-element growth (CPE, Warburg truths)

### cpe

rtol sweep (rtol tightens left to right):
| 1e-02 | 3e-03 | 1e-03 | 3e-04 | 1e-04 | 1e-06 |
|---|---|---|---|---|---|
| 6 | 8 | 9 | 12 | 15 | 27 |
monotonic non-decreasing as rtol tightens: **True**

bandwidth sweep (decades widen left to right):
| 1e+11 | 1e+13 | 1e+15 | 1e+17 | 1e+19 |
|---|---|---|---|---|
| 15 | 15 | 16 | 16 | 15 |
monotonic non-decreasing as bandwidth widens: **False**

### randles_warburg

rtol sweep (rtol tightens left to right):
| 1e-02 | 3e-03 | 1e-03 | 3e-04 | 1e-04 | 1e-06 |
|---|---|---|---|---|---|
| 8 | 9 | 9 | 12 | 14 | 22 |
monotonic non-decreasing as rtol tightens: **True**

bandwidth sweep (decades widen left to right):
| 1e+11 | 1e+13 | 1e+15 | 1e+17 | 1e+19 |
|---|---|---|---|---|
| 14 | 15 | 15 | 15 | 15 |
monotonic non-decreasing as bandwidth widens: **True**
