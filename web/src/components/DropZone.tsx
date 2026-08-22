// The drop target shown at the top of the page. Window-level drag-and-drop is wired up by the
// caller (App); this component renders the visible target plus a real, keyboard-reachable
// <input type="file"> for people who do not want to drag.

import { useId } from "react";
import type { ChangeEvent } from "react";

export interface DropZoneProps {
  dragActive: boolean;
  /**
   * Whether the reader exists yet.
   *
   * Used only to say so. The zone stays live either way (see below); what this adds is that the
   * queueing is stated *before* the click rather than in a pending row after it, because a control
   * that silently defers its work is indistinguishable from one that ignored you.
   */
  dataReady: boolean;
  /**
   * Which readers the loaded core has, from its own registry.
   *
   * "What files can I drop here?" is a question asked *at* the drop zone, and it used to be
   * answered in the page header on every screen instead (docs/METRICS_AND_UX_PLAN.md section 3).
   * Empty until the worker has answered, which is *not* when dropping starts working -- see
   * below.
   */
  formats: string[];
  onFiles: (files: File[]) => void;
}

/**
 * The zone is never disabled, and that is the change rather than an oversight.
 *
 * It used to be, for the seconds the Python runtime takes to come up, which made the first thing
 * a visitor met a control that refused them (`docs/STARTUP_AND_EDITING_PLAN.md` section 3.4). A
 * file chosen now is held by `App` and read the moment the reader exists, and the page says so
 * while it waits -- which is both truer and shorter than making them wait to click.
 */
export function DropZone({ dragActive, dataReady, formats, onFiles }: DropZoneProps) {
  const inputId = useId();

  function handleChange(event: ChangeEvent<HTMLInputElement>): void {
    const files = event.target.files;
    if (files !== null && files.length > 0) onFiles(Array.from(files));
    // Reset so choosing the same file again still fires a change event.
    event.target.value = "";
  }

  const classes = ["drop-zone", dragActive ? "drop-zone--active" : ""].filter(Boolean).join(" ");

  return (
    <div className={classes}>
      <p className="drop-zone__hint">Drag and drop impedance data files anywhere on this page.</p>
      {!dataReady && (
        <p className="drop-zone__waiting">
          The reader is still loading — a file chosen now is queued and read as soon as it is up.
          You do not have to click again.
        </p>
      )}
      {formats.length > 0 && (
        <p className="drop-zone__formats">Reads {formats.join(", ")} — the format is sniffed.</p>
      )}
      <label className="file-button" htmlFor={inputId}>
        Choose files&hellip;
        <input
          id={inputId}
          className="file-button__input"
          type="file"
          multiple
          onChange={handleChange}
        />
      </label>
    </div>
  );
}
