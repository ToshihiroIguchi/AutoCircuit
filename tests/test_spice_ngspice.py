"""ngspice round-trip: the exported netlist as a real simulator reads it.

``test_spice.py`` proves the emitted netlist is *electrically* what the model says, by parsing it
back and solving it with a nodal-analysis engine written for that purpose. What that cannot prove
is that the netlist is *dialect* right -- that ngspice reads every device line, node name and
number the way the exporter meant. This module runs a real ngspice and compares.

The comparison is against that same nodal engine rather than against the model, and the choice is
the point: it factors the ladder-synthesis error out entirely, so a disagreement can only be about
how the file was read. Against the model the fractional elements sit at ~1e-2 by design, which
would hide a dialect fault three orders of magnitude smaller than itself.

[measured] ngspice 42 agrees with the nodal engine exactly on the lone resistor and to
4.6e-15 .. 4.5e-12 on the other eight cases below, the four ladder-synthesised elements included.
The tolerance here is 1e-9, some 200x the worst observed.

Skipped when ngspice is not on PATH; ``.github/workflows/tests.yml`` installs it, so CI runs it.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from typing import NamedTuple

import numpy as np
import pytest
from numpy.typing import NDArray

from autocircuit.core.circuit import Circuit
from autocircuit.core.spice import to_netlist
from test_spice import netlist_impedance

NGSPICE = shutil.which("ngspice")

pytestmark = pytest.mark.skipif(NGSPICE is None, reason="ngspice is not installed")

#: Diagnostics ngspice emits about the *operating point* of a network that is a DC open at its
#: port. Every AutoCircuit netlist beginning with a capacitor is one, and an AC analysis of a
#: linear network does not depend on the operating point it failed to find -- which is why the
#: numeric test below passes on exactly these cases. See ``Case.dc_open``.
OP_POINT_NOISE = (
    "singular matrix",
    "gmin stepping failed",
    "source stepping failed",
)


class Case(NamedTuple):
    """One circuit to export and simulate."""

    name: str
    dsl: str
    params: dict[str, float]
    f_min: float
    f_max: float
    dc_open: bool
    """The network is an open circuit at DC -- true of every model beginning with a capacitor,
    and what makes ngspice's operating point singular."""


class Run(NamedTuple):
    """What one ngspice invocation produced."""

    netlist: str
    frequency: NDArray[np.float64]
    z: NDArray[np.complex128]
    diagnostics: list[str]


def _read_rawfile(path: pathlib.Path) -> tuple[list[str], NDArray[np.complex128]]:
    """Read an ngspice binary rawfile; returns the vector names and (n_points, n_vars) data.

    Binary rather than ASCII because an AC sweep is compared here at 1e-9, and the printed forms
    round. Complex vectors are stored as consecutive (real, imaginary) little-endian doubles.
    """
    blob = path.read_bytes()
    marker = b"Binary:\n"
    cut = blob.find(marker)
    if cut < 0:
        raise AssertionError(f"{path.name}: no Binary: section; ngspice wrote no data")

    n_vars = n_points = 0
    is_complex = False
    names: list[str] = []
    in_variables = False
    for line in blob[:cut].decode("ascii", errors="replace").splitlines():
        lowered = line.strip().lower()
        if lowered.startswith("flags:"):
            is_complex = "complex" in lowered
        elif lowered.startswith("no. variables:"):
            n_vars = int(lowered.split(":")[1])
        elif lowered.startswith("no. points:"):
            n_points = int(lowered.split(":")[1])
        elif lowered.startswith("variables:"):
            in_variables = True
        elif in_variables and line.startswith(("\t", " ")):
            fields = line.split()
            if len(fields) >= 2:
                names.append(fields[1])

    if not is_complex:
        raise AssertionError(f"{path.name}: expected a complex (AC) rawfile")
    wanted = n_points * n_vars * 2
    doubles = np.frombuffer(blob[cut + len(marker) :][: wanted * 8], dtype="<f8")
    if doubles.size != wanted:
        raise AssertionError(f"{path.name}: expected {wanted} doubles, found {doubles.size}")
    pairs = doubles.reshape(n_points, n_vars, 2)
    return names, pairs[..., 0] + 1j * pairs[..., 1]


