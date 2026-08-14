// The Lin-KK verdict for the selected spectrum: a large PASS/FAIL, the numbers behind it, and
// the CLI's own summary text verbatim. A failed verdict is exactly the case where the user most
// needs to read that text, so it is never hidden behind a disclosure.

import type { LoadedSpectrum } from "../core/types";
import { decodeFloat } from "../core/wire";
import { formatNumber, formatPercent } from "../utils/format";
import { KKBadge, kkBadgeState } from "./KKBadge";

export function KKPanel({ spectrum }: { spectrum: LoadedSpectrum }) {
  const state = kkBadgeState(spectrum);

  return (
    <section className="kk-panel">
      <h2 className="panel-title">Kramers-Kronig validation</h2>

      {state === "checking" && <p className="kk-panel__pending">Running the Lin-KK test&hellip;</p>}

      {state === "na" && (
        <p className="kk-panel__error" role="alert">
          {spectrum.validationError}
        </p>
      )}

      {spectrum.validation !== null && (
        <>
          <div className="kk-panel__verdict">
            <KKBadge state={state} large />
          </div>
          <dl className="kk-panel__stats">
            <div>
              <dt>Voigt elements</dt>
              <dd>{spectrum.validation.n_elements}</dd>
            </div>
            <div>
              <dt>mu</dt>
              <dd>{formatNumber(decodeFloat(spectrum.validation.mu), 4)}</dd>
            </div>
            <div>
              <dt>Max residual</dt>
              <dd>
                {formatPercent(decodeFloat(spectrum.validation.max_residual))} (limit{" "}
                {formatPercent(decodeFloat(spectrum.validation.residual_limit))})
              </dd>
            </div>
            <div>
              <dt>RMS residual</dt>
              <dd>{formatPercent(decodeFloat(spectrum.validation.rms_residual))}</dd>
            </div>
            <div>
              <dt>Residual pattern</dt>
              <dd>
                {spectrum.validation.systematic ? "systematic" : "random"} (runs z ={" "}
                {formatNumber(decodeFloat(spectrum.validation.runs_z), 3)})
              </dd>
            </div>
          </dl>
          <pre className="kk-panel__summary">{spectrum.validation.summary}</pre>
        </>
      )}
    </section>
  );
}
