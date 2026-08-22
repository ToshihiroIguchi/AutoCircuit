"""Which elements the search needs, decided from the spectrum instead of from the part.

``CLAUDE.md`` requires the automatic path to take frequency and impedance and nothing else, and
in particular never to ask what kind of component this is. A fixed default pool breaks that
quietly: ``("R", "C", "L", "CPE")`` is the answer "this is not an electrochemical cell",
written into a default the target user will never change, and the coverage sentence goes on
saying *every plausible topology from this pool* without mentioning that a whole family of
elements was never on the table.

This module supplies the two decisions that replace it. Both are measured in
``docs/POOL_FROM_SPECTRUM_PLAN.md``; what follows is what the measurements settled.

**The trigger is two readings, and neither one alone would do.** Both were tried as the sole
trigger and both were rejected by measurement, on *different* spectra:

* The **shape** reading -- how many decades the spectrum runs at 45 degrees -- separates a pure
  diffusion spectrum from a pure relaxation one completely and fails on composite ones. With a
  relaxation sitting on the diffusion branch, ``R1-p(R2,CPE1)-Wo1`` gives a run of 0.20 to 0.60
  decades against a *diffusion-free* range of 0.00 to 0.50, because a depressed arc's own
  tangent sweeps through 45 degrees on its way round. No threshold admits it.
* The **residual** reading -- whether a completed base-pool search left something that looks
  like structure rather than noise -- catches that case at runs z -5.42, and loses ``R1-Ws1``:
  -2.07, -0.77 and -1.03 at three noise seeds. Given five elements the base pool builds an
  eight-parameter CPE stack that explains the data to within noise, so the sign pattern of what
  is left carries almost nothing. What separates the models there is parsimony, three parameters
  against eight, and the runs test does not see parsimony.

So :func:`choose_pool` widens when *either* asks. That is affordable because the two errors are
not symmetric: a spurious widening costs a second search and changes no reported number, since
the base pool's candidates are kept and the coverage it reached is recorded separately, while a
missed one returns an eight-parameter stand-in that no statistic in the report flags.

**Which codes is a question about the DC limit.** ``Ws``, ``Wo`` and ``G`` are alike at high
frequency (all exponent -0.5) and differ only at the other end: 0, -1 and 0.
:class:`~autocircuit.core.enumerate.EndpointBehaviour` already measures the interval of
low-frequency exponents the data admits, generously widened, and the feasibility screen already
trusts it to *drop* topologies; :func:`admissible_diffusion_codes` asks it the same question one
step earlier. The true code lands in the admitted set in 138 of 144 measured trials.

**``W`` is never added, and that is the one exclusion here with a measurement behind it.** A
semi-infinite Warburg *is* a CPE at ``n = 0.5`` -- ``A/sqrt(j w)`` against ``1/(Q (j w)^n)`` --
and on an ``R1-W1`` spectrum ``R1-CPE1`` fits to 1.3344%, the same five figures as the truth's
own 1.3344%. The pool already contains it under another name, so a slot spent on ``W`` buys one
parameter of parsimony and no reach.

That exclusion is what makes an ``R1-W1`` spectrum come out right, and by a route worth
following: the shape reading fires on it loudly -- three decades of 45 degrees at worst, since
it *is* a 45-degree spectrum -- and the residual reading does not, at runs z +0.00, because the
pool can already express it. The widening therefore runs, the low-frequency band admits only
``W``, and **nothing is added**. Two independent facts agreeing, and the report says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from . import elements
from .elements import DEFAULT_POOL
from .enumerate import EndpointBehaviour
from .spectrum import Spectrum

#: What a completed base-pool search said about needing more elements.
#:
#: ``"unasked"`` exists because the genetic search never finishes a pool, so there is no
#: residual to read and the honest report is that nothing checked -- which is a different
#: statement from having checked and found nothing.
Trigger = Literal["yes", "no", "unasked"]

#: Runs-test z below which a completed base-pool search is taken to be missing an *element*.
#:
#: Deliberately looser than :data:`~autocircuit.core.validate.RUNS_Z_LIMIT`, which the same
#: statistic is compared against for a different decision. [measured,
#: docs/POOL_FROM_SPECTRUM_PLAN.md section 5] At the production limit of five elements, spectra
#: generated from ``Ws``, ``Wo`` and ``G`` leave the best default-pool fit at z = -2.07, -2.58
#: and -5.42, while spectra the default pool covers exactly leave it at -0.26, -0.26 and +0.00
#: -- so the statistic separates them and -3.0 sits on the wrong side of two of them.
#:
#: The bar is low because the two errors are not symmetric: firing wrongly costs a second
#: search and changes no reported number, since the base pool's candidates are kept and the
#: coverage it reached is recorded in ``DiscoveryResult.base_complete_up_to``. Failing to fire
#: returns an eight-parameter CPE stack in place of a three-parameter Warburg, which no
#: statistic in the report flags.
#:
#: The price is computable rather than guessed: the runs z is standard normal when the signs
#: are random and the smaller of two halves is taken, so a *correctly* fitted spectrum widens
#: spuriously with probability ``1 - (1 - Phi(t))**2`` -- 12.9% here, against 4.5% at -2.0 and
#: 0.27% at -3.0.
POOL_WIDENING_RUNS_Z = -1.5

#: Diffusion codes the automatic path may spend a pool slot on, in report order.
#:
#: ``W`` is deliberately absent; see the module docstring. ``CC``, ``HN``, ``SKINF`` and
#: ``SKINW`` are absent for a different reason -- nothing has measured whether the default pool
#: can already express them, so adding them here would be the same unmeasured guess this module
#: exists to remove.
WIDENING_CANDIDATES: tuple[str, ...] = ("Ws", "Wo", "G")

#: Every diffusion code the decision is *about*, which is one more than it may add.
#:
#: ``W`` belongs here and not above: it is considered on every run and rejected on every
#: run, always for the same measured reason, and a report that simply never mentioned it
#: would be silent about an element in exactly the way this module exists to stop.
CONSIDERED: tuple[str, ...] = ("W",) + WIDENING_CANDIDATES

#: Why a candidate code was not added. Keyed by code where the reason is about the code itself.
_REDUNDANT = (
    "a CPE at n = 0.5 is the same impedance, so the pool already contains it (measured: "
    "identical 1.3344% relative error on an R1-W1 spectrum)"
)


@dataclass(frozen=True)
class PoolChoice:
    """Which elements the search was given, and what the spectrum said about the rest.

    Recorded whether or not anything was added, because the silent case is the one the rule
    exists for: a report that says nothing about the diffusion elements has excluded them just
    as thoroughly as one that names them.
    """

    base: tuple[str, ...]
    """The pool every automatic search starts from. Never reduced by anything here."""
    added: tuple[str, ...]
    """Codes the widening spent a slot on, empty when it did not fire or admitted nothing."""
    rejected: tuple[tuple[str, str], ...]
    """``(code, reason)`` for every candidate considered and left out."""
    low_band: tuple[float, float]
    """The measured low-frequency exponent interval the choice was made against."""
    diffusion_decades: float
    """Longest 45-degree run the spectrum shows. Always measured, since it needs no search."""
    residual_runs_z: float
    """Runs z of the best base-pool fit, or NaN when no completed search could supply one."""

    @property
    def pool(self) -> tuple[str, ...]:
        return self.base + self.added

    @property
    def shape_asks(self) -> bool:
        """The spectrum's own shape asks for the diffusion elements."""
        return self.diffusion_decades >= DIFFUSION_RUN_DECADES

    @property
    def residual_asks(self) -> bool:
        """A completed base-pool search left a residual that looks like a missing element."""
        z = self.residual_runs_z
        return False if math.isnan(z) else z < POOL_WIDENING_RUNS_Z

    @property
    def triggered(self) -> Trigger:
        """Whether anything asked for a wider pool, in three states rather than two.

        Derived rather than stored, so the record cannot disagree with the readings it was
        built from -- a version of this class that carried the verdict as its own field let a
        test construct a ``"yes"`` whose two readings both said no, and the sentence and the
        flag then described different runs.

        ``"unasked"`` is not a variant of ``"no"`` and must never be reported as one. It is the
        genetic search, which never completes a pool and so never produces half the evidence
        this decision rests on. It wins over a firing shape reading on purpose: half the
        evidence is missing whatever the other half says, and :meth:`sentence` reports the
        shape reading separately, so a spectrum that looks like diffusion under a search that
        could not check says exactly that.
        """
        if math.isnan(self.residual_runs_z):
            return "unasked"
        return "yes" if (self.shape_asks or self.residual_asks) else "no"

    def to_dict(self) -> dict[str, object]:
        """The machine-readable form, for the CLI's ``--json`` and the browser's download."""
        return {
            "base": list(self.base),
            "added": list(self.added),
            "pool": list(self.pool),
            "rejected": [{"code": code, "reason": why} for code, why in self.rejected],
            # An unconstrained edge is null rather than Infinity: `json.dumps` writes
            # `-Infinity` for a float infinity, which Python reads back and no other parser
            # accepts -- including the browser's, which reads this same report.
            "low_band": [
                edge if math.isfinite(edge) else None for edge in self.low_band
            ],
            "diffusion_decades": self.diffusion_decades,
            "residual_runs_z": (
                self.residual_runs_z if math.isfinite(self.residual_runs_z) else None
            ),
            "triggered": self.triggered,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        """One line naming what was left out and why, for the coverage report."""
        family = ", ".join(CONSIDERED)
        base = ", ".join(self.base)
        if self.triggered == "unasked":
            return (
                f"Pool: {base}, with the diffusion elements ({family}) left out. "
                f"{self._evidence()} -- and the other half of that check is a completed "
                "exhaustive search, which this run did not do -- so their absence here is not "
                f"evidence against them. {self._left_out()}"
            )
        if self.triggered == "no":
            return (
                f"Pool: {base}. {self._evidence()}, so the diffusion elements ({family}) were "
                "considered and not needed. They were never fitted, so this report is not "
                f"evidence against them either. {self._left_out()}"
            )
        if not self.added:
            return (
                f"Pool: {base}. {self._evidence()}, so more elements were looked for, but none "
                f"of {family} survived {self._band()} and the pool was not widened. "
                f"{self._left_out()}"
            )
        return (
            f"Pool: {base}. {self._evidence()}, so {', '.join(self.added)} was added, admitted "
            f"by {self._band()}. {self._left_out()}"
        )

    def _evidence(self) -> str:
        """What the two independent readings said, both of them, in the report's own words.

        Both are named whichever fired, because a reader who sees only the one that fired
        cannot tell a spectrum both instruments agreed on from one where they disagreed -- and
        they disagree often, which is the whole reason there are two.
        """
        shape = (
            f"the spectrum shows a {self.diffusion_decades:.2f}-decade 45-degree branch"
            if self.shape_asks
            else f"the longest 45-degree branch is {self.diffusion_decades:.2f} decades"
        )
        if math.isnan(self.residual_runs_z):
            return f"Nothing tested the fit's residual and {shape}"
        residual = (
            f"the fit left a systematic residual (runs z {self.residual_runs_z:+.2f})"
            if self.residual_asks
            else f"the fit left no systematic residual (runs z {self.residual_runs_z:+.2f})"
        )
        return f"{residual.capitalize()} and {shape}"

    def _band(self) -> str:
        """The low-frequency band as a noun phrase, saying so when it constrained nothing.

        An unconstrained edge means the sweep never reached the limit that tells the
        finite-length elements apart, so every candidate is admitted -- the generous answer,
        and not a measurement. Printing it as "[-inf, +inf]" would read as one.
        """
        lo, hi = self.low_band
        if not (math.isfinite(lo) and math.isfinite(hi)):
            return (
                "a low-frequency limit the sweep never reaches, which rules nothing out"
            )
        return f"a measured low-frequency exponent of [{lo:+.2f}, {hi:+.2f}]"

    def _left_out(self) -> str:
        """The rejected codes, grouped by reason so a shared one is stated once.

        Every rejection carries its own reason because they are not always the same one, but
        listing four codes with four copies of one sentence buries the case where they differ,
        which is the case a reader needs to see.
        """
        if not self.rejected:
            return "Nothing else was considered."
        by_reason: dict[str, list[str]] = {}
        for code, why in self.rejected:
            by_reason.setdefault(why, []).append(code)
        parts = [f"{', '.join(codes)}, because {why}" for why, codes in by_reason.items()]
        return f"Left out: {'; '.join(parts)}."


def admissible_diffusion_codes(
    spectrum: Spectrum,
    *,
    candidates: tuple[str, ...] = WIDENING_CANDIDATES,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Split ``candidates`` into the codes the low-frequency band admits and the rest.

    The band comes from :meth:`EndpointBehaviour.from_spectrum`, so it is the same interval,
    with the same tolerance and the same three-standard-error widening, that the feasibility
    screen uses to drop topologies. A code is admitted when its ``dc_exponent`` interval
    overlaps that band at all -- the generous test, because a false positive costs search time
    and a false negative costs the answer.

    A band of ``(-inf, inf)`` means the data says nothing about its low-frequency end, in which
    case every candidate is admitted rather than none.
    """
    behaviour = EndpointBehaviour.from_spectrum(spectrum)
    lo, hi = behaviour.low_band
    admitted: list[str] = []
    rejected: list[tuple[str, str]] = []
    for code in candidates:
        e_lo, e_hi = elements.get(code).dc_exponent
        if e_hi >= lo and e_lo <= hi:
            admitted.append(code)
        else:
            rejected.append(
                (
                    code,
                    f"a DC limit of exponent {e_lo:+.2f} is outside the measured "
                    f"[{lo:+.2f}, {hi:+.2f}]",
                )
            )
    return tuple(admitted), tuple(rejected)


def choose_pool(
    spectrum: Spectrum,
    *,
    residual_runs_z: float,
    base: tuple[str, ...] = DEFAULT_POOL,
) -> PoolChoice:
    """The pool to search with, from two independent readings of the same question.

    ``residual_runs_z`` is what a completed search on ``base`` left behind, or NaN when no
    completed search could supply one. It is passed in because this module has no business
    running a search; the other reading, the spectrum's own 45-degree run, is computed here
    because it needs nothing but ``f`` and ``Z``.

    **Either reading is enough to widen, and that is a measurement, not caution.** They fail on
    different spectra: on ``R1-Ws1`` the residual reads -2.07 at one noise seed and -0.77 at the
    next, because given five elements the base pool builds an eight-parameter CPE stack that
    explains the data to within noise, while the shape reads 1.60 decades at worst; on
    ``R1-p(R2,CPE1)-Wo1`` the shape reads 0.20 to 0.60, inside the diffusion-free range, while
    the residual reads -5.42. Neither alone covers the set.

    The decision is reported in all three states, including when nothing widened, because the
    silent case is the one the rule exists for.
    """
    behaviour = EndpointBehaviour.from_spectrum(spectrum)
    decades = diffusion_branch_decades(spectrum)
    shape_asks = decades >= DIFFUSION_RUN_DECADES
    residual_asks = (
        False if math.isnan(residual_runs_z) else residual_runs_z < POOL_WIDENING_RUNS_Z
    )

    if not (shape_asks or residual_asks):
        # A search that never ran cannot report having checked. The shape half *was* checked
        # even then -- it needs no search -- so "unasked" here means exactly one of the two
        # readings is missing, and the sentence says which.
        reason = (
            "no completed search was available to say whether it was needed, and the "
            "spectrum shows no 45-degree branch either"
            if math.isnan(residual_runs_z)
            else "the base pool fitted without leaving a systematic residual, and the "
            "spectrum shows no 45-degree branch"
        )
        return PoolChoice(
            base=base,
            added=(),
            rejected=tuple((code, reason) for code in WIDENING_CANDIDATES)
            + (("W", _REDUNDANT),),
            low_band=behaviour.low_band,
            diffusion_decades=decades,
            residual_runs_z=residual_runs_z,
        )

    admitted, rejected = admissible_diffusion_codes(spectrum)
    added = tuple(code for code in admitted if code not in base)
    return PoolChoice(
        base=base,
        added=added,
        rejected=rejected + (("W", _REDUNDANT),),
        low_band=behaviour.low_band,
        diffusion_decades=decades,
        residual_runs_z=residual_runs_z,
    )


#: Half-width in decades of the window each local Nyquist angle is regressed over.
#:
#: 0.35 either side is about seven points on a 10-per-decade sweep -- enough that 1% noise does
#: not dominate the slope, short enough that a transition is not averaged away.
ANGLE_HALF_DECADES = 0.35

#: How far from 45 degrees a local Nyquist angle may sit and still count as diffusion-like.
ANGLE_TOLERANCE_DEG = 12.0

#: How long a 45-degree run must be, in decades, before it is evidence rather than a tangent.
#:
#: [measured, docs/POOL_FROM_SPECTRUM_PLAN.md section 3] Every arc's tangent passes through 45
#: degrees on its way round, so the question is never "is there a 45-degree point" but "for how
#: long". Over 3 seeds x 2 noise levels x 4 grids, eight diffusion-free truths reach at most
#: 0.50 decades and a depressed arc at ``n = 0.80`` at most 0.60, while ``R1-Ws1``, ``R1-Wo1``
#: and ``R1-G1`` never fall below 1.00. 0.75 sits between them, nearer the side whose error is
#: cheap: a spurious widening costs a second search and changes no reported number.
DIFFUSION_RUN_DECADES = 0.75


def diffusion_branch_decades(
    spectrum: Spectrum,
    *,
    half_decades: float = ANGLE_HALF_DECADES,
    tolerance_deg: float = ANGLE_TOLERANCE_DEG,
) -> float:
    """Longest contiguous stretch, in decades, where the spectrum runs at 45 degrees.

    The quantity is the **local Nyquist angle**, ``atan2(dIm/dln w, -dRe/dln w)``, and both
    halves of that expression were arrived at by a measurement rather than by inspection
    (docs/POOL_FROM_SPECTRUM_PLAN.md section 3):

    * It is a *derivative*, so an additive constant vanishes. The phase of ``Z`` itself is the
      wrong quantity, because ``Ws``, ``Wo`` and ``G`` are 45-degree at their high-frequency
      end -- exactly where a series resistance dominates the total -- and a detector built on
      ``arg Z`` misses ``R1-Wo1`` and ``R1-G1`` completely.
    * The sign is the direction of travel. A Nyquist plot is traversed towards *decreasing*
      frequency; taken the other way every case reports no branch at all.

    Read what this is for in :func:`is_diffusion_shaped`: it is one of two triggers, and on its
    own it is known to fail on composite spectra.
    """
    if spectrum.n < 3:
        return 0.0
    log_omega = np.log(spectrum.omega)
    window = half_decades * math.log(10.0)
    re, im = spectrum.z.real, spectrum.z.imag

    best = 0.0
    run_start: float | None = None
    previous_ok = False
    for i in range(log_omega.size):
        selected = np.abs(log_omega - log_omega[i]) <= window
        ok = False
        if int(np.count_nonzero(selected)) >= 3:
            centred = log_omega[selected] - log_omega[selected].mean()
            sxx = float(np.dot(centred, centred))
            if sxx > 0.0:
                d_re = float(np.dot(centred, re[selected] - re[selected].mean()) / sxx)
                d_im = float(np.dot(centred, im[selected] - im[selected].mean()) / sxx)
                angle = math.degrees(math.atan2(d_im, -d_re))
                ok = abs(angle - 45.0) <= tolerance_deg
        if ok and not previous_ok:
            run_start = float(log_omega[i])
        if not ok and previous_ok and run_start is not None:
            best = max(best, (float(log_omega[i - 1]) - run_start) / math.log(10.0))
        previous_ok = ok
    if previous_ok and run_start is not None:
        best = max(best, (float(log_omega[-1]) - run_start) / math.log(10.0))
    return best


def is_diffusion_shaped(
    spectrum: Spectrum, *, min_decades: float = DIFFUSION_RUN_DECADES
) -> bool:
    """Whether the spectrum's own shape asks for the diffusion elements.

    **This is the second of two triggers and neither one is sufficient**, which is a
    measurement rather than a hedge. [measured, every truth at three noise seeds] The residual
    reading fires for the *composite* truths 6 times in 6 and for the *single-element* ones 2
    times in 9; this reading is the exact mirror image, 24/24 on the single-element truths and
    degrading to 17/24 and then 0/24 as the diffusion branch gets more obscured.

    That is not two noisy instruments averaging out. The shape reading sees an unobstructed
    diffusion branch; the residual reading sees the misfit a diffusion branch causes *when
    something else obscures it*. Exactly what hides one is what reveals the other. ``R1-G1`` is
    the sharpest case: its residuals read -0.77, +0.77 and -0.26, *inside* the distribution that
    diffusion-free spectra occupy, so no residual threshold whatever could separate it -- and
    this reading calls it 24 times out of 24.
    """
    return diffusion_branch_decades(spectrum) >= min_decades
