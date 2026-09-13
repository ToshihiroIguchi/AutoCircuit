// A circuit drawn from its DSL string, read-only: the picture beside a search result.
//
// It asks the bridge to parse the string and hands the tree to the same `CircuitCanvas` the Fit
// screen edits, in read-only mode. No JavaScript parses a circuit here -- that is the rule
// `CircuitCanvas`'s header states, and it is the reason the Fit screen sends structural edits as
// positions rather than as rebuilt strings. A second parser in TypeScript would be a second
// grammar for the command line to disagree with.

import { useEffect, useState } from "react";
import type { CircuitWire } from "../core/types";
import { BridgeClient, BridgeError } from "../worker/client";
import { CircuitCanvas } from "./CircuitCanvas";

export interface CircuitPreviewProps {
  client: BridgeClient;
  ready: boolean;
  /** The circuit to draw, as the report names it. Null draws nothing. */
  circuit: string | null;
}

function errorMessage(error: unknown): string {
  return error instanceof BridgeError || error instanceof Error ? error.message : String(error);
}

// Keyed by circuit string, module-level so it survives a remount of this component -- which
// happens here, since a live-search picker (`SearchProgressPanel`) and the post-search picker
// (`DiscoverScreen`) each mount their own `CircuitPreview` instance rather than sharing one.
// `client.circuit()` is a worker round trip that competes with the search's own message
// traffic (`worker/client.ts`'s serial queue), so re-parsing a circuit already seen this session
// -- clicking the same front row twice, or switching back to a row already drawn -- would cost a
// redundant trip for a picture already in hand. The cache never evicts: circuit strings are
// small, a session draws at most a few hundred distinct ones, and correctness never depends on
// re-parsing the same string twice.
const parseCache = new Map<string, CircuitWire>();

export function CircuitPreview({ client, ready, circuit }: CircuitPreviewProps) {
  const [parsed, setParsed] = useState<CircuitWire | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || circuit === null) {
      setParsed(null);
      return undefined;
    }
    const cached = parseCache.get(circuit);
    if (cached !== undefined) {
      setError(null);
      setParsed(cached);
      return undefined;
    }
    // A ticket, because the user can click down a long front faster than the worker answers and
    // the last click is the one whose picture belongs on screen.
    let current = true;
    setError(null);
    client
      .circuit(circuit)
      .then((result) => {
        parseCache.set(circuit, result);
        if (current) setParsed(result);
      })
      .catch((err: unknown) => {
        if (current) {
          setParsed(null);
          setError(errorMessage(err));
        }
      });
    return () => {
      current = false;
    };
  }, [client, ready, circuit]);

  if (circuit === null) return null;

  return (
    <div className="circuit-preview">
      {error !== null ? (
        <p className="circuit-preview__error" role="alert">
          {error}
        </p>
      ) : parsed === null ? (
        <p className="empty-hint">Drawing {circuit}…</p>
      ) : (
        <CircuitCanvas
          tree={parsed.tree}
          selectedPath={null}
          armedCode={null}
          armedMove={null}
          busy={false}
          readOnly
          onSelect={() => {}}
          onArmMove={() => {}}
          onInsert={() => {}}
          onMove={() => {}}
          onRemove={() => {}}
        />
      )}
    </div>
  );
}
