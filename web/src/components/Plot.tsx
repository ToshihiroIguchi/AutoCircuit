// One small wrapper around Plotly's imperative API. It owns a <div>, keeps it in sync with
// `data`/`layout` via Plotly.react, and cleans up with Plotly.purge on unmount. No react-plotly.js
// dependency -- that package is not in the installed set and the rule is no new npm dependencies.
//
// Plotly itself is imported dynamically, which is worth 1.1 MB of the 1.4 MB bundle: the page
// cannot draw a plot until a spectrum has been read, and a spectrum cannot be read until the
// Python runtime is up, so a static import puts the chart library in front of the first paint to
// be ready for something that is seconds away (`docs/STARTUP_AND_EDITING_PLAN.md` section 3.3).
// The module is fetched once, on the first plot, and the promise below is what makes that once.

import { useEffect, useRef } from "react";
import type PlotlyModule from "plotly.js-basic-dist-min";

type Plotly = typeof PlotlyModule;

let plotly: Promise<Plotly> | null = null;

function loadPlotly(): Promise<Plotly> {
  plotly ??= import("plotly.js-basic-dist-min").then((module) => module.default);
  return plotly;
}

export type RelayoutEvent = PlotlyModule.PlotRelayoutEvent;

export interface PlotProps {
  data: PlotlyModule.Data[];
  layout: Partial<PlotlyModule.Layout>;
  config?: Partial<PlotlyModule.Config>;
  /** Fired on every Plotly relayout (zoom, pan, double-click reset). */
  onRelayout?: (event: RelayoutEvent) => void;
  className?: string;
}

const DEFAULT_CONFIG: Partial<PlotlyModule.Config> = {
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
    void loadPlotly().then((Plotly) =>
      Plotly.react(el, data, layout, config ?? DEFAULT_CONFIG).then((gd) => {
        if (listenerAttached.current) return;
        listenerAttached.current = true;
        gd.on("plotly_relayout", (event: RelayoutEvent) => {
          onRelayoutRef.current?.(event);
        });
      }),
    );
  }, [data, layout, config]);

  useEffect(() => {
    const el = divRef.current;
    return () => {
      // Only if the module is already here: nothing was drawn otherwise, and importing a chart
      // library in order to tear down a plot that was never made would be the wrong way round.
      if (el !== null && plotly !== null) void plotly.then((Plotly) => Plotly.purge(el));
    };
  }, []);

  return <div ref={divRef} className={className} />;
}
