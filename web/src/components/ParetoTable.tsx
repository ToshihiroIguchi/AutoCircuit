// The accuracy-versus-complexity trade-off curve: one row per candidate, simplest first. This
// is deliberately not a leaderboard -- there is no "winner" column, because a score alone is the
// wrong headline (`autocircuit.core.discover.DiscoveryResult.recommended`) and different rows
// here are frequently exact reparameterisations of one another rather than competitors.
//
// It marks two rows and they are not the same claim. *Recommended* is the simplest model that
// fits as well as any and whose parameters the data resolves; *lowest AIC* (or BIC, or whichever
// criterion ran) is the minimum of a penalty term, which routinely lands on a circuit carrying a
// parameter whose standard error exceeds its own value. Showing only one of them would have it
// read as the other.

import type { CandidateRowWire } from "../core/types";
import { decodeFloat } from "../core/wire";
import { formatNumber } from "../utils/format";

export interface ParetoTableProps {
  title: string;
  rows: CandidateRowWire[];
  /** The simplest candidate that fits as well as any, if the search has one to name. */
  recommended?: string | null;
  /** What the chosen criterion picks, when that is a different row. */
  byCriterion?: string | null;
  /** Heading for the score column: "AIC", "BIC", ... An F-test run scores as AIC. */
  scoreLabel?: string;
  /** The row whose schematic is drawn above the table, when the caller draws one. */
  selected?: string | null;
  onSelect?: (circuit: string) => void;
}

export function ParetoTable({
  title,
  rows,
  recommended = null,
  byCriterion = null,
  scoreLabel = "Score",
  selected = null,
  onSelect,
}: ParetoTableProps) {
  const selectable = onSelect !== undefined;

  return (
    <section className="pareto-table">
      <h2 className="panel-title">{title}</h2>
      {rows.length === 0 ? (
        <p className="empty-hint">Nothing has been refitted yet.</p>
      ) : (
        <table className={`pareto-table__table${selectable ? " pareto-table__table--pick" : ""}`}>
          <thead>
            <tr>
              <th>Circuit</th>
              <th className="num">Elements</th>
              <th className="num">Params</th>
              <th className="num">{scoreLabel}</th>
              <th className="num">chi² (reduced)</th>
              <th className="num">Complexity</th>
              <th>Unresolved</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const classes = [
                row.circuit === recommended ? "pareto-table__row--recommended" : "",
                row.circuit === selected ? "pareto-table__row--selected" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <tr
                  key={row.circuit}
                  className={classes}
                  aria-selected={selectable ? row.circuit === selected : undefined}
                >
                  <td className="pareto-table__circuit">
                    {selectable ? (
                      <button
                        type="button"
                        className="pareto-table__pick"
                        onClick={() => onSelect(row.circuit)}
                        aria-pressed={row.circuit === selected}
                        title={`Draw ${row.circuit} above the table`}
                      >
                        <code>{row.circuit}</code>
                      </button>
                    ) : (
                      <code>{row.circuit}</code>
                    )}
                    {row.circuit === recommended && (
                      <span className="pareto-table__badge">simplest that fits as well as any</span>
                    )}
                    {row.circuit === byCriterion && row.circuit !== recommended && (
                      <span className="pareto-table__badge pareto-table__badge--score">
                        best {scoreLabel}
                      </span>
                    )}
                  </td>
                  <td className="num">{row.n_elements}</td>
                  <td className="num">{row.n_params}</td>
                  <td className="num">{formatNumber(decodeFloat(row.score), 6)}</td>
                  <td className="num">{formatNumber(decodeFloat(row.chi2_reduced), 5)}</td>
                  <td className="num">{formatNumber(decodeFloat(row.complexity), 3)}</td>
                  <td className="pareto-table__unresolved">
                    {row.unresolved.length === 0 ? "" : row.unresolved.join(", ")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
