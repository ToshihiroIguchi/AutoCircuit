/// <reference lib="webworker" />
// Holds one Pyodide instance and forwards requests to `autocircuit.web.bridge.handle`.
//
// Pyodide is imported from a URL the main thread computed, not from the `pyodide` npm package:
// the distribution loads its own Emscripten glue and its wasm relative to `indexURL`, which a
// bundler cannot rewrite, so it is served from public/ as-is and imported at run time.

import { BRIDGE_VERSION, type WorkerRequest, type WorkerResponse } from "./protocol";
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

async function init(pyodideUrl: string, indexUrl: string, archiveUrl: string): Promise<VersionsWire> {
  status("booting", "Starting the Python runtime");
  const module = await import(/* @vite-ignore */ pyodideUrl);
  pyodide = await module.loadPyodide({ indexURL: indexUrl });

  status("packages", "Loading numpy and scipy");
  await pyodide.loadPackage(["numpy", "scipy"]);

  status("importing", "Loading AutoCircuit");
  const archive = await fetch(archiveUrl);
  if (!archive.ok) throw new Error(`${archiveUrl} -> HTTP ${archive.status}`);
  pyodide.unpackArchive(new Uint8Array(await archive.arrayBuffer()), "zip", {
    extractDir: "/autocircuit-src",
  });
  pyodide.runPython(`
import sys
sys.path.insert(0, "/autocircuit-src")
from autocircuit.web import handle
`);
  handle = pyodide.globals.get("handle");

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
  return versions;
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
      case "init":
        post({
          kind: "init",
          id: message.id,
          versions: await init(message.pyodideUrl, message.indexUrl, message.archiveUrl),
        });
        break;
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
