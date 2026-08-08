"""One-off generator for tests/test_io/data fixtures. Not a test module itself; run manually
with `python tests/test_io/_gen_fixtures.py` whenever fixtures need to be regenerated."""

from __future__ import annotations

import math
from pathlib import Path

DATA = Path(__file__).parent / "data"
DATA.mkdir(parents=True, exist_ok=True)


def write(name: str, content: str) -> None:
    (DATA / name).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------------------
# generic_csv fixtures
# ---------------------------------------------------------------------------------------

freqs = [1000.0, 10000.0, 100000.0]
re = [12.5, 8.3, 5.1]
im = [-150.2, -15.0, -1.6]  # capacitive: negative imaginary already

write(
    "generic_re_im.csv",
    "Frequency,Re(Z),Im(Z)\n"
    + "\n".join(f"{f:.6g},{r:.6g},{i:.6g}" for f, r, i in zip(freqs, re, im))
    + "\n",
)

mag = [150.72, 17.32, 5.23]
phase = [-85.24, -61.18, -17.58]  # degrees, negative => capacitive
re_from_polar = [m * math.cos(math.radians(p)) for m, p in zip(mag, phase)]
im_from_polar = [m * math.sin(math.radians(p)) for m, p in zip(mag, phase)]

write(
    "generic_mag_phase.tsv",
    "Freq\t|Z|\tPhase\n"
    + "\n".join(f"{f:.6g}\t{m:.6g}\t{p:.6g}" for f, m, p in zip(freqs, mag, phase))
    + "\n",
)

write(
    "generic_zpp_convention.csv",
    "Frequency,Re(Z),Z''\n"
    + "\n".join(f"{f:.6g},{r:.6g},{-i:.6g}" for f, r, i in zip(freqs, re, im))
    + "\n",
)

write(
    "generic_no_header.txt",
    "# generated fixture, no header row\n"
    "% freq(Hz)  re(ohm)  im(ohm)\n"
    + "\n".join(f"{f:.6g} {r:.6g} {i:.6g}" for f, r, i in zip(freqs, re, im))
    + "\n",
)

omega = [2.0 * math.pi * f for f in freqs]
write(
    "generic_omega.csv",
    "Omega,Re(Z),Im(Z)\n"
    + "\n".join(f"{w:.10g},{r:.6g},{i:.6g}" for w, r, i in zip(omega, re, im))
    + "\n",
)

write(
    "generic_bad_columns.csv",
    "Foo,Bar,Baz\n1,2,3\n4,5,6\n",
)

# ---------------------------------------------------------------------------------------
# zview fixtures
# ---------------------------------------------------------------------------------------

zv_re = [12.5, 8.3, 5.1]
zv_im = [-150.2, -15.0, -1.6]  # ZPlot already signs Z'' as Im(Z); capacitive negative

header_rows = "\n".join(
    f"{f:.6g}\t0\t0\t0\t{r:.6g}\t{i:.6g}" for f, r, i in zip(freqs, zv_re, zv_im)
)
write(
    "sample_header.z",
    "Area: 1.0\n"
    "Comment: test capacitor\n"
    "Instrument: Solartron 1260\n"
    "Freq(Hz)\tAmpl\tBias\tTime(Sec)\tZ'(a)\tZ''(b)\n" + header_rows + "\n",
)

pos_rows = "\n".join(
    f"{f:.6g},0,0,0,{r:.6g},{i:.6g},0,0" for f, r, i in zip(freqs, zv_re, zv_im)
)
write(
    "sample_positional.z",
    "Instrument: Solartron 1260\nOperator: AC\n" + pos_rows + "\n",
)

# ---------------------------------------------------------------------------------------
# touchstone fixtures
# ---------------------------------------------------------------------------------------

ts_freqs = [1.0e3, 1.0e4, 1.0e5, 1.0e6]
z0 = 50.0
R_esr = 0.05
C_cap = 10.0e-6


def z_of(f: float) -> complex:
    w = 2.0 * math.pi * f
    return complex(R_esr, -1.0 / (w * C_cap))


zs = [z_of(f) for f in ts_freqs]

