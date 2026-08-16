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

/**
 * Start fetching the numpy and scipy wheels now, and hand them to `loadPackage` later.
 *
 * They are 17 MB of the site's 41, and nothing about them depends on the interpreter existing --
 * but `loadPackage` cannot be called until `loadPyodide()` has resolved, and that call first
 * fetches the 9.6 MB wasm and the 7.1 MB stdlib. So without this they sit behind a barrier they
 * do not need, and the download begins only once the boot has finished
 * (docs/METRICS_AND_UX_PLAN.md section 1).
 *
 * [measured] The obvious version of this -- `<link rel="preload">` in index.html -- does not
 * work and is not merely useless: a document's preload cache does not serve a *worker's* fetch,
 * so Chrome fetched all 17 MB a second time and logged "preloaded ... but not used". Hence the
 * interception here, in the same context as the fetch it is feeding.
 *
 * Matching is by file name rather than by whole URL, because the string `loadPackage` builds
 * from `indexURL` need not be character-for-character what this function built. Anything that
 * goes wrong -- no manifest, a failed fetch -- falls back to the network, which is what would
 * have happened anyway. Returns a function that puts the real `fetch` back.
 */
async function prefetchWheels(indexUrl: string): Promise<() => void> {
  const base = indexUrl.endsWith("/") ? indexUrl : `${indexUrl}/`;
  let names: string[];
  try {
    const response = await fetch(`${base}wheels.json`);
    if (!response.ok) return () => {};
    names = (await response.json()) as string[];
  } catch {
    return () => {};
  }
  if (names.length === 0) return () => {};

  // Resolves to null rather than rejecting, so a failed prefetch costs a re-fetch and not a
  // failed boot.
  const pending = new Map<string, Promise<Response | null>>();
  for (const name of names) {
    pending.set(
      name,
      fetch(`${base}${name}`).then(
        (response) => (response.ok ? response : null),
        () => null,
      ),
    );
  }

  const original = self.fetch.bind(self);
  self.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
    for (const [name, promise] of pending) {
      if (!url.endsWith(name)) continue;
      pending.delete(name);
      return promise.then((response) =>
        response === null ? original(input, init) : response.clone(),
      );
    }
    return original(input, init);
  }) as typeof fetch;

  return () => {
    self.fetch = original;
  };
}

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
  // The wheels are wanted after the boot and depend on nothing in it, so the transfer starts
  // here and overlaps it; see prefetchWheels.
  const restoreFetch = await prefetchWheels(indexUrl);
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
  try {
    await pyodide.loadPackage(["numpy", "scipy"]);
  } finally {
    restoreFetch();
  }
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
