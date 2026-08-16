// Four panels for one spectrum: Nyquist, Bode magnitude, Bode phase, and residuals. Zoom is
// linked across the three frequency-axis panels (magnitude, phase, residuals) by lifting each
// plot's x-range into this component's state and feeding it back into all three layouts. Nyquist
// has no frequency axis, so it is deliberately left out of that link.
//
// Three screens draw these, over three different models of the same measurement: the Data screen
// over the Lin-KK reconstruction, the Fit screen over the circuit the user drew, and the Discover
// screen over the fit behind whichever row of the front they selected. So this takes a bare
// `SpectrumWire` -- the data, and nothing about which row of a table it came from -- plus at most
// one overlay. The Lin-KK verdict is an argument rather than something read off the spectrum for
// the same reason: it belongs to the Data screen's bookkeeping, not to the measurement.

import { useMemo, useState } from "react";
import type Plotly from "plotly.js";
import type { SpectrumWire, ValidationWire } from "../core/types";
import { usePlotTokens, type PlotTokens } from "../core/theme";
import { decodeArray, decodeComplexArray } from "../core/wire";
import { Plot, type RelayoutEvent } from "./Plot";

type XRange = [number, number] | null;

/** Left-aligned, so the horizontal legend can share the strip above the plot without landing
 *  on top of it. */
function panelTitle(text: string): Partial<Plotly.Layout>["title"] {
  return { text, x: 0, xanchor: "left", font: { size: 12 } };
}

function useDecodedSpectrum(spectrum: SpectrumWire) {
  return useMemo(() => {
    const f = decodeArray(spectrum.f);
    const { re, im } = decodeComplexArray(spectrum.z);
    const magnitude = new Float64Array(f.length);
    const phaseDeg = new Float64Array(f.length);
    for (let i = 0; i < f.length; i += 1) {
      const rv = re[i] as number;
      const iv = im[i] as number;
      magnitude[i] = Math.hypot(rv, iv);
      phaseDeg[i] = (Math.atan2(iv, rv) * 180) / Math.PI;
    }
    return { f, re, im, magnitude, phaseDeg };
  }, [spectrum]);
}

/**
 * A model curve to draw over the data instead of the Lin-KK one.
 *
 * The Fit screen owns a different model from the Data screen's, but not a different picture of
 * it, so the panels are shared rather than copied. The residuals are passed in already computed
 * -- they are the ones the fit minimised, split by Python -- because deriving them here would
 * be a second definition of "residual" for the same plot.
 */
export interface ModelOverlay {
  label: string;
  re: Float64Array;
  im: Float64Array;
  residualReal: Float64Array | null;
  residualImag: Float64Array | null;
  residualTitle: string;
  residualUnit: string;
  /** Shown in the residual panel when there are no residuals to draw. */
  residualPlaceholder: string;
}

/**
 * The Lin-KK verdict on this spectrum, as the Data screen holds it.
 *
 * Only that screen passes one: it is what the panels draw when there is no model to draw
 * instead, and its two pending states are distinct messages rather than a blank.
 */
export interface ValidationState {
  result: ValidationWire | null;
  running: boolean;
  error: string | null;
}

function useKKOverlay(validation: ValidationState | null): ModelOverlay | null {
  return useMemo(() => {
    if (validation?.result == null) return null;
    const { re, im } = decodeComplexArray(validation.result.z_fit);
    return {
      label: "Lin-KK fit",
      re,
      im,
      residualReal: decodeArray(validation.result.residual_real),
      residualImag: decodeArray(validation.result.residual_imag),
      residualTitle: "Lin-KK residuals",
      residualUnit: "%",
      residualPlaceholder: "Residuals unavailable.",
    };
  }, [validation?.result]);
}

