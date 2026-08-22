"""Fitting-engine benchmarks: accuracy, uncertainty calibration, and restart tuning.

These are measurements, not tests. The test suite asserts that the fitter works; these
scripts say *how well*, and are the source of the **[measured]** claims in
``docs/IMPLEMENTATION_PLAN.md``. Re-run them after changing the optimizer.

Usage (needs PYTHONPATH=src)::

    python benchmarks/fitting.py accuracy      # parameter recovery, 0% and 1% noise
    python benchmarks/fitting.py calibration   # are the reported standard errors honest?
    python benchmarks/fitting.py restarts      # how many restarts are actually needed?
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import numpy as np

from autocircuit.core.circuit import Circuit
from autocircuit.core.fit import fit
from autocircuit.core.simulate import log_frequencies, simulate


@dataclass(frozen=True)
class Case:
    """One reference circuit, its true parameters, and the sweep it is measured over.

    A record rather than a tuple because two of the cases below need a sweep the others do
    not: ``points_per_decade`` was a literal ``10`` in three places until the piezoelectric
    resonator arrived, and that case is unmeasurable at 10 points per decade (see its own
    comment). The suite is also selected from *by label* rather than by index -- ``HARD`` was
    ``SUITE[-1]`` and the calibration pair was ``(SUITE[1], SUITE[4])``, so appending a case
    silently moved the restart sweep onto a different circuit while still printing the old
    circuit's heading.
    """

    label: str
    dsl: str
    truth: dict[str, float]
    f_min: float
    f_max: float
    points_per_decade: int = 10

    def frequencies(self) -> np.ndarray:
        return log_frequencies(self.f_min, self.f_max, self.points_per_decade)


SUITE = [
    Case("capacitor C-ESR-ESL", "C1-R1-L1", {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10}, 1e2, 1e9),
    Case(
        "capacitor + skin effect",
        "C1-R1-L1-SKINF1",
        {"C1.C": 1e-6, "R1.R": 1e-2, "L1.L": 5e-10, "SKINF1.A": 2e-5, "SKINF1.n": 0.5},
        1e2,
        1e9,
    ),
    Case(
        "Randles",
        "R1-p(C1,R2-W1)",
        {"R1.R": 20.0, "C1.C": 1e-5, "R2.R": 100.0, "W1.A": 150.0},
        1e-2,
        1e5,
    ),
    Case(
        "Maxwell-Wagner, 2 blocks",
        "p(R1,C1)-p(R2,C2)",
        {"R1.R": 1e4, "C1.C": 1e-10, "R2.R": 5e5, "C2.C": 2e-8},
        1e-1,
        1e7,
    ),
    Case(
        "brick layer + CPE",
        "R1-p(R2,C1)-p(R3,CPE1)",
        {"R1.R": 50.0, "R2.R": 1e4, "C1.C": 1e-10, "R3.R": 8e4, "CPE1.Q": 3e-9, "CPE1.n": 0.8},
        1e-1,
        1e7,
    ),
    # Four parallel RC blocks in series: the Voigt (Maxwell) ladder, which is what a
    # multi-relaxation dielectric or ceramic (grain / grain boundary / two interfaces) reduces
    # to, and the same series form the linear Kramers-Kronig test fits internally. It is here
    # for *scale* rather than for degeneracy -- eight free parameters, the largest in the
    # suite -- so the time constants are placed ~2 decades apart (1e-7, 9e-6, 1e-3, 8e-2 s)
    # where every block is separately resolvable. The deliberately hard, overlapping version
    # lives in ``benchmarks/discovery_v2.py`` as ``LARGE_REFERENCES[0]``, whose last two blocks
    # are 0.6 decades apart; measuring both under one label would confuse "can the fitter carry
    # eight parameters" with "can the data separate two relaxations", which are different
    # questions with different answers.
    #
    # Swapping any two blocks' labels is the same circuit, so recovery is only meaningful
    # after ``canonicalize_values`` -- which is what ``canonical()`` below exists for.
    # [measured] 0/8 parameters unresolved at 1% noise, worst deviation 2.8% over 5 seeds.
    Case(
        "Voigt ladder, 4 blocks",
        "p(R1,C1)-p(R2,C2)-p(R3,C3)-p(R4,C4)",
        {
            "R1.R": 2e3,
            "C1.C": 5e-11,
            "R2.R": 3e3,
            "C2.C": 3e-9,
            "R3.R": 5e3,
            "C3.C": 2e-7,
            "R4.R": 8e3,
            "C4.C": 1e-5,
        },
        1e-2,
        1e7,
    ),
    # A piezoelectric resonator as the Butterworth-Van Dyke model: the clamped capacitance C0
    # in parallel with a motional branch R1-L1-C1. It is the only case in the suite with a
    # *resonance* rather than a relaxation, and the only one built from R, C and L alone --
    # which is the point, because everything else here is over-damped and a resonant circuit
    # exercises the optimizer on a feature that occupies a hundredth of the sweep.
    #
    # The numbers are a soft-PZT disc: fs = 198.94 kHz, fp = 208.65 kHz, mechanical Q = 100,
    # capacitance ratio C1/C0 = 0.1.
    #
    # **The sweep is part of the reference, not a detail.** A resonance of quality factor Q is
    # only ~1/Q wide, so resolving it needs roughly ``8 * ln(10) * Q`` points per decade -- 1500
    # here, for ~8 points inside the -3 dB width. That is also why the window is 0.2 decades
    # wide rather than the several decades the other cases use: a log sweep cannot
    # simultaneously span a wide band and resolve a Q = 100 peak at any sane point count, which
    # is exactly why resonator measurement is done as a narrow sweep around fs.
    #
    # What the sweep buys is precision, and only precision. The guess this comment first
    # carried was that the case would be unmeasurable at the suite's 10 points per decade;
    # [measured] it is not. The three points left in this window at 10 per decade recover all
    # four parameters exactly from noise-free data, and leave none unresolved at 1% noise --
    # what moves is the worst deviation over 10 seeds, 0.29% at 1500 points per decade against
    # 9.9% at 10. ``tests/test_fit.py::test_the_resonator_earns_its_sweep`` pins that ratio.
    Case(
        "piezo resonator (BVD)",
        "p(C1,R1-L1-C2)",
        {"C1.C": 2e-9, "R1.R": 40.0, "L1.L": 3.2e-3, "C2.C": 2e-10},
        1.6e5,
        2.6e5,
        points_per_decade=1500,
    ),
    # ---- Real parts, from here down -------------------------------------------------------
    #
    # The seven cases above are shapes: a relaxation, a resonance, a ladder, a skin effect. The
    # ones below are *devices* -- the equivalent circuits actually used to fit measured spectra of
    # a lithium-ion cell, a polymer capacitor, a ferrite bead, a coated steel panel, a solid-oxide
    # fuel cell, a piece of tissue, a dielectric and a thin-layer cell. They are here for two
    # reasons the shape cases cannot cover:
    #
    #  * **Element coverage.** Before these, ``Gerischer``, ``ColeCole``, ``HavriliakNegami`` and
    #    ``WarburgShort`` appeared in no benchmark at all. They have analytic tests, which says the
    #    formula is right; nothing said whether the *fitter* can recover their parameters from
    #    noisy data without initial values, which is this project's actual claim.
    #  * **Topology coverage.** ``coated steel panel`` is the first nested case in the suite -- a
    #    parallel block inside the branch of another parallel block -- and ``ferrite bead`` is the
    #    first three-way parallel. Every case above is a flat series of blocks.
    #
    # The parameter values are order-of-magnitude realistic for the named part rather than chosen
    # to fit well, and each one was measured before it was added: fitting the truth to its own data
    # at 0% and 1% noise over 5-10 seeds. Where a parameter came back badly the comment says which
    # and why, and one candidate was **dropped** rather than tuned:
    #
    # A wound ferrite-core inductor, ``p(C1,SKINW1-L1)``, was measured and is deliberately not
    # here. [measured] Its ``SKINW1.tau_s`` came back off by 27-142% over 3 seeds at 1% noise while
    # the other three parameters were exact, and the reason is not a fitter weakness: a winding's
    # skin effect is a resistance underneath its own reactance, so at the frequency where the skin
    # corner sits the loss is well under a percent of |Z| and 1% proportional noise erases it.
    # Measuring it needs a Q meter, not an impedance sweep. A reference whose truth the data does
    # not contain would measure the noise model rather than the fitter.
    Case(
        # A commercial lithium-ion cell, which is the most-fitted equivalent circuit in this whole
        # file: cable and cell inductance, the ohmic/electrolyte resistance, an SEI arc, and a
        # charge-transfer arc sharing its branch with solid-state diffusion. Ten parameters over
        # eight decades, the largest case in the suite.
        #
        # ``Wo`` rather than ``W`` for the diffusion: intercalation into a particle of finite size
        # is a reflecting boundary, so the low-frequency tail turns capacitive instead of holding
        # 45 degrees forever. ``W`` would be the wrong physics and would also be unbounded at DC.
        #
        # **The two time constants are 4 decades apart on purpose, and that is the case's whole
        # measurement.** [measured] With the SEI arc at 500 Hz and the charge-transfer arc at
        # 20 Hz -- 1.4 decades, which is what a room-temperature full cell really looks like --
        # 1 seed in 3 landed in a different basin at the *same* residual (1.318% against 1.240%),
        # with ``CPE1.Q`` out by 18740% and ``CPE2.Q`` by -99%. That is not a fitter failure: the
        # SEI/charge-transfer split genuinely is not identifiable when the arcs overlap, which is
        # why the literature resolves it on half cells or at low temperature. The fitter said so --
        # that run carried eight "varies across restarts: the fit is not unique" warnings and a
        # +0.9917 correlation between the two Warburg parameters -- so nothing was silently wrong;
        # but a *parameter-recovery* reference has to be recoverable. At 2 kHz and 0.2 Hz it is:
        # 10/10 seeds converge with no uniqueness warning at all.
        #
        # [measured] The worst parameter is then always ``CPE1.Q``, up to 29.4%, and that number is
        # a unit artefact rather than an error. Q is in S*s^n, so holding the CPE impedance fixed
        # while n moves forces d(ln Q) = -dn * ln(omega); regressing the ten seeds gives a slope of
        # -8.79 against the predicted -ln(2*pi*2000) = -9.44, correlation -0.986. The impedance
        # CPE1 actually produces at the arc's peak is recovered to within 6.58%.
        "lithium-ion cell",
        "L1-R1-p(R2,CPE1)-p(CPE2,R3-Wo1)",
        {
            "L1.L": 3e-7,
            "R1.R": 0.03,
            "R2.R": 0.012,
            "CPE1.Q": 0.0273,
            "CPE1.n": 0.85,
            "CPE2.Q": 41.6,
            "CPE2.n": 0.80,
            "R3.R": 0.02,
            "Wo1.R": 0.05,
            "Wo1.tau": 30.0,
        },
        1e-3,
        1e5,
    ),
    Case(
        # A conductive-polymer aluminium electrolytic capacitor: ~100 uF, 8 mOhm ESR, 1.5 nH ESL,
        # self-resonant near 410 kHz.
        #
        # It differs from "capacitor C-ESR-ESL" above in exactly one element, and that is the
        # point. A polymer capacitor's *measured* ESR rises towards low frequency, and the
        # circuit-level way to say that is a CPE with n just under 1 rather than an ideal C. At
        # n = 0.97 the CPE real part is cos(87.3 deg) = 4.7% of its magnitude, which at 100 Hz is
        # 0.9 Ohm against an 8 mOhm series ESR -- so below the resonance the loss that is measured
        # is the dielectric, not the ESR, which is exactly what a datasheet ESR curve shows and
        # what the ideal-C case cannot represent.
        #
        # There is no leakage resistance in parallel with the CPE, and leaving it out is a
        # measurement rather than a simplification: a 200 kOhm leakage only becomes visible where
        # 1/(omega*C) approaches it, which for 100 uF is 8 mHz. Inside a 100 Hz - 100 MHz window it
        # changes |Z| by 1e-4 of a percent. Putting it in the truth would ask the fitter to recover
        # a number the data does not contain.
        "polymer capacitor",
        "L1-R1-CPE1",
        {"L1.L": 1.5e-9, "R1.R": 8e-3, "CPE1.Q": 1.0e-4, "CPE1.n": 0.97},
        1e2,
        1e8,
    ),
    Case(
        # A ferrite bead -- 120 Ohm at 100 MHz, the commonest EMI part there is -- as its standard
        # model: the winding DC resistance in series with a parallel R, L, C.
        #
        # Two firsts in the suite. It is the only **three-way parallel**, so it is the only case
        # that exercises a parallel node of more than two branches at all. And it is the only
        # *lossy* resonance: Q = R*sqrt(C/L) = 1.28 here, against the piezoelectric resonator's
        # 100. A ferrite bead works precisely because that resonance is over-damped -- the broad
        # impedance hump is the loss it is sold for -- so the two resonant cases in this file sit
        # at opposite ends of the only axis that matters for a resonance, and the narrow dense
        # sweep the piezo needs is unnecessary here.
        #
        # The window reaches down to 10 kHz so that R1 is measurable: the bead is inductive over
        # most of the sweep, and only at the bottom does the 50 mOhm winding resistance dominate
        # |Z| (98% of it at 10 kHz).
        "ferrite bead",
        "R1-p(R2,L1,C1)",
        {"R1.R": 0.05, "R2.R": 120.0, "L1.L": 1.5e-7, "C1.C": 1.7e-11},
        1e4,
        1e9,
    ),
    Case(
        # An organic coating on steel in dilute salt, the standard coating-health model: solution
        # resistance, then the coating's own capacitance and pore resistance, and *inside the pore
        # branch* the double layer and charge transfer at the metal underneath.
        #
        # **The first nested topology in the suite.** Every case above is a flat series of blocks;
        # this one has a parallel block in the branch of another parallel block, which is a shape
        # the fitter, the canonical form, the SPICE writer and the schematic renderer all have to
        # handle and which nothing else here produces.
        #
        # [measured] The window and the solution resistance are both set by one failed first
        # attempt. At R1 = 30 Ohm over 10 mHz - 100 kHz the solution resistance came back out by
        # up to 50% over 5 seeds while every other parameter was within 3%, because at the top of
        # that window the coating impedance is still 1.5 kOhm and 30 Ohm of it is under the noise.
        # That is a real and well-known difficulty in coating work rather than an artefact -- but a
        # reference should measure the fitter, so the electrolyte was made a realistic 100 Ohm and
        # the sweep taken to 1 MHz, where the coating is down to 186 Ohm. Worst deviation over 5
        # seeds is then 2.8%.
        "coated steel panel",
        "R1-p(CPE1,R2-p(CPE2,R3))",
        {
            "R1.R": 100.0,
            "CPE1.Q": 3e-9,
            "CPE1.n": 0.92,
            "R2.R": 2e4,
            "CPE2.Q": 5e-5,
            "CPE2.n": 0.80,
            "R3.R": 3e5,
        },
        1e-2,
        1e6,
    ),
    Case(
        # A solid-oxide fuel cell cathode: lead inductance, the electrolyte ohmic resistance, one
        # R-CPE arc, and a Gerischer for the coupled surface reaction and ion transport in a
        # mixed-conducting electrode.
        #
        # Here for the Gerischer, which had no benchmark of any kind. It is not interchangeable
        # with a Warburg despite both going to 45 degrees at high frequency: G is resistive at DC
        # where W diverges, so the low-frequency end is where the two are told apart -- which is
        # why the window goes down to 0.1 Hz rather than stopping at the arc.
        #
        # [measured] Worst deviation over 5 seeds is 30.0% and it is always CPE1.Q, for the unit
        # reason set out on the lithium-ion case above; every other parameter is within 4%.
        "SOFC cathode (Gerischer)",
        "L1-R1-p(R2,CPE1)-G1",
        {
            "L1.L": 1e-7,
            "R1.R": 0.15,
            "R2.R": 0.08,
            "CPE1.Q": 5e-3,
            "CPE1.n": 0.85,
            "G1.R": 0.25,
            "G1.tau": 0.05,
        },
        1e-1,
        1e6,
    ),
    Case(
        # Tissue between two electrodes as the Cole model: an extracellular resistance in series
        # with one depressed relaxation, alpha = 0.8.
        #
        # Here for the ``CC`` element, which had no benchmark. It is also the smallest case in the
        # file at two elements, and it is worth having small: ``R1-p(R2,CPE1)`` fits the same data
        # to the same residual with the same number of parameters, so this is the suite's clearest
        # example of two different circuits being one model. The Cole element states the depressed
        # semicircle directly instead of manufacturing it from a CPE, which is the form the
        # bioimpedance literature reports in.
        "tissue (Cole)",
        "R1-CC1",
        {"R1.R": 300.0, "CC1.R": 700.0, "CC1.tau": 3e-5, "CC1.alpha": 0.80},
        1e1,
        1e6,
    ),
    Case(
        # A lossy polymer dielectric measured as a capacitor: the geometric capacitance in parallel
        # with a Havriliak-Negami relaxation, alpha = 0.8, beta = 0.6.
        #
        # Here for ``HN``, which had no benchmark, and it is the one that most needed one: alpha
        # and beta are two exponents multiplying into a single high-frequency slope of -alpha*beta,
        # so the obvious worry is that only their product is identifiable. [measured] It is not
        # only the product -- both come back, worst deviation 3.09% over 5 seeds at 1% noise, 0/25
        # parameters unresolved -- because alpha and beta separate the *asymmetry* of the loss peak
        # from its width, and the window here covers both flanks.
        "polymer dielectric (HN)",
        "p(C1,HN1)",
        {"C1.C": 2e-11, "HN1.R": 5e6, "HN1.tau": 1e-3, "HN1.alpha": 0.80, "HN1.beta": 0.60},
        1e-2,
        1e6,
    ),
    Case(
        # A thin-layer cell: electrolyte resistance, double-layer CPE, and charge transfer in
        # series with diffusion across a *transmissive* finite layer -- ``Ws``, whose far boundary
        # is a second electrode rather than a wall, so the low-frequency limit is a resistance.
        #
        # Here for ``Ws``, which had no benchmark, and it turned into the one genuinely awkward
        # case in the file. **[measured] It is the first case the default restart budget is not
        # enough for.** At the default 5 restarts it lands in a wrong basin -- 18% residual against
        # a 1.3% noise floor -- on 4 of 10 seeds; at 10 restarts, 1 of 10; at 20, 0 of 10. When it
        # does converge, all six parameters come back within 2%.
        #
        # The default is left at 5 rather than raised, for two reasons. Raising it multiplies the
        # cost of every fit in the program, including the tier-2 refits the topology search runs
        # thousands of, to fix a basin one circuit in fifteen falls into. And the failure is not
        # silent: those runs report ``R1.R`` and ``R2.R`` with standard errors larger than their
        # own values, which is the fitter saying it does not believe its own answer. Somebody
        # fitting this circuit should read that and pass ``restarts=20``; ``fitting.py restarts``
        # is where that number came from and is where to re-derive it.
        "thin-layer cell (Ws)",
        "R1-p(CPE1,R2-Ws1)",
        {
            "R1.R": 15.0,
            "CPE1.Q": 2e-5,
            "CPE1.n": 0.88,
            "R2.R": 60.0,
            "Ws1.R": 120.0,
            "Ws1.tau": 4.0,
        },
        1e-2,
        1e5,
    ),
]


def case(label: str) -> Case:
    """The suite entry with this label. By name, never by index: see :class:`Case`."""
    for entry in SUITE:
        if entry.label == label:
            return entry
    raise KeyError(label)


#: The hardest case in the suite; used for the restart sweep. Six parameters, three of which
#: trade against each other. Pinned by label so that appending to ``SUITE`` cannot move it --
#: the numbers in ``benchmarks/README.md`` are this circuit's.
HARD = case("brick layer + CPE")

#: The calibration pair, also pinned by label. Two relaxation cases plus the two additions --
#: eight parameters, and a resonance, both of which are new shapes for the covariance estimate
#: rather than more of the same.
CALIBRATION = [
    case("capacitor + skin effect"),
    case("brick layer + CPE"),
    case("Voigt ladder, 4 blocks"),
    case("piezo resonator (BVD)"),
]


def canonical(circuit: Circuit, values: dict[str, float] | np.ndarray) -> dict[str, float]:
    """Parameters in canonical branch order, so a relabelling is not counted as an error."""
    array = circuit.values_array(values) if isinstance(values, dict) else np.asarray(values)
    return circuit.values_dict(circuit.canonicalize_values(array))


def run_accuracy() -> None:
    for noise in (0.0, 0.01):
        print(f"\n=== parameter recovery, noise = {noise:.1%} ===")
        for entry in SUITE:
            circuit = Circuit.parse(entry.dsl)
            data = simulate(circuit, entry.frequencies(), entry.truth, noise=noise, seed=0)
            started = time.perf_counter()
            result = fit(circuit, data, seed=0)
            elapsed = time.perf_counter() - started

            expected = canonical(circuit, entry.truth)
            got = canonical(circuit, result.values)
            worst = max(abs(got[k] - v) / abs(v) for k, v in expected.items())
            # The fit's own verdict, printed beside the deviation because the two answer
            # different questions and a reader who sees only the first will misread the second.
            # ``thin-layer cell (Ws)`` is the case that forced this: at the default restart
            # budget it lands in a wrong basin on some seeds and prints a five-figure deviation,
            # which looks like a broken suite until you can see that the fitter flagged the run.
            # A large deviation with warn=0 is a *silent* error and is the serious kind; a large
            # deviation with warn>0 is the program saying it does not believe its own answer.
            warned = len(result.warnings)
            print(
                f"  {entry.label:<26}n={circuit.n_params:<3}worst={worst:9.2%}  "
                f"rel|Z|={result.relative_error:7.3%}  warn={warned}  t={elapsed:5.2f}s"
            )


def run_calibration(trials: int = 25, noise: float = 0.01) -> None:
    """A z-score is (fitted - true) / reported stderr. It should look like N(0, 1)."""
    for entry in CALIBRATION:
        circuit = Circuit.parse(entry.dsl)
        f = entry.frequencies()
        scores: dict[str, list[float]] = {name: [] for name in entry.truth}
        for trial in range(trials):
            data = simulate(circuit, f, entry.truth, noise=noise, seed=1000 + trial)
            result = fit(circuit, data, seed=trial)
            errors = result.stderr
            for name, true_value in entry.truth.items():
                if errors[name] > 0:
                    scores[name].append((result.params[name] - true_value) / errors[name])

        print(f"\n{entry.label} ({trials} noise realisations at {noise:.0%})")
        print(f"  {'parameter':<12}{'mean z':>9}{'std z':>9}{'|z|<2':>8}  (ideal 0.0, 1.0, ~95%)")
        for name, values in scores.items():
            array = np.array(values)
            print(
                f"  {name:<12}{array.mean():>9.2f}{array.std():>9.2f}"
                f"{np.mean(np.abs(array) < 2.0):>8.0%}"
            )


def run_restarts(trials: int = 25) -> None:
    circuit = Circuit.parse(HARD.dsl)
    truth = HARD.truth
    f = HARD.frequencies()
    datasets = [simulate(circuit, f, truth, noise=0.01, seed=1000 + t) for t in range(trials)]

    print(f"\n=== restart sweep on '{HARD.label}' ({trials} noise realisations) ===")
    print(f"{'restarts':>9}{'popsize':>9}{'failures':>10}{'worst err':>11}{'mean t':>9}")
    for restarts, popsize in ((3, 20), (5, 20), (8, 20), (3, 40), (5, 40)):
        failures = 0
        worst_overall = 0.0
        started = time.perf_counter()
        for trial, data in enumerate(datasets):
            result = fit(circuit, data, restarts=restarts, popsize=popsize, seed=trial)
            worst = max(abs(result.params[k] - v) / abs(v) for k, v in truth.items())
            if worst > 0.2:
                failures += 1
            else:
                worst_overall = max(worst_overall, worst)
        elapsed = (time.perf_counter() - started) / trials
        print(
            f"{restarts:>9}{popsize:>9}{failures:>4}/{trials:<5}"
            f"{worst_overall:>11.2%}{elapsed:>9.2f}s"
        )


COMMANDS = {"accuracy": run_accuracy, "calibration": run_calibration, "restarts": run_restarts}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "accuracy"
    if name not in COMMANDS:
        raise SystemExit(f"usage: fitting.py [{'|'.join(COMMANDS)}]")
    COMMANDS[name]()
