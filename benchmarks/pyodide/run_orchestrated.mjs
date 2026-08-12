// Prototype of the browser discovery architecture chosen in docs/WEB_UI_PLAN.md section 2:
// orchestration stays in Python, JavaScript only carries batches of screening work out to
// Web Workers and the costs back.
//
//   node benchmarks/pyodide/run_orchestrated.mjs src.zip 4
//
// Prints the same summary shape as the CPython A/B dump, so the two can be diffed. If they
// match, the browser is running the identical two-tier logic -- including the per-size
// shortlist quota gate G1 depends on -- rather than a JavaScript reimplementation of it.
import { readFileSync } from "node:fs";
import { Worker } from "node:worker_threads";
import { loadPyodide } from "pyodide";

const SRC_ZIP = process.argv[2];
const POOL_SIZE = Number(process.argv[3] ?? 4);

function spawnScreeners(count) {
  return Array.from({ length: count }, () => {
    const worker = new Worker(new URL("./screen_task_worker.mjs", import.meta.url), {
      workerData: { srcZip: SRC_ZIP },
    });
    // One error listener for the worker's whole life. Attaching a fresh one per batch is what
    // trips Node's MaxListenersExceededWarning after ten batches.
    const failed = new Promise((_, reject) => worker.once("error", reject));
    const ready = new Promise((resolve) => {
      const onMessage = (m) => {
        if (!m.ready) return;
        worker.off("message", onMessage);
        resolve();
      };
      worker.on("message", onMessage);
    });
    return { worker, ready: Promise.race([ready, failed]), failed };
  });
}

/** Split one batch across the pool, preserving order on the way back. */
function screenBatch(pool, tasks) {
  const slices = pool.map((_, i) => tasks.filter((_, j) => j % pool.length === i));
  return Promise.all(
    pool.map(({ worker, failed }, i) => {
      if (slices[i].length === 0) return Promise.resolve([]);
      const answered = new Promise((resolve) => {
        const onMessage = (m) => {
          if (!m.costs) return;
          worker.off("message", onMessage);
          resolve(m.costs);
        };
        worker.on("message", onMessage);
        worker.postMessage(JSON.stringify(slices[i]));
      });
      return Promise.race([answered, failed]);
    }),
  ).then((sliceCosts) => tasks.map((_, j) => sliceCosts[j % pool.length][Math.floor(j / pool.length)]));
}

const bootStarted = performance.now();
const pool = spawnScreeners(POOL_SIZE);

const orchestrator = await loadPyodide({ stdout: () => {}, stderr: () => {} });
await orchestrator.loadPackage(["numpy", "scipy"]);
await orchestrator.unpackArchive(new Uint8Array(readFileSync(SRC_ZIP)), "zip", {
  extractDir: "/autocircuit-src",
});
orchestrator.runPython('import sys; sys.path.insert(0, "/autocircuit-src")');
orchestrator.runPython(
  readFileSync(new URL("./orchestrate.py", import.meta.url), "utf-8"),
);
await Promise.all(pool.map((p) => p.ready));
const bootSeconds = (performance.now() - bootStarted) / 1000;

const py = (name) => orchestrator.globals.get(name);
const started = performance.now();

const { candidates } = JSON.parse(py("start")());
console.error(`${candidates} candidates, ${POOL_SIZE} screening workers`);

let done = 0;
for (;;) {
  const batch = JSON.parse(py("next_batch")());
  if (batch === null) break;
  const costs = await screenBatch(pool, batch);
  py("submit")(JSON.stringify(costs));
  done += batch.length;
  process.stderr.write(`\r  screened ${done}/${candidates}`);
}
process.stderr.write("\n");
const screenSeconds = (performance.now() - started) / 1000;

const report = JSON.parse(py("finish")());
const totalSeconds = (performance.now() - started) / 1000;
await Promise.all(pool.map((p) => p.worker.terminate()));

console.error(
  `boot ${bootSeconds.toFixed(1)} s, screen ${screenSeconds.toFixed(1)} s,` +
    ` total ${totalSeconds.toFixed(1)} s`,
);
console.log(JSON.stringify(report, null, 1));