def _run_ac(netlist: str, f_min: float, f_max: float, work: pathlib.Path) -> Run:
    """Simulate ``netlist`` between its two ports.

    The deck adds nothing to help the simulator -- no ``.option rshunt``, no shunt resistor. That
    is deliberate: [measured] ``rshunt=1e12`` silences the operating-point complaints but moves
    the answer by up to 7e-7, which is worse than the quantity being measured. A network that
    cannot be simulated bare is a fact about the netlist, and this test would rather see it.
    """
    assert NGSPICE is not None
    (work / "dut.cir").write_text(netlist, encoding="ascii")
    deck = "\n".join(
        [
            "* AutoCircuit ngspice round-trip",
            ".include dut.cir",
            "X1 probe 0 DUT",
            "I1 0 probe DC 0 AC 1",  # 1 A into the port, so V(probe) is numerically Z
            f".ac dec 20 {f_min:.9g} {f_max:.9g}",
            ".end",
            "",
        ]
    )
    (work / "deck.cir").write_text(deck, encoding="ascii")

    completed = subprocess.run(
        [NGSPICE, "-b", "-r", "out.raw", "deck.cir"],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    # ngspice exits 0 even when the operating point fails, so the exit code is not the check --
    # the diagnostics and the numbers are.
    diagnostics = [
        line.strip()
        for line in output.splitlines()
        if "warning" in line.lower() or "error" in line.lower()
    ]

    raw = work / "out.raw"
    if not raw.exists():
        # [measured] This is how a netlist ngspice cannot read fails: it refuses the deck and
        # writes nothing, rather than writing something wrong.
        raise AssertionError(f"ngspice wrote no rawfile (exit {completed.returncode}):\n{output}")

    names, data = _read_rawfile(raw)
    if "v(probe)" not in names:
        raise AssertionError(f"no v(probe) in {names}; ngspice said:\n{output}")
    frequency = np.asarray(data[:, names.index("frequency")].real, dtype=np.float64)
    return Run(netlist, frequency, data[:, names.index("v(probe)")], diagnostics)


#: The corpus, which is `test_spice.py`'s plus a `SKINW` wire: both ladder forms, both primitive
#: and fractional elements, a nested topology, and two networks that are a DC open at the port.
CASES = [
    Case("resistor", "R1", {"R1.R": 47.0}, 1e0, 1e6, False),
    Case("esr_esl", "C1-R1-L1", {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}, 1e2, 1e9, True),
    Case(
        "two_rc",
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        1e0,
        1e8,
        False,
    ),
    Case(
        "nested",
        "p(R1,C1-p(R2,L1))-R3",
        {"R1.R": 1e3, "C1.C": 1e-9, "R2.R": 200.0, "L1.L": 1e-5, "R3.R": 7.0},
        1e0,
        1e8,
        False,
    ),
    Case(
        "randles",
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 100.0, "W1.A": 150.0},
        1e-2,
        1e5,
        False,
    ),
    Case(
        "cpe",
        "R1-p(CPE1,R2)",
        {"R1.R": 50.0, "CPE1.Q": 3e-9, "CPE1.n": 0.8, "R2.R": 8e4},
        1e-1,
        1e7,
        False,
    ),
    Case(
        "finite_warburg",
        "R1-p(R2,Ws1)",
        {"R1.R": 5.0, "R2.R": 200.0, "Ws1.R": 80.0, "Ws1.tau": 1e-3},
        1e-2,
        1e5,
        False,
    ),
    Case(
        "skin_effect",
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        1e2,
        1e9,
        True,
    ),
    Case(
        "wire",
        "R1-SKINW1",
        {"R1.R": 1e-3, "SKINW1.Rdc": 1e-2, "SKINW1.tau_s": 1e-8},
        1e2,
        1e9,
        False,
    ),
]

IDS = [case.name for case in CASES]


def test_the_round_trip_notices_a_netlist_ngspice_cannot_read(tmp_path: pathlib.Path) -> None:
    """Sanity-check the harness itself before trusting it to judge the exporter.

    [measured] An unknown device makes ngspice 42 print ``Error on line``, exit 1 and write no
    rawfile at all, so the failure arrives as a missing file rather than as a plausible wrong
    number. A round-trip that treated a missing rawfile as "nothing to compare" would pass.
    """
    broken = ".subckt DUT 1 2\nR_a 1 n1 10\nZ_bad n1 n2 1e-6\nC_a n2 2 1e-6\n.ends DUT\n"
    with pytest.raises(AssertionError, match="wrote no rawfile"):
        _run_ac(broken, 1.0, 1e6, tmp_path)


@pytest.fixture(scope="module")
def simulated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Run]:
    """Export and simulate every case once; the two tests below read different halves."""
    runs = {}
    for case in CASES:
        circuit = Circuit.parse(case.dsl)
        netlist = to_netlist(
            circuit, case.params, f_min=case.f_min, f_max=case.f_max, name="DUT"
        )
        work = tmp_path_factory.mktemp(case.name)
        runs[case.name] = _run_ac(netlist, case.f_min, case.f_max, work)
    return runs


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_ngspice_reproduces_the_exported_netlist(
    case: Case, simulated: dict[str, Run]
) -> None:
    """A real simulator must compute what the netlist says, to the last digit that matters."""
    run = simulated[case.name]
    z_engine = netlist_impedance(run.netlist, 2 * np.pi * run.frequency)
    deviation = np.abs(run.z - z_engine) / np.abs(z_engine)
    worst = int(np.argmax(deviation))
    assert deviation[worst] < 1e-9, (
        f"{case.dsl}: ngspice and the nodal engine differ by {deviation[worst]:.3e} at "
        f"{run.frequency[worst]:.6g} Hz ({run.z[worst]:.12g} vs {z_engine[worst]:.12g})"
    )


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_ngspice_accepts_the_netlist_without_complaint(
    case: Case, simulated: dict[str, Run]
) -> None:
    """Nothing in the file may puzzle ngspice -- and the exit code will not tell you so.

    [measured] ngspice 42 exits 0 having reported a singular matrix, failed gmin stepping and
    failed source stepping, then falling back to a transient operating point. A round-trip that
    gated on the return code would have called that a pass. So the diagnostics themselves are the
    assertion: a network with a DC path at its port must produce none at all, and one without may
    produce only the operating-point family -- an unknown device, an unparsable value or a node
    name ngspice reads differently would land outside it.
    """
    unexpected = [
        line
        for line in simulated[case.name].diagnostics
        if not (case.dc_open and any(noise in line.lower() for noise in OP_POINT_NOISE))
    ]
    assert not unexpected, f"{case.dsl}: ngspice reported " + "; ".join(unexpected)
