/// <reference lib="webworker" />
// Holds one Pyodide instance and forwards requests to `autocircuit.web.bridge.handle`.
//
// Pyodide is imported from a URL the main thread computed, not from the `pyodide` npm package:
// the distribution loads its own Emscripten glue and its wasm relative to `indexURL`, which a
// bundler cannot rewrite, so it is served from public/ as-is and imported at run time.
//
// The load runs in two stages, and which stage a request needs is decided in Python rather than
// here: stage A brings up the interpreter, numpy and the data path, stage B adds scipy and the
// fitter. See `init` and `loadFitting` below, and `docs/STARTUP_AND_EDITING_PLAN.md` section 3.

import {
  BRIDGE_VERSION,
  type LoadStage,
  type LoadTimings,
  type RuntimeTimings,
  type WorkerRequest,
  type WorkerResponse,
} from "./protocol";
import type { RuntimeWire, VersionsWire } from "../core/types";

declare const self: DedicatedWorkerGlobalScope;

// Pyodide's own typings describe the npm entry point, which is not how it is loaded here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Pyodide = any;

let pyodide: Pyodide | null = null;
let handle: ((request: string) => string) | null = null;
let uploads = 0;
/**
 * The second stage, once it has been started.
 *
 * A request the light bridge cannot serve is not refused and not raced: it waits on this. That
 * is what lets the main thread send whatever it likes without tracking which side of the scipy
 * line an operation is on -- the one place that knows is `autocircuit.web.light`, in Python, and
 * the set below is only a *scheduling* hint. Getting it wrong costs a wait, never a wrong
 * answer: an operation wrongly called light still reaches the same dispatch.
 */
let fitting: Promise<void> | null = null;

/**
 * The operations stage A can already answer; everything else waits for stage B.
 *
 * Filled in from the core's own `version` answer rather than written out here. A copy of the list
 * in TypeScript could disagree in the direction that matters -- an operation this file thought
 * was light would be sent straight through and answered "scipy is not installed" instead of
 * answered -- and this project has the same rule for the reader list, the element pools and the
 * criteria menu: what the running build offers, not what the front end remembers.
 *
 * Empty until `version` has answered, which means everything waits. That is the safe direction.
 */
let lightOperations = new Set<string>();

function post(message: WorkerResponse): void {
  self.postMessage(message);
}

function status(stage: LoadStage, detail: string): void {
  post({ kind: "status", stage, detail });
}

/** Fetch a build artefact as bytes. `unpackArchive` wants a `Uint8Array`, not a `Buffer`. */
async function download(url: string): Promise<Uint8Array> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} -> HTTP ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

// There is deliberately no prefetch of the numpy and scipy wheels here, and the reason is a
// measurement rather than an oversight.
//
// The idea is obvious: they are 17 MB of the site's 41 and nothing about them depends on the
// interpreter existing, yet `loadPackage` cannot be called until `loadPyodide()` has resolved --
// and that call first fetches the 9.6 MB wasm and the 7.1 MB stdlib. Both forms of it were built
// and both were measured against the deployed site with a fresh browser profile:
//
// * A `<link rel="preload" as="fetch">` in index.html does not satisfy the fetch at all. A
//   document's preload cache does not serve a *Web Worker's* fetch, so Chrome downloaded all
//   17 MB a second time and logged "preloaded ... but not used".
// * Starting the fetches here, before `loadPyodide`, and answering `loadPackage` from them does
//   work -- the packages stage fell from 7.84 / 4.39 s to 1.67 / 1.80 s -- **and the total got
//   worse**: 22.3 / 16.6 / 15.8 / 30.6 s against 15.2 / 13.5 s before. The cold start over this
//   link is bandwidth-bound, so the wheels do not overlap the boot, they compete with it: the
//   wasm the boot blocks on arrives later, and the time moves from one stage to the other.
//
// So reordering the transfers cannot help; only sending fewer bytes before the page is usable
// can, which is what section 1.4 of docs/METRICS_AND_UX_PLAN.md is about -- and it is what the
// two stages below do. Nothing is fetched *earlier* than before: scipy and its bytecode, 18.3 MB
// of the 41, are fetched **later**, once the page can already read a file, so they compete with
// a visitor reading their data rather than with the wasm the boot blocks on. Do not fold this
// back into one stage, and do not re-add a prefetch without a measurement of the *total*, on a
// real network: the stage breakdown alone says the flattering half.

/** Where the wheels are installed, which is where an overlay is unpacked. */
function sitePackages(): string {
  return pyodide.runPython(`
import sys
next(p for p in sys.path if p.endswith("site-packages"))
`);
}

/**
 * Fetch one bytecode overlay, or null if it is not there.
 *
 * An overlay is `__pycache__` folders holding a .pyc for every module of a wheel this page
 * imports, compiled by the build (`web/scripts/precompile.mjs`); without it every visitor
 * compiles them again. It is an optimisation, so its absence is caught here rather than left to
 * reject a load that would otherwise have succeeded.
 */
function overlay(url: string): Promise<Uint8Array | null> {
  return download(url).catch((error: unknown) => {
    console.warn(`AutoCircuit: no bytecode overlay, importing from source (${String(error)})`);
    return null;
  });
}

