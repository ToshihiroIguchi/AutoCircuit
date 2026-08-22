"""Gates K1-K4 of ``docs/KK_RESONANCE_PLAN.md``: the Lin-KK resonance probe.

A measurement, not a test -- although this one is fast enough that the same assertions also
live in ``tests/test_validate.py``. What this script adds is the table: every family, the
verdict with and without the probe, and the probe's own numbers beside them, which is what
says the probe changed exactly what it was meant to change.

Usage (needs PYTHONPATH=src)::

    python benchmarks/kk_resonance.py
"""

from __future__ import annotations

import numpy as np

from autocircuit.core.circuit import Circuit
from autocircuit.core.simulate import log_frequencies, simulate
from autocircuit.core.spectrum import Spectrum
from autocircuit.core.validate import lin_kk

#: The resonator of ``benchmarks/fitting.py``'s suite, with R1 set from the wanted Q.
BVD_SERIES_HZ = 1.9894e5


def bvd(q: float, points_per_decade: int = 1500) -> Spectrum:
    inductance, c_clamped, c_motional = 3.2e-3, 2e-9, 2e-10
    values = {
        "C1.C": c_clamped,
        "R1.R": 2 * np.pi * BVD_SERIES_HZ * inductance / q,
        "L1.L": inductance,
        "C2.C": c_motional,
    }
    f = log_frequencies(1.6e5, 2.6e5, points_per_decade)
    return simulate("p(C1,R1-L1-C2)", f, values, noise=0.01, seed=0)


def randles(drift: float = 0.0, points_per_decade: int = 10) -> Spectrum:
    """A Randles cell, optionally multiplied by a ramp -- a smooth, causal-looking KK violation."""
    circuit = Circuit.parse("R1-p(C1,R2-W1)")
    values = {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 200.0, "W1.A": 50.0}
    f = log_frequencies(1e-2, 1e5, points_per_decade)
    z = circuit.impedance(2 * np.pi * f, circuit.values_array(values))
    if drift:
        z = z * np.linspace(1.0, 1.0 + drift, f.size)
    rng = np.random.default_rng(0)
    z = z + rng.normal(0, np.abs(z) * 0.01) + 1j * rng.normal(0, np.abs(z) * 0.01)
    return Spectrum(f, z, {})


def row(label: str, spectrum: Spectrum, wanted: str) -> bool:
    with_probe = lin_kk(spectrum)
    without = lin_kk(spectrum, resonance_probe=False)
    probe = (
        "-"
        if np.isnan(with_probe.probe_rms)
        else f"{with_probe.probe_rms:.2%} / {with_probe.probe_runs_z:+.2f}"
    )
    ok = with_probe.verdict == wanted
    print(
        f"  {'OK ' if ok else '!! '}{label:<32}{without.verdict:<14}{with_probe.verdict:<14}"
        f"{with_probe.rms_residual:>8.2%}  {probe}"
    )
    return ok


def main() -> None:
    failures = 0
    header = f"  {'':3}{'case':<32}{'no probe':<14}{'with probe':<14}{'rms':>8}  probe rms / z"

    print("\n=== K2 - a genuine violation must still be a verdict about the data ===")
    print(header)
    for points_per_decade in (10, 30, 50):
        for drift in (0.4, 1.0, 3.0, 10.0):
            failures += not row(
                f"Randles +{drift:.0%} drift, {points_per_decade}/dec",
                randles(drift, points_per_decade),
                "fail",
            )

    print("\n=== K3 - a resonator must never be reported as bad data ===")
    print(header)
    for q in (2, 5, 15, 100, 300):
        failures += not row(f"Butterworth-Van Dyke, Q={q}", bvd(q), "inconclusive")

    print("\n=== K1 and K4 - valid data untouched, and nothing becomes a pass ===")
    print(header)
    for points_per_decade in (10, 30, 50):
        failures += not row(
            f"Randles, clean, {points_per_decade}/dec", randles(0.0, points_per_decade), "pass"
        )
    failures += not row(
        "series L-C-R (in the basis)",
        simulate(
            "L1-C1-R1",
            log_frequencies(1e4, 1e6, 300),
            {"L1.L": 1e-3, "C1.C": 1e-9, "R1.R": 20.0},
        ),
        "pass",
    )
    clean = randles()
    failures += not row(
        "Randles, Im sign flipped",
        Spectrum(clean.f, clean.z.real - 1j * clean.z.imag, {}),
        "inconclusive",
    )

    print(f"\n{'all gates pass' if failures == 0 else f'{failures} gate rows failed'}")


if __name__ == "__main__":
    main()
