// Proves the browser's Python path works, without a browser.
//
// Node and a browser load the identical Pyodide wasm build, so everything between "bytes land
// in the filesystem" and "the bridge answers" can be checked here: the vendored distribution in
// public/ is the one loaded, the source archive in public/ is the one unpacked, and the file is
// read through the same FS.writeFile the worker uses. What this cannot cover is the worker
// message loop itself, which needs the real browser.
//
//   npm run smoke
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const HERE = dirname(fileURLToPath(import.meta.url));
const PUBLIC = resolve(HERE, "..", "public");

/**
 * The protocol version *this bundle speaks*, read out of the front end's own constant.
 *
 * Not a third hand-typed number. The question this smoke run exists to answer is whether the core
 * being shipped answers the protocol the page being shipped expects -- which is exactly what
 * `bridge.worker.ts` refuses to run without. A literal here would be a fourth place to remember on
 * every bump, and it was duly forgotten once: a pin reading 5 failed the deploy of a build whose
 * Python and TypeScript already agreed on 6. A regex that stops matching fails the check loudly
 * rather than passing it quietly.
 */
function bundleBridgeVersion() {
  const source = readFileSync(resolve(HERE, "..", "src", "worker", "protocol.ts"), "utf8");
  const found = source.match(/export const BRIDGE_VERSION = (\d+)/);
  return found === null ? null : Number(found[1]);
}

// A four-point spectrum is enough to exercise the reader, the sniffer and the wire format.
// Lin-KK needs more than that to say anything, so the validation check below uses a longer one
// generated in Python from the same simulate() the CLI uses.
const CSV = `Frequency,Re(Z),Im(Z)
100,0.01,-1591.549
1000,0.01,-159.155
10000,0.01,-15.915
100000,0.01,-1.592
`;

const failures = [];

function check(name, condition, detail = "") {
  if (condition) {
    console.log(`  ok   ${name}`);
  } else {
    console.log(`  FAIL ${name}${detail ? ` -- ${detail}` : ""}`);
    failures.push(name);
  }
}

const started = Date.now();
const pyodide = await loadPyodide({ indexURL: join(PUBLIC, "pyodide"), stdout: () => {} });

const site = () =>
  pyodide.runPython(`
import sys
next(p for p in sys.path if p.endswith("site-packages"))
`);
// Wrapped: unpackArchive rejects a Node Buffer with "Unknown typed array type 'Buffer'".
const unpack = (file, dir) =>
  pyodide.unpackArchive(new Uint8Array(readFileSync(join(PUBLIC, file))), "zip", {
    extractDir: dir,
  });

// -- stage A, exactly as the worker runs it: numpy, and no scipy anywhere ------------------------
//
// The staging is the thing this half checks, and it can only be checked by *not* loading scipy:
// the Data screen comes up on numpy alone (docs/STARTUP_AND_EDITING_PLAN.md section 3), which is
// a property of an import graph that one convenient `from .fit import ...` would quietly undo.
// The bytecode overlays go on in the same order and at the same points, because that order is
// itself load-bearing -- scipy's laid down before its wheel leaves scipy unimportable.
await pyodide.loadPackage(["numpy"]);
unpack("pyodide-bytecode-numpy.zip", site());
unpack("autocircuit-src.zip", "/autocircuit-src");
pyodide.runPython(`
import sys
sys.path.insert(0, "/autocircuit-src")
from autocircuit.web import handle
`);
const handle = pyodide.globals.get("handle");
const stageA = (Date.now() - started) / 1000;
console.log(`data runtime loaded in ${stageA.toFixed(1)} s`);

const ask = (request) => JSON.parse(handle(JSON.stringify(request)));

