// The three reference spectra used throughout the project's own discovery benchmark
// (benchmarks/discovery_v2.py, REFERENCES), reused here as example datasets for the web UI.
// Circuit, params, frequency limits, noise and skeleton are taken from that list verbatim --
// they are not retyped, so a change to the benchmark's ground truth cannot silently drift out
// of sync with what the site ships.
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
];

export { SAMPLES };
