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

export function SamplePanel({
  disabled,
  onFile,
}: {
  disabled: boolean;
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
        Synthetic spectra, each generated from a known circuit with proportional noise — the same
        three references this project measures its discovery gates against. They are here to try
        the program on, not to stand in for a measurement.
      </p>

      {error !== null && <p className="sample-panel__error">{error}</p>}

      <ul className="sample-panel__list">
        {(samples ?? []).map((sample) => (
          <li key={sample.id} className="sample-panel__item">
            <div className="sample-panel__row">
              <button
                type="button"
                className="sample-panel__load"
                disabled={disabled || busy !== null}
                onClick={() => void load(sample)}
              >
                {busy === sample.id ? "Loading…" : "Load"}
              </button>
              <span className="sample-panel__label">{sample.label}</span>
              <code className="sample-panel__circuit">{sample.circuit}</code>
              <span className="sample-panel__meta">
                {formatSiRange(sample.fMin, sample.fMax, "Hz")} · {formatPercent(sample.noise, 0)}{" "}
                noise
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
