// One small wrapper around Plotly's imperative API. It owns a <div>, keeps it in sync with
// `data`/`layout` via Plotly.react, and cleans up with Plotly.purge on unmount. No react-plotly.js
// dependency -- that package is not in the installed set and the rule is no new npm dependencies.

import { useEffect, useRef } from "react";
import Plotly from "plotly.js-basic-dist-min";

export type RelayoutEvent = Plotly.PlotRelayoutEvent;

export interface PlotProps {
  data: Plotly.Data[];
  layout: Partial<Plotly.Layout>;
  config?: Partial<Plotly.Config>;
  /** Fired on every Plotly relayout (zoom, pan, double-click reset). */
  onRelayout?: (event: RelayoutEvent) => void;
  className?: string;
}

const DEFAULT_CONFIG: Partial<Plotly.Config> = {
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
};

export function Plot({ data, layout, config, onRelayout, className }: PlotProps) {
  const divRef = useRef<HTMLDivElement | null>(null);
  // Keeps the effect that draws the plot from needing `onRelayout` in its dependency list, so a
  // new callback identity each render does not tear down and re-create the whole plot.
  const onRelayoutRef = useRef(onRelayout);
  onRelayoutRef.current = onRelayout;
  const listenerAttached = useRef(false);

  useEffect(() => {
    const el = divRef.current;
    if (el === null) return;
    void Plotly.react(el, data, layout, config ?? DEFAULT_CONFIG).then((gd) => {
      if (listenerAttached.current) return;
      listenerAttached.current = true;
      gd.on("plotly_relayout", (event: RelayoutEvent) => {
        onRelayoutRef.current?.(event);
      });
    });
  }, [data, layout, config]);

  useEffect(() => {
    const el = divRef.current;
    return () => {
      if (el !== null) Plotly.purge(el);
    };
  }, []);

  return <div ref={divRef} className={className} />;
}