# 1-port: S11 = (Z - z0) / (Z + z0)
s11s = [(z - z0) / (z + z0) for z in zs]
lines = ["! Synthetic 1-port capacitor fixture for autocircuit.io tests", "# HZ S RI R 50"]
for f, s in zip(ts_freqs, s11s):
    lines.append(f"{f:.6g} {s.real:.10g} {s.imag:.10g}")
write("cap_1port.s1p", "\n".join(lines) + "\n")

# 2-port series-thru: Z = 2*z0*(1-S21)/S21  =>  S21 = 2*z0/(Z + 2*z0)
s21_series = [2.0 * z0 / (z + 2.0 * z0) for z in zs]
lines = [
    "! Synthetic 2-port capacitor fixture (series-thru) for autocircuit.io tests",
    "# HZ S RI R 50",
]
for f, s21 in zip(ts_freqs, s21_series):
    # S11=S22=0, S12=S21 (reciprocal network)
    lines.append(f"{f:.6g} 0 0 {s21.real:.10g} {s21.imag:.10g} {s21.real:.10g} {s21.imag:.10g} 0 0")
write("cap_series_thru.s2p", "\n".join(lines) + "\n")

# 2-port shunt-thru: Z = z0*S21/(2*(1-S21))  =>  S21 = 2*Z/(2*Z + z0)
s21_shunt = [2.0 * z / (2.0 * z + z0) for z in zs]
lines = [
    "[Version] 2.0",
    "! Synthetic 2-port capacitor fixture (shunt-thru) for autocircuit.io tests",
    "[Number of Ports] 2",
    "# HZ S RI R 50",
]
for f, s21 in zip(ts_freqs, s21_shunt):
    lines.append(f"{f:.6g} 0 0 {s21.real:.10g} {s21.imag:.10g} {s21.real:.10g} {s21.imag:.10g} 0 0")
write("cap_shunt_thru.s2p", "\n".join(lines) + "\n")

# ---------------------------------------------------------------------------------------
# keysight fixtures
# ---------------------------------------------------------------------------------------

write(
    "kv_r_x.csv",
    '"Title","Keysight Test"\n'
    '"Date","2026-08-08"\n'
    '"Frequency","R","X"\n'
    + "\n".join(f"{f:.6g},{r:.6g},{i:.6g}" for f, r, i in zip(freqs, re, im))
    + "\n",
)

write(
    "kv_z_theta.csv",
    '"Title","Keysight Test"\n'
    '"Frequency","Z","THR"\n'
    + "\n".join(f"{f:.6g},{m:.6g},{p:.6g}" for f, m, p in zip(freqs, mag, phase))
    + "\n",
)

ls_freqs = [1.0e5, 1.0e6, 1.0e7]
L_val = 1.0e-6
R_val = 0.5
ls_omega = [2.0 * math.pi * f for f in ls_freqs]
write(
    "kv_ls_rs.csv",
    '"Title","Keysight Test"\n'
    '"Frequency","LS","RS"\n'
    + "\n".join(f"{f:.6g},{L_val:.6g},{R_val:.6g}" for f in ls_freqs)
    + "\n",
)

cs_freqs = [1.0e3, 1.0e4, 1.0e5]
Cs_val = 10.0e-6
Rs_val = 0.05
write(
    "kv_cs_rs.csv",
    '"Title","Keysight Test"\n'
    '"Frequency","CS","RS"\n'
    + "\n".join(f"{f:.6g},{Cs_val:.6g},{Rs_val:.6g}" for f in cs_freqs)
    + "\n",
)

D_val = 0.02
write(
    "kv_cs_d.csv",
    '"Title","Keysight Test"\n'
    '"Frequency","CS","D"\n'
    + "\n".join(f"{f:.6g},{Cs_val:.6g},{D_val:.6g}" for f in cs_freqs)
    + "\n",
)

write(
    "kv_fallback.csv",
    '"Title","Unusual trace names"\n'
    '"Frequency","Re(Z)","Im(Z)"\n'
    + "\n".join(f"{f:.6g},{r:.6g},{i:.6g}" for f, r, i in zip(freqs, re, im))
    + "\n",
)

print("Fixtures written to", DATA)