export function PlotsPanel({
  spectrum,
  model = null,
  validation = null,
}: {
  spectrum: SpectrumWire;
  model?: ModelOverlay | null;
  validation?: ValidationState | null;
}) {
  const [xRange, setXRange] = useState<XRange>(null);
  const tokens = usePlotTokens();
  const base = plotLayoutBase(tokens);
  const axis = axisBase(tokens);
  const { f, re, im, magnitude, phaseDeg } = useDecodedSpectrum(spectrum);
  const kk = useKKOverlay(validation);
  const overlay = model ?? kk;
  const fit = useMemo(() => {
    if (overlay === null) return null;
    const magnitudes = new Float64Array(overlay.re.length);
    const phases = new Float64Array(overlay.re.length);
    for (let i = 0; i < overlay.re.length; i += 1) {
      const rv = overlay.re[i] as number;
      const iv = overlay.im[i] as number;
      magnitudes[i] = Math.hypot(rv, iv);
      phases[i] = (Math.atan2(iv, rv) * 180) / Math.PI;
    }
    return {
      re: overlay.re,
      im: overlay.im,
      magnitude: magnitudes,
      phaseDeg: phases,
      label: overlay.label,
    };
  }, [overlay]);

  function handleFreqRelayout(event: RelayoutEvent): void {
    if (event["xaxis.autorange"] === true) {
      setXRange(null);
      return;
    }
    const x0 = event["xaxis.range[0]"];
    const x1 = event["xaxis.range[1]"];
    if (typeof x0 === "number" && typeof x1 === "number") setXRange([x0, x1]);
  }

  const freqAxis: Partial<Plotly.LayoutAxis> = xRange
    ? { ...axis, type: "log", range: xRange, title: { text: "Frequency (Hz)" } }
    : { ...axis, type: "log", autorange: true, title: { text: "Frequency (Hz)" } };

  const nyquistData: Plotly.Data[] = [
    {
      type: "scatter",
      mode: "markers",
      name: "Measured",
      x: Array.from(re),
      y: Array.from(im, (v) => -v),
      marker: { color: tokens.measured, size: 5 },
    },
  ];
  if (fit !== null) {
    nyquistData.push({
      type: "scatter",
      mode: "lines",
      name: fit.label,
      x: Array.from(fit.re),
      y: Array.from(fit.im, (v) => -v),
      line: { color: tokens.model, width: 1 },
    });
  }
  const nyquistLayout: Partial<Plotly.Layout> = {
    ...base,
    showlegend: fit !== null,
    title: panelTitle("Nyquist"),
    xaxis: { ...axis, title: { text: "Re(Z) (Ω)" }, zeroline: true },
    yaxis: {
      ...axis,
      title: { text: "-Im(Z) (Ω)" },
      zeroline: true,
      scaleanchor: "x",
      scaleratio: 1,
    },
  };

  const magnitudeData: Plotly.Data[] = [
    {
      type: "scatter",
      mode: "markers",
      name: "Measured",
      x: Array.from(f),
      y: Array.from(magnitude),
      marker: { color: tokens.measured, size: 5 },
    },
  ];
  if (fit !== null) {
    magnitudeData.push({
      type: "scatter",
      mode: "lines",
      name: fit.label,
      x: Array.from(f),
      y: Array.from(fit.magnitude),
      line: { color: tokens.model, width: 1 },
    });
  }
  const magnitudeLayout: Partial<Plotly.Layout> = {
    ...base,
    showlegend: fit !== null,
    title: panelTitle("Bode magnitude"),
    xaxis: freqAxis,
    yaxis: { ...axis, type: "log", title: { text: "|Z| (Ω)" } },
  };

  const phaseData: Plotly.Data[] = [
    {
      type: "scatter",
      mode: "markers",
      name: "Measured",
      x: Array.from(f),
      y: Array.from(phaseDeg),
      marker: { color: tokens.measured, size: 5 },
    },
  ];
  if (fit !== null) {
    // The phase is where a model that matches |Z| everywhere can still be wrong, so the overlay
    // belongs here as much as on the other two panels.
    phaseData.push({
      type: "scatter",
      mode: "lines",
      name: fit.label,
      x: Array.from(f),
      y: Array.from(fit.phaseDeg),
      line: { color: tokens.model, width: 1 },
    });
  }
  const phaseLayout: Partial<Plotly.Layout> = {
    ...base,
    showlegend: fit !== null,
    title: panelTitle("Bode phase"),
    xaxis: freqAxis,
    yaxis: { ...axis, title: { text: "arg(Z) (deg)" } },
  };

  const hasResiduals =
    overlay !== null && overlay.residualReal !== null && overlay.residualImag !== null;
  const residualLayout: Partial<Plotly.Layout> = {
    ...base,
    showlegend: true,
    title: panelTitle(overlay?.residualTitle ?? "Residuals"),
    xaxis: freqAxis,
    yaxis: {
      ...axis,
      title: { text: `Residual (${overlay?.residualUnit ?? "%"})` },
      zeroline: true,
    },
  };

  return (
    <section className="plots-panel">
      <h2 className="panel-title">Plots</h2>
      <div className="plots-panel__grid">
        <Plot className="plots-panel__plot" data={nyquistData} layout={nyquistLayout} />
        <Plot
          className="plots-panel__plot"
          data={magnitudeData}
          layout={magnitudeLayout}
          onRelayout={handleFreqRelayout}
        />
        <Plot
          className="plots-panel__plot"
          data={phaseData}
          layout={phaseLayout}
          onRelayout={handleFreqRelayout}
        />
        {hasResiduals && overlay !== null ? (
          <Plot
            className="plots-panel__plot"
            data={residualData(f, overlay, tokens)}
            layout={residualLayout}
            onRelayout={handleFreqRelayout}
          />
        ) : (
          <div className="plots-panel__plot plots-panel__placeholder">
            {model === null && (validation?.running ?? false)
              ? "Computing the Lin-KK residuals…"
              : model === null
                ? (validation?.error ?? "Residuals unavailable.")
                : (overlay?.residualPlaceholder ?? "Residuals unavailable.")}
          </div>
        )}
      </div>
    </section>
  );
}

