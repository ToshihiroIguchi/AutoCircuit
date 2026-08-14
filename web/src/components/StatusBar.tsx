// The four load stages the bridge client reports, then a discreet build line once ready. Cold
// start is about 5 s (Pyodide boot, then numpy/scipy, then the AutoCircuit import) so this is the
// only thing on screen for a few seconds -- it must say what is happening, not just spin.

import type { LoadStage } from "../worker/protocol";
import type { VersionsWire } from "../core/types";

const STAGE_LABELS: Record<LoadStage, string> = {
  booting: "Starting the Python runtime",
  packages: "Loading numpy and scipy",
  importing: "Loading AutoCircuit",
  ready: "Ready",
};

export interface StatusBarProps {
  stage: LoadStage;
  detail: string;
  versions: VersionsWire | null;
  bootError: string | null;
}

export function StatusBar({ stage, detail, versions, bootError }: StatusBarProps) {
  if (bootError !== null) {
    return (
      <div className="status-bar status-bar--error" role="alert">
        Failed to start the Python runtime: {bootError}
      </div>
    );
  }

  if (versions === null) {
    const stages: LoadStage[] = ["booting", "packages", "importing", "ready"];
    return (
      <div className="status-bar status-bar--loading" role="status" aria-live="polite">
        <span className="status-bar__spinner" aria-hidden="true" />
        <span className="status-bar__detail">{detail || STAGE_LABELS[stage]}</span>
        <ol className="status-bar__steps">
          {stages.map((s) => (
            <li
              key={s}
              className={
                s === stage
                  ? "status-bar__step status-bar__step--current"
                  : stages.indexOf(s) < stages.indexOf(stage)
                    ? "status-bar__step status-bar__step--done"
                    : "status-bar__step"
              }
            >
              {STAGE_LABELS[s]}
            </li>
          ))}
        </ol>
      </div>
    );
  }

  return (
    <div className="status-bar status-bar--ready">
      <span className="status-bar__build">
        bridge v{versions.bridge} &middot; fit v{versions.fit} &middot; spectrum v
        {versions.spectrum} &middot; validate v{versions.validate}
      </span>
      <span className="status-bar__formats">formats: {versions.formats.join(", ")}</span>
    </div>
  );
}
