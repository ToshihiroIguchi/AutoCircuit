// Frequency-window trimming for the selected spectrum. Apply always calls the bridge's `trim`
// against `spectrum.original`, never against `spectrum.current` -- that is what makes trimming
// non-cumulative and Reset exact, per `LoadedSpectrum` in core/types.ts.

import { useState } from "react";
import type { FormEvent } from "react";
import type { LoadedSpectrum } from "../core/types";

export interface TrimPanelProps {
  spectrum: LoadedSpectrum;
  onApply: (id: string, fMin: number | null, fMax: number | null) => Promise<string | null>;
  onReset: (id: string) => void;
}

function parseBound(text: string): number | null {
  const trimmed = text.trim();
  return trimmed === "" ? null : Number(trimmed);
}

export function TrimPanel({ spectrum, onApply, onReset }: TrimPanelProps) {
  const [minText, setMinText] = useState("");
  const [maxText, setMaxText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const fMin = parseBound(minText);
    const fMax = parseBound(maxText);
    if ((fMin !== null && Number.isNaN(fMin)) || (fMax !== null && Number.isNaN(fMax))) {
      setError("Enter a number, or leave a field blank for an open bound.");
      return;
    }
    setApplying(true);
    const message = await onApply(spectrum.id, fMin, fMax);
    setApplying(false);
    setError(message);
  }

  function handleReset(): void {
    setMinText("");
    setMaxText("");
    setError(null);
    onReset(spectrum.id);
  }

  return (
    <form className="trim-panel" onSubmit={(event) => void handleSubmit(event)}>
      <h2 className="panel-title">Frequency window</h2>
      <div className="trim-panel__fields">
        <label>
          Min (Hz)
          <input
            type="text"
            inputMode="decimal"
            placeholder="unbounded"
            value={minText}
            onChange={(event) => setMinText(event.target.value)}
          />
        </label>
        <label>
          Max (Hz)
          <input
            type="text"
            inputMode="decimal"
            placeholder="unbounded"
            value={maxText}
            onChange={(event) => setMaxText(event.target.value)}
          />
        </label>
        <button type="submit" disabled={applying}>
          {applying ? "Applying…" : "Apply"}
        </button>
        <button type="button" onClick={handleReset} disabled={applying}>
          Reset
        </button>
      </div>
      {error !== null && (
        <p className="trim-panel__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
