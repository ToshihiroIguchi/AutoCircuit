# Screening round — cheap instruments for shortlisting search algorithms

The write-up, with every number and every correction, is `docs/SEARCH_ALGORITHM_SCREENING.md`.
This directory holds the scripts that produced it.

**These are shortlisting instruments, not gates.** They exist because
`benchmarks/discovery_v2.py evolve-gate` costs 2.5–3 hours per arm, which is not a budget for
comparing twelve candidates. Nothing here should be read as a pass/fail on the genetic search;
`evolve-gate` remains the gate.

Everything runs on one reference — the three-block Maxwell-Wagner of
`docs/EVOLVE_SEARCH_PLAN.md` §3.1, copied verbatim into `landscape.py` — because it is the only
one of EV1's three whose topology space can be enumerated at all. That limitation is the first
thing to read in `docs/SEARCH_ALGORITHM_SCREENING.md` §2.1.

## The idea

Screen every plausible topology in the space once, keep the table, and a topology search becomes
a lookup-table walk: milliseconds a run, hundreds of seeds free, and the budget counted in
**fits** rather than seconds — so the comparison does not measure the machine. `arms.py` drives
`discover._next_generation`, `mutate`, `crossover`, `_tournament` and `_unique_best` directly, so
the incumbent arm is the real search and not a copy of it. The same now goes for the arm that
won: `ga_bounded` calls `discover._breeding_pool`, which shipped after this round, so re-running
`--arms current,ga_bounded` re-measures the library rather than a description of it.

## The generated tables are not committed

Same rule as `benchmarks/pyodide` — the results live in the write-up and the inputs are rebuilt.
`land_*.json` and `sample_rclcpe.json` are 3.4 MB of regenerable screening costs; the
`targets_*.json` files *are* committed, because they are small and expensive (the CPE one is
~50 min of full-budget refits) and because they define what "the truth" means for every later
run.

## Rebuilding, with measured runtimes

```powershell
$env:PYTHONPATH = "C:\Users\toshi\python\AutoCircuit\src;C:\Users\toshi\python\AutoCircuit\benchmarks\screening_round"
cd benchmarks\screening_round

python landscape.py  --pool R,C,L      --n-max 6 --workers 8 --out land_rcl6.json      #  1.9 min
python landscape2.py --pool R,C,L      --n-max 7 --workers 8 --jsonl rcl7.jsonl `
                     --out land_rcl7.json                                              # ~15 min
python landscape.py  --pool R,C,L,CPE  --n-max 6 --workers 8 --out land_rclcpe6.json   # 51.9 min

python targets.py land_rcl6.json     --out targets_rcl6.json      # seconds
python targets.py land_rcl7.json     --out targets_rcl7.json      # ~10 min
python targets.py land_rclcpe6.json  --out targets_rclcpe6.json   # ~50 min
```

**Use `landscape2.py` for anything long.** It appends to a JSONL and flushes as it goes, and a
restart skips what is already there; `landscape.py` writes only at the end. Two 20-minute builds
were lost to something outside the process before that was fixed, and one 51-minute build was
wrongly *declared* lost on the strength of a stale log line — the arena that
`docs/SEARCH_ALGORITHM_SCREENING.md` §4.2 rests on is the one that had already finished.

## The measurements

```powershell
python analyse.py land_rclcpe6.json                       # KPI-0: the truth's rank in the arena
python arms.py land_rclcpe6.json targets_rclcpe6.json `
       --seeds 120 --budget 900 --max-elements 6          # KPI-1/2: the arms, ~10 min
python param_opt.py land_rcl6.json --cases 12 --seeds 2   # KPI-3: optimisers at equal NFE
python profile_eval.py                                    # KPI-4: where one evaluation's time goes
python kpi0_sample.py --pool R,C,L,CPE --per-size 400     # KPI-0 by sampling — see the warning below
python evolve_probe.py --seeds 2 --pool R,C,L --warm 0    # the real search, instrumented
python reach_probe.py --seeds 3 --pool R,C,L --warm 0     # the same question, 100x cheaper
python report_probe.py --max-elements 9 --time-limit 180  # which reporting stage drops it, ~5 min
```

`report_probe.py` is the follow-up to the one row of §4.6 that was a defect rather than a
measurement. `evolve_probe.py` can see that the truth's class was visited and not reported;
this one wraps `_shortlist_candidates` and `_refine` and says which of them lost it — the
answer was neither, and §4.6.1 has it.

## Three traps this directory walked into, so the next person does not

**A sample is not a rank.** `kpi0_sample.py` on 1,176 topologies reported that nothing
out-scores the truth. Sixteen things do; they are 0.09% of the level, so a 400-point sample
expects 0.35 of them. It is kept because the estimate is still useful and cheap — but the rank
comes from the full table.

**Cost proximity is not equivalence.** Using "within 5% of the truth's screening cost" as the
target set over-counted the CPE arena's class by **7.6x** (136 against 18), and it changed a
verdict: MAP-Elites read 118/120 on the proxy and 120/120 on the verified set. `targets.py` is
the response test and it is the one that decides.

**An empty result looks like a pass.** `evolve_probe.py` reported "class members visited: 0" for
a whole session because it fed `Circuit.canonical_form()` — which is `[p(C,R)-p(C,R)-p(C,R)]`, a
label and not a circuit string — to `fit`, and a bare `except` swallowed all forty raises. It now
counts and prints its own refit failures.