/** Stage A: the interpreter, numpy, and the part of the bridge that reads and validates data. */
async function init(
  pyodideUrl: string,
  indexUrl: string,
  archiveUrl: string,
  numpyBytecodeUrl: string,
): Promise<{ versions: VersionsWire; timings: LoadTimings }> {
  const timings: LoadTimings = { boot: 0, packages: 0, unpack: 0, importing: 0 };
  let mark = performance.now();
  const since = (): number => {
    const now = performance.now();
    const elapsed = now - mark;
    mark = now;
    return elapsed;
  };

  status("booting", "Starting the Python runtime");
  const module = await import(/* @vite-ignore */ pyodideUrl);
  // Both archives are wanted the moment the wheel is in, and neither depends on the interpreter
  // existing, so they are asked for now and awaited later.
  const archive = download(archiveUrl);
  const bytecode = overlay(numpyBytecodeUrl);
  pyodide = await module.loadPyodide({ indexURL: indexUrl });
  timings.boot = since();

  status("numpy", "Loading numpy");
  await pyodide.loadPackage(["numpy"]);
  timings.packages = since();

  status("importing", "Loading AutoCircuit");
  const numpyOverlay = await bytecode;
  if (numpyOverlay !== null) {
    pyodide.unpackArchive(numpyOverlay, "zip", { extractDir: sitePackages() });
  }
  pyodide.unpackArchive(await archive, "zip", { extractDir: "/autocircuit-src" });
  timings.unpack = since();

  pyodide.runPython(`
import sys
sys.path.insert(0, "/autocircuit-src")
from autocircuit.web import handle
`);
  handle = pyodide.globals.get("handle");
  timings.importing = since();

  const answer = JSON.parse(call(JSON.stringify({ op: "version" })));
  if (!answer.ok) throw new Error(answer.error.message);
  const versions = answer.result as VersionsWire;
  lightOperations = new Set(versions.light_operations);
  if (versions.bridge !== BRIDGE_VERSION) {
    // A cached bundle talking to a freshly deployed core, or the reverse. Saying so is the
    // whole point of the version: the alternative is a plausible-looking wrong answer.
    throw new Error(
      `This page speaks bridge version ${BRIDGE_VERSION} but the Python core answers ` +
        `version ${versions.bridge}. Reload the page to pick up the matching build.`,
    );
  }
  status("data", "Ready to read data");
  return { versions, timings };
}

/**
 * Stage B: scipy, and the rest of the bridge.
 *
 * Started by the worker the moment stage A lands rather than waited for by anyone -- the page is
 * usable in the meantime, and a visitor who walks straight to the Fit screen finds this already
 * running. The import is driven by an ordinary `runtime` request, so the first thing to exercise
 * the fitter's import path is the same channel every later fit uses.
 */
async function loadFitting(scipyBytecodeUrl: string): Promise<void> {
  let mark = performance.now();
  const since = (): number => {
    const now = performance.now();
    const elapsed = now - mark;
    mark = now;
    return elapsed;
  };
  const timings: RuntimeTimings = { packages: 0, unpack: 0, importing: 0 };

  status("scipy", "Loading scipy");
  const bytecode = overlay(scipyBytecodeUrl);
  await pyodide.loadPackage(["scipy"]);
  timings.packages = since();

  // After the wheel, never before it. [measured] Laying scipy's __pycache__ into site-packages
  // ahead of `loadPackage("scipy")` leaves the package unimportable -- "cannot import name
  // 'loggamma' from 'scipy.special' (unknown location)" -- which is why the build writes two
  // overlays rather than one (`docs/STARTUP_AND_EDITING_PLAN.md` section 0).
  const scipyOverlay = await bytecode;
  if (scipyOverlay !== null) {
    pyodide.unpackArchive(scipyOverlay, "zip", { extractDir: sitePackages() });
  }
  timings.unpack = since();

  status("fitting", "Loading the fitter");
  const answer = JSON.parse(call(JSON.stringify({ op: "runtime" })));
  if (!answer.ok) throw new Error(answer.error.message);
  timings.importing = since();
  status("ready", "Ready");
  post({ kind: "runtime", runtime: answer.result as RuntimeWire, timings });
}

function call(request: string): string {
  if (handle === null) throw new Error("the worker has not finished loading");
  return handle(request);
}

/** Which stage an incoming request needs, read off the operation it names. */
function needsFitting(request: string): boolean {
  try {
    return !lightOperations.has(JSON.parse(request).op);
  } catch {
    // Malformed JSON is an error response the bridge writes, not something to decide here.
    return false;
  }
}

function upload(name: string, bytes: ArrayBuffer): string {
  if (pyodide === null) throw new Error("the worker has not finished loading");
  // Each file gets its own directory so that two files of the same name can be loaded at once
  // and so the path the reader records in the spectrum's metadata is the name the user knows.
  uploads += 1;
  const directory = `/uploads/${uploads}`;
  pyodide.FS.mkdirTree(directory);
  const path = `${directory}/${name.split(/[\\/]/).pop() || "data"}`;
  pyodide.FS.writeFile(path, new Uint8Array(bytes));
  return path;
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const message = event.data;
  try {
    switch (message.kind) {
      case "init": {
        const loaded = await init(
          message.pyodideUrl,
          message.indexUrl,
          message.archiveUrl,
          message.numpyBytecodeUrl,
        );
        post({ kind: "init", id: message.id, versions: loaded.versions, timings: loaded.timings });
        // Not awaited: the page is usable now, and this is what makes it more so. A failure
        // here leaves the Data screen working and says which half is broken.
        fitting = loadFitting(message.scipyBytecodeUrl).catch((error: unknown) => {
          post({ kind: "runtime-failed", message: String(error) });
          throw error;
        });
        // Nothing awaits `fitting` until a request needs it, and an unhandled rejection would
        // be reported as a worker error in the meantime.
        fitting.catch(() => {});
        break;
      }
      case "upload":
        post({ kind: "upload", id: message.id, path: upload(message.name, message.bytes) });
        break;
      case "call":
        if (needsFitting(message.request)) await fitting;
        post({ kind: "call", id: message.id, response: call(message.request) });
        break;
    }
  } catch (error) {
    post({ kind: "failed", id: message.id, message: String(error) });
  }
};
