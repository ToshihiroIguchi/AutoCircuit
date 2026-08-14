// Puts everything the browser needs to run the Python core into public/, which is otherwise
// empty and is not checked in. Two kinds of thing land there:
//
//   public/autocircuit-src.zip   the package itself, built by the same make_zip.py the Pyodide
//                                benchmark uses -- one archive builder, so the site and the
//                                benchmark cannot ship different cores.
//   public/pyodide/              the Pyodide distribution *including the numpy and scipy
//                                wheels*, which the npm package does not carry. Copied here so
//                                loadPackage resolves them beside pyodide-lock.json instead of
//                                reaching for a CDN: that is what makes the site work offline
//                                and what keeps a development machine off the network.
//
// Run by `npm run dev` and `npm run build`, so a change to the Python source is picked up
// without anyone having to remember a second command.
import { createWriteStream } from "node:fs";
import { copyFile, mkdir, readFile, stat } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const REPO = resolve(WEB, "..");
const PUBLIC = join(WEB, "public");
const PYODIDE_OUT = join(PUBLIC, "pyodide");
const PYODIDE_PKG = join(WEB, "node_modules", "pyodide");

// Everything loadPyodide fetches at run time. The source maps and the bundled consoles are
// deliberately left behind; they are several megabytes of things the site never asks for.
const RUNTIME_FILES = [
  "pyodide.mjs",
  "pyodide.asm.mjs",
  "pyodide.asm.wasm",
  "pyodide-lock.json",
  "python_stdlib.zip",
];

// The packages the core imports. numpy and scipy are the only runtime dependencies AutoCircuit
// has, which is what makes this list short enough to vendor -- see CLAUDE.md.
const WHEELS = ["numpy", "scipy"];

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

function buildSourceArchive() {
  const script = join(REPO, "benchmarks", "pyodide", "make_zip.py");
  const out = join(PUBLIC, "autocircuit-src.zip");
  const result = spawnSync("python", [script, "-o", out], { stdio: "inherit" });
  if (result.status !== 0) {
    throw new Error(`make_zip.py failed (exit ${result.status}); is python on PATH?`);
  }
}

async function copyRuntime() {
  await mkdir(PYODIDE_OUT, { recursive: true });
  for (const name of RUNTIME_FILES) {
    await copyFile(join(PYODIDE_PKG, name), join(PYODIDE_OUT, name));
  }
  console.log(`pyodide runtime -> ${PYODIDE_OUT} (${RUNTIME_FILES.length} files)`);
}

async function copyWheels() {
  const lock = JSON.parse(await readFile(join(PYODIDE_PKG, "pyodide-lock.json"), "utf8"));
  const version = JSON.parse(await readFile(join(PYODIDE_PKG, "package.json"), "utf8")).version;
  for (const name of WHEELS) {
    const entry = lock.packages[name];
    if (!entry) throw new Error(`pyodide-lock.json has no package ${name}`);
    const target = join(PYODIDE_OUT, entry.file_name);
    if (await exists(target)) continue;

    // The npm package ships the runtime but not the wheels, except that running Pyodide under
    // Node once leaves them cached in its directory. Prefer whatever is already on disk --
    // node_modules here, then the benchmark's -- and only then the network.
    const local = [
      join(PYODIDE_PKG, entry.file_name),
      join(REPO, "benchmarks", "pyodide", "node_modules", "pyodide", entry.file_name),
    ];
    let copied = false;
    for (const candidate of local) {
      if (await exists(candidate)) {
        await copyFile(candidate, target);
        console.log(`${entry.file_name} <- ${candidate}`);
        copied = true;
        break;
      }
    }
    if (copied) continue;

    const url = `https://cdn.jsdelivr.net/pyodide/v${version}/full/${entry.file_name}`;
    console.log(`${entry.file_name} <- ${url}`);
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url} -> HTTP ${response.status}`);
    await pipeline(Readable.fromWeb(response.body), createWriteStream(target));
  }
}

await mkdir(PUBLIC, { recursive: true });
buildSourceArchive();
await copyRuntime();
await copyWheels();