function residualData(
  f: Float64Array,
  overlay: ModelOverlay,
  tokens: PlotTokens,
): Plotly.Data[] {
  // A fraction is drawn as a percentage; anything else is drawn as it arrived. The Lin-KK
  // residuals are relative, the fit's are the weighted ones it minimised, and rescaling the
  // second like the first would put a percent sign on a number that is not one.
  const scale = overlay.residualUnit === "%" ? 100 : 1;
  return [
    {
      type: "scatter",
      mode: "lines+markers",
      name: "Re(Z) residual",
      x: Array.from(f),
      y: Array.from(overlay.residualReal ?? [], (v) => v * scale),
      marker: { color: tokens.measured, size: 4 },
      line: { color: tokens.measured, width: 1 },
    },
    {
      type: "scatter",
      mode: "lines+markers",
      name: "Im(Z) residual",
      x: Array.from(f),
      y: Array.from(overlay.residualImag ?? [], (v) => v * scale),
      marker: { color: tokens.model, size: 4 },
      line: { color: tokens.model, width: 1 },
    },
  ];
}

// The backgrounds stay transparent so the panel behind them supplies the plane, which is what
// makes a theme switch reach the plots at all; everything drawn *on* that plane is a canvas and
// has to be told its colour explicitly.
function plotLayoutBase(tokens: PlotTokens): Partial<Plotly.Layout> {
  return {
    margin: { l: 56, r: 16, t: 32, b: 44 },
    // No height here on purpose: `.plots-panel__plot` sets it in CSS and the responsive config
    // makes Plotly fill that box. See the comment there for what happens when it is the other
    // way round.
    font: {
      family: "system-ui, -apple-system, 'Segoe UI', sans-serif",
      size: 11,
      color: tokens.text,
    },
    showlegend: false,
    legend: {
      orientation: "h",
      x: 1,
      xanchor: "right",
      y: 1.02,
      yanchor: "bottom",
      font: { size: 10 },
    },
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
  };
}

/** Gridlines and axis lines. Plotly's defaults are a near-white grid, invisible on a dark plane. */
function axisBase(tokens: PlotTokens): Partial<Plotly.LayoutAxis> {
  return { gridcolor: tokens.grid, linecolor: tokens.axis, zerolinecolor: tokens.axis };
}

