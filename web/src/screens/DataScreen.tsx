// The Data screen: what was loaded, what window of it is in use, and whether Kramers-Kronig
// believes it. Unchanged in substance from when it was the whole application -- it is a screen
// now rather than the page, and the spectra it works on live in `App` because the Fit screen
// needs the selected one too.

import type { LoadedSpectrum } from "../core/types";
import { DropZone } from "../components/DropZone";
import { KKPanel } from "../components/KKPanel";
import { PlotsPanel } from "../components/PlotsPanel";
import { SamplePanel } from "../components/SamplePanel";
import { SpectraTable } from "../components/SpectraTable";
import { TrimPanel } from "../components/TrimPanel";

export interface FileError {
  id: string;
  name: string;
  message: string;
}

export interface DataScreenProps {
  ready: boolean;
  dragActive: boolean;
  /** The reader names the loaded core offers; shown on the drop zone. */
  formats: string[];
  spectra: LoadedSpectrum[];
  selected: LoadedSpectrum | null;
  selectedId: string | null;
  fileErrors: FileError[];
  onFiles: (files: File[]) => void;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  onDismissError: (id: string) => void;
  onApplyTrim: (id: string, fMin: number | null, fMax: number | null) => Promise<string | null>;
  onResetTrim: (id: string) => void;
}

export function DataScreen(props: DataScreenProps) {
  return (
    <>
      <DropZone
        disabled={!props.ready}
        dragActive={props.dragActive}
        formats={props.formats}
        onFiles={props.onFiles}
      />

      <SamplePanel disabled={!props.ready} onFile={(file) => props.onFiles([file])} />

      {props.fileErrors.length > 0 && (
        <ul className="file-errors">
          {props.fileErrors.map((entry) => (
            <li key={entry.id} className="file-error">
              <span className="file-error__name">{entry.name}</span>
              <span className="file-error__message">{entry.message}</span>
              <button
                type="button"
                className="file-error__dismiss"
                onClick={() => props.onDismissError(entry.id)}
                aria-label={`Dismiss error for ${entry.name}`}
              >
                &times;
              </button>
            </li>
          ))}
        </ul>
      )}

      <main className="app-main">
        <section className="app-left">
          <h2 className="panel-title">Loaded spectra</h2>
          <SpectraTable
            spectra={props.spectra}
            selectedId={props.selectedId}
            onSelect={props.onSelect}
            onRemove={props.onRemove}
          />
        </section>
        <section className="app-right">
          {props.selected === null ? (
            <p className="empty-hint">
              Load a spectrum to see its plots and Kramers-Kronig verdict.
            </p>
          ) : (
            <>
              <TrimPanel
                key={`trim-${props.selected.id}`}
                spectrum={props.selected}
                onApply={props.onApplyTrim}
                onReset={props.onResetTrim}
              />
              <KKPanel spectrum={props.selected} />
              <PlotsPanel key={`plots-${props.selected.id}`} spectrum={props.selected} />
            </>
          )}
        </section>
      </main>
    </>
  );
}
