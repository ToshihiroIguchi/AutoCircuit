// The drop target shown at the top of the page. Window-level drag-and-drop is wired up by the
// caller (App); this component renders the visible target plus a real, keyboard-reachable
// <input type="file"> for people who do not want to drag.

import { useId } from "react";
import type { ChangeEvent } from "react";

export interface DropZoneProps {
  disabled: boolean;
  dragActive: boolean;
  /**
   * Which readers the loaded core has, from its own registry.
   *
   * "What files can I drop here?" is a question asked *at* the drop zone, and it used to be
   * answered in the page header on every screen instead (docs/METRICS_AND_UX_PLAN.md section 3).
   * Empty until the worker is ready, which is also when dropping starts working.
   */
  formats: string[];
  onFiles: (files: File[]) => void;
}

export function DropZone({ disabled, dragActive, formats, onFiles }: DropZoneProps) {
  const inputId = useId();

  function handleChange(event: ChangeEvent<HTMLInputElement>): void {
    const files = event.target.files;
    if (files !== null && files.length > 0) onFiles(Array.from(files));
    // Reset so choosing the same file again still fires a change event.
    event.target.value = "";
  }

  const classes = [
    "drop-zone",
    dragActive ? "drop-zone--active" : "",
    disabled ? "drop-zone--disabled" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes}>
      <p className="drop-zone__hint">
        {disabled
          ? "Loading the Python runtime -- files can be dropped once it is ready."
          : "Drag and drop impedance data files anywhere on this page."}
      </p>
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
          disabled={disabled}
          onChange={handleChange}
        />
      </label>
    </div>
  );
}
