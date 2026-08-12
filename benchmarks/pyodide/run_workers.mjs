// Does the tier-1 screen scale across Web Workers?
//
// The CLI fans screening across processes with `--workers`, and a browser has no
// `multiprocessing` -- but it does have Web Workers, and each can hold its own Pyodide
// instance. Whether that actually buys anything decides what `exhaustive_limit` the web UI can
// offer, so it is measured rather than assumed. Node's worker_threads are the same shape of
// isolation (separate heap, structured-clone messaging), so the scaling transfers even though
// the shell does not.
//
//   node benchmarks/pyodide/run_workers.mjs src.zip "1,2,4,8"
import { Worker } from "node:worker_threads";

const SRC_ZIP = process.argv[2];
const COUNTS = (process.argv[3] ?? "1,2,4").split(",").map(Number);
const POOL = "R,C,L,CPE,SKINF";
const LIMIT = 4;

async function runWith(total) {
  const workers = [];
  const bootStarted = performance.now();
  const ready = [];
  for (let index = 0; index < total; index += 1) {
    const worker = new Worker(new URL("./screen_worker.mjs", import.meta.url), {
      workerData: {
        index,
        total,
        srcZip: SRC_ZIP,
        strideScript: new URL("./screen_stride.py", import.meta.url).pathname.slice(1),
        poolCsv: POOL,
        limit: LIMIT,
      },
    });
    workers.push(worker);
    ready.push(
      new Promise((resolve, reject) => {
        const onMessage = (m) => {
          if (!m.ready) return;
          worker.off("message", onMessage);
          resolve(m);
        };
        worker.on("message", onMessage);
        worker.once("error", reject);
      }),
    );
  }
  await Promise.all(ready);
  const bootSeconds = (performance.now() - bootStarted) / 1000;

  // Only now start the clock: worker start-up is reported separately because a real UI pays
  // it once, in the background, while the user is still choosing a file.
  const started = performance.now();
  const results = await Promise.all(
    workers.map(
      (worker) =>
        new Promise((resolve, reject) => {
          worker.on("message", (m) => {
            if (m.result) resolve(m.result);
          });
          worker.once("error", reject);
          worker.postMessage("go");
        }),
    ),
  );
  const wallSeconds = (performance.now() - started) / 1000;
  await Promise.all(workers.map((w) => w.terminate()));

  const screened = results.reduce((sum, r) => sum + r.n, 0);
  return { workers: total, bootSeconds, wallSeconds, screened, candidates: results[0].total };
}

const rows = [];
for (const total of COUNTS) {
  const row = await runWith(total);
  rows.push(row);
  console.error(
    `${row.workers} worker(s): boot ${row.bootSeconds.toFixed(1)} s,` +
      ` screen ${row.wallSeconds.toFixed(1)} s for ${row.screened} candidates`,
  );
}

const baseline = rows[0].wallSeconds;
console.log(
  JSON.stringify(
    rows.map((r) => ({ ...r, speedup: baseline / r.wallSeconds })),
    null,
    2,
  ),
);
