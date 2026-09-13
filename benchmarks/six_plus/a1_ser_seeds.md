## Recovery on the six- and seven-element truths

| arm | reported | on the front | recommended | median seconds |
|---|---:|---:|---:|---:|
| grow | 15/60 | 9/60 | 0/60 | 76 |
| params7 | 9/60 | 1/60 | 0/60 | 121 |

## The negative control: five-element truths

A method that always grows would score perfectly above and be worthless. `over-grown` counts the runs whose recommendation has **more** elements than the truth.

| arm | recommended correctly | over-grown | median seconds |
|---|---:|---:|---:|

## By shape, `reported` only

| arm | parallel | series | mixed |
|---|---:|---:|---:|
| grow | - | 15/60 | - |
| params7 | - | 9/60 | - |

## Paired: `grow` vs `params7`, `reported` (exact McNemar)

| truth | both | only grow | only params7 | neither | discordant | p |
|---|---:|---:|---:|---:|---:|---:|
| ser6 | 0 | 15 | 0 | 15 | 15 | 0.0001 |
| ser7 | 0 | 0 | 9 | 21 | 9 | 0.0039 |