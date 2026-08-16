// Ships bytecode instead of source, so the browser does not compile Python on every visit.
//
// Nothing here changes what runs; it changes when it was compiled. A CPython import of a .py
// file parses and compiles it, then caches the result in a __pycache__ next to it -- which in a
// browser is a filesystem that dies with the tab, so every visitor pays the compile again. The
// interpreter is 3-5x slower under wasm than under Node (`docs/WEB_UI_PLAN.md` section 2.3),
// and compiling is exactly the interpreter-bound work that ratio is about.
//
// [measured, Node] boot 0.91 s -> 0.20 s, and `import autocircuit.web` (numpy and scipy with it)
// 2.64 s -> 1.01 s. Three artefacts come out:
//
//   public/pyodide/python_stdlib.zip  the stdlib Pyodide boots from, with a .pyc beside every
//                                     .py. zipimport prefers the .pyc, so the boot stops
//                                     compiling 559 modules. 2.5 MB -> 7.1 MB.
//   public/pyodide-bytecode-numpy.zip a __pycache__ overlay for numpy, unpacked into
//   public/pyodide-bytecode-scipy.zip site-packages after the matching wheel is installed.
//   public/autocircuit-src.zip        rewritten with this package's own __pycache__ folded in.
//
// Two overlays rather than one, because the page installs the two wheels at different times: the
// Data screen comes up on numpy and scipy follows behind it
// (`docs/STARTUP_AND_EDITING_PLAN.md` section 3). [measured] The single overlay could not simply
// be unpacked early and left to wait for its wheel -- laying scipy's __pycache__ into
// site-packages *before* `loadPackage("scipy")` gives `ImportError: cannot import name
// 'loggamma' from 'scipy.special' (unknown location)`. Each overlay goes on after its own wheel.
//
// The bytecode is compiled *inside Pyodide*, because a .pyc is only valid for the interpreter
// that wrote it and this machine's Python is not the one the browser runs -- 3.13 here, 3.14
// there. That is also why this is a build step and not something checked in.
//
// No .pyc here is timestamp-invalidated (PEP 552 hash invalidation throughout). A timestamp
// would compare against an mtime the browser invents when it unpacks the wheels, so every .pyc
// would read as stale and be silently recompiled, buying nothing. Which *kind* of hash
// invalidation each artefact gets is decided by whether its bytecode can ever be paired with a
// source it was not compiled from:
//
//   stdlib zip      UNCHECKED: source and bytecode travel in one file, so they cannot separate.
//   overlay         CHECKED:   a browser could hold this in its cache across a Pyodide upgrade
//                              and lay it over wheels it was not built from. Checked bytecode
//                              is recompiled when it does not match; unchecked bytecode would
//                              simply run, which is the kind of wrong that is never noticed.
//   package archive CHECKED:   same reasoning, and it is 29 modules to hash rather than 576.
import { createHash } from "node:crypto";
import { readFile, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { loadPyodide } from "pyodide";

// Bumping this invalidates every stamp, for when the recipe below changes rather than its input.
// 2: one overlay became two, split at the load stage each belongs to.
// 3: the split is taken between two imports rather than by top-level package, because the first
//    import no longer reaches scipy at all -- which had quietly left the scipy overlay empty.
const RECIPE_VERSION = 3;

const STAMP = ".bytecode-stamp";

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

/** What the outputs were built from: change any of it and they are rebuilt. */
async function stampOf(pyodidePkg, sourceArchive) {
  const version = JSON.parse(await readFile(join(pyodidePkg, "package.json"), "utf8")).version;
  const source = createHash("sha256").update(await readFile(sourceArchive)).digest("hex");
  return `${RECIPE_VERSION} pyodide-${version} src-${source}`;
}

/**
 * Rebuild the three artefacts, unless they are already the ones this input produces.
 *
 * Both `python_stdlib.zip` and the package archive the browser fetches are outputs of this step
 * rather than copies made earlier, so a skipped rebuild cannot leave a source-only file where a
 * compiled one is expected. That is why the package archive is read from `sourceArchive`, which
 * is somewhere else entirely: this step's input and its output would otherwise be one path,
 * whose content decides whether the step is skipped.
 */
export async function precompile(publicDir, pyodidePkg, sourceArchive) {
  const pyodideOut = join(publicDir, "pyodide");
  const stdlibOut = join(pyodideOut, "python_stdlib.zip");
  const numpyOut = join(publicDir, "pyodide-bytecode-numpy.zip");
  const scipyOut = join(publicDir, "pyodide-bytecode-scipy.zip");
  const archiveOut = join(publicDir, "autocircuit-src.zip");
  const stampPath = join(publicDir, STAMP);

  // public/ is not checked in and is not emptied between builds, and `vite build` copies whatever
  // is in it into dist/. A tree that predates the split would therefore publish the 5.8 MB
  // single overlay that nothing fetches any more.
  await rm(join(publicDir, "pyodide-bytecode.zip"), { force: true });

  const stamp = await stampOf(pyodidePkg, sourceArchive);
  const built =
    (await exists(stdlibOut)) &&
    (await exists(numpyOut)) &&
    (await exists(scipyOut)) &&
    (await exists(archiveOut));
  const previous = (await exists(stampPath)) ? await readFile(stampPath, "utf8") : "";
  if (built && previous === stamp) {
    console.log("bytecode is up to date");
    return;
  }

  // The interpreter comes from node_modules, so this step never reads its own output: the
  // stdlib it boots from is the one that ships, and public/ holds only what is written here.
  // `packageCacheDir` is what keeps the build off the network -- loadPackage looks there before
  // it reaches for the CDN, and the wheels were vendored into it a moment ago. (Naming the
  // wheel files directly does not work: Pyodide derives a package name from the string it is
  // given, and an absolute Windows path is not one.)
  const pristine = new Uint8Array(await readFile(join(pyodidePkg, "python_stdlib.zip")));
  const pyodide = await loadPyodide({
    indexURL: pyodidePkg,
    packageCacheDir: pyodideOut,
    stdout: () => {},
  });
  await pyodide.loadPackage(["numpy", "scipy"], { messageCallback: () => {} });

  pyodide.FS.writeFile("/build-stdlib.zip", pristine);
  pyodide.unpackArchive(new Uint8Array(await readFile(sourceArchive)), "zip", {
    extractDir: "/autocircuit-src",
  });

  // `import autocircuit.web` and then `autocircuit.web.bridge` is the whole import set the page
  // pays for, in the two instalments the page pays it in: a read, a fit and a validate through
  // the bridge add five modules to the 969 those two pulled in, so there is nothing to gain from
  // driving a request here.
  const compile = pyodide.runPython(`
import io, os, py_compile, sys, zipfile

sys.path.insert(0, "/autocircuit-src")
# Two imports, and the snapshot between them is what splits the overlays. The first is the data
# path -- what the browser's first stage imports -- and the second is everything else. Splitting
# by *when* a module was imported rather than by which wheel it belongs to is what keeps stage A
# from carrying bytecode only the fitter will ever use.
from autocircuit.web import handle  # noqa: F401  -- imported for its side effect on sys.modules

UNCHECKED = py_compile.PycInvalidationMode.UNCHECKED_HASH
CHECKED = py_compile.PycInvalidationMode.CHECKED_HASH
SITE = next(p for p in sys.path if p.endswith("site-packages"))


def compile_tree(root, mode):
    """Compile every source under *root*, returning the bytecode paths."""
    made = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if not name.endswith(".py"):
                continue
            source = os.path.join(dirpath, name)
            try:
                made.append(py_compile.compile(source, doraise=True, invalidation_mode=mode))
            except Exception as exc:  # a module that cannot compile is one that is not shipped
                print(f"  skipped {source}: {exc}")
    return made


def zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in entries:
            archive.write(path, arcname.replace(os.sep, "/"))
    return buf.getvalue()


# -- the stdlib -------------------------------------------------------------------------------
# zipimport has no notion of __pycache__: it looks for foo.pyc beside foo.py and prefers it,
# so the bytecode is moved out of the folder compileall put it in. The sources stay, both for
# tracebacks and so that anything this misses still imports.
with zipfile.ZipFile("/build-stdlib.zip") as archive:
    archive.extractall("/build-stdlib")
entries = []
for path in compile_tree("/build-stdlib", UNCHECKED):
    folder = os.path.dirname(os.path.dirname(path))
    stem = os.path.basename(path).rsplit(".", 2)[0]
    entries.append((path, os.path.relpath(os.path.join(folder, stem + ".pyc"), "/build-stdlib")))
for dirpath, dirs, files in os.walk("/build-stdlib"):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for name in files:
        path = os.path.join(dirpath, name)
        entries.append((path, os.path.relpath(path, "/build-stdlib")))
stdlib = zip_bytes(entries)

# -- numpy and scipy --------------------------------------------------------------------------
# Only what the imports actually touched. Compiling all of scipy would be ~1000 modules against
# the ~500 a session imports, and an overlay is downloaded on every cold visit; anything not in
# one still imports from source.
#
# Two archives, one per load stage, because the browser installs the wheels at different times
# and an overlay laid down before its wheel breaks the import (see the header).
def installed_sources():
    """Every site-packages source file imported so far."""
    return {
        path
        for path in (getattr(module, "__file__", None) for module in list(sys.modules.values()))
        if path and path.endswith(".py") and path.startswith(SITE)
    }


def overlay_of(sources):
    """The __pycache__ archive for a set of source files, as paths relative to site-packages."""
    return zip_bytes(
        [
            (cached, os.path.relpath(cached, SITE))
            for cached in (
                py_compile.compile(source, doraise=True, invalidation_mode=CHECKED)
                for source in sorted(sources)
            )
        ]
    )


numpy_sources = installed_sources()
import autocircuit.web.bridge  # noqa: F401  -- the rest of the bridge, which is what needs scipy

scipy_sources = installed_sources() - numpy_sources
numpy_overlay = overlay_of(numpy_sources)
scipy_overlay = overlay_of(scipy_sources)

# -- this package -----------------------------------------------------------------------------
# Written into the archive the browser fetches, beside the sources it was compiled from, so the
# two are one download and cannot be cached apart from one another.
compile_tree("/autocircuit-src", CHECKED)
package = zip_bytes(
    [
        (os.path.join(dirpath, name), os.path.relpath(os.path.join(dirpath, name), "/autocircuit-src"))
        for dirpath, _dirs, files in os.walk("/autocircuit-src")
        for name in files
    ]
)
(stdlib, numpy_overlay, scipy_overlay, package, len(numpy_sources), len(scipy_sources))
`);

  const [stdlib, numpyOverlay, scipyOverlay, packageZip, numpyCount, scipyCount] = compile.toJs();
  compile.destroy();
  await writeFile(stdlibOut, Buffer.from(stdlib));
  await writeFile(numpyOut, Buffer.from(numpyOverlay));
  await writeFile(scipyOut, Buffer.from(scipyOverlay));
  await writeFile(archiveOut, Buffer.from(packageZip));
  await writeFile(stampPath, stamp, "utf8");
  const mb = (bytes) => `${(bytes.length / 1e6).toFixed(1)} MB`;
  console.log(
    `bytecode: stdlib ${mb(pristine)} -> ${mb(stdlib)}, ` +
      `numpy overlay ${mb(numpyOverlay)} (${numpyCount} modules), ` +
      `scipy overlay ${mb(scipyOverlay)} (${scipyCount} modules), ` +
      `package ${mb(packageZip)}`,
  );
}
