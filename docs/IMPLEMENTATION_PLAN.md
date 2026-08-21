# AutoCircuit — Implementation Plan

Status: v2 (2026-08-08). Phases 0-5 are implemented; phase 6 (web UI) has its worker-boundary
transport built (§10) and no UI yet.
Sections marked **[measured]** record results from the code as it exists, not intentions.
Update this document whenever a decision changes.

## 1. Goal

Analyze measured frequency characteristics (impedance spectra) of passive components and
produce equivalent circuit models, in two modes:

1. **Manual topology, automatic parameters** — the user specifies the circuit; all parameters
   are fitted **without user-supplied initial values**. ZView requires human initial guesses,
   which makes results depend on analyst skill; AutoCircuit removes that dependency with
   modern global optimization.
2. **Fully automatic** — both topology and parameters are discovered by an evolutionary
   search over a circuit grammar (symbolic-regression-style, see §6).

Primary early use cases:
- Capacitor spectra: extract C, ESR, ESL; handle √f ESR rise from skin effect.
- Sintered ceramics: Maxwell-Wagner / brick-layer behavior (grain, grain boundary, electrode).
- General passive components (inductors, ferrite beads, resistors, filters) thereafter.

Deliverables in order: core library → CLI → static-site Web UI (WASM).

## 2. Decisions

| # | Decision | Choice | Notes |
|---|----------|--------|-------|
| D1 | Core language | **Python 3.12+ (numpy/scipy)**, Web via **Pyodide** | User did not object to the recommendation. Core stays Pyodide-compatible; hot spots can move to Rust later if browser search speed becomes a real problem. The floor was 3.11 until it was raised to match what is actually verified: mypy has to run as 3.12 because numpy's bundled stubs use 3.12 syntax, so nothing ever checked 3.11 and nothing ran it either. |
| D2 | UI language | **English only** | Consistent with the "everything except conversation is English" rule. Revisit if a Japanese audience becomes a target. |
| D3 | Test data | **Synthetic + public data** | User has no measurement files at hand. Synthetic round-trips are the backbone; vendor-published Touchstone/SPICE data (Murata, TDK) used as realistic smoke tests. |
| D4 | CLI framework | **`argparse` (stdlib)** | Changed from `typer` during implementation: keeping numpy+scipy as the *only* runtime dependencies is what makes the Pyodide target painless, and the CLI is simple enough that a framework earns nothing. |
| D5 | Web frontend | Vite + TypeScript + React, Pyodide in a Web Worker | See §9. |
| D6 | Packaging | `uv`, `src/` layout, wheel consumed by Pyodide unchanged | |

## 3. Research conclusions (requested investigations)

### 3.1 Skin effect — can it be analyzed, and should it be built in?

**Conclusion: yes to both.** The physics and the modeling techniques are well established.

- Skin depth scales as f^(-1/2), so above the crossover the series resistance of electrodes,
  leads, and windings rises ∝ √f while the internal inductance falls. For capacitors, vendor
  literature (Murata, AIC tech) confirms ESR at high frequency is dominated by skin/proximity
  effect, while low-frequency ESR is dielectric loss + ohmic terms.
- Classic circuit treatments approximate this with **RL ladder networks**: Kim & Neikirk,
  "Compact equivalent circuit model for the skin effect" (IEEE MTT-S 1996) give a 4-rung
  ladder with simple element-value rules, accurate far past the skin-depth crossover; later
  "dynamic equivalent network" work (concentric-tube decomposition with mutual inductances)
  refines this for time-domain simulators.
- **Key insight for AutoCircuit:** ladders are only needed when the simulator requires
  frequency-independent R/L (i.e., SPICE time domain). Our fitter evaluates Z(ω) numerically,
  so we can implement skin effect **exactly** in the frequency domain:
  - `SKINF` — phenomenological fractional element: Z = A·(jω)^n with n ≈ 0.5 (a CPE used in
    the inductive/resistive sense). Cheap, robust, covers most fitting needs.
  - `SKINW` — exact round-wire internal impedance via the Bessel-function form
    Z_int(ω) = k·√(jωμσ)·J₀(√(-jωμσ)·a) / J₁(...) parameterized as (R_dc, τ); scipy's complex
    Bessel functions make this direct.
- For **SPICE export**, synthesize an RL ladder (Kim–Neikirk-style, rung count chosen from the
  fitted band) that matches the fitted element over the measured frequency range (§7).

