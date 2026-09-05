// The example datasets shipped beside the site.
//
// They are not fixtures invented for the browser: they are the three reference spectra
// `benchmarks/discovery_v2.py` measures every discovery gate against, generated at build time by
// the project's own `simulate` command (`web/scripts/build-assets.mjs`). The manifest is written
// by that script, so the description of a sample cannot drift from the file it describes -- and it
// carries the exact command line that produced each one, because a synthetic spectrum whose recipe
// is hidden is a demo rather than an example.
//
// A loaded sample takes the path a dropped file takes -- bytes into the Pyodide filesystem, read
// back by `autocircuit.io.read_many` -- so it exercises the reader rather than bypassing it.

/**
 * One entry of `public/samples/index.json`, as `build-assets.mjs` writes it.
 *
 * Every field except `id`, `source`, `group`, `label`, `file` and `measured` is specific to one
 * of the two kinds of row. A synthetic row (`measured` absent or false) carries the fields a
 * generated spectrum has: a circuit, the parameters, the sweep, the noise, and the command that
 * reproduces it. A measured row (`measured: true`) carries none of those -- there is no circuit
 * to name until discovery runs, and no command, because nothing here generated the file -- and
 * instead carries what a real file needs: what physical system it is, where it came from, and
 * under what licence. See `docs/IMPACT_PLAN.md` item C and `scripts/measured-samples.mjs`.
 */
export interface Sample {
  id: string;
  /**
   * Which benchmark entry this is a copy of, as `<list>:<label>` for a synthetic row or
   * `measured:<dataset id>` for a measured one.
   *
   * Not shown. It exists so `scripts/samples-check.mjs` can compare every field against the
   * Python list and `npm run check` can refuse to publish an example that has drifted from the
   * case it names.
   */
  source: string;
  /** Which heading the row appears under: "Shapes", "Devices" or "Measured". A UI grouping. */
  group: string;
  label: string;
  blurb?: string;
  /** Path relative to the site's base URL. */
  file: string;

  // -- synthetic rows only --
  /** The circuit the data was generated from. Shown, never hidden: see the note above. */
  circuit?: string;
  params?: Record<string, number>;
  fMin?: number;
  fMax?: number;
  pointsPerDecade?: number;
  /** Relative noise the sample was generated with, as a fraction. */
  noise?: number;
  seed?: number;
  /** The part of `circuit` a user of this kind of sample would already know -- a mode-2 skeleton. */
  skeleton?: string;
  /** The command line that produced the file, runnable from a clone of the repository. */
  command?: string;

  // -- measured rows only --
  measured?: boolean;
  /** What physical system this is, as far as the source states it. */
  system?: string;
  sourceUrl?: string;
  license?: string;
  /** Which real-instrument artefact this dataset was chosen to exhibit. */
  artefact?: string;
  /** A circuit the *source* fitted, in AutoCircuit DSL -- a citation, never a truth. */
  publishedCircuit?: string;
  publishedCircuitNote?: string;
}

function siteUrl(path: string): string {
  // Same rule as the bridge client's: resolve against the app's base rather than the module's own
  // location, because a hashed bundle in assets/ says nothing about where public/ ended up.
  return new URL(path, new URL(import.meta.env.BASE_URL, window.location.href)).href;
}

/** The manifest, or an empty list if the site was built without one. */
export async function loadSamples(): Promise<Sample[]> {
  const response = await fetch(siteUrl("samples/index.json"));
  if (!response.ok) throw new Error(`samples/index.json -> HTTP ${response.status}`);
  const parsed: unknown = await response.json();
  if (!Array.isArray(parsed)) throw new Error("samples/index.json is not a list");
  return parsed as Sample[];
}

/**
 * Fetches one sample as a `File`, so it can be handed to the same loader a drop uses.
 *
 * A synthetic sample is always the `simulate` command's own CSV, so it is named `<id>.csv`. A
 * measured sample keeps the real file's own extension (`.mpt`, `.DTA`, ...): the browser's
 * upload path threads only a filename into Pyodide's virtual filesystem
 * (`bridge.worker.ts`'s `upload()`), and `autocircuit.io.read`'s format sniffing keys off that
 * extension, the same way it would for a file the user dropped from disk.
 */
export async function fetchSample(sample: Sample): Promise<File> {
  const url = siteUrl(sample.file);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${sample.file} -> HTTP ${response.status}`);
  const blob = await response.blob();
  const name = sample.measured === true ? sample.file.split("/").pop()! : `${sample.id}.csv`;
  return new File([blob], name, { type: sample.measured === true ? "" : "text/csv" });
}
