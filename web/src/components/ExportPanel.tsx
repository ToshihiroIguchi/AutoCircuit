// A row of download buttons for whatever `ExportArtifactWire`s a screen can produce. This
// component knows nothing about netlists or reports -- it only runs the `run()` a caller hands
// it and turns the resulting bytes into a browser download. The rendering itself (SPICE ladder
// synthesis, JSON serialisation, ...) all happens in `autocircuit.core`, the same code the CLI
// calls, which is the point: these files are never a second implementation of the format.

import { useState } from "react";
import type { ExportArtifactWire } from "../core/types";

export interface ExportItem {
  key: string;
  label: string;
  /** One line: what the file is, and its CLI counterpart. */
  hint: string;
  run: () => Promise<ExportArtifactWire>;
}

export interface ExportPanelProps {
  title: string;
  description: string;
  items: ExportItem[];
  disabled?: boolean;
}

/** Build a download from an artifact and click it, without leaking the object URL. */
function triggerDownload(artifact: ExportArtifactWire): void {
  const blob = new Blob([artifact.content], { type: artifact.mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = artifact.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // The click has already handed the browser the bytes it needs by the time this runs; revoking
  // any sooner risks the download starting against a URL that no longer resolves.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ExportPanel({ title, description, items, disabled = false }: ExportPanelProps) {
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string | null>>({});

  async function handleRun(item: ExportItem): Promise<void> {
    setBusy((prev) => ({ ...prev, [item.key]: true }));
    setErrors((prev) => ({ ...prev, [item.key]: null }));
    try {
      const artifact = await item.run();
      triggerDownload(artifact);
    } catch (error) {
      setErrors((prev) => ({
        ...prev,
        [item.key]: error instanceof Error ? error.message : String(error),
      }));
    } finally {
      setBusy((prev) => ({ ...prev, [item.key]: false }));
    }
  }

  return (
    <section className="export-panel">
      <h2 className="panel-title">{title}</h2>
      <p className="export-panel__description">{description}</p>

      {items.length === 0 ? (
        <p className="empty-hint">Nothing is ready to export yet.</p>
      ) : (
        <ul className="export-panel__items">
          {items.map((item) => {
            const isBusy = busy[item.key] ?? false;
            const itemError = errors[item.key] ?? null;
            return (
              <li className="export-panel__item" key={item.key}>
                <div className="export-panel__row">
                  <button
                    type="button"
                    className="export-panel__button"
                    disabled={disabled || isBusy}
                    onClick={() => void handleRun(item)}
                  >
                    {isBusy ? "Rendering…" : item.label}
                  </button>
                  <span className="export-panel__hint">{item.hint}</span>
                </div>
                {itemError !== null && (
                  <p className="export-panel__error" role="alert">
                    {itemError}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <p className="export-panel__note">
        These files are written by the same code the command line writes them with, not
        reimplemented for the browser.
      </p>
    </section>
  );
}
