// A fitting worker for the browser prototype: it holds a Pyodide instance and answers two
// questions, "screen these circuits with these abandon thresholds" (-> costs) and "refit these
// circuits at full budget" (-> whole FitResults in wire form). It makes no decisions -- which
// circuits, in what order, against what threshold, which ones deserve a refit -- because those
// all come from screen_plan() and refit_plan() in the orchestrator.
import { readFileSync } from "node:fs";
import { parentPort, workerData } from "node:worker_threads";
import { loadPyodide } from "pyodide";

const { srcZip } = workerData;

const pyodide = await loadPyodide({
  stdout: () => {},
  stderr: () => {},
});
await pyodide.loadPackage(["numpy", "scipy"]);
await pyodide.unpackArchive(new Uint8Array(readFileSync(srcZip)), "zip", {
  extractDir: "/autocircuit-src",
});

pyodide.runPython(`
import json
import math
import sys
sys.path.insert(0, "/autocircuit-src")

from autocircuit.core.discover import SCREEN_BUDGET, ScreenTask, _full_fit, _screen_one
from autocircuit.core.simulate import log_frequencies, simulate

SPECTRUM = simulate(
    "C1-R1-L1-SKINF1",
    log_frequencies(1e2, 1e9, 10),
    {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
    noise=0.01,
    seed=0,
)


def run(tasks_json):
    # null is the wire representation of infinity in both directions; see orchestrate.py.
    tasks = json.loads(tasks_json)
    costs = [
        _screen_one(
            ScreenTask(text, math.inf if abandon is None else float(abandon)),
            SPECTRUM,
            weighting="modulus",
            seed=0,
            budget=SCREEN_BUDGET,
        )
        for text, abandon in tasks
    ]
    return json.dumps([None if math.isinf(cost) else cost for cost in costs])


def refit(tasks_json):
    # A whole FitResult per task -- covariance, restart spread, fitted response and all -- in
    # the lossless wire form; null for a topology that could not be fitted at all. Nothing is
    # summarised here, because summarising is what loses the restart spread.
    results = [
        _full_fit(text, SPECTRUM, "modulus", restarts, seed)
        for text, restarts, seed in json.loads(tasks_json)
    ]
    return json.dumps([None if r is None else r.to_wire() for r in results])
`);

const run = pyodide.globals.get("run");
const refit = pyodide.globals.get("refit");
parentPort.postMessage({ ready: true });

parentPort.on("message", ({ kind, tasks }) => {
  if (kind === "refit") {
    parentPort.postMessage({ kind, results: JSON.parse(refit(JSON.stringify(tasks))) });
  } else {
    parentPort.postMessage({ kind, costs: JSON.parse(run(JSON.stringify(tasks))) });
  }
});
