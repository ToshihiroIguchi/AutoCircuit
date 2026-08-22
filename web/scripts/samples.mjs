// The example datasets for the web UI, every one of them a spectrum the project already
// measures itself against.
//
// Two groups, and the split is the same one `benchmarks/fitting.py` makes half way down its SUITE.
// The **shapes** are cases chosen for a feature of the impedance -- a relaxation, a resonance, a
// ladder -- and the first three of them are also the reference spectra every discovery gate is
// measured against (`benchmarks/discovery_v2.py`, REFERENCES). The **devices** are the equivalent
// circuits actually used to fit a named real part: a lithium-ion cell, a polymer capacitor, a
// ferrite bead, a coated panel, a fuel-cell cathode, tissue, a dielectric, a thin-layer cell.
//
// Circuit, params, frequency limits, sweep density and noise are taken from those benchmark lists
// verbatim; they are not retyped, so a change to a benchmark ground truth cannot silently drift
// out of sync with what the site ships. Every one of them is *synthetic*, and the panel says so
// beside each row along with the command that made it.
//
// `skeleton` is the one field with no source in either benchmark: it is a mode-2 claim about what
// a user of that kind of sample would already know, and each one below has been checked with
// `contains_skeleton` to be a skeleton the circuit really contains.
//
// `source` is `<list>:<label>` -- which benchmark entry this row is a copy of -- and it is what
// makes the paragraph above true rather than merely intended. `scripts/samples-check.mjs` walks the
// Python lists and compares every field against it, and `npm run check` runs it, so an example that
// has drifted from the case it names cannot be published. Before that script the values here were
// retyped beside a Python list nothing compared them against.
//
// `group` orders and heads the list in the UI. It is not a property of the data.
const SAMPLES = [
  {
    id: "capacitor",
    source: "discovery:capacitor (C-R-L + skin effect)",
    group: "Shapes",
    label: "Capacitor (C-R-L + skin effect)",
    circuit: "C1-R1-L1-SKINF1",
    params: { "C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5 },
    fMin: 1e2,
    fMax: 1e9,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "C1-R1-L1",
    blurb:
      "A real capacitor over seven decades: the capacitance itself, its series ESR and ESL, " +
      "and a conductor skin effect that only shows up at the high-frequency end.",
  },
  {
    id: "maxwell-wagner",
    source: "discovery:Maxwell-Wagner (two blocks)",
    group: "Shapes",
    label: "Maxwell-Wagner (two blocks)",
    circuit: "p(R1,C1)-p(R2,C2)",
    params: { "R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8 },
    fMin: 1e-1,
    fMax: 1e7,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "p(R1,C1)",
    blurb:
      "Two interfacial relaxations in series. The topology has three exact " +
      "reparameterisations, which a full-auto report groups into a single equivalence class " +
      "rather than picking one as \"the\" answer.",
  },
  {
    id: "randles",
    source: "discovery:Randles (with Warburg)",
    group: "Shapes",
    label: "Randles (with Warburg)",
    circuit: "R1-p(C1,R2-W1)",
    params: { "R1.R": 20.0, "C1.C": 1e-5, "R2.R": 200.0, "W1.A": 50.0 },
    fMin: 1e-2,
    fMax: 1e5,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "R1-p(C1,R2)",
    blurb:
      "An electrochemical cell with diffusion: the textbook Randles circuit, electrolyte " +
      "resistance plus a double layer with a Warburg element in its charge-transfer branch.",
  },
  {
    id: "voigt-ladder",
    source: "fitting:Voigt ladder, 4 blocks",
    group: "Shapes",
    label: "Voigt ladder (four RC blocks)",
    circuit: "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)",
    params: {
      "R1.R": 2e3, "C1.C": 5e-11,
      "R2.R": 3e3, "C2.C": 3e-9,
      "R3.R": 5e3, "C3.C": 2e-7,
      "R4.R": 8e3, "C4.C": 1e-5,
    },
    fMin: 1e-2,
    fMax: 1e7,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "p(R1,C1)-p(R2,C2)",
    blurb:
      "Four relaxations in series over nine decades -- the Voigt ladder a multi-phase ceramic " +
      "reduces to, and the largest example here at eight free parameters. Its time constants " +
      "are two decades apart, so every block is separately resolvable; the four blocks are " +
      "interchangeable, so their numbering carries no meaning.",
  },
  {
    id: "piezo-resonator",
    source: "fitting:piezo resonator (BVD)",
    group: "Shapes",
    label: "Piezoelectric resonator (BVD)",
    circuit: "p(C1,R1-L1-C2)",
    params: { "C1.C": 2e-9, "R1.R": 40.0, "L1.L": 3.2e-3, "C2.C": 2e-10 },
    fMin: 1.6e5,
    fMax: 2.6e5,
    pointsPerDecade: 1500,
    noise: 0.01,
    seed: 0,
    skeleton: "p(C1,L1-C2)",
    blurb:
      "A piezoelectric disc as the Butterworth-Van Dyke model: a clamped capacitance in " +
      "parallel with a motional R-L-C branch. The only resonant example here, and the only one " +
      "built from R, C and L alone. The sweep is narrow and dense on purpose -- a Q = 100 " +
      "resonance is about 1% of its frequency wide, so it is measured around fs rather than " +
      "over decades. The Lin-KK check reports no verdict on it: a Voigt series cannot express " +
      "an anti-resonance, so there is nothing it can say about data that is, by construction, " +
      "perfectly Kramers-Kronig consistent.",
  },
  {
    id: "li-ion-cell",
    source: "fitting:lithium-ion cell",
    group: "Devices",
    label: "Lithium-ion cell",
    circuit: "L1-R1-p(R2,CPE1)-p(CPE2,R3-Wo1)",
    params: {
      "L1.L": 3e-7,
      "R1.R": 0.03,
      "R2.R": 0.012,
      "CPE1.Q": 0.0273,
      "CPE1.n": 0.85,
      "CPE2.Q": 41.6,
      "CPE2.n": 0.8,
      "R3.R": 0.02,
      "Wo1.R": 0.05,
      "Wo1.tau": 30.0,
    },
    fMin: 1e-3,
    fMax: 1e5,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "L1-R1-p(R2,CPE1)",
    blurb:
      "The most-fitted equivalent circuit there is: cable inductance, the ohmic resistance, an " +
      "SEI arc, and a charge-transfer arc sharing its branch with solid-state diffusion into the " +
      "particle (a reflecting Warburg, so the low-frequency tail turns capacitive). Ten free " +
      "parameters over eight decades, the largest example here. Its two arcs are four decades " +
      "apart on purpose: at the 1.4 decades a room-temperature full cell really shows, the " +
      "SEI/charge-transfer split stops being identifiable and the fitter says so rather than " +
      "picking one.",
  },
  {
    id: "polymer-capacitor",
    source: "fitting:polymer capacitor",
    group: "Devices",
    label: "Polymer capacitor",
    circuit: "L1-R1-CPE1",
    params: { "L1.L": 1.5e-9, "R1.R": 8e-3, "CPE1.Q": 1.0e-4, "CPE1.n": 0.97 },
    fMin: 1e2,
    fMax: 1e8,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "L1-R1",
    blurb:
      "A conductive-polymer aluminium electrolytic: 100 uF, 8 mOhm ESR, 1.5 nH ESL, self-resonant " +
      "near 410 kHz. It differs from the capacitor above in one element, and that is the point -- " +
      "the capacitance is a CPE with n = 0.97, which is how the rising low-frequency ESR on a " +
      "datasheet curve is said in circuit terms. Below resonance the loss you measure is the " +
      "dielectric, not the 8 mOhm series ESR.",
  },
  {
    id: "ferrite-bead",
    source: "fitting:ferrite bead",
    group: "Devices",
    label: "Ferrite bead",
    circuit: "R1-p(R2,L1,C1)",
    params: { "R1.R": 0.05, "R2.R": 120.0, "L1.L": 1.5e-7, "C1.C": 1.7e-11 },
    fMin: 1e4,
    fMax: 1e9,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "p(R1,L1)",
    blurb:
      "120 Ohm at 100 MHz, the commonest EMI part there is: the winding resistance in series with " +
      "a parallel R, L and C. The only three-way parallel here, and the only lossy resonance -- " +
      "Q = 1.3, against the piezoelectric resonator's 100. That over-damping is the loss a bead " +
      "is sold for, which is why this one needs no dense sweep and the resonator does.",
  },
  {
    id: "coated-steel",
    source: "fitting:coated steel panel",
    group: "Devices",
    label: "Coated steel panel",
    circuit: "R1-p(CPE1,R2-p(CPE2,R3))",
    params: {
      "R1.R": 100.0,
      "CPE1.Q": 3e-9,
      "CPE1.n": 0.92,
      "R2.R": 2e4,
      "CPE2.Q": 5e-5,
      "CPE2.n": 0.8,
      "R3.R": 3e5,
    },
    fMin: 1e-2,
    fMax: 1e6,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "R1-p(CPE1,R2)",
    blurb:
      "An organic coating on steel in dilute salt, the standard coating-health model: solution " +
      "resistance, the coating's own capacitance and pore resistance, and inside that pore branch " +
      "the double layer and charge transfer at the metal underneath. The only nested topology " +
      "here -- a parallel block inside the branch of another one -- so it is the example that " +
      "shows what the schematic does with nesting.",
  },
  {
    id: "sofc-cathode",
    source: "fitting:SOFC cathode (Gerischer)",
    group: "Devices",
    label: "SOFC cathode (Gerischer)",
    circuit: "L1-R1-p(R2,CPE1)-G1",
    params: {
      "L1.L": 1e-7,
      "R1.R": 0.15,
      "R2.R": 0.08,
      "CPE1.Q": 5e-3,
      "CPE1.n": 0.85,
      "G1.R": 0.25,
      "G1.tau": 0.05,
    },
    fMin: 1e-1,
    fMax: 1e6,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "R1-p(R2,CPE1)",
    blurb:
      "A solid-oxide fuel cell cathode, and the only Gerischer element here: the coupled surface " +
      "reaction and ion transport of a mixed-conducting electrode. A Gerischer and a Warburg both " +
      "reach 45 degrees at high frequency and are told apart at the other end -- G settles to a " +
      "resistance where W diverges -- which is why the sweep goes down to 0.1 Hz instead of " +
      "stopping at the arc.",
  },
  {
    id: "tissue-cole",
    source: "fitting:tissue (Cole)",
    group: "Devices",
    label: "Tissue (Cole)",
    circuit: "R1-CC1",
    params: { "R1.R": 300.0, "CC1.R": 700.0, "CC1.tau": 3e-5, "CC1.alpha": 0.8 },
    fMin: 1e1,
    fMax: 1e6,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "R1",
    blurb:
      "Tissue between two electrodes as the Cole model: extracellular resistance plus one " +
      "depressed relaxation. Two elements, the smallest example here, and the clearest case of " +
      "two circuits being one model -- R1-p(R2,CPE1) fits this to the same residual with the same " +
      "number of parameters, which is what a full-auto report groups rather than chooses between.",
  },
  {
    id: "polymer-dielectric",
    source: "fitting:polymer dielectric (HN)",
    group: "Devices",
    label: "Polymer dielectric (Havriliak-Negami)",
    circuit: "p(C1,HN1)",
    params: { "C1.C": 2e-11, "HN1.R": 5e6, "HN1.tau": 1e-3, "HN1.alpha": 0.8, "HN1.beta": 0.6 },
    fMin: 1e-2,
    fMax: 1e6,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "C1",
    blurb:
      "A lossy polymer dielectric: the geometric capacitance in parallel with a " +
      "Havriliak-Negami relaxation. Its two exponents multiply into a single high-frequency " +
      "slope, so the obvious worry is that only their product can be recovered; both come back, " +
      "because alpha and beta separate the asymmetry of the loss peak from its width and this " +
      "window covers both flanks.",
  },
  {
    id: "thin-layer-cell",
    source: "fitting:thin-layer cell (Ws)",
    group: "Devices",
    label: "Thin-layer cell (finite-length Warburg)",
    circuit: "R1-p(CPE1,R2-Ws1)",
    params: {
      "R1.R": 15.0,
      "CPE1.Q": 2e-5,
      "CPE1.n": 0.88,
      "R2.R": 60.0,
      "Ws1.R": 120.0,
      "Ws1.tau": 4.0,
    },
    fMin: 1e-2,
    fMax: 1e5,
    pointsPerDecade: 10,
    noise: 0.01,
    seed: 0,
    skeleton: "R1-p(CPE1,R2)",
    blurb:
      "Diffusion across a layer whose far side is a second electrode rather than a wall, so the " +
      "low-frequency limit is a resistance instead of a capacitance. It is also the hardest fit " +
      "here: at the default five restarts it lands in a wrong basin about four times in ten, and " +
      "reports standard errors larger than the values when it does. Twenty restarts fixes it. " +
      "Worth trying twice on purpose.",
  },
];

export { SAMPLES };
