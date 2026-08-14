// The accuracy-versus-complexity trade-off curve: one row per candidate, simplest first. This
// is deliberately not a leaderboard -- there is no "score" column and no highlighted winner,
// because AICc alone is the wrong headline (`autocircuit.core.discover.DiscoveryResult.recommended`)
// and different rows here are frequently exact reparameterisations of one another rather than
// competitors.

import type { CandidateRowWire } from "../core/types";
import { decodeFloat } from "../core/wire";
import { formatNumber } from "../utils/format";

export interface ParetoTableProps {
  title: string;
  rows: CandidateRowWire[];
  /** The simplest candidate that fits as well as any, if the search has one to name. */
  recommended?: string | null;
}

export function ParetoTable({ title, rows, recommended = null }: ParetoTableProps) {
  return (
    <section className="pareto-table">
      <h2 className="panel-title">{title}</h2>
      {rows.length === 0 ? (
        <p className="empty-hint">Nothing has been refitted yet.</p>
      ) : (
        <table className="pareto-table__table">
          <thead>
            <tr>
              <th>Circuit</th>
              <th className="num">Elements</th>
              <th className="num">Params</th>
              <th className="num">AICc</th>
              <th className="num">chi² (reduced)</th>
              <th className="num">Complexity</th>
              <th>Unresolved</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.circuit}
                className={row.circuit === recommended ? "pareto-table__row--recommended" : ""}
              >
                <td className="pareto-table__circuit">
                  <code>{row.circuit}</code>
                  {row.circuit === recommended && (
                    <span className="pareto-table__badge">simplest that fits as well as any</span>
                  )}
                </td>
                <td className="num">{row.n_elements}</td>
                <td className="num">{row.n_params}</td>
                <td className="num">{formatNumber(decodeFloat(row.aicc), 6)}</td>
                <td className="num">{formatNumber(decodeFloat(row.chi2_reduced), 5)}</td>
                <td className="num">{formatNumber(decodeFloat(row.complexity), 3)}</td>
                <td className="pareto-table__unresolved">
                  {row.unresolved.length === 0 ? "" : row.unresolved.join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
