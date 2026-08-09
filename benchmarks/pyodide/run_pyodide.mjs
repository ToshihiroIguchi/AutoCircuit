// Run bench.py inside Pyodide under Node, so the browser cost can be measured without a
// browser. Node and a real browser run the identical WASM build; what differs is the shell
// around it, which none of these measurements touch.
//
//   node benchmarks/pyodide/run_pyodide.mjs src.zip benchmarks/pyodide/bench.py
//
// Build src.zip with make_zip.py first.
import { readFileSync } from "node:fs";
import { loadPyodide } from "pyodide";

const SRC_ZIP = process.argv[2];
const BENCH_PY = process.argv[3];

const t0 = performance.now();
const pyodide = await loadPyodide();
const bootMs = performance.now() - t0;

const t1 = performance.now();
await pyodide.loadPackage(["numpy", "scipy"]);
const packagesMs = performance.now() - t1;

// The package is not pip-installed anywhere, so ship the source tree in and put it on the
// path. unpackArchive rejects a Node Buffer ("Unknown typed array type 'Buffer'") and wants a
// plain Uint8Array view.
const zip = new Uint8Array(readFileSync(SRC_ZIP));
await pyodide.unpackArchive(zip, "zip", { extractDir: "/autocircuit-src" });
pyodide.runPython(`
import sys
sys.path.insert(0, "/autocircuit-src")
`);

console.error(
  `pyodide boot ${(bootMs / 1000).toFixed(2)} s,` +
    ` numpy+scipy load ${(packagesMs / 1000).toFixed(2)} s`,
);

// Run the shared script as a module body, then call main() -- rather than exec'ing it as
// __main__ -- so its JSON comes back as a value instead of through captured stdout.
const code = readFileSync(BENCH_PY, "utf-8");
pyodide.runPython(code.replace('if __name__ == "__main__":', "if False:"));
const payload = JSON.parse(pyodide.runPython("import json; json.dumps(main())"));

payload.pyodide_boot_s = bootMs / 1000;
payload.numpy_scipy_load_s = packagesMs / 1000;
payload.pyodide_version = pyodide.version;
console.log(JSON.stringify(payload, null, 2));
