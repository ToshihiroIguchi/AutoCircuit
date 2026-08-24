# The objective — what the user wants out, and the rule that it may not reach a number

`CLAUDE.md`'s "Objectives" section states the axis and its invariant; this document is how it
was built, what was measured, and the two places the obvious implementation was wrong.

**Status: implemented in the core, the CLI and the browser; gate O1 measured on three
references.**

## 1. The axis, and why it is not the mode

There are two reasons to bring an impedance spectrum here:

* **`model`** — an equivalent circuit to use, typically in a simulator. Deliverable: the SPICE
  subcircuit plus the band it is valid over. Readouts: ESR over the band, ESL, self-resonant
  frequency, Q, minimum |Z|, tan δ, DC resistance. Its claim is complete and checkable from the
  data alone — *this reproduces the measured Z over this band*.
* **`interpret`** — what the spectrum says is happening inside the part. Deliverable: the
  processes the data can distinguish. Its claim is always conditional.

The **mode** (how much of the topology the user fixes: manual, skeleton, full auto) changes the
*search*. The **objective** changes only the *report*. They are orthogonal and conflating them
would undo the thing this project is for: two people with the same spectrum must get the same
circuit and the same values whatever they came for, or the analyst-independence that separates
this from ZView is gone.

What the objective legitimately changes is **how loudly the report says the data cannot
decide**. `R1-p(R2,C1)` and `p(R1,C1-R2)` fit the same data to 1.2e-15. Under `model` that is
harmless — same terminal Z over the band, either exports and simulates identically. Under
`interpret` it *is* the question, because whether a resistance is a grain boundary or an
electrode interface is exactly that difference in form.

`model` is the default, for one reason: its claim is the one the data can check by itself.

## 2. Where it lives

`core/objective.py`, and nowhere else. It consumes a **finished** `DiscoveryResult` or
`FitResult` and produces an `ObjectiveReport`; it holds no number the analysis did not already
produce, and rendering one does not mutate the result it was rendered from (asserted in
`tests/test_objective.py`).

The invariant is enforced **by construction rather than by convention**: `discover()` and
`fit()` do not take an objective, and neither module imports this one. That is the half of gate
O1 that actually holds the property — a value the search cannot receive cannot change it.

The command line takes `--objective {model,interpret}` on `fit` and `discover`, plus
`autocircuit objectives` for the explanation. `--interpret` is kept as the older spelling of
`--objective interpret`, because that is exactly what it named before the axis had one.

## 3. Gate O1 — the objective changes no number

Stated in `CLAUDE.md` as: the full pipeline run under both objectives on the same spectrum and
seed produces a byte-identical `DiscoveryResult` wire payload; only the rendered report differs.
`benchmarks/o1_objective.py` is the instrument, modelled on `benchmarks/ev5_fingerprint.py`.

Both halves, and both are needed:

1. **Structural** — `discover()` and `fit()` take no objective and neither imports the
   reporting layer. Checked by signature and by an AST walk of the imports.
2. **Measured** — the command line is driven end to end once per objective, same file, same
   seed, and the two `--json` payloads are compared byte for byte with the objective's own
   section removed and every clock dropped. The rendered reports must **differ**, or the axis
   is decoration and the comparison above is vacuous.

[measured, 2026-08-24, `python benchmarks/o1_objective.py --limit 3`]

```
pass (structural): neither discover() nor fit() can see an objective
capacitor (C-R-L + skin effect)    payload identical, report differs  -- pass
Maxwell-Wagner (two blocks)        payload identical, report differs  -- pass
Randles (with Warburg)             payload identical, report differs  -- pass
O1: pass
```

A cheap version of the same check runs in the suite
(`tests/test_cli.py::test_the_objective_changes_the_report_and_not_one_number`), so a change
that lets the objective leak into the search fails CI rather than waiting for the benchmark.

## 4. Five things not to re-derive

### 4.1 `--objective` must default to `None`, not to `model`

With `default="model"` argparse cannot tell *asked for model* from *asked for nothing*, so
`--interpret --objective model` — two answers to one question — was accepted silently and the
alias won. The flag defaults to `None` and `_objective_of` resolves it, which is the only way
the conflict is visible at all. The same shape as every other silent-narrowing bug in this
repo: the run looks healthy and reports something nobody asked for.

### 4.2 A payload comparison has to drop clocks *recursively*

Popping the top-level `elapsed_s` is not enough — every candidate in the report carries its own,
so two runs of the same search differ in dozens of places for reasons that have nothing to do
with the objective. The benchmark's `_stable` walks the whole tree, and the test does the same.
A gate that fails for a reason it is not about is a gate that will be reworded rather than read.

