// The example datasets, offered where a file would otherwise have to be dropped.
//
// Each row says what the sample is *for*, and then says the thing a demo would leave out: this is
// synthetic data, here is the circuit it was generated from, here is the noise, and here is the
// command that made it. Someone who then runs a search and gets that circuit back has watched the
// program pass a test whose answer was printed beside it -- which is a fair thing to show, and only
// fair while it is labelled.

import { useEffect, useState } from "react";
import { fetchSample, loadSamples, type Sample } from "../core/samples";
import { formatPercent, formatSiRange } from "../utils/format";

/**
 * The samples under their headings, in manifest order.
 *
 * The list grew from five to thirteen when the device cases were added, and thirteen blurbed rows
 * is a wall rather than a menu. The grouping is the manifest's own `group` field, so the page
 * cannot invent a category the data does not carry; a Map preserves first-seen order, so the
 * headings appear in the order `scripts/samples.mjs` lists them rather than alphabetically.
 */
function groupsOf(samples: Sample[]): Array<[string, Sample[]]> {
  const groups = new Map<string, Sample[]>();
  for (const sample of samples) {
    const key = sample.group || "Examples";
    const rows = groups.get(key);
    if (rows === undefined) groups.set(key, [sample]);
    else rows.push(sample);
  }
  return Array.from(groups);
}

/**
 * The Load buttons are live from the first paint, not from the moment Python is up.
 *
 * They used to be disabled until the whole runtime had loaded, which is what "not even the
 * example loads" was about (`docs/STARTUP_AND_EDITING_PLAN.md` section 3.4). The manifest and the
 * CSV are a few kB from the same origin; the fetched file is handed to `App`, which holds it
 * until the reader exists and names it in a pending row meanwhile. Clicking early now costs a
 * wait that was going to happen anyway, instead of a second click.
 */
export function SamplePanel({
  dataReady,
  onFile,
}: {
  /** Whether the reader exists yet; used only to label the buttons honestly. */
  dataReady: boolean;
  /** Handed the fetched file, which then takes the path a dropped one takes. */
  onFile: (file: File) => void;
}) {
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let live = true;
    loadSamples()
      .then((list) => {
        if (live) setSamples(list);
      })
      .catch((err: unknown) => {
        if (live) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      live = false;
    };
  }, []);

  async function load(sample: Sample): Promise<void> {
    setBusy(sample.id);
    setError(null);
    try {
      onFile(await fetchSample(sample));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  // Nothing to say while the manifest is in flight: it is a few hundred bytes from the same origin
  // and the page has a Pyodide runtime to load in the meantime.
  if (samples === null && error === null) return null;

  return (
    <section className="sample-panel">
      <h2 className="panel-title">Example data</h2>
      <p className="sample-panel__intro">
        Synthetic spectra, each generated from a known circuit with proportional noise — every one
        of them a case this project measures itself against, in{" "}
        <code>benchmarks/discovery_v2.py</code> or <code>benchmarks/fitting.py</code>. They are
        here to try the program on, not to stand in for a measurement. <em>Shapes</em> are chosen
        for a feature of the impedance; <em>devices</em> are the circuits actually used to fit a
        named real part.
      </p>
      {!dataReady && (
        <p className="drop-zone__waiting">
          The reader is still loading, so these say Queue rather than Load: the file is fetched now
          and read the moment the reader is up.
        </p>
      )}

      {error !== null && <p className="sample-panel__error">{error}</p>}

      {groupsOf(samples ?? []).map(([group, rows]) => (
        <div key={group}>
          <h3 className="sample-panel__group">{group}</h3>
          <ul className="sample-panel__list">
            {rows.map((sample) => (
              <li key={sample.id} className="sample-panel__item">
                <div className="sample-panel__row">
                  <button
                    type="button"
                    className="sample-panel__load"
                    disabled={busy !== null}
                    onClick={() => void load(sample)}
                  >
                    {busy === sample.id ? "Loading…" : dataReady ? "Load" : "Queue"}
                  </button>
                  <span className="sample-panel__label">{sample.label}</span>
                  <code className="sample-panel__circuit">{sample.circuit}</code>
                  <span className="sample-panel__meta">
                    {formatSiRange(sample.fMin, sample.fMax, "Hz")} ·{" "}
                    {formatPercent(sample.noise, 0)} noise
                  </span>
                </div>
                <p className="sample-panel__blurb">{sample.blurb}</p>
                {expanded && (
                  <p className="sample-panel__command">
                    <code>{sample.command}</code>
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}

      {samples !== null && samples.length > 0 && (
        <button
          type="button"
          className="sample-panel__toggle"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={expanded}
        >
          {expanded ? "Hide the commands that made these" : "Show the commands that made these"}
        </button>
      )}
    </section>
  );
}