console.log("the data runtime, before scipy");
check(
  "scipy really is absent",
  pyodide.runPython("'scipy' in sys.modules") === false,
);
const version = ask({ op: "version" });
check("version answers", version.ok === true, JSON.stringify(version));
const expectedBridge = bundleBridgeVersion();
check(
  `the core answers the bridge version this bundle speaks (${expectedBridge})`,
  expectedBridge !== null && version.result?.bridge === expectedBridge,
  `core says ${version.result?.bridge}, protocol.ts says ${expectedBridge}`,
);
check(
  "the model-selection menu comes from the core's own registry",
  JSON.stringify((version.result?.criteria ?? []).map((c) => c.name)) ===
    JSON.stringify(["aic", "aicc", "bic", "caic", "hqc", "waic", "ftest"]),
  JSON.stringify(version.result?.criteria),
);
check("and names its default, which the page adopts", version.result?.default_criterion === "aic");
check(
  "all four readers are present",
  JSON.stringify(version.result?.formats) ===
    JSON.stringify(["generic_csv", "keysight", "touchstone", "zview"]),
  JSON.stringify(version.result?.formats),
);
pyodide.FS.mkdirTree("/uploads/0");
pyodide.FS.writeFile("/uploads/0/early.csv", new TextEncoder().encode(CSV));
const early = ask({ op: "read", path: "/uploads/0/early.csv" });
check("a file can be read before scipy exists", early.ok === true, JSON.stringify(early.error));
const earlySpectrum = early.result?.spectra?.[0];
check(
  "and trimmed",
  ask({ op: "trim", spectrum: earlySpectrum, f_min: 1000, f_max: 10000 }).ok === true,
);
const notYet = ask({ op: "elements" });
check(
  "a fitting operation says which package is missing rather than hanging or 404-ing",
  notYet.ok === false && /scipy/.test(notYet.error?.message ?? ""),
  JSON.stringify(notYet.error),
);
check("and scipy was not dragged in by trying", pyodide.runPython("'scipy' in sys.modules") === false);

// -- stage B: scipy, its overlay, and the rest of the bridge --------------------------------------
const beforeScipy = Date.now();
await pyodide.loadPackage(["scipy"]);
// The bytecode overlay, exactly as the worker applies it and where. A .pyc the interpreter rejects
// is a slow page rather than a broken one, but a .pyc it accepts and should not have is the kind
// of thing that only shows up as a wrong answer, so the whole run below happens on top of it.
unpack("pyodide-bytecode-scipy.zip", site());
const runtime = ask({ op: "runtime" });
check("runtime answers once scipy is in", runtime.ok === true, JSON.stringify(runtime.error));
check(
  "with the wire versions that belong to the fitter",
  typeof runtime.result?.fit === "number" && typeof runtime.result?.drt === "number",
  JSON.stringify(runtime.result),
);
console.log(
  `model runtime loaded in ${((Date.now() - beforeScipy) / 1000).toFixed(1)} s ` +
    `(${((Date.now() - started) / 1000).toFixed(1)} s in total)`,
);

console.log("read");
pyodide.FS.mkdirTree("/uploads/1");
pyodide.FS.writeFile("/uploads/1/example.csv", new TextEncoder().encode(CSV));
const read = ask({ op: "read", path: "/uploads/1/example.csv" });
check("read succeeds", read.ok === true, JSON.stringify(read.error));
const spectrum = read.result?.spectra?.[0];
check("one sweep, four points", read.result?.spectra?.length === 1 && spectrum?.f.data.length === 4);
check("format was sniffed as generic_csv", spectrum?.metadata?.format === "generic_csv");
check(
  "the imaginary part kept its sign",
  spectrum?.z.im[0] === -1591.549,
  JSON.stringify(spectrum?.z.im),
);

console.log("trim");
const trimmed = ask({ op: "trim", spectrum, f_min: 1000, f_max: 10000 });
check("trim succeeds", trimmed.ok === true, JSON.stringify(trimmed.error));
check("two points survive", trimmed.result?.spectrum.f.data.length === 2);
const empty = ask({ op: "trim", spectrum, f_min: 1e12, f_max: null });
check("an empty window is an error response, not a crash", empty.ok === false);
check(
  "and it says what went wrong",
  empty.error?.message === "frequency window selects no points",
  JSON.stringify(empty.error),
);

