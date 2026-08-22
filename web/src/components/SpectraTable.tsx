// One row per loaded sweep. Selecting a row drives the trim panel, the KK panel and the plots;
// removing a row drops it from every one of those.

import { useMemo } from "react";
import type { LoadedSpectrum } from "../core/types";
import { summarizeSpectrum } from "../utils/summarize";
import { formatSiRange } from "../utils/format";
import { KKBadge, kkBadgeState } from "./KKBadge";

export interface SpectraTableProps {
  spectra: LoadedSpectrum[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
}

function formatOf(spectrum: LoadedSpectrum): string {
  const value = spectrum.current.metadata["format"];
  return typeof value === "string" ? value : "unknown";
}

function Row({
  spectrum,
  selected,
  onSelect,
  onRemove,
}: {
  spectrum: LoadedSpectrum;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const summary = useMemo(() => summarizeSpectrum(spectrum.current), [spectrum.current]);
  const badgeState = kkBadgeState(spectrum);
  // A hover for the two states whose one-word label cannot carry its own meaning. The panel
  // beside the table has the full text; this is for the row.
  const badgeTitle =
    spectrum.validationError ??
    (badgeState === "inconclusive"
      ? "The Lin-KK model could not follow this data, so the test has not been applied. " +
        "This is not a verdict on the measurement -- see the panel."
      : undefined);

  return (
    <tr
      className={selected ? "spectra-table__row spectra-table__row--selected" : "spectra-table__row"}
      onClick={onSelect}
      aria-selected={selected}
    >
      <td className="spectra-table__label" title={spectrum.label}>
        {spectrum.label}
      </td>
      <td>{formatOf(spectrum)}</td>
      <td className="num">{summary.points}</td>
      <td className="num">{formatSiRange(summary.fMin, summary.fMax, "Hz")}</td>
      <td className="num">{formatSiRange(summary.zMagMin, summary.zMagMax, "Ω")}</td>
      <td>
        <KKBadge state={badgeState} title={badgeTitle} />
      </td>
      <td>
        <button
          type="button"
          className="spectra-table__remove"
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          aria-label={`Remove ${spectrum.label}`}
        >
          Remove
        </button>
      </td>
    </tr>
  );
}

export function SpectraTable({ spectra, selectedId, onSelect, onRemove }: SpectraTableProps) {
  if (spectra.length === 0) {
    return <p className="empty-hint">No spectra loaded yet.</p>;
  }

  return (
    <table className="spectra-table">
      <thead>
        <tr>
          <th>File</th>
          <th>Format</th>
          <th className="num">Points</th>
          <th className="num">Frequency range</th>
          <th className="num">|Z| range</th>
          <th>KK</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {spectra.map((spectrum) => (
          <Row
            key={spectrum.id}
            spectrum={spectrum}
            selected={spectrum.id === selectedId}
            onSelect={() => onSelect(spectrum.id)}
            onRemove={() => onRemove(spectrum.id)}
          />
        ))}
      </tbody>
    </table>
  );
}
