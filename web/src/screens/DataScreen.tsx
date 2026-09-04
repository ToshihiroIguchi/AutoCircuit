// The Data screen: what was loaded, what window of it is in use, and whether Kramers-Kronig
// believes it. Unchanged in substance from when it was the whole application -- it is a screen
// now rather than the page, and the spectra it works on live in `App` because the Fit screen
// needs the selected one too.

import { useEffect, useRef } from "react";
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

/** A file being read. Named rather than counted: what it has to say is *which* file is waiting. */
export interface PendingFile {
  id: string;
  name: string;
}

export interface DataScreenProps {
  /**
   * The first load stage has landed: the worker can read, trim and validate.
   *
   * This screen waits on that and not on the whole runtime, which is the point of staging the
   * load -- nothing here uses scipy (`docs/STARTUP_AND_EDITING_PLAN.md` section 3). Nothing is
   * *disabled* while it is false either: a file chosen now is read when the reader exists.
   */
  dataReady: boolean;
  dragActive: boolean;
  /** The reader names the loaded core offers; shown on the drop zone. */
  formats: string[];
  spectra: LoadedSpectrum[];
  selected: LoadedSpectrum | null;
  selectedId: string | null;
  fileErrors: FileError[];
  pending: PendingFile[];
  onFiles: (files: File[]) => void;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  onDismissError: (id: string) => void;
  onApplyTrim: (id: string, fMin: number | null, fMax: number | null) => Promise<string | null>;
  onResetTrim: (id: string) => void;
}

export function DataScreen(props: DataScreenProps) {
  // A file loaded from a drop, a picker or the Example data panel lands in the table below the
  // fold on most screens -- the panel above it (drop zone, then a wall of example blurbs) is
  // taller than the viewport. Without this, the only feedback a click gets is a button that
  // reads "Loading..." for well under a second and then reverts, which is what "pressed the
  // button, nothing happened" was actually about: something did happen, off screen.
  const resultsRef = useRef<HTMLElement>(null);
  const previousCount = useRef(props.spectra.length);
  useEffect(() => {
    if (props.spectra.length > previousCount.current) {
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    previousCount.current = props.spectra.length;
  }, [props.spectra.length]);

  return (
    <>
      <DropZone
        dragActive={props.dragActive}
        dataReady={props.dataReady}
        formats={props.formats}
        onFiles={props.onFiles}
      />

      <SamplePanel dataReady={props.dataReady} onFile={(file) => props.onFiles([file])} />

      {props.pending.length > 0 && (
        <ul className="pending-files" role="status" aria-live="polite">
          {props.pending.map((entry) => (
            <li key={entry.id} className="pending-file">
              <span className="pending-file__name">{entry.name}</span>
              <span className="pending-file__message">
                {props.dataReady
                  ? "Reading…"
                  : "Waiting for the Python runtime, then reading — you do not have to click again."}
              </span>
            </li>
          ))}
        </ul>
      )}

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

      <main className="app-main" ref={resultsRef}>
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
              {/* The only screen that draws the Lin-KK reconstruction, so the only one that
                  passes it: elsewhere the overlay is a fitted circuit. */}
              <PlotsPanel
                key={`plots-${props.selected.id}`}
                spectrum={props.selected.current}
                validation={{
                  result: props.selected.validation,
                  running: props.selected.validating,
                  error: props.selected.validationError,
                }}
              />
            </>
          )}
        </section>
      </main>
    </>
  );
}