### 3.2 Automatic topology discovery — is a PySR-like approach valid?

**Conclusion: the concept is valid and has published precedent; do not reuse PySR itself.**

- Prior art exists and works: **EquivalentCircuits.jl** (gene expression programming over
  circuit configurations, GitHub: MaximeVH), the underlying method published as "Practical
  equivalent electrical circuit identification for EIS analysis with gene expression
  programming" (IEEE T-IM 2021), and **AutoEIS** ("Automated Bayesian model selection and
  analysis for EIS", J. Electrochem. Soc. 2023; JOSS 2024), which layers Kramers-Kronig data
  validation, physics-based post-filtering, and Bayesian parameter inference on top of the
  evolutionary search. An older GA paper (2003, "An evolutionary approach for modeling the
  equivalent circuit for EIS") established feasibility two decades ago.
- PySR itself is not directly reusable: it evolves scalar math expression trees, needs a Julia
  backend (won't run in WASM), and its operator grammar does not map to two-terminal networks.
  What **does** transfer from PySR is the search design: regularized evolution over a typed
  grammar, an **accuracy-vs-complexity Pareto front** instead of a single answer, and model
  selection by a parsimony score. Equivalent circuits are famously degenerate (different
  topologies fit equally well), so returning a Pareto front + fit statistics and letting the
  user choose is the honest UX.
- Our design (§6): custom GP over a series/parallel circuit grammar with per-candidate global
  fitting, complexity = element count + per-type cost, AICc-based ranking, AutoEIS-style
  post-filters (remove redundant elements, merge series R's, etc.).
- **[measured] The degeneracy is worse than "several models fit well" — some are literally the
  same model.** `R1-p(R2,C1)` and `p(R1,C1-R2)` fit identical data to 1.2e-15 relative error:
  they are algebraic reparameterisations, not merely similar. Any honest automatic tool must
  detect this rather than report one of them as *the* answer, which is why §6 grew an
  equivalence-class step that no published tool in the list above provides.

### 3.3 Maxwell-Wagner (sintered ceramics)

Standard treatment is the **brick-layer model**: series chain of parallel R‖C (or R‖CPE)
blocks for grain interior, grain boundary, and electrode interface. This needs no special
element — it falls out of the grammar (`R0-p(R1,C1)-p(R2,C2)…`) — but we will ship it as a
**named circuit template** with dielectric-oriented reporting (per-block relaxation frequency,
permittivity if geometry is given, tan δ). Optional Cole-Cole / Havriliak-Negami distributed
elements (§4) cover non-Debye broadening.

### 3.4 SPICE export of fractional elements

CPE, Warburg, Gerischer, and skin-effect elements have no native SPICE primitive. Established
solution: **RC (or RL) ladder approximation** — Valsa & Vlach, "RC models of a constant phase
element" (Int. J. Circuit Theory Appl. 2013) give a passive RC ladder with corrective elements
accurate over a chosen band; follow-ups (Athanasiou 2018 for Warburg; "Simple circuit
equivalents for the CPE", 2021) confirm the approach. We generate ladders valid over the
measured band and annotate the `.subckt` with the validity range.

## 4. Element library

Interface (core abstraction):

```python
class Element(Protocol):
    code: str                      # e.g. "R", "CPE", "Ws"
    params: tuple[ParamSpec, ...]  # name, unit, default bounds, log_scale: bool
    def impedance(self, omega: NDArray[f8], values: NDArray[f8]) -> NDArray[c16]: ...
    def spice_synthesis(self, values, band) -> Subckt | None  # None => native primitive
```

ZView-equivalent set plus extensions:

| Code | Element | Z(ω) | Params |
|------|---------|------|--------|
| R | Resistor | R | R |
| C | Capacitor | 1/(jωC) | C |
| L | Inductor | jωL | L |
| CPE | Constant phase element | 1/(Q·(jω)^n) | Q, n |
| W | Warburg (semi-infinite) | σ·(jω)^(-1/2)·(1-j)·… | σ |
| Ws | Warburg, finite-length short (transmissive) | R·tanh(√(jωτ))/√(jωτ) | R, τ |
| Wo | Warburg, finite-length open (reflective) | R·coth(√(jωτ))/√(jωτ) | R, τ |
| G | Gerischer | R/√(1+jωτ) | R, τ |
| Ls | Inductor with loss (L + series R lumped) | convenience composite | L, R |
| DX-CC | Cole-Cole dielectric relaxation | ΔZ/(1+(jωτ)^α) form | R, τ, α |
| DX-HN | Havriliak-Negami | R/(1+(jωτ)^α)^β | R, τ, α, β |
| SKINF | Fractional skin-effect element | A·(jω)^n (n≈0.5) | A, n |
| SKINW | Round-wire skin effect (exact, Bessel) | Z_int(R_dc, τ_s) | R_dc, τ_s |

Notes:
- Element codes in the DSL are `CC` and `HN` (not `DX-CC`), because `-` is the series operator.
- The `Ls` convenience composite from the original draft was dropped: `R-L` already expresses
  it, and having both would add a degenerate branch to the topology search for no gain.
- Remaining ZView DX variants (generalized finite Warburg etc.) are added on demand — the
  interface makes each one ~30 lines + tests.
- Every param gets physically-motivated **default bounds derived from the data** (§5.2), and a
  `log_scale` flag (almost all are log-scale).
- **[measured]** `SKINW` switches from the Bessel evaluation to a Hankel asymptotic expansion
  at |q| = 1e5. The expansion must be carried to three terms,
  `J0/J1 = j + 1/(2q) - 3j/(8q²) + O(q⁻³)`; the series converges as 1/|q|, **not**
  exponentially, so the leading term alone left a 0.17% discontinuity at the switch. Verified
  against `scipy.special.jve` to 1e-13 relative; regression-tested at both the old and the
  current switch point.
- **[measured]** Every element is **broadcast-safe**: `impedance()` accepts a batch of
  parameter sets and evaluates the whole optimizer population in one call. This roughly
  tripled topology-search throughput (87 → 291 topologies in the same 136 s) and is verified
  bit-exact against per-candidate evaluation for all twelve elements.

**Circuit representation:** expression tree with `series(...)` / `parallel(...)` nodes and a
canonical string DSL, e.g. `R1-L1-p(R2,C1)-p(CPE1,R3)` (impedance.py-style; a Boukamp CDC
importer can come later). JSON schema for tooling/Web. Canonicalization (sort commutative
children, merge nested series/parallel) enables duplicate detection during topology search.

## 5. Fitting engine (no initial values)

### 5.1 Objective

Complex nonlinear least squares on stacked (Re, Im) residuals with selectable weighting:
`unit`, `modulus` (1/|Z|, default — ZView's "calc-modulus" equivalent), `proportional`
(1/Re², 1/Im²). Optionally fit in log|Z|/phase space for spectra spanning many decades
(capacitor |Z| spans 5+ decades; this matters).

### 5.2 Making initial values unnecessary

1. **Log-parameter transform**: fit x = log10(p) for all log-scale params → scale-invariant
   search space, positivity for free.
2. **Data-driven bounds**: e.g. C bounded via |Z| at lowest/highest measured ω, R by |Z|
   extremes, L by high-frequency slope, τ by measured ω range extended ±2 decades. Bounds are
   per-element heuristics attached to `ParamSpec`.
3. **Global stage**: `scipy.optimize.differential_evolution` (rand-to-best, seeded, vectorized
   objective) over the bounded log-space. Fallback/alternative: CMA-ES via `cma` (optional
   extra, not in the Pyodide build initially).
4. **Polish stage**: `scipy.optimize.least_squares` (TRF, analytic-free jacobian first;
   analytic jacobians per element later if profiling demands).
5. **Multi-start**: N restarts of the global stage with different seeds; report dispersion —
   if restarts disagree, the model is unidentifiable and we say so.

**[measured]** Defaults chosen by sweeping the hardest 6-parameter case (`R1-p(R2,C1)-p(R3,CPE1)`,
1% noise, 25 noise realisations):

| restarts | popsize | failures | mean time |
|----------|---------|----------|-----------|
| 3 | 20 | 1/25 | 1.8 s |
| **5** | **20** | **0/25** | **2.8 s** |
| 8 | 20 | 0/25 | 5.8 s |
| 3 | 40 | 3/25 | 4.4 s |

Hence the default `restarts=5, popsize=20`. A larger population is *worse* per unit time.
Failed restarts are not silent: a run that lands in a local minimum shows a chi² an order of
magnitude worse, which is what the restart comparison detects.

### 5.3 Statistics and validation

- Covariance from the polish-stage Jacobian → per-parameter σ and correlation matrix; flag
  |corr| > 0.99 as "parameters not independently identifiable".
- **[measured]** The covariance **must** be formed in the log search space and only then
  mapped to parameter units. Computing it in parameter space gives a Gauss-Newton Hessian
  with condition number ~1e20 for a circuit spanning 1e-10 F and 1e5 Ω; its pseudo-inverse
  collapses to near rank one and reports a spurious ±1.0000 correlation between *every* pair
  of parameters. Correlations are invariant under the diagonal map `p = 10^x`, so only the
  standard errors need rescaling by `dp/dx = p ln 10`.
- Rank of the Jacobian is reported; `rank < n_params` means structural over-parameterisation.
- χ², weighted residual plots, AICc (drives model comparison in auto mode).
- **[measured]** Reported standard errors are calibrated: over 25 noise realisations of each
  of four models — capacitor with skin effect, brick layer with CPE, a four-block Voigt ladder
  (eight parameters) and a Butterworth-Van Dyke resonator — the z-scores have mean within
  ±0.55, standard deviation 0.72–1.34 and 88–100% coverage inside ±2σ. Re-measured 2026-08-22;
  the wider band is partly the two added models and partly the original pair reading 88%
  coverage at its lowest where this line previously said 92%. See `benchmarks/README.md`.
- Branch order is canonicalised after fitting. `p(R1,C1)-p(R2,C2)` is unchanged by swapping
  its two blocks, so without this the optimizer returns either assignment at random, repeated
  runs look like they disagree, and the uniqueness check fires spuriously.
- **Lin-KK** data validation (Schönleber/Ivers-Tiffée 2014 linear Kramers-Kronig test) as a
  standalone `validate` command and as an automatic pre-flight warning before fitting.
  - **[measured]** The linear solve needs column scaling. The series-capacitance column scales
    as 1/ω and the series-inductance column as ω, so over eight decades they differ by ~1e16
    and `lstsq` truncates the solution to nonsense — a *series RLC*, which is exactly
    representable in the Lin-KK basis, came out with 6.9% residual instead of zero.
  - **[measured]** Pass/fail cannot be a fixed residual threshold, because 1%-noise data
    legitimately produces ~2.7% peak residuals. The decision is instead based on whether the
    residuals are *systematic*: a Wald-Wolfowitz runs test on the residual signs. Noise
    changes sign about half the time; a KK violation is smooth in frequency and does not.
    Measured: clean data runs z ≈ 0 (pass), 30% drift gives runs z = −7.9 (fail).
  - **[measured]** A failed test is not automatically a verdict about the data. The Voigt
    basis has only real poles, so a *resonance* is unreachable by it: on a Butterworth-Van
    Dyke spectrum, which is KK-compliant by construction, the residual is 96.8% of |Z| at
    every order from M = 3 to M = 317. A genuine violation looks nothing like that — 40%
    drift is tracked to 1.8% RMS and improves 11.5× with model order, against 1.24× here. So
    above `validate.MODEL_FAILURE_RMS` (25% RMS) the report says the test could not be applied
    and names both possible causes rather than asserting drift. `passed` is unchanged: a test
    that could not be applied is not a pass.

## 6. Automatic topology discovery

Genetic programming over the circuit grammar:

- **Genome**: the circuit expression tree (§4). Mutations: replace element type, insert
  element in series/parallel, delete node, subtree swap (crossover).
- **Element pool**: user-selectable subset (default: R, C, L, CPE, Ws, Wo, G; SKINF for
  component work). Restricting the pool is the main physics prior.
- **Fitness**: AICc from a *budget-limited* fit (small DE population + polish) — full-rigor
  fitting only for surviving candidates. Complexity = Σ per-element cost (CPE costs more
  than R, discouraging "CPE fixes everything").
- **Selection**: regularized evolution (age-based) with island populations; deduplicate via
  canonical form; cache fitted results keyed by canonical string.
- **Output**: Pareto front (complexity vs. fit quality) + per-candidate statistics, never a
  single "the answer". AutoEIS-style post-filters prune unphysical/redundant candidates
  (series R merging, nested parallel simplification, dangling elements).
- **[measured] The headline candidate is chosen by parsimony, not by AICc.** Reporting the
  minimum-AICc model turned out to be actively misleading: on a 71-point capacitor spectrum it
  selected a nine-parameter circuit with two parameters whose standard errors exceeded their
  own values, over a six-parameter circuit fitting within a factor 1.6 in chi². AICc's
  parameter penalty is simply small next to the residual gain available from fitting noise.
  `DiscoveryResult.recommended` therefore returns the structurally simplest Pareto candidate
  that (a) fits within a factor 2 of the best chi² seen and (b) has every parameter resolved
  by the data, and the report states plainly when that differs from the lowest-AICc model and
  why.
- Parallelism: `multiprocessing` on CLI; sequential (or small worker pool) under Pyodide —
  budget knobs (`--generations`, `--population`, `--time-limit`) keep browser runs sane.

**[measured] Equivalence classes — an addition, not in the original draft.** Distinct
topologies are frequently *exact reparameterisations* of one another. `R1-p(R2,C1)` and
`p(R1,C1-R2)` both describe precisely the set of single Nyquist semicircles; fitted to the
same data they agree to 1.2e-15 relative. No impedance measurement can prefer one, so
presenting whichever the search reached first would be misleading. `DiscoveryResult` therefore
groups candidates whose fitted responses agree to better than 1e-6 everywhere and reports them
as indistinguishable. This is the honest form of the degeneracy caveat, and it turns what
would look like a search failure into information.

**[measured] Current capability of the genetic search.** On synthetic data it recovers the true
topology (or an exact equivalent) onto the Pareto front for capacitor models and
single-relaxation models. For multi-relaxation electrochemical spectra (two Maxwell-Wagner
blocks, Randles) it reliably finds topologies that fit *as well as* the truth at the same or
lower complexity, but does not consistently surface the textbook form within a two-minute
budget — it evaluated only 113–257 topologies in that time.

### 6.1 Discovery v2 — exhaustive first (implemented; see `docs/DISCOVERY_V2_PLAN.md`)

That coverage problem is what the redesign fixes, and it fixes it by not searching at all.
`core/enumerate.py` produces every distinct plausible topology for a pool and element count;
`discover(mode="exhaustive")` fits all of them in two tiers — a cheap screen for everything,
the full budget for the shortlist and for every near-tie. The default `mode="auto"` runs that
first and only falls back to the genetic search if the residuals of the best model still look
systematic under a runs test.

- **[measured] The space is small enough to enumerate**: 2 to 11,550 distinct topologies at
  ≤ 5 elements depending on the pool (`benchmarks/README.md`), enumerated in under a second.
- **[measured] The structural feasibility filter is a minor lever, not a major one.** It
  removes 43% of the capacitor sweep and 13–15% of the electrochemical ones — well below the
  2–5× the plan expected, because a conservative filter has to allow for corner frequencies
  falling outside the measured window. It costs ~0.3 s, so it stays; the real lever is
  `--workers`.
- What this buys that no amount of GP tuning could: `DiscoveryResult.complete_up_to`, and with
  it a report that can say *"every plausible topology with up to N elements was evaluated"*.
  Absence from the report becomes evidence.

### 6.1.1 Skeleton-constrained discovery (implemented; see `docs/PARTIAL_TOPOLOGY_PLAN.md`)

The middle of the same axis, not a new one: `fit` fixes the whole topology, `discover` fixes
none of it, and `discover(skeleton=...)` fixes the part the user actually knows — a
capacitor's ESR and ESL, a cell's electrolyte resistance. The search grows the skeleton
outwards; containment is *deletion-and-collapse*, not subtree matching, because `series()` and
`parallel()` flatten, so `R1-C1` is not a subtree of `R1-C1-p(R2,L1)`.

- **[measured] It is the largest lever in the system.** At five elements from the component
  pool: 10,214 candidates unconstrained, 6,711 with `R1`, 2,631 with `R1-L1`, 601 with
  `C1-R1-L1`, 71 with `C1-R1-L1-SKINF1`. Against 1.15–1.75× for the feasibility filter. It is
  also the first thing that makes six elements affordable while still claiming completeness.
- **[measured] One or two added elements is the practical range, and that is the interesting
  range anyway.** Each level costs 40–70× the last: from a ten-element skeleton, +1 is 167
  candidates, +2 is 11,418, +3 is 521,438, +5 is ~10⁹. "I have ten elements, add five" has no
  answer, twice over — the enumeration, and well before it a model with more parameters than
  the data can resolve.
- **A constraint narrows what the report may claim, and that is not optional.**
  `complete_up_to`'s sentence names the skeleton; placement ambiguity is reported rather than
  resolved; a front on which nothing is identifiable is stated as a finding about the
  measurement. §3 of the plan is the part to read before changing any of it.

### 6.2 Structure probing — DRT (`core/drt.py`, `autocircuit drt`)

A separate question from "what circuit?": *how many relaxations does this sample show, and is
any of them distributed?* Fixing the time constants on a log grid makes the Debye expansion
linear, so a regularised least-squares solve answers it with no initial values — the Lin-KK
machinery of §5 plus a smoothness prior. λ comes from generalised cross-validation on the
unconstrained problem, where GCV is valid; the reported distribution is then recomputed under
`γ ≥ 0`, because letting the inversion oscillate through zero invents peaks and the peak
*count* is the output.

- **[measured] It is a standalone analysis, not a search prior.** The plan had it raising the
  enumeration floor. That removes 0.1–0.4% of the filtered topology space, which is
  concentrated in its largest level, and costs `complete_up_to` — a bad trade, and a worse one
  once a mis-counted peak can delete the right answer from a search still claiming to be
  exhaustive. `core/discover.py` does not import `core/drt.py`.
- **[measured] Gate G4 passes 10/10** for 1, 2 and 3 relaxations at 0% and 1% noise, recovering
  peak positions within 0.026 decades and weights within 1.4%.
- **[measured] A relaxation is detected against the noise, not against the largest peak.** The
  obvious threshold rejects the smaller block of a two-block Maxwell-Wagner sample, which
  carries 2% of the total polarisation — the exact case the feature exists for. See
  `docs/DISCOVERY_V2_PLAN.md` §5.2.
- **[measured] It reports when it does not apply.** No sum of capacitive RC relaxations can
  represent a distributed inductive process, so on a capacitor with skin effect the inversion
  returns no peaks, a 7×-wrong series resistance and a 64% residual. `well_described` says so
  and the CLI exits non-zero, rather than presenting "0 relaxations" as a finding.

## 7. SPICE export

- `autocircuit fit ... --spice model.cir` → `.subckt` netlist with two terminals.
- R/C/L map to primitives. CPE/W/Ws/Wo/G/CC/HN/SKIN* → **ladder synthesis**.
- **[measured] One general solver instead of one recipe per element.** Both ladder families are
  linear in their resistances once the time constants are fixed on a logarithmic grid:
  - RC (capacitive) Foster form: `Z = R0 + 1/(jwC0) + Σ R_k/(1 + jw τ_k)`
  - RL (inductive) Foster form: `Z = R0 + jwL0 + Σ R_k·(jw τ_k)/(1 + jw τ_k)`

  so the section values come from a **non-negative least squares** solve against the exact
  element impedance. Non-negativity is what guarantees the network is passive and therefore
  simulable. Each element declares only which of the two forms it belongs to (`spice_form`),
  so a new element gets SPICE export for free. Section count is raised until a 1% error target
  is met; the band and achieved error are written into the netlist comments.
- **[measured]** All ten fractional-element cases reach <1% error over seven decades
  (100 Hz – 1 GHz) with 3–19 sections.
- **[measured] Verification is of the netlist, not the formula.** The test suite contains a
  minimal nodal-analysis AC engine that parses the emitted `.subckt` and solves it, exactly as
  a SPICE AC sweep would. Pure R/C/L circuits — including nested cases such as
  `p(R1,C1-p(R2,L1))-R3` — must reproduce the model to 1e-9; circuits with fractional elements
  to within the synthesis tolerance. This catches node-allocation bugs, which a formula-level
  test cannot.
- **[measured] And a real ngspice reads it the same way.** `tests/test_spice_ngspice.py` exports
  nine circuits, simulates each with ngspice 42 and compares against *that same nodal engine*
  rather than against the model — which is the point: comparing against the model leaves the
  ladder error at ~1e-2, three orders of magnitude above any dialect fault it would be hiding.
  Agreement is **exactly zero for a lone resistor and 4.6e-15 to 4.5e-12 for the other eight**,
  the four ladder-synthesised elements included, so the netlist is dialect-right as well as
  electrically right. Two things the simulator said that nothing else could:
  - **A model beginning with a capacitor is a DC open, and ngspice's operating point fails on
    it** — singular matrix, gmin stepping failed, source stepping failed — **while still exiting
    0** and still computing the right AC answer, because an AC analysis of a linear network does
    not depend on the operating point. A round-trip gated on the return code would have called
    that a pass; this one asserts on the diagnostics. The netlist header now tells the user, and
    gives the deck that drives it.
  - **`.option rshunt=1e12` silences those diagnostics and costs up to 7e-7 in |Z|** — worse than
    the quantity being measured, and not simply |Z|/R because the ladder's internal nodes are
    shunted too. So the test deck adds nothing to help the simulator.

## 8. Data I/O

| Priority | Format | Notes |
|----------|--------|-------|
| P0 | Generic CSV/TSV (f, Re Z, Im Z / f, |Z|, θ) | Column-mapping heuristics + explicit override flags |
| P0 | ZView `.z` / ZPlot text | Covers Solartron workflows (1260/1287 exported via ZPlot) |
| P0 | Touchstone `.s1p`/`.s2p` | Vendor capacitor data (Murata/TDK); S→Z with port config: series-thru / shunt-thru (low-ESR caps need shunt-thru math) |
| P1 | Keysight/Agilent CSV (E4990A, 4294A state dumps) | Header-sniffing reader |
| P1 | Gamry `.DTA`, BioLogic `.mpt` | Common in electrochemistry; cheap to add |
| P2 | Solartron MTData / other binaries | Only if real files surface |

Single entry point `autocircuit.io.read(path, **hints)` with format sniffing; all readers
return a common `Spectrum` (f [Hz], Z [complex], metadata). Export: CSV and ZView-compatible
`.z` so results can be cross-checked in ZView.

## 9. Web application (after CLI is solid)

> Superseded in detail by **`docs/WEB_UI_PLAN.md`** (step 1 built; steps 2–6 await approval),
> which is built on the measurements below rather than on the estimates this section originally
> carried.

- **Static site** (deployable on GitHub Pages): Vite + TypeScript + React; the Python core
  wheel runs in **Pyodide inside a Web Worker** (UI never blocks; progress messages stream
  from the worker). No server.
- Layout (ZView's workflow, modern execution): left rail = data sets + import; center =
  linked Nyquist / Bode(|Z|, θ) / residual plots (zoom-synced, log axes); right = **circuit
  canvas** — drag-drop series/parallel block editor that reads like a schematic, with live
  model preview overlaid on the data before/without fitting.
- Auto-discovery view: Pareto front (complexity vs. AICc) scatter; clicking a point loads
  that circuit + parameters into the canvas.
- Extras: fit report export (JSON/CSV/netlist download), dark/light theme, example datasets
  bundled. Plotting: Plotly.js initially (fast to ship), replaceable.
- Risk controls: Pyodide initial load (~15 MB) mitigated by lazy load + cache + a visible
  loading stage.

**[measured] The WASM performance risk is much smaller than this section assumed**
(`benchmarks/pyodide/`, the same `bench.py` run under CPython and under Pyodide 314 / Python
3.14, both single-threaded):

| operation | CPython | Pyodide | ratio |
|-----------|--------:|--------:|------:|
| `fit`, 6 parameters | 0.704 s | 0.906 s | 1.3× |
| `screen`, 4 elements | 32.2 ms | 45.1 ms | 1.4× |
| enumerate + feasibility, n ≤ 5 | 0.200 s | 0.316 s | 1.6× |
| `import autocircuit` | 0.40 s | 1.58 s | 3.9× |
| `discover`, component pool, n ≤ 4 | 127.5 s | 169.1 s | 1.33× |

The penalty on numerical work is 1.3–1.8×, because the cost sits in numpy and scipy compiled to
WASM rather than in interpreted Python; only interpreter-bound paths pay ~4×, and that is a
one-off 1.6 s import. Consequences, all now measured rather than guessed:

- **Neither fallback in the old risk line is needed.** No reduced web budget — and cutting the
  screening budget is separately known to lose the answer (§6.1). No Rust/WASM port of the
  inner loop; `fit_budget()` stays put.
- **Cold start to the first fit is ~4 s** (1.2 s boot + 1.1 s cached numpy/scipy + 1.6 s
  import), so the loading stage is a UI state, not an architectural problem.
- **`exhaustive_limit=4` is the web default and costs 2.8 min single-threaded**, or a measured
  2.0 min across four Pyodide workers. A browser has no `multiprocessing`, so `--workers` has no
  analogue there — Web Workers are, and both tiers of the search now fan out across them
  (`docs/WEB_UI_PLAN.md` §2.2). Either way progress streaming through the existing `on_progress`
  callback is mandatory, not decorative.
- **`exhaustive_limit=5` stays an explicit opt-in** at roughly half an hour.

## 10. Milestones

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 0 | Repo scaffold | **done** — `pyproject.toml`, src layout, pytest config. `uv` was not available on the dev machine; the project installs with plain `pip install -e .`. |
| 1 | Core: elements + circuit AST + DSL parser + synthetic generator | **done** — 12 elements, all analytically tested; batched evaluation |
| 2 | Fitting engine | **done** — recovers a 9-circuit synthetic suite at 0% and 1% noise with no initial values; calibrated uncertainties; Lin-KK |
| 3 | CLI | **done** — `fit`, `discover`, `validate`, `simulate`, `convert`, `elements` |
| 4 | SPICE export | **done** — NNLS Foster-form ladder synthesis; netlist verified by nodal analysis and, in CI, by a real ngspice (agreement 5e-15 .. 4.5e-12 over nine circuits). |
| 5 | Topology discovery | **done** — genetic search, then the exhaustive-first redesign of §6.1, all seven steps of `docs/DISCOVERY_V2_PLAN.md` including DRT structure probing (§6.2) |
| 6 | Web UI | **done** — all seven steps of `docs/WEB_UI_PLAN.md`; the site is live at <https://toshihiroiguchi.github.io/AutoCircuit/>. Gates W1, W2, W4 and W6 pass, W3 passes on a rested machine and not on a loaded one, W5 is retired. |

Test corpus actually used: series/parallel RC, capacitor C+ESR+ESL, capacitor with `SKINF`,
Randles with Warburg, two-block Maxwell-Wagner, three-block brick layer with CPE, depressed
semicircle, and a wire with `SKINW` — each at 0% and 1% noise.

### 10.1 Next steps

1. ~~**Web UI (phase 6)**~~ — done; see the table above and `docs/HANDOFF.md` §8–§14.
2. ~~**ngspice round-trip in CI**~~ — done; see §7 and `docs/HANDOFF.md` §15.
3. ~~**Performance for the browser**~~ — measured (§9 above), and the cold start was attacked in
   web-UI step 7. What is left there is the wheel install (2.2–4.4 s) and the 41 MB transfer.
4. **More readers** — Gamry `.DTA`, BioLogic `.mpt` (P1 in §8) once real files are available.

## 11. References

- Kim & Neikirk, *Compact equivalent circuit model for the skin effect*, IEEE MTT-S 1996 — https://www.weewave.mer.utexas.edu/MED_files/MED_research/Intrcncts/Skin_Effect_Ldr/MTT_96_skn_ldr.html
- *A dynamic equivalent network model of the skin effect* — https://www.researchgate.net/publication/260737981
- Murata, *Impedance/ESR frequency characteristics in capacitors* — https://article.murata.com/en-us/article/impedance-esr-frequency-characteristics-in-capacitors
- AIC tech, *Capacitor impedance: ESR, ESL, reactance* — https://www.aictech-inc.com/en/valuable-articles/capacitor_foundation04.html
- AutoEIS (J. Electrochem. Soc. 2023) — https://iopscience.iop.org/article/10.1149/1945-7111/aceab2 ; JOSS paper — https://joss.theoj.org/papers/10.21105/joss.06256 ; code — https://github.com/AUTODIAL/AutoEIS
- EquivalentCircuits.jl — https://github.com/MaximeVH/EquivalentCircuits.jl
- Van Haeverbeke et al., *Practical equivalent circuit identification with GEP*, IEEE T-IM 2021 — https://ieeexplore.ieee.org/document/9539171/
- Valsa & Vlach, *RC models of a constant phase element*, IJCTA 2013 — https://onlinelibrary.wiley.com/doi/full/10.1002/cta.785
- Athanasiou et al., *Efficient simulation of circuits with CPEs: Warburg as a test case*, IJCTA 2018 — https://onlinelibrary.wiley.com/doi/10.1002/cta.2474
- *Simple circuit equivalents for the constant phase element* — https://pmc.ncbi.nlm.nih.gov/articles/PMC7997031/
