# The AutoEIS comparison round

Plan: `docs/AUTOEIS_COMPARISON_PLAN.md`. Results: `docs/AUTOEIS_COMPARISON.md`.

**This round is a description, not a gate. No default in this repository changes on its result.**

## Why there are two producers and one scorer

The two environments never meet. AutoEIS needs Julia, JAX and NumPyro; this project ships on
numpy and scipy alone so that the same wheel runs under Pyodide. So:

| script | environment | imports |
|---|---|---|
| `run_autoeis.py` | the AutoEIS venv | `autoeis`, never `autocircuit` |
| `run_autocircuit.py` | the project env | `autocircuit`, never `autoeis` |
| `score.py` | the project env | `autocircuit` and `translate.py`, never `autoeis` |
| `translate.py` | the project env | `autocircuit.core.dsl` only |

Both producers write frozen result tables as JSON. `score.py` reads both tables and applies **one
referee to both sides** — this repository's `canonical_form()` and its numeric equivalence at
`EQUIVALENCE_RTOL`. Applying equivalence detection to our own output and a string comparison to
theirs would be scoring the referee rather than the searches.

`translate.py` is the piece that can silently become a score: a bug there turns into a hit or a
miss with no visible symptom, which is why it has its own test file
(`tests/test_autoeis_translate.py`) with hand-checked cases in both directions and a numerical
round trip.

## Running the round

Every step below is **restartable**: re-issuing the identical command continues rather than
starting over, and a machine that dies costs at most the one run that was in flight. That is not
a convenience, it is the operating condition — the machine can shut down without an operator
present, so nothing may live only in memory.

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src"

# 1. Build arena C. Its identifiability screen is a full fit per draw, so this takes a while;
#    verdicts are cached in arena_c/screen_cache.jsonl and a restart reuses them.
python benchmarks/autoeis_round/arena.py --out benchmarks/autoeis_round/arena_c

# 2. The two producers. They may run in either order, but NOT at the same time -- both saturate
#    the machine, and benchmarks here are not to be run concurrently.
python benchmarks/autoeis_round/run_autocircuit.py --arena benchmarks/autoeis_round/arena_c --max-seeds 5
C:\Users\toshi\python\autoeis-env\Scripts\python.exe benchmarks/autoeis_round/run_autoeis.py --arena benchmarks/autoeis_round/arena_c --max-seeds 5

# 3. Score. Refuses to run if any smoke record is present.
python benchmarks/autoeis_round/score.py --arena benchmarks/autoeis_round/arena_c --out benchmarks/autoeis_round/arena_c/report.json
```

`--max-seeds` is the stage boundary: 5, then 10, then 20, which are the values `arena.py`
pre-registers. Raising it and re-running adds the new seeds to what is already there.

**On stopping.** The round stops when the machine time runs out or the seed list is exhausted,
and never because a result looked significant. See `arena.py`'s module docstring; the reason it
is written down is so the claim can be checked rather than believed.

**On what an arena can resolve.** `score.py` reports `d`, the smallest all-in-one-direction
discordant count that could reach p ≤ 0.05. It is **6, whatever the arena size** — five reaches
only 0.0625 — so more seeds buy the *opportunity* for discordant runs, not a lower bar. If the
outcome lands inside `d` the finding is "indistinguishable at this seed count", and the response
is more seeds or nothing.

To launch a long step so that it outlives the shell that started it (measured: the child survives
its launcher's exit):

```powershell
Start-Process -FilePath python.exe -ArgumentList "benchmarks/autoeis_round/run_autocircuit.py","--arena","benchmarks/autoeis_round/arena_c" `
  -WorkingDirectory C:\Users\toshi\python\AutoCircuit -RedirectStandardOutput run.log -RedirectStandardError run.err -WindowStyle Hidden
```

## The AutoEIS environment

Not created by anything in this repository, and deliberately outside it:

```powershell
# Python 3.12 is required: autoeis 0.0.44 declares requires_python ">=3.10,<3.13",
# and this machine's default interpreter is 3.13.
winget install --id Python.Python.3.12 --exact --scope user
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv C:\Users\toshi\python\autoeis-env
& C:\Users\toshi\python\autoeis-env\Scripts\python.exe -m pip install autoeis
# Required: autoeis 0.0.44 requires `arviz` with no upper bound, pip resolves 1.3.0, and arviz
# 1.x removed `az.waic`, so `compute_fitness_metrics` -- the stage AutoEIS's own WAIC ranking
# comes from -- dies with an AttributeError. 0.23.4 is the last release that has it.
& C:\Users\toshi\python\autoeis-env\Scripts\python.exe -m pip install "arviz==0.23.4"
```

The first import of the Julia runtime takes about 147 s: `juliapkg` fetches Julia 1.10 (its
`juliapkg.json` requires `~1.10.0`, so a system Julia 1.12 is not used) and precompiles
EquivalentCircuits.jl. **That cost is paid once per process, so `run_autoeis.py` must run many
spectra in one process.**

Do not add any of this to `pyproject.toml`.

## Facts about AutoEIS that the scripts depend on

All confirmed from the installed version 0.0.44, not from its documentation. The evidence is in
`docs/AUTOEIS_COMPARISON.md` §0.

- Vocabulary is `R`, `C`, `L`, `P` (CPE). **No Warburg.** The default `terminals` is `"RLP"`.
- `perform_full_analysis()` raises `NotImplementedError`; the pipeline is the four step-by-step
  calls.
- **The default (`parallel=True`) path ignores the seed.** Every run is an independent draw.
  `seed=0` is not a seed either — it falls back to the clock, so seeds start at 1.
- Parallelism is Julia `Distributed`, one `julia.exe` worker per physical core, with no argument
  to change it. The parent Python process shows almost no CPU; that is normal and is not a stall.
- The circuit grammar is `-` for series and `[a,b]` for parallel, with a single global element
  counter (`[[P1-L2,R3]-[L4,R5],R6]-R7`). Parameters arrive as `dict[str, float]` keyed `R1`,
  `C2`, `L3`, and `P4w`/`P4n` for a CPE.
- The CPE is `Z = 1/(Pw·(jω)^Pn)`, identical to this repository's `Z = 1/(Q·(jω)^n)`. No unit
  conversion.
- AutoEIS's own ranking is `WAIC (sum)` ascending (`visualization.py`), which is what defines its
  single top answer for the `recommended` metric.
