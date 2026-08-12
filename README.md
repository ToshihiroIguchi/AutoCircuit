# AutoCircuit

Equivalent circuit analysis of passive-component frequency characteristics — **without
user-supplied initial values**.

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
the same code to run in a browser under Pyodide later.

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

chi^2 (reduced) : 9.07659e-05
AICc            : -1316.28
RMS relative |Z| error : 1.3234%

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

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests -q       # full suite
python -m pytest tests -q -k "not fit and not discover"   # fast subset
python -m ruff check .          # lint
python -m mypy                  # types
```
