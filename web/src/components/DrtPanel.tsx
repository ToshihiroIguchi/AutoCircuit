// The distribution-of-relaxation-times probe: a structure read *beside* the search, never fed
// back into it. `docs/DISCOVERY_V2_PLAN.md` section 3.4 is why -- a peak count read off a
// regularised inversion of noisy data must not be able to delete a topology from a search that
// still calls itself exhaustive. `well_described` gates the peaks table for the same reason a
// step further in: a spectrum the Debye model cannot represent still produces peaks, and they
// mean nothing, so a table under a hint that says so would contradict the hint. When that gate
// is closed this panel renders the hints and nothing else -- no table, no residual figures --
// because anything else here would itself be a claim the data does not support.

import type { DrtWire } from "../core/types";
import { decodeFloat } from "../core/wire";
import { formatNumber, formatPercent } from "../utils/format";

export interface DrtPanelProps {
  drt: DrtWire | null;
  running: boolean;
  error: string | null;
  disabled: boolean;
  onRun: () => void;
}

export function DrtPanel({ drt, running, error, disabled, onRun }: DrtPanelProps) {
  return (
    <section className="drt-panel">
      <h2 className="panel-title">Structure probe (DRT)</h2>

      {drt === null && (
        <p className="drt-panel__description">
          The distribution of relaxation times is a structure probe, read beside the search and
          never fed into it: a peak count read off a regularised inversion of noisy data must not
          be able to remove a topology from a search that calls itself exhaustive.
        </p>
      )}

      <button
        type="button"
        className="drt-panel__run"
        disabled={disabled || running}
        onClick={onRun}
      >
        {running ? "Probing…" : "Probe structure"}
      </button>

      {error !== null && (
        <p className="drt-panel__error" role="alert">
          {error}
        </p>
      )}

      {drt !== null && (
        <div className="drt-panel__result">
          <ul className="drt-panel__hints">
            {drt.hints.map((hint, index) => (
              <li key={index}>{hint}</li>
            ))}
          </ul>

          {drt.well_described && (
            <>
              {drt.peaks.length === 0 ? (
                <p className="empty-hint">No relaxations resolved.</p>
              ) : (
                <table className="drt-panel__peaks">
                  <thead>
                    <tr>
                      <th className="num">tau (s)</th>
                      <th className="num">Peak frequency (Hz)</th>
                      <th className="num">Weight (ohm)</th>
                      <th className="num">Width (decades)</th>
                      <th>Shape</th>
                    </tr>
                  </thead>
                  <tbody>
                    {drt.peaks.map((peak, index) => (
                      <tr key={index}>
                        <td className="num">{formatNumber(decodeFloat(peak.tau), 4)}</td>
                        <td className="num">{formatNumber(decodeFloat(peak.f_peak), 4)}</td>
                        <td className="num">{formatNumber(decodeFloat(peak.weight), 4)}</td>
                        <td className="num">{formatNumber(decodeFloat(peak.fwhm_decades), 4)}</td>
                        <td>
                          {peak.broadened && (
                            <span className="drt-panel__broadened">broadened</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {drt.peaks.some((peak) => peak.broadened) && (
                <p className="drt-panel__broadened-note">
                  A broadened peak suggests a CPE or Cole-Cole in place of a plain C.
                </p>
              )}

              <p className="drt-panel__meta">
                lambda {formatNumber(decodeFloat(drt.lam), 4)} ({drt.lam_rule}) — max residual{" "}
                {formatPercent(decodeFloat(drt.max_residual))}, RMS residual{" "}
                {formatPercent(decodeFloat(drt.rms_residual))}
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
