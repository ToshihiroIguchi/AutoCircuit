// One-off tool for docs/SEARCH_TIME_PLAN.md §8 / STARTUP_AND_EDITING_PLAN.md §3's stdlib-
// bytecode wire-cost measurement: switches public/pyodide/python_stdlib.zip between the
// bytecode-compiled artefact the shipped site uses and a pristine (source-only) copy, in
// place, via `precompile.mjs`'s own `skipStdlibBytecode` option -- nothing else in public/
// changes. Not part of `npm run dev`/`npm run build`; run by hand, then `vite build --outDir
// <variant>` picks up whichever state public/ is currently in.
//
//   node scripts/set-stdlib-variant.mjs baseline   # restores the shipped, bytecode-compiled stdlib
//   node scripts/set-stdlib-variant.mjs nostdlib   # swaps in the pristine, source-only stdlib
//
// Requires `npm run assets` to have populated public/ already (source archive, wheels, runtime).
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { precompile } from "./precompile.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const PUBLIC = join(WEB, "public");
const SOURCE_ARCHIVE = join(WEB, ".build", "autocircuit-source.zip");
const PYODIDE_PKG = join(WEB, "node_modules", "pyodide");

const variant = process.argv[2];
if (!["baseline", "nostdlib"].includes(variant)) {
  console.error("usage: node scripts/set-stdlib-variant.mjs <baseline|nostdlib>");
  process.exit(1);
}
await precompile(PUBLIC, PYODIDE_PKG, SOURCE_ARCHIVE, {
  skipStdlibBytecode: variant === "nostdlib",
});
