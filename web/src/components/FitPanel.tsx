// The Fit controls and what came back. Every number shown here was computed by the same
// `autocircuit.core.fit.fit` the command line calls, and the text at the bottom is that call's
// own report, carried verbatim rather than paraphrased -- the same rule the Lin-KK panel
// follows on the Data screen.

import type { FitWire, PreviewWire } from "../core/types";
import { decodeFloat } from "../core/wire";
import { formatNumber, formatPercent } from "../utils/format";

/** `sigma` is left out: it needs per-point standard deviations, which no reader supplies yet. */
const WEIGHTINGS = ["modulus", "proportional", "unit"];

export interface FitPanelProps {
  fit: FitWire | null;
  preview: PreviewWire | null;
  weighting: string;
  restarts: number;
  seed: number;
  fitting: boolean;
  disabled: boolean;
  error: string | null;
  onWeighting: (value: string) => void;
  onRestarts: (value: number) => void;
  onSeed: (value: number) => void;
  onFit: () => void;
}

export function FitPanel(props: FitPanelProps) {
  const stats = props.fit?.fit.statistics ?? null;

  return (
    <section className="fit-panel">
      <h2 className="panel-title">Fit</h2>

      <div className="fit-panel__controls">
        <label>
          Weighting
          <select
            value={props.weighting}
            disabled={props.disabled}
            onChange={(event) => props.onWeighting(event.target.value)}
          >
            {WEIGHTINGS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Restarts
          <input
            type="number"
            min={1}
            max={20}
            value={props.restarts}
            disabled={props.disabled}
            onChange={(event) => props.onRestarts(Number(event.target.value))}
          />
        </label>
        <label>
          Seed
          <input
            type="number"
            value={props.seed}
            disabled={props.disabled}
            onChange={(event) => props.onSeed(Number(event.target.value))}
          />
        </label>
        <button
          type="button"
          className="fit-panel__run"
          disabled={props.disabled || props.fitting}
          onClick={props.onFit}
        >
          {props.fitting ? "Fitting…" : "Fit"}
        </button>
      </div>

      {props.error !== null && (
        <p className="fit-panel__error" role="alert">
          {props.error}
        </p>
      )}

      {props.fit === null ? (
        <p className="fit-panel__pending">
          {props.fitting
            ? "Searching the parameter space. No starting values are needed, so this is a global search."
            : props.preview === null
              ? "Draw a circuit to preview it against the data."
              : `Not fitted. The preview curve is ${formatPercent(
                  decodeFloat(props.preview.relative_error),
                  1,
                )} from the data, at the values the fitter would start from.`}
        </p>
      ) : (
        <>
          <p
            className={`fit-panel__status${
              props.fit.fit.success ? "" : " fit-panel__status--failed"
            }`}
          >
            {props.fit.fit.success ? "Converged" : "FAILED"} — {props.fit.fit.message}, in{" "}
            {formatNumber(decodeFloat(props.fit.fit.elapsed_s), 3)} s
          </p>
          <dl className="fit-panel__stats">
            <div>
              <dt>RMS relative |Z| error</dt>
              <dd>{formatPercent(decodeFloat(props.fit.relative_error), 3)}</dd>
            </div>
            <div>
              <dt>chi² (reduced)</dt>
              <dd>{stats === null ? "" : formatNumber(decodeFloat(stats.chi2_reduced), 5)}</dd>
            </div>
            <div>
              <dt>AICc</dt>
              <dd>{stats === null ? "" : formatNumber(decodeFloat(stats.aicc), 6)}</dd>
            </div>
            <div>
              <dt>Points / free parameters</dt>
              <dd>
                {stats === null ? "" : `${stats.n_data / 2} / ${stats.n_params}`}
              </dd>
            </div>
          </dl>
          {props.fit.warnings.length > 0 && (
            <ul className="fit-panel__warnings">
              {props.fit.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <details className="fit-panel__report">
            <summary>Full report</summary>
            <pre>{props.fit.summary}</pre>
          </details>
        </>
      )}
    </section>
  );
}