console.log("validate");
// A real spectrum, generated by the same code the CLI simulates with, because Lin-KK on four
// points has nothing to say.
pyodide.runPython(`
import json
from autocircuit.core.simulate import log_frequencies, simulate

_spectrum = simulate(
    "C1-R1-L1",
    log_frequencies(1e2, 1e9, 10),
    {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10},
    noise=0.01,
    seed=0,
)
_wire = json.dumps(_spectrum.to_wire())
`);
const simulated = JSON.parse(pyodide.globals.get("_wire"));
const validation = ask({ op: "validate", spectrum: simulated });
check("validate succeeds", validation.ok === true, JSON.stringify(validation.error));
const kk = validation.result?.validation;
check("the verdict is a pass on clean synthetic data", kk?.passed === true);
check("the residual pattern is random", kk?.systematic === false);
check("the summary text travelled", typeof kk?.summary === "string" && kk.summary.includes("Lin-KK"));

console.log("circuit");
const catalogue = ask({ op: "elements" });
check("elements answers", catalogue.ok === true, JSON.stringify(catalogue.error));
check(
  "the palette is the registry, not a copy of it",
  catalogue.result?.elements?.some((element) => element.code === "CPE") === true,
);
check(
  "the pools are the ones --pool offers",
  JSON.stringify(Object.keys(catalogue.result?.pools ?? {})) ===
    JSON.stringify(["default", "component", "electrochemical"]),
);

const described = ask({ op: "circuit", circuit: "C1-R1-L1", spectrum: simulated });
check("circuit parses", described.ok === true, JSON.stringify(described.error));
check("its tree is a series of three", described.result?.tree?.children?.length === 3);
check(
  "each parameter carries the interval the fitter searches",
  described.result?.params?.every((p) => typeof p.start === "number" && p.lower < p.upper) === true,
);
const broken = ask({ op: "circuit", circuit: "C1-p(R2" });
check("a syntax error is an error response, not a crash", broken.ok === false);

const edited = ask({ op: "edit", circuit: "C1-R1", path: [1], action: "parallel", code: "C" });
check("an edit answers with the circuit it produced", edited.result?.circuit === "C1-p(R1,C2)");
const collapsed = ask({
  op: "edit",
  circuit: "C1-R1-p(R2,C2)",
  path: [2, 1],
  action: "remove",
});
check(
  "deleting one branch of a pair collapses the block",
  collapsed.result?.circuit === "C1-R1-R2",
  JSON.stringify(collapsed),
);
// Dragging an element that is already in the circuit somewhere else. The target path addresses
// the circuit *before* anything moved, which is the whole reason this is one operation.
const moved = ask({
  op: "edit",
  circuit: "C1-R1-L1",
  path: [2],
  action: "move",
  to: [0],
  connect: "series",
  position: "before",
});
check("an element can be moved to another position", moved.result?.circuit === "L1-C1-R1", JSON.stringify(moved));
const movedParallel = ask({
  op: "edit",
  circuit: "C1-R1-L1",
  path: [0],
  action: "move",
  to: [2],
  connect: "parallel",
  position: "after",
});
check(
  "and into parallel with another, keeping its label",
  movedParallel.result?.circuit === "R1-p(L1,C1)",
  JSON.stringify(movedParallel),
);
check(
  "moving an element onto itself is a no-op rather than an error",
  ask({
    op: "edit",
    circuit: "C1-R1-L1",
    path: [1],
    action: "move",
    to: [1],
    connect: "series",
    position: "after",
  }).result?.circuit === "C1-R1-L1",
);

console.log("preview and fit");
const preview = ask({ op: "preview", circuit: "C1-R1-L1", spectrum: simulated });
check("preview answers", preview.ok === true, JSON.stringify(preview.error));
check(
  "it evaluates at every measured frequency",
  preview.result?.z_model?.re.length === simulated.f.data.length,
);
const fitted = ask({ op: "fit", circuit: "C1-R1-L1", spectrum: simulated, restarts: 2 });
check("fit answers", fitted.ok === true, JSON.stringify(fitted.error));
check("it converged", fitted.result?.fit?.success === true, fitted.result?.fit?.message);
check(
  "it recovered the capacitance it was generated from",
  Math.abs(fitted.result?.fit?.values.data[0] / 1e-6 - 1) < 0.05,
  JSON.stringify(fitted.result?.fit?.values.data),
);
check(
  "the residuals arrive already split, one value per point",
  fitted.result?.residual_real?.data.length === simulated.f.data.length &&
    fitted.result?.residual_imag?.data.length === simulated.f.data.length,
);
check(
  "the report text travelled",
  typeof fitted.result?.summary === "string" && fitted.result.summary.includes("chi^2"),
);

