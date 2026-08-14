// Four panels for the selected spectrum: Nyquist, Bode magnitude, Bode phase, and Lin-KK
// residuals. Zoom is linked across the three frequency-axis panels (magnitude, phase, residuals)
// by lifting each plot's x-range into this component's state and feeding it back into all three
// layouts. Nyquist has no frequency axis, so it is deliberately left out of that link.

import { useMemo, useState } from "react";
import type Plotly from "plotly.js";
import type { LoadedSpectrum } from "../core/types";
import { decodeArray, decodeComplexArray } from "../core/wire";
import { Plot, type RelayoutEvent } from "./Plot";

// Categorical slots 1 (blue) and 2 (orange) from the project's data-viz palette: measured data
// and the KK model overlay, an adjacent pair validated for colorblind-safe contrast.
const MEASURED_COLOR = "#2a78d6";
const FIT_COLOR = "#eb6834";
const AXIS_LINE_COLOR = "#c3c2b7";

type XRange = [number, number] | null;

/** Left-aligned, so the horizontal legend can share the strip above the plot without landing
 *  on top of it. */
function panelTitle(text: string): Partial<Plotly.Layout>["title"] {
  return { text, x: 0, xanchor: "left", font: { size: 12 } };
}

function useDecodedSpectrum(spectrum: LoadedSpectrum) {
  return useMemo(() => {
    const f = decodeArray(spectrum.current.f);
    const { re, im } = decodeComplexArray(spectrum.current.z);
    const magnitude = new Float64Array(f.length);
    const phaseDeg = new Float64Array(f.length);
    for (let i = 0; i < f.length; i += 1) {
      const rv = re[i] as number;
      const iv = im[i] as number;
      magnitude[i] = Math.hypot(rv, iv);
      phaseDeg[i] = (Math.atan2(iv, rv) * 180) / Math.PI;
    }
    return { f, re, im, magnitude, phaseDeg };
  }, [spectrum.current]);
}

function useFitOverlay(spectrum: LoadedSpectrum) {
  return useMemo(() => {
    if (spectrum.validation === null) return null;
    const { re, im } = decodeComplexArray(spectrum.validation.z_fit);
    const magnitude = new Float64Array(re.length);
    for (let i = 0; i < re.length; i += 1) {
      magnitude[i] = Math.hypot(re[i] as number, im[i] as number);
    }
    return { re, im, magnitude };
  }, [spectrum.validation]);
}

export function PlotsPanel({ spectrum }: { spectrum: LoadedSpectrum }) {
  const [xRange, setXRange] = useState<XRange>(null);
  const { f, re, im, magnitude, phaseDeg } = useDecodedSpectrum(spectrum);
  const fit = useFitOverlay(spectrum);

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
    ? { type: "log", range: xRange, title: { text: "Frequency (Hz)" } }
    : { type: "log", autorange: true, title: { text: "Frequency (Hz)" } };

  const nyquistData: Plotly.Data[] = [
    {
      type: "scatter",
      mode: "markers",
      name: "Measured",
      x: Array.from(re),
      y: Array.from(im, (v) => -v),
      marker: { color: MEASURED_COLOR, size: 5 },
    },
  ];
  if (fit !== null) {
    nyquistData.push({
      type: "scatter",
      mode: "lines",
      name: "Lin-KK fit",
      x: Array.from(fit.re),
      y: Array.from(fit.im, (v) => -v),
      line: { color: FIT_COLOR, width: 1 },
    });
  }
  const nyquistLayout: Partial<Plotly.Layout> = {
    ...PLOT_LAYOUT_BASE,
    showlegend: fit !== null,
    title: panelTitle("Nyquist"),
    xaxis: { title: { text: "Re(Z) (Ω)" }, zeroline: true, zerolinecolor: AXIS_LINE_COLOR },
    yaxis: {
      title: { text: "-Im(Z) (Ω)" },
      zeroline: true,
      zerolinecolor: AXIS_LINE_COLOR,
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
      marker: { color: MEASURED_COLOR, size: 5 },
    },
  ];
  if (fit !== null) {
    magnitudeData.push({
      type: "scatter",
      mode: "lines",
      name: "Lin-KK fit",
      x: Array.from(f),
      y: Array.from(fit.magnitude),
      line: { color: FIT_COLOR, width: 1 },
    });
  }
  const magnitudeLayout: Partial<Plotly.Layout> = {
    ...PLOT_LAYOUT_BASE,
    showlegend: fit !== null,
    title: panelTitle("Bode magnitude"),
    xaxis: freqAxis,
    yaxis: { type: "log", title: { text: "|Z| (Ω)" } },
  };

  const phaseData: Plotly.Data[] = [
    {
      type: "scatter",
      mode: "markers",
      name: "Measured",
      x: Array.from(f),
      y: Array.from(phaseDeg),
      marker: { color: MEASURED_COLOR, size: 5 },
    },
  ];
  const phaseLayout: Partial<Plotly.Layout> = {
    ...PLOT_LAYOUT_BASE,
    title: panelTitle("Bode phase"),
    xaxis: freqAxis,
    yaxis: { title: { text: "arg(Z) (deg)" } },
  };

  const residualLayout: Partial<Plotly.Layout> = {
    ...PLOT_LAYOUT_BASE,
    showlegend: true,
    title: panelTitle("Lin-KK residuals"),
    xaxis: freqAxis,
    yaxis: {
      title: { text: "Residual (%)" },
      zeroline: true,
      zerolinecolor: AXIS_LINE_COLOR,
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
        {spectrum.validation !== null ? (
          <Plot
            className="plots-panel__plot"
            data={residualData(f, spectrum.validation)}
            layout={residualLayout}
            onRelayout={handleFreqRelayout}
          />
        ) : (
          <div className="plots-panel__plot plots-panel__placeholder">
            {spectrum.validating
              ? "Computing the Lin-KK residuals…"
              : (spectrum.validationError ?? "Residuals unavailable.")}
          </div>
        )}
      </div>
    </section>
  );
}

function residualData(
  f: Float64Array,
  validation: NonNullable<LoadedSpectrum["validation"]>,
): Plotly.Data[] {
  const residualReal = decodeArray(validation.residual_real);
  const residualImag = decodeArray(validation.residual_imag);
  return [
    {
      type: "scatter",
      mode: "lines+markers",
      name: "Re(Z) residual",
      x: Array.from(f),
      y: Array.from(residualReal, (v) => v * 100),
      marker: { color: MEASURED_COLOR, size: 4 },
      line: { color: MEASURED_COLOR, width: 1 },
    },
    {
      type: "scatter",
      mode: "lines+markers",
      name: "Im(Z) residual",
      x: Array.from(f),
      y: Array.from(residualImag, (v) => v * 100),
      marker: { color: FIT_COLOR, size: 4 },
      line: { color: FIT_COLOR, width: 1 },
    },
  ];
}

const PLOT_LAYOUT_BASE: Partial<Plotly.Layout> = {
  margin: { l: 56, r: 16, t: 32, b: 44 },
  // No height here on purpose: `.plots-panel__plot` sets it in CSS and the responsive config
  // makes Plotly fill that box. See the comment there for what happens when it is the other
  // way round.
  font: { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", size: 11 },
  showlegend: false,
  legend: { orientation: "h", x: 1, xanchor: "right", y: 1.02, yanchor: "bottom", font: { size: 10 } },
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
};