### 4.3 The `model` readouts must all be invariant, and that is checked

The model report says its numbers are "properties of Z, so every equivalent topology agrees".
That sentence is only true because every name in `MODEL_READOUTS` is marked `invariant` in
`core/interpret.py`. A test asserts it rather than trusting the list, since the failure mode —
a form-dependent number printed under a heading promising a property of the measurement — is
invisible in the output and is precisely what `interpret.py` was built to prevent.

### 4.4 ESL is the *apparent* inductance at the top of the band

`inductance_at_f_max` is `Im Z / omega` at `f_max`, gated on the response actually being
inductive there. For a series R-L-C that is `L - 1/(omega^2 C)`, which approaches `L` only well
above resonance — so the number is what a bridge would read at that frequency, not the model's
`L` parameter, and the note beside it names the frequency. Reporting the parameter instead would
be reporting a property of the reported form under an invariant heading (§4.3).

A related tidy-up: the "standard error exceeds the value" rule moved from `core/discover.py` to
`core/stats.py` as `unresolved_mask`, because three readers now ask that same question of a fit
— the Pareto table's `free?` column, the skeleton's "the data does not test this part of your
assertion", and the `model` objective's warning that a value carries no information on its own.
A second copy of the threshold would let them disagree about one fit.

### 4.5 A class that agrees on a *zero* used to report infinite disagreement

`ClassSpread.spread` is `max|v - median| / |median|`, and the guard for a zero median returned
`inf`. But a quantity every member reports as the *same* zero -- `r_inf` of a network that is a
short at the top of the band, which `core/interpret.py` reports as exactly zero on purpose --
is perfect agreement, and it was being printed as total disagreement. Worse, the browser's wire
is strict JSON (`allow_nan=False`), so that one value made the **whole response undeliverable**:
the reader got "Out of range float values are not JSON compliant" instead of a report.

[measured] `p(R1,C1)` and `p(C1,R1)` as one class: `r_inf` spread `inf`, `json.dumps(...,
allow_nan=False)` raises. Both halves are fixed, and both were needed. Exact agreement now
reads 0 whatever the median is; and every objective payload leaves the bridge through
`wire.encode_payload`, so no report can be lost to a non-finite value it merely mentions.

## 5. What the two reports contain

`model`: the circuit, the band (`f_min .. f_max`, the measured one, stated as the limit of the
claim), the agreement in that band (RMS |dZ|/|Z|, the worst single point, chi²_red), the
invariant readouts, `Re Z` sampled across the band, and two notes — what the equivalence class
means here (nothing, over this band, and the members are free to differ outside it) and what an
unresolved parameter means here (harmless for simulation, meaningless as a measurement).

`interpret`: the whole `ClassInterpretation` — the recommendation read as internal structure and
every other member of its class read the same way, with the measured spread beside each quantity
and the relaxation-count disagreement as an alert — plus the sentence that everything above is
conditional on the reported form. When the DRT was computed alongside the search, its model-free
relaxation count is passed in for the cross-check; it is advice in both places and changes no
candidate and no number (`docs/DISCOVERY_V2_PLAN.md` §3.4).

## 7. The browser

Wired. `discover_interpret` became `discover_objective` (`BRIDGE_VERSION` 10 -> 11), which takes
the objective with the request for a *report*; no search operation takes one, and that is the
same structural claim §3 makes on the command line. The Report screen's panel is
`ObjectivePanel`, with a two-button switch that re-fetches and cannot re-run anything.

[measured, in Chrome, dev server] Tissue (Cole) at a three-element limit. Under `model`:
`p(R1,CPE1)-R2` over 10 Hz - 1 MHz, RMS |dZ|/|Z| 1.28%, worst point 2.37%, and the note that the
one other topology in the class exports and simulates identically over that band. Under
`interpret`: the same search, the relaxation-count alert (`p(R1,CPE1)-R2` says 1,
`p(R1-CPE1,R2)` says 0) and the four invariant quantities agreeing to 1.9e-9 - 4.6e-9 percent.
No console errors, and switching does not re-run the search.

## 8. What is not done

* The SPICE netlist is **not** embedded in the model report. Both front ends already write one
  (`--spice`, and the browser's download), and a report that carries a synthesised ladder would
  duplicate that with an error target nobody chose.
* The multi-condition fit — several sweeps at different temperature or DC bias fitted to one
  circuit — is still the one instrument that could *break* a degeneracy, and it belongs to
  `interpret` alone. Not started; see `docs/HANDOFF.md` §6.