console.log("discovery");
// One Pyodide instance playing both roles the browser splits across workers: the orchestrator
// that holds the plan, and the pool that answers `screen_task`/`refit_task`. That is the whole
// message flow of the Discover screen, minus the fan-out -- which is the part only a real
// browser can exercise.
function drive(job, { stopAfterScreenBatches = null, stopAfterRefitBatches = null } = {}) {
  let costs = null;
  for (let batch = 0; ; batch += 1) {
    if (stopAfterScreenBatches !== null && batch >= stopAfterScreenBatches) return "screen";
    const step = ask({ op: "discover_screen", job, costs });
    if (step.ok !== true) throw new Error(JSON.stringify(step.error));
    if (step.result.tasks === null) break;
    costs = step.result.tasks.map(
      ([circuit, abandon]) =>
        ask({ op: "screen_task", spectrum: simulated, circuit, abandon_above: abandon }).result
          .cost,
    );
  }
  let results = null;
  for (let batch = 0; ; batch += 1) {
    if (stopAfterRefitBatches !== null && batch >= stopAfterRefitBatches) return "refit";
    const step = ask({ op: "discover_refit", job, results });
    if (step.ok !== true) throw new Error(JSON.stringify(step.error));
    if (step.result.tasks === null) break;
    results = step.result.tasks.map(
      ([circuit, restarts, seed]) =>
        ask({ op: "refit_task", spectrum: simulated, circuit, restarts, seed }).result.fit,
    );
  }
  return "done";
}

const search = ask({
  op: "discover_start",
  spectrum: simulated,
  // R and C alone cannot describe a spectrum that turns inductive: the feasibility screen
  // rejects every candidate and the search evaluates nothing, which is a real answer but not
  // the one this section is about.
  pool: ["R", "C", "L"],
  exhaustive_limit: 3,
  restarts: 1,
});
check("discover_start answers", search.ok === true, JSON.stringify(search.error));
check(
  "it says how much work each element count is",
  search.result?.levels?.every((level) => typeof level.candidates === "number") === true,
  JSON.stringify(search.result?.levels),
);
check("the search is exhaustive; the browser has no genetic fallback", search.result?.mode === "exhaustive");

check("a whole search runs to the end", drive(search.result.job) === "done");
const report = ask({ op: "discover_report", job: search.result.job }).result;
check("it claims the coverage it reached", report?.complete_up_to === 3, JSON.stringify(report?.complete_up_to));
check(
  "and says so in the sentence the screen renders verbatim",
  typeof report?.completeness === "string" &&
    report.completeness.includes("every plausible topology with up to 3 elements"),
  report?.completeness,
);
check("nothing is claimed partial when nothing was cut short", report?.refit_progress === null);
check("it recommends a candidate", typeof report?.recommended === "string", JSON.stringify(report?.recommended));
check("the Pareto front is not empty", (report?.pareto?.length ?? 0) > 0);
check("it ran under the default criterion, since none was named", report?.criterion === "aic");
check(
  // `restarts: 1` above, not the default 5: the point of carrying this to the Fit screen is that
  // it is what the search *did*, so the check is that it reports this run rather than a constant.
  "and says what its rows were refitted under, which is what the Fit screen adopts",
  report?.weighting === "modulus" && report?.seed === 0 && report?.refit_restarts === 1,
  JSON.stringify([report?.weighting, report?.seed, report?.refit_restarts]),
);
check("and labels the column its scores are in", report?.score_label === "AIC", report?.score_label);
check(
  "every row carries all six scores, not only the one that ranked it",
  report?.pareto?.every((row) =>
    ["aic", "aicc", "bic", "caic", "hqc", "waic"].every((name) => name in row),
  ) === true,
  JSON.stringify(report?.pareto?.[0]),
);
check(
  "the ranking really is the named criterion's",
  report?.pareto?.every((row) => row.score === row.aic) === true,
  JSON.stringify(report?.pareto?.map((row) => [row.score, row.aic])),
);

