# AutoCircuit

Equivalent circuit analysis of passive-component frequency characteristics — **without
user-supplied initial values**.

**Run it in your browser: <https://toshihiroiguchi.github.io/AutoCircuit/>** — nothing to
install, and nothing to upload. The page runs this package under Pyodide, so the fitting happens
on your machine and the data never leaves it.

Software such as ZView requires the analyst to guess starting parameters before a fit will
converge, which makes the answer depend on the analyst. AutoCircuit derives its own search
bounds from the measured data and finds the parameters by global optimization, so the same
data always gives the same answer. It can also search for the circuit *topology* itself.

## What it does

- **Fit a circuit you specify** — all parameters found automatically, with standard errors,
  correlations, and explicit warnings when the data cannot identify a parameter.
- **Discover the circuit** — genetic-programming search over circuit topologies, reported as
  an accuracy-versus-complexity Pareto front rather than a single answer, with
  numerically-indistinguishable topologies grouped together. The recommended model is chosen
  by parsimony — the simplest circuit that fits as well as any, with every parameter actually
  resolved by the data — not by the raw information criterion, which prefers over-fitted
  circuits.
- **Validate the data first** — a linear Kramers-Kronig test runs before every fit and says so
  when the spectrum is not physically consistent (drift, non-linearity, bad contact).
- **Export to SPICE** — including constant-phase, Warburg and skin-effect elements, which have
  no SPICE primitive and are synthesised as passive RC/RL ladders valid over the measured band.
- **Read the common instrument formats** — generic CSV, ZView/ZPlot `.z`, Touchstone
  `.s1p`/`.s2p` (series-thru and shunt-thru), Keysight/Agilent impedance-analyser CSV.

Designed for capacitor characterisation (C, ESR, ESL, skin effect), sintered ceramics
(Maxwell-Wagner / brick-layer), and passive components generally.

## Install

```
pip install -e .
```

Requires Python 3.12+. The only runtime dependencies are numpy and scipy, which is what allows
the same code to run in a browser under Pyodide — see below.

## Quick start

```bash
# What elements are available?
autocircuit elements

# Generate a test spectrum: 1 uF capacitor, 10 mohm ESR, 0.5 nH ESL, plus skin effect
autocircuit simulate -c "C1-R1-L1-SKINF1" \
    -p C1.C=1e-6 -p R1.R=1e-2 -p L1.L=5e-10 -p SKINF1.A=2e-5 -p SKINF1.n=0.5 \
    --fmin 100 --fmax 1e9 --noise 0.01 -o cap.csv

# Fit it. No initial values are given, and none are needed.
autocircuit fit cap.csv -c "C1-R1-L1-SKINF1" --spice cap.cir --json cap.json

# Let the software work out the topology too. By default this enumerates *every* plausible
# topology up to five elements, so the report can state what it covered rather than what it
# happened to find. --workers fans the screening pass across cores.
autocircuit discover cap.csv --pool component --workers 8 --progress

# Rank that search by something other than AIC. `autocircuit criteria` explains the seven.
autocircuit discover cap.csv --pool component --criterion bic

# Check the data is Kramers-Kronig consistent before believing any of it
autocircuit validate cap.csv

# Ask a different question: how many relaxations does this sample show, and is any of them
# broad enough to want a CPE rather than a C? Exits non-zero if the data is not relaxation-like.
autocircuit drt cell.csv --json drt.json
```

Typical `fit` output:

```
Parameter              Value    Std. error     Rel.  Unit
C1.C             1.00002e-06      1.46e-09     0.1%  F
R1.R              0.00996752      0.000736     7.4%  ohm
L1.L             5.06163e-10      5.15e-12     1.0%  H
SKINF1.A         2.12652e-05      1.28e-06     6.0%  ohm*s^n
SKINF1.n             0.49672       0.00321     0.6%  -

chi^2 (reduced) : 9.07659e-05   (modulus weighting)
RMS |dZ|/|Z|    : 1.3234%
AIC       -1316.72   AICc      -1316.28   BIC       -1301.94
CAIC      -1296.94   HQC       -1310.71   WAIC       -1315.8
WAIC effective parameters: 5.58 of 5   (Laplace approximation)
Data points     : 71   Free parameters: 5

Warnings:
  - SKINF1.A and SKINF1.n are -0.9983 correlated: they are not independently
    identifiable from this data
```

