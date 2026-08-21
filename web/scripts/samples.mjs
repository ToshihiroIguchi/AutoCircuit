// The example datasets for the web UI, every one of them a spectrum the project already
// measures itself against.
//
// The first three are the reference spectra used throughout the discovery benchmark
// (benchmarks/discovery_v2.py, REFERENCES). The last two come from the fitting benchmark
// (benchmarks/fitting.py, SUITE) instead, because they are cases for *mode 1* -- the topology is
// given and all of its parameters are fitted without initial values -- rather than cases the
// topology search is measured on. Circuit, params, frequency limits, sweep density and noise are
// taken from those lists verbatim; they are not retyped, so a change to a benchmark's ground
// truth cannot silently drift out of sync with what the site ships.
//
// `skeleton` is the one field with no source in either benchmark for the last two: it is a
// mode-2 claim about what a user of that kind of sample would already know, and each one below
// has been checked to be a skeleton the circuit really contains.
const SAMPLES = [
  {
    id: "capacitor",
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
      "over decades.",
  },
];

export { SAMPLES };
