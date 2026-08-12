// One Pyodide instance in a Node worker thread, standing in for one browser Web Worker.
//
// Each worker enumerates the same candidate list itself -- enumeration is deterministic and
// costs a fraction of a second -- and screens the stride it is given, so the message traffic
// is two integers. That is also what a real worker pool would want: the tier-1 worker in
// core/discover.py already takes a circuit string and re-parses it, precisely so that nothing
// but strings and arrays has to cross an isolation boundary.
import { readFileSync } from "node:fs";
import { parentPort, workerData } from "node:worker_threads";
import { loadPyodide } from "pyodide";

const { index, total, srcZip, strideScript, poolCsv, limit } = workerData;

// Pyodide writes through an fd that does not exist inside a worker thread, so stdout and
// stderr have to be redirected explicitly or every print raises ERR_INVALID_ARG_TYPE.
const pyodide = await loadPyodide({
  stdout: (line) => parentPort.postMessage({ log: line }),
  stderr: (line) => parentPort.postMessage({ log: line }),
});
await pyodide.loadPackage(["numpy", "scipy"]);
await pyodide.unpackArchive(new Uint8Array(readFileSync(srcZip)), "zip", {
  extractDir: "/autocircuit-src",
});

pyodide.runPython('import sys; sys.path.insert(0, "/autocircuit-src")');
pyodide.globals.set("POOL_CSV", poolCsv);
pyodide.globals.set("LIMIT", limit);
pyodide.runPython(readFileSync(strideScript, "utf-8"));

parentPort.postMessage({ ready: true });

parentPort.on("message", (message) => {
  if (message !== "go") return;
  pyodide.globals.set("WORKER_INDEX", index);
  pyodide.globals.set("WORKER_TOTAL", total);
  const result = pyodide.runPython("screen_stride(WORKER_INDEX, WORKER_TOTAL)");
  parentPort.postMessage({ result: JSON.parse(result) });
});
