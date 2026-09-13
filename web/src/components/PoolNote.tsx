// What element pool a search actually used, and why -- surfaced as its own line rather than
// buried inside `completeness`'s longer paragraph.
//
// `core/discover.py`'s `_with_pool_note` already appends `pool_choice.sentence()` to the
// coverage statement, so the words shown here are not new: `report.completeness` already
// contains them. What was missing is a place a reader's eye actually lands -- one dense
// paragraph mixing a completeness claim with a vocabulary claim reads as neither, which is
// exactly the "I can't tell what pool this used" complaint this component exists to fix.
//
// `pool_choice` is rendered verbatim, the same rule `completeness` and `summary` follow: the
// sentence is composed in Python because the part that says what may or may not be claimed is
// the part a second implementation in TypeScript would get subtly wrong (`docs/POOL_FROM_
// SPECTRUM_PLAN.md`). The one line this component *does* compose itself -- for the case where
// `pool_choice` is null -- states a fact with no judgement in it (the caller named the pool, so
// the spectrum was never asked), not an interpretation of the search.

import type { PoolChoiceWire } from "../core/types";

export interface PoolNoteProps {
  /** The pool the search actually used, whether asserted or derived. */
  pool: string[];
  /** Null means the caller named the pool; the spectrum's shape was never consulted. */
  poolChoice: PoolChoiceWire | null;
}

export function PoolNote({ pool, poolChoice }: PoolNoteProps) {
  return (
    <p className="discover-report__pool">
      {poolChoice !== null
        ? poolChoice.sentence
        : `Pool: ${pool.join(", ")}. Chosen by you; the spectrum's shape was not consulted.`}
    </p>
  );
}