## Circuit syntax

`-` is series, `p(a,b)` is parallel:

| Circuit | Meaning |
|---------|---------|
| `C1-R1-L1` | capacitor with ESR and ESL |
| `C1-R1-L1-SKINF1` | the same, plus a skin-effect term |
| `p(R1,C1)-p(R2,C2)` | two Maxwell-Wagner relaxations in series |
| `R1-p(C1,R2-W1)` | Randles cell |
| `R1-p(R2,C1)-p(R3,CPE1)` | brick-layer model with a depressed second arc |

Element codes: `R`, `C`, `L`, `CPE`, `W`, `Ws`, `Wo`, `G`, `CC`, `HN`, `SKINF`, `SKINW`.
Run `autocircuit elements` for units and SPICE realisation of each.

## Python API

```python
from autocircuit.core.fit import fit
from autocircuit.core.spice import to_netlist
from autocircuit.io import read

spectrum = read("measurement.s2p", port_config="shunt_thru")  # correct for low-ESR caps
result = fit("C1-R1-L1-SKINF1", spectrum)

print(result.summary(spectrum))
print(result.params["R1.R"], "+/-", result.stderr["R1.R"])

netlist = to_netlist(
    result.circuit, result.values, f_min=spectrum.f[0], f_max=spectrum.f[-1]
)
```

## Notes on the harder parts

**Skin effect.** Two elements are provided: `SKINF`, a fractional element `Z = A(jw)^n` that
absorbs the sqrt(f) rise of ESR at high frequency, and `SKINW`, the exact Bessel-function
internal impedance of a solid round conductor. The fitter evaluates them exactly in the
frequency domain; the RL-ladder approximations found in the literature are needed only for
time-domain SPICE, and are generated automatically at export time.

**The exported netlist is checked twice.** The test suite parses the emitted `.subckt` back and
solves it by nodal analysis, which catches node-allocation bugs a formula-level test cannot; and
CI then runs a real ngspice over nine exported circuits and compares against that same engine,
which is what makes the file *dialect* right rather than only electrically right. The two agree
to within 4.5e-12, ladder-synthesised elements included. Every netlist carries the deck that
drives it, and the one snag: a model beginning with a capacitor is an open circuit at DC, so
ngspice reports a singular operating point — harmlessly, since an AC analysis of a linear network
does not depend on one.

**Topology discovery is not magic.** Different topologies are frequently exact
reparameterisations of one another — `R1-p(R2,C1)` and `p(R1,C1-R2)` describe exactly the same
set of Nyquist semicircles and fit any such data identically. AutoCircuit detects and reports
these as indistinguishable rather than picking one and presenting it as the answer. Choosing
between them requires physical knowledge of the sample, not more computation.

**Discovery is exhaustive first.** The distinct topology space is small — a few thousand
candidates at five elements — so `discover` enumerates all of it (`--mode exhaustive`) instead
of sampling it, and reports how far that coverage reached:

```
Coverage: every plausible topology with up to 5 elements from this pool was evaluated.
```

That line is the point of the feature: a topology missing from the report is missing because
it does not fit, not because the search never tried it. `--mode evolve` switches back to the
genetic search, which is still what runs above `--exhaustive-limit`; `--mode auto` (the
default) does the enumeration and only falls back to evolution if the residuals still look
systematic.

**Seven model-selection criteria, and one of them is not a score.** `--criterion` chooses what
ranks the candidates, draws the Pareto front and orders the tier-1 shortlist: AIC (the default),
AICc, BIC, CAIC, HQC, WAIC or an F-test. Two of them carry an assumption worth reading before
using, and `autocircuit criteria` prints it:

* **WAIC** is defined over a posterior and this is a least-squares fitter, so it is computed
  under a Laplace approximation at the fitted point with the residual linearised through the same
  Jacobian the covariance comes from. Its penalty counts the parameters the data *resolves*
  rather than the ones the model declares, which is the reason to ask for it — on a fit where
  they agree it is AIC to within a fraction of a unit.