// The F-test is the one choice that is not a score, so it is the one worth driving end to end:
// it must rank by AIC, label the column AIC, and still name a choice of its own.
const tested = ask({
  op: "discover_start",
  spectrum: simulated,
  pool: ["R", "C", "L"],
  exhaustive_limit: 3,
  restarts: 1,
  criterion: "ftest",
});
check("a search can name its criterion", tested.ok === true, JSON.stringify(tested.error));
check("an F-test search runs to the end", drive(tested.result.job) === "done");
const testedReport = ask({ op: "discover_report", job: tested.result.job }).result;
check("it reports the criterion it was asked for", testedReport?.criterion === "ftest");
check(
  "and ranks by AIC, because a test between two models is not an axis",
  testedReport?.score_label === "AIC" &&
    testedReport?.pareto?.every((row) => row.score === row.aic) === true,
  testedReport?.score_label,
);
check(
  "it still names what the test chose",
  typeof testedReport?.by_criterion === "string",
  JSON.stringify(testedReport?.by_criterion),
);
check(
  "an unknown criterion is an error response rather than a silent default",
  ask({ op: "discover_start", spectrum: simulated, criterion: "r-squared" }).ok === false,
);

const cancelled = ask({
  op: "discover_start",
  spectrum: simulated,
  // R and C alone cannot describe a spectrum that turns inductive: the feasibility screen
  // rejects every candidate and the search evaluates nothing, which is a real answer but not
  // the one this section is about.
  pool: ["R", "C", "L"],
  exhaustive_limit: 3,
  restarts: 1,
  refit_chunk: 1,
});
check("a second search replaces the first", cancelled.result?.job !== search.result?.job);
check("stopped mid-refit", drive(cancelled.result.job, { stopAfterRefitBatches: 2 }) === "refit");
ask({ op: "discover_cancel", job: cancelled.result.job });
const partial = ask({ op: "discover_report", job: cancelled.result.job }).result;
check("a cancelled run still reports", partial?.stopped === true);
check("the screen finished, so its claim stands", partial?.complete_up_to === 3);
check(
  "but the ranking says it is partial",
  Array.isArray(partial?.refit_progress) && partial.completeness.includes("shortlisted"),
  partial?.completeness,
);
check(
  "and it reports fewer candidates than the whole shortlist",
  partial.refit_progress[0] < partial.refit_progress[1],
  JSON.stringify(partial?.refit_progress),
);
check(
  "a job that has been replaced is refused rather than confused with the current one",
  ask({ op: "discover_screen", job: search.result.job }).ok === false,
);

console.log("what the skeleton excluded");
// The Report screen's own job: a pass over the topologies the assertion removed, driven exactly
// as the search is -- batches out, costs back -- and screened against the reported model's own
// fitted response rather than against the data.
const constrained = ask({
  op: "discover_start",
  spectrum: simulated,
  pool: ["R", "C", "L"],
  skeleton: "C1-R1",
  exhaustive_limit: 3,
  restarts: 1,
});
check("a constrained search starts", constrained.ok === true, JSON.stringify(constrained.error));
check("it runs to the end", drive(constrained.result.job) === "done");
const constrainedReport = ask({ op: "discover_report", job: constrained.result.job }).result;
check(
  "its coverage names the skeleton, not just the element count",
  constrainedReport?.completeness.includes("contains C1-R1"),
  constrainedReport?.completeness,
);
check(
  "the classes arrive grouped, singletons included",
  Array.isArray(constrainedReport?.equivalence_classes) &&
    constrainedReport.equivalence_classes.flat().length === constrainedReport.candidates.length,
  JSON.stringify(constrainedReport?.equivalence_classes),
);
check(
  "where the skeleton sits is reported per front row",
  constrainedReport?.skeleton_placements !== null &&
    Object.keys(constrainedReport?.skeleton_placements ?? {}).length ===
      constrainedReport?.pareto.length,
);
check(
  "and what the data could not test is a list rather than a paragraph",
  Array.isArray(constrainedReport?.unsupported_assertion),
  JSON.stringify(constrainedReport?.unsupported_assertion),
);

