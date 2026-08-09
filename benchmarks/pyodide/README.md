# How much slower is AutoCircuit in a browser?

Phase 6 of `docs/IMPLEMENTATION_PLAN.md` puts the same core in a browser through Pyodide, and
three of its design decisions were resting on a guess about WASM performance: what
`exhaustive_limit` can default to, whether progress has to be streamed, and whether the fitter
needs a separate reduced budget for the web. This measures it.

No browser is involved, and none is needed: Node and a browser load the identical Pyodide WASM
build, and nothing measured here touches the DOM, the network or a worker boundary.

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"
python benchmarks/pyodide/bench.py            # CPython baseline

cd benchmarks/pyodide
npm install
python make_zip.py
node run_pyodide.mjs src.zip bench.py         # the same script under Pyodide
```

`bench.py` is deliberately shared between the two: a browser-versus-desktop ratio is only worth
having if both sides ran identical code. Everything is single-threaded, because a browser has
no `multiprocessing`.

## Results

Pyodide 314.0.3 (Python 3.14.2, numpy 2.4.3, scipy 1.18.0) under Node 24 against CPython 3.13.14
with numpy 2.5.1 and scipy 1.17.1, same machine, both single-core. Medians.

| operation | CPython | Pyodide | ratio |
|-----------|--------:|--------:|------:|
| `import autocircuit...` | 0.40 s | 1.58 s | 3.9× |
| `fit`, 3 parameters | 0.163 s | 0.265 s | 1.6× |
| `fit`, 6 parameters | 0.704 s | 0.906 s | 1.3× |
| `screen`, 3 elements | 13.3 ms | 23.6 ms | 1.8× |
| `screen`, 4 elements | 32.2 ms | 45.1 ms | 1.4× |
| `lin_kk` | 10.2 ms | 20.1 ms | 2.0× |
| enumerate + feasibility, n ≤ 5 (6,598 kept) | 0.200 s | 0.316 s | 1.6× |
| `discover`, R/C pool, n ≤ 4 (17 screened) | 4.95 s | 7.10 s | 1.4× |
| **`discover`, component pool, n ≤ 4 (741 screened)** | **127.5 s** | **169.1 s** | **1.33×** |
| Pyodide boot | — | 1.17 s | — |
| numpy + scipy load (warm cache) | — | 1.1 s | — |

**WASM is not the problem.** The plan's risk section expected "minutes-not-seconds"; the real
penalty on the numerical work is 1.3–1.8×, because the expensive part is numpy and scipy
compiled to WASM rather than interpreted Python. The interpreter-bound paths pay more — the
import is 3.9× — but that is a one-off 1.6 s. The ratio is *smallest* on the heaviest job,
which is the good direction.

What this settles for phase 6:

- **Cold start to the first fit is about 4 s**: 1.2 s boot, 1.1 s numpy/scipy from cache
  (2.2 s the first time, when the wheels are fetched), 1.6 s importing the package. That needs
  a loading state, not an architecture.
- **`exhaustive_limit=4` is the right web default, and it is 2.8 minutes**, not seconds. So
  progress streaming through the existing `on_progress` callback is not a nicety, it is
  required; and the CLI's 8-worker parity is not available, so the browser is doing what a
  single core does.
- **`exhaustive_limit=5` is not a default.** The same search over 6,598 candidates costs ~22
  min single-core on CPython, so ~30 min here. It stays available as an explicit choice.
- **The fitter does not need a separate web budget.** `restarts=5, popsize=20` and the
  `8×40` screen run 1.3–1.6× slower and are otherwise unchanged, and the screening budget is
  already known to have no headroom (`benchmarks/README.md`, `screen-rank`). Cutting it for the
  browser would trade the answer for the clock in exactly the way that experiment measured.

`src.zip` is a build artifact (gitignored); `make_zip.py` regenerates it. It exists because
PowerShell's `Compress-Archive` writes backslash separators that Python's `zipfile` unpacks
into files literally named `autocircuit\__init__.py`, which fails only at the import.
