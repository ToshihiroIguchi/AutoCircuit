## Recovery on the six- and seven-element truths

| arm | reported | on the front | recommended | median seconds |
|---|---:|---:|---:|---:|
| base | 0/18 | 0/18 | 0/18 | 20 |
| grow | 14/18 | 14/18 | 12/18 | 46 |
| seeds2 | 0/18 | 0/18 | 0/18 | 24 |

## The negative control: five-element truths

A method that always grows would score perfectly above and be worthless. `over-grown` counts the runs whose recommendation has **more** elements than the truth.

| arm | recommended correctly | over-grown | median seconds |
|---|---:|---:|---:|
| base | 9/9 | 0/9 | 13 |
| grow | 9/9 | 0/9 | 57 |
| seeds2 | 9/9 | 0/9 | 12 |

## By shape, `reported` only

| arm | parallel | series | mixed |
|---|---:|---:|---:|
| base | 3/9 | 3/9 | 3/9 |
| grow | 9/9 | 5/9 | 9/9 |
| seeds2 | 3/9 | 3/9 | 3/9 |