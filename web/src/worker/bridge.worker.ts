/// <reference lib="webworker" />
// Holds one Pyodide instance and forwards requests to `autocircuit.web.bridge.handle`.
//
// Pyodide is imported from a URL the main thread computed, not from the `pyodide` npm package:
// the distribution loads its own Emscripten glue and its wasm relative to `indexURL`, which a
// bundler cannot rewrite, so it is served from public/ as-is and imported at run time.

import {
  BRIDGE_VERSION,
  type LoadTimings,
  type WorkerRequest,
  type WorkerResponse,
} from "./protocol";
import type { VersionsWire } from "../core/types";

declare const self: DedicatedWorkerGlobalScope;

// Pyodide's own typings describe the npm entry point, which is not how it is loaded here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Pyodide = any;

let pyodide: Pyodide | null = null;
let handle: ((request: string) => string) | null = null;
let uploads = 0;

function post(message: WorkerResponse): void {
  self.postMessage(message);
}

function status(stage: "booting" | "packages" | "importing" | "ready", detail: string): void {
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
// can, which is what section 1.4 of docs/METRICS_AND_UX_PLAN.md is about. Do not re-add this
// without a measurement of the *total*, on a real network: the stage breakdown alone says the
// flattering half.

async function init(
  pyodideUrl: string,
  indexUrl: string,
  archiveUrl: string,
  bytecodeUrl: string,
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
  // Both archives are wanted the moment the wheels are in, and neither depends on the
  // interpreter existing, so they are asked for now and awaited later.
  const archive = download(archiveUrl);
  // The overlay below is an optimisation, so its absence is caught here rather than left to
  // reject an init that would otherwise have succeeded.
  const bytecode = download(bytecodeUrl).catch((error: unknown) => {
    console.warn(`AutoCircuit: no bytecode overlay, importing from source (${String(error)})`);
    return null;
  });
  pyodide = await module.loadPyodide({ indexURL: indexUrl });
  timings.boot = since();

  status("packages", "Loading numpy and scipy");
  await pyodide.loadPackage(["numpy", "scipy"]);
  timings.packages = since();

  status("importing", "Loading AutoCircuit");
  // The bytecode overlay goes on top of the installed wheels: `__pycache__` folders holding a
  // .pyc for every numpy and scipy module this page imports, compiled by the build (see
  // `web/scripts/precompile.mjs`). Without it every visitor compiles them again.
  const overlay = await bytecode;
  if (overlay !== null) {
    const site: string = pyodide.runPython(`
import sys
next(p for p in sys.path if p.endswith("site-packages"))
`);
    pyodide.unpackArchive(overlay, "zip", { extractDir: site });
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
  if (versions.bridge !== BRIDGE_VERSION) {
    // A cached bundle talking to a freshly deployed core, or the reverse. Saying so is the
    // whole point of the version: the alternative is a plausible-looking wrong answer.
    throw new Error(
      `This page speaks bridge version ${BRIDGE_VERSION} but the Python core answers ` +
        `version ${versions.bridge}. Reload the page to pick up the matching build.`,
    );
  }
  status("ready", "Ready");
  return { versions, timings };
}

function call(request: string): string {
  if (handle === null) throw new Error("the worker has not finished loading");
  return handle(request);
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
          message.bytecodeUrl,
        );
        post({ kind: "init", id: message.id, versions: loaded.versions, timings: loaded.timings });
        break;
      }
      case "upload":
        post({ kind: "upload", id: message.id, path: upload(message.name, message.bytes) });
        break;
      case "call":
        post({ kind: "call", id: message.id, response: call(message.request) });
        break;
    }
  } catch (error) {
    post({ kind: "failed", id: message.id, message: String(error) });
  }
};
