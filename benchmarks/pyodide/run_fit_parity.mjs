// Gate W1: does the browser's manual fit return what the command line's does?
//
//   python benchmarks/pyodide/fit_parity.py        # writes fit_parity_ref.json
//   node benchmarks/pyodide/run_fit_parity.mjs src.zip
//
// The reference file carries the spectra as well as the answers, so this fits the identical
// numbers rather than a regenerated copy of them, and it goes through
// `autocircuit.web.bridge.handle` -- the same entry point the Pyodide worker in web/ calls,
// with the same JSON envelope -- rather than through Python the browser never runs.
//
// Node and the browser load the same Pyodide wasm build. What differs between them is timing
// (docs/WEB_UI_PLAN.md section 2.3), not arithmetic, so a parity result measured here holds in
// the browser; a *speed* result would not.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC_ZIP = process.argv[2] ?? join(HERE, "src.zip");
const reference = JSON.parse(readFileSync(join(HERE, "fit_parity_ref.json"), "utf-8"));

/** Decode the wire's float sentinels; see autocircuit/core/wire.py. */
function decode(value) {
  if (typeof value === "number") return value;
  if (value === "inf") return Number.POSITIVE_INFINITY;
  if (value === "-inf") return Number.NEGATIVE_INFINITY;
  if (value === "nan") return Number.NaN;
  throw new Error(`unknown sentinel ${JSON.stringify(value)}`);
}

/** Agreement at the six significant digits the CLI prints, which is what gate W1 asks about. */
function agreesToSixDigits(a, b) {
  if (Object.is(a, b)) return true;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  return a.toPrecision(6) === b.toPrecision(6);
}

const pyodide = await loadPyodide({ stdout: () => {} });
await pyodide.loadPackage(["numpy", "scipy"]);
pyodide.unpackArchive(new Uint8Array(readFileSync(SRC_ZIP)), "zip", {
  extractDir: "/autocircuit-src",
});
pyodide.runPython(`
import sys
sys.path.insert(0, "/autocircuit-src")
from autocircuit.web import handle
`);
const handle = pyodide.globals.get("handle");

let mismatches = 0;
let exact = 0;
let compared = 0;
console.log(
  `${"case".padEnd(28)} ${"parameter".padEnd(12)} ${"browser".padStart(16)} ` +
    `${"CPython".padStart(16)}  rel.diff`,
);

for (const testCase of reference.cases) {
  const started = Date.now();
  const answer = JSON.parse(
    handle(
      JSON.stringify({
        op: "fit",
        circuit: testCase.circuit,
        spectrum: testCase.spectrum,
        restarts: testCase.restarts,
        seed: testCase.seed,
      }),
    ),
  );
  if (!answer.ok) {
    console.log(`${testCase.label.padEnd(28)} FAILED: ${answer.error.message}`);
    mismatches += 1;
    continue;
  }

  const mine = answer.result.fit.values.data.map(decode);
  const theirs = testCase.fit.values.data.map(decode);
  // The parameter names are not on the wire -- the circuit string is, and both sides derive the
  // same order from it, which is the contract `FitResult.from_wire` already relies on.
  const names = pyodide.runPython(
    `__import__("json").dumps(list(__import__("autocircuit.core.circuit", fromlist=["Circuit"])` +
      `.Circuit.parse(${JSON.stringify(testCase.circuit)}).param_names))`,
  );
  const labels = JSON.parse(names);

  let worst = 0;
  let worstIndex = 0;
  for (let i = 0; i < theirs.length; i += 1) {
    compared += 1;
    if (Object.is(mine[i], theirs[i])) exact += 1;
    const relative = theirs[i] === 0 ? Math.abs(mine[i]) : Math.abs(mine[i] / theirs[i] - 1);
    if (!agreesToSixDigits(mine[i], theirs[i])) mismatches += 1;
    if (relative > worst) {
      worst = relative;
      worstIndex = i;
    }
  }
  console.log(
    `${testCase.label.padEnd(28)} ${labels[worstIndex].padEnd(12)} ` +
      `${mine[worstIndex].toPrecision(8).padStart(16)} ` +
      `${theirs[worstIndex].toPrecision(8).padStart(16)}  ${worst.toExponential(2)}` +
      `   (${((Date.now() - started) / 1000).toFixed(1)} s, CPython ${testCase.elapsed_s.toFixed(1)} s)`,
  );
}

console.log(
  `\n${compared} parameters compared: ${exact} bit-identical, ` +
    `${mismatches} disagreeing at six significant digits`,
);

// Second question, and a narrower one: is the *arithmetic* identical, or only the answer?
//
// A fitted parameter travels through differential evolution and a trust-region solve, so a last-
// bit difference anywhere compounds into the optimizer's path. Evaluating one circuit at one set
// of values does not: it is numpy and nothing else. `FitResult.to_wire` carries `z_model` across
// the worker boundary rather than recomputing it on arrival precisely because nobody had
// measured this (see its docstring), so measure it: feed the browser the values CPython settled
// on and compare the response it draws with the one CPython drew.
console.log("\nimpedance evaluated at CPython's fitted values:");
let evaluated = 0;
let identical = 0;
let worstEval = 0;
for (const testCase of reference.cases) {
  const names = JSON.parse(
    pyodide.runPython(
      `__import__("json").dumps(list(__import__("autocircuit.core.circuit", fromlist=["Circuit"])` +
        `.Circuit.parse(${JSON.stringify(testCase.circuit)}).param_names))`,
    ),
  );
  const values = {};
  names.forEach((name, i) => {
    values[name] = decode(testCase.fit.values.data[i]);
  });
  const answer = JSON.parse(
    handle(
      JSON.stringify({
        op: "preview",
        circuit: testCase.circuit,
        spectrum: testCase.spectrum,
        values,
      }),
    ),
  );
  if (!answer.ok) {
    console.log(`${testCase.label.padEnd(28)} FAILED: ${answer.error.message}`);
    continue;
  }
  let worst = 0;
  for (let i = 0; i < testCase.fit.z_model.re.length; i += 1) {
    for (const part of ["re", "im"]) {
      const mine = decode(answer.result.z_model[part][i]);
      const theirs = decode(testCase.fit.z_model[part][i]);
      evaluated += 1;
      if (Object.is(mine, theirs)) identical += 1;
      const relative = theirs === 0 ? Math.abs(mine) : Math.abs(mine / theirs - 1);
      if (relative > worst) worst = relative;
    }
  }
  if (worst > worstEval) worstEval = worst;
  console.log(
    `${testCase.label.padEnd(28)} worst relative difference ${worst.toExponential(2)}`,
  );
}
console.log(
  `\n${evaluated} impedance components compared: ${identical} bit-identical ` +
    `(${((identical / evaluated) * 100).toFixed(1)}%), worst ${worstEval.toExponential(2)}`,
);

process.exit(mismatches === 0 ? 0 : 1);
