// Real, measured example spectra for the Data screen -- `docs/IMPACT_PLAN.md` item C, gate R5.
//
// Unlike `scripts/samples.mjs`'s synthetic rows, these have no circuit, no noise level and no
// command that reproduces them: they are files someone else's instrument wrote. The single
// source of truth is `benchmarks/measured/datasets.py`'s `DATASETS` list -- this module reads
// it at build time (the same way `samples-check.mjs` reads the fitting/discovery benchmark
// lists) rather than retyping citation and licence text in JavaScript, for the same reason: a
// second copy of a citation is a second place for it to drift from the one that matters.
//
// Only a curated subset is published, named here by id -- not every dataset the arena's Python
// benchmark carries needs to be on the site, and the ones chosen are picked for how different
// their real-instrument shape is from every synthetic example beside them.
//
// A second constraint narrows the choice further than the Python arena's own: the browser's
// upload path (`bridge.worker.ts`'s `upload()`) threads only a filename into Pyodide's
// filesystem, not per-file reader hints, so a dropped or fetched file is read by
// `autocircuit.io.read`'s ordinary sniffing alone. Two of the arena's datasets need an explicit
// positional-column hint (`datasets.py`'s `reader_hints`, e.g. the Zenodo battery CSVs' unrecognised
// `Real_Ohm`/`Imag_Ohm` headers) and are left off the site for that reason -- they stay in the
// Python arena, where gates R1-R4 pass `reader_hints` directly.

import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");

/** Which `benchmarks/measured/datasets.py` entries the site ships, and why. */
export const MEASURED_SAMPLE_IDS = [
  "impedancepy-generic",
  "impedancepy-biologic",
  "impedancepy-gamry",
];

const DUMP = `
import json, sys
sys.path[:0] = [r"${join(REPO, "benchmarks", "measured")}", r"${join(REPO, "src")}"]
from datasets import DATASETS
out = {}
for d in DATASETS:
    out[d.id] = dict(
        label=d.label, file=d.file, format=d.format, system=d.system,
        source_url=d.source_url, license=d.license, artefact=d.artefact,
        published_circuit=d.published_circuit,
        published_circuit_note=d.published_circuit_note,
    )
json.dump(out, sys.stdout)
`;

/** Reads the chosen entries from `datasets.py`, in `MEASURED_SAMPLE_IDS` order. */
export function loadMeasuredSamples() {
  const result = spawnSync("python", ["-c", DUMP], { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(
      `could not read benchmarks/measured/datasets.py (exit ${result.status}): ` +
        (result.stderr || "no output"),
    );
  }
  const all = JSON.parse(result.stdout);
  return MEASURED_SAMPLE_IDS.map((id) => {
    const entry = all[id];
    if (entry === undefined) {
      throw new Error(`MEASURED_SAMPLE_IDS names "${id}", which is not in datasets.py`);
    }
    return { id, ...entry };
  });
}
