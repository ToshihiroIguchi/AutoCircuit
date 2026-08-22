// Checks that every example spectrum on the site really is a benchmark case.
//
// `scripts/samples.mjs` says of itself that circuit, params, window, density and noise "are taken
// from those benchmark lists verbatim; they are not retyped, so a change to a benchmark ground
// truth cannot silently drift out of sync with what the site ships". Until this script existed
// that sentence was an intention: the values *are* retyped, in JavaScript, beside a Python list
// nothing compared them against. Editing `benchmarks/fitting.py` and forgetting `samples.mjs`
// would have left the site shipping a spectrum labelled with a circuit it was no longer generated
// from -- and the label is the whole reason showing synthetic data is honest.
//
// So the claim is now enforced rather than made. Each sample names the list it comes from and the
// label of its entry, and this walks the Python lists and compares field by field.
//
// It shells out to Python for the same reason `build-assets.mjs` does: the benchmark lists are
// Python, and re-expressing them in JSON would put a second copy exactly where this script exists
// to forbid one. Run by `npm run check`, so a drifted example cannot be published.

import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { SAMPLES } from "./samples.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");

// Dumps both benchmark lists in one shape. `Case` and `Reference` differ -- a Case has
// `points_per_decade` and no noise, a Reference has `noise` and a fixed 10 per decade -- so the
// difference is flattened here, once, rather than at each comparison below.
const DUMP = `
import json, sys
sys.path[:0] = [r"${join(REPO, "benchmarks")}", r"${join(REPO, "src")}"]
import fitting, discovery_v2
out = {}
for c in fitting.SUITE:
    out["fitting:" + c.label] = dict(
        circuit=c.dsl, params=c.truth, f_min=c.f_min, f_max=c.f_max,
        points_per_decade=c.points_per_decade, noise=None,
    )
for r in discovery_v2.REFERENCES:
    out["discovery:" + r.label] = dict(
        circuit=r.circuit, params=r.params, f_min=r.f_min, f_max=r.f_max,
        points_per_decade=10, noise=r.noise,
    )
json.dump(out, sys.stdout)
`;

const result = spawnSync("python", ["-c", DUMP], { encoding: "utf8" });
if (result.status !== 0) {
  console.error(result.stderr || "python failed with no output");
  throw new Error(`could not read the benchmark lists (exit ${result.status})`);
}
const truth = JSON.parse(result.stdout);

let failures = 0;
function check(name, ok, detail) {
  if (ok) {
    console.log(`  ok   ${name}`);
  } else {
    console.log(`  FAIL ${name}: ${detail}`);
    failures += 1;
  }
}

for (const sample of SAMPLES) {
  console.log(`${sample.id}  <-  ${sample.source}`);
  const entry = truth[sample.source];
  if (entry === undefined) {
    check("the benchmark entry exists", false, `no entry named ${sample.source}`);
    continue;
  }

  check("circuit", sample.circuit === entry.circuit, `${sample.circuit} != ${entry.circuit}`);

  const ours = Object.keys(sample.params).sort();
  const theirs = Object.keys(entry.params).sort();
  const sameNames = ours.length === theirs.length && ours.every((k, i) => k === theirs[i]);
  check("parameter names", sameNames, `${ours.join(",")} != ${theirs.join(",")}`);
  if (sameNames) {
    const wrong = ours.filter((k) => sample.params[k] !== entry.params[k]);
    // Compared with === rather than a tolerance on purpose: these are two spellings of one
    // constant, not two measurements of one quantity, so anything but equality is a typo.
    check(
      "parameter values",
      wrong.length === 0,
      wrong.map((k) => `${k} ${sample.params[k]} != ${entry.params[k]}`).join("; "),
    );
  }

  check(
    "frequency window",
    sample.fMin === entry.f_min && sample.fMax === entry.f_max,
    `${sample.fMin}..${sample.fMax} != ${entry.f_min}..${entry.f_max}`,
  );
  check(
    "points per decade",
    sample.pointsPerDecade === entry.points_per_decade,
    `${sample.pointsPerDecade} != ${entry.points_per_decade}`,
  );
  // A `Case` carries no noise level -- the fitting benchmark sweeps it -- so for those the site
  // chooses one, and 1% is the level every other measurement in this project is quoted at.
  check(
    "noise",
    entry.noise === null ? sample.noise === 0.01 : sample.noise === entry.noise,
    `${sample.noise} != ${entry.noise ?? "0.01 (the project's standard, this list fixes none)"}`,
  );
}

console.log("");
if (failures > 0) {
  console.error(`${failures} example(s) no longer match the benchmark they claim to come from.`);
  process.exit(1);
}
console.log(`all ${SAMPLES.length} examples match their benchmark entries`);
