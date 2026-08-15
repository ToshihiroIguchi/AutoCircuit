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

/** One entry of `public/samples/index.json`, as `build-assets.mjs` writes it. */
export interface Sample {
  id: string;
  label: string;
  /** The circuit the data was generated from. Shown, never hidden: see the note above. */
  circuit: string;
  params: Record<string, number>;
  fMin: number;
  fMax: number;
  pointsPerDecade: number;
  /** Relative noise the sample was generated with, as a fraction. */
  noise: number;
  seed: number;
  /** The part of `circuit` a user of this kind of sample would already know -- a mode-2 skeleton. */
  skeleton: string;
  blurb: string;
  /** Path relative to the site's base URL. */
  file: string;
  /** The command line that produced the file, runnable from a clone of the repository. */
  command: string;
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
 * The name is the one the manifest gives it, which is what the spectrum will be labelled with and
 * what the reader will name in any complaint about it.
 */
export async function fetchSample(sample: Sample): Promise<File> {
  const url = siteUrl(sample.file);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${sample.file} -> HTTP ${response.status}`);
  const blob = await response.blob();
  return new File([blob], `${sample.id}.csv`, { type: "text/csv" });
}