* **An F-test compares two models, not one against a scale.** It ranks by AIC and then walks the
  Pareto front, stepping up only where the extra parameters are significant — and it assumes each
  row is nested in the next, which topologies generally are not. It is a guide to whether extra
  elements earned their place, not a p-value to publish.

None of the seven changes what the report *recommends*. That is a separate rule and a rule about
identifiability: the simplest model that fits as well as any **and** whose parameters the data
actually pins down. [measured] Minimum-AICc on a 71-point capacitor spectrum selects a
9-parameter circuit with two parameters whose standard errors exceed their own values; choosing
BIC instead does not make that a different kind of mistake.

**You can assert the part you already know.** A film capacitor has an ESR and an ESL in series
with it; a cell has an electrolyte resistance in series with everything. `--skeleton` states
that much and lets the search supply the rest — it adds elements to what you wrote and never
removes them:

```
autocircuit discover cap.csv --pool component --skeleton "C1-R1-L1"
```

It is the sharpest instrument here: at five elements from the component pool, asserting
`C1-R1-L1` cuts 10,214 candidates to 601, which is what brings six-element models into range
at all. It is also the only option that can remove the right answer while leaving a report
that looks healthy, so the coverage line changes with it and says so in the same sentence —
*every plausible topology with up to 6 elements **that contains C1-R1-L1** was evaluated* —
and the report adds what a constrained search owes you: when your skeleton fits into a reported
circuit in more than one place, it says so instead of picking one; when the fit could only work
by switching one of your asserted elements off, it names that element, because that — and not a
worse fit — is what a wrong skeleton actually looks like; and when every candidate that fits
leaves parameters the data cannot resolve, it says that too, since that is a fact about the
measurement rather than about the search.

`--excluded-equivalents` answers the remaining question: *what did my assertion rule out that
would have fitted just as well?* It screens the same-size topologies the skeleton removed
against the recommended model and names the ones that reproduce it exactly. It is opt-in
because it costs about as much as the search. On every reference measured so far the answer has
the same shape — a CPE standing in for an ideal element — which is a useful thing to be told:
what a skeleton really commits you to is an *ideal* capacitor or inductor where a distributed
one fits the same points.

**Data validation is not optional.** A spectrum that drifted during the sweep will still fit a
circuit, and will still report small error bars. The Lin-KK pre-check exists to catch that
before the numbers are believed.

**DRT tells you about the sample, not about the search.** `autocircuit drt` inverts a spectrum
into a distribution of relaxation times: how many distinct relaxations there are, how much
polarisation each carries, and whether any is broader than an ideal Debye peak — which is the
signature of a distributed process and the reason to reach for a CPE. It is deliberately kept
out of `discover`: using it to narrow the search would save a fraction of a percent of the work
and would forfeit the coverage statement above. `discover` prints it beside the report, as a
second opinion, and `--no-drt` turns that off. When the data is not a sum of relaxations at all
— a capacitor with skin effect, say — DRT says so instead of reporting a count.

See `docs/IMPLEMENTATION_PLAN.md` for the design and the literature it is based on.

## In the browser

<https://toshihiroiguchi.github.io/AutoCircuit/> runs this package unchanged, on a CPython
compiled to WebAssembly that starts inside the page. There is no server and there will not be
one, so nothing you open is uploaded anywhere; the four screens are Data (read a file, see the Kramers-Kronig verdict), Fit
(draw a circuit, fit it), Discover (run the topology search, with progress and a stop button) and
Report (download the results).

The point of running the real package rather than a re-implementation is that the two cannot
drift: the browser's Lin-KK verdicts match the CLI's, its fits match to every reported digit, its
search returns the same Pareto front row for row, and every file it downloads is written by the
same Python function `autocircuit fit --json`, `--spice` and `discover --json` use. Example
spectra are built into the site, so there is something to try without a measurement of your own.

One honest number: a first visit has to fetch and start a Python runtime, and that is 41 MB.
Measured from the public URL on the development machine, a cold visit reached a usable page in
21 s, and a later one with the runtime cached in 5–11 s — that spread is the machine's own load,
not the network. After that a fit takes a second or two, as it does on the command line. See
`web/README.md` to build or serve it yourself.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests -q       # full suite
python -m pytest tests -q -k "not fit and not discover"   # fast subset
python -m ruff check .          # lint
python -m mypy                  # types
```