const pass = ask({ op: "excluded_start", job: constrained.result.job });
check("excluded_start answers", pass.ok === true, JSON.stringify(pass.error));
check("nothing has been screened yet", pass.result?.screened === 0);
check("but the size of the pass is already known", (pass.result?.excluded ?? 0) > 0);
check(
  "the screens run against the model, not the measurement",
  JSON.stringify(pass.result?.target?.z) !== JSON.stringify(simulated.z),
);

let excludedCosts = null;
for (;;) {
  const step = ask({ op: "excluded_screen", job: pass.result.job, costs: excludedCosts });
  if (step.ok !== true) throw new Error(JSON.stringify(step.error));
  if (step.result.tasks === null) break;
  excludedCosts = step.result.tasks.map(
    ([circuit, abandon]) =>
      ask({
        op: "screen_task",
        spectrum: pass.result.target,
        circuit,
        abandon_above: abandon,
      }).result.cost,
  );
}
const excluded = ask({ op: "excluded_report", job: pass.result.job }).result;
check("the pass finishes", excluded?.finished === true && excluded?.partial === false);
check("it checked everything it enumerated", excluded?.screened === excluded?.excluded);
check(
  "and its sentence is the whole claim",
  typeof excluded?.summary === "string" && excluded.summary.includes("excluded"),
  excluded?.summary,
);

console.log("structure probe");
const probe = ask({ op: "drt", spectrum: simulated });
check("drt answers", probe.ok === true, JSON.stringify(probe.error));
check("its advice travelled verbatim", Array.isArray(probe.result?.drt?.hints) && probe.result.drt.hints.length > 0);
check(
  "an absent series capacitance travels as a sentinel rather than breaking the wire",
  ask({ op: "drt", spectrum: simulated, series_capacitance: false }).result?.drt?.capacitance ===
    "inf",
);

console.log("downloads");
const jsonFile = ask({
  op: "export",
  kind: "json",
  job: constrained.result.job,
  excluded: pass.result.job,
});
check("a JSON report is written", jsonFile.ok === true, JSON.stringify(jsonFile.error));
const written = JSON.parse(jsonFile.result.content);
check(
  "it carries the coverage sentence, so the file says what the search may claim",
  written.coverage === constrainedReport.completeness,
);
check(
  "and the excluded pass, because one was run",
  written.excluded_equivalents?.summary === excluded.summary,
);
const csvFile = ask({ op: "export", kind: "csv", job: constrained.result.job });
check("a CSV table is written", csvFile.ok === true, JSON.stringify(csvFile.error));
check(
  "with a column naming the rows it cannot be told apart from",
  csvFile.result?.content.split("\n")[0].includes("equivalents"),
  csvFile.result?.content.split("\n")[0],
);
const netlist = ask({ op: "export", kind: "netlist", job: constrained.result.job });
check("a netlist is written", netlist.ok === true, JSON.stringify(netlist.error));
check(
  "of the recommended candidate",
  netlist.result?.content.includes(`Circuit: ${constrainedReport.recommended}`),
);
const fitFile = ask({
  op: "export",
  kind: "json",
  fit: fitted.result.fit,
  spectrum: simulated,
  source: "example.csv",
});
check("a manual fit exports too", fitFile.ok === true, JSON.stringify(fitFile.error));
check(
  "naming the data as the user knows it",
  JSON.parse(fitFile.result.content).data?.source === "example.csv",
);

console.log("errors");
check("a missing file is an error response", ask({ op: "read", path: "/nope.csv" }).ok === false);
check("an unknown operation is an error response", ask({ op: "nonsense" }).ok === false);
check("malformed JSON is an error response", JSON.parse(handle("{not json")).ok === false);

console.log(failures.length === 0 ? "\nall checks passed" : `\n${failures.length} FAILED`);
process.exit(failures.length === 0 ? 0 : 1);
