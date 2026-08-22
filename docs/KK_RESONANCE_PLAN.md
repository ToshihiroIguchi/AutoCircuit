# Lin-KK and the resonance it cannot express

Status: **implemented; gates K1–K4 measured.** Written 2026-08-22.

This plan exists because a benchmark addition exposed a defect in the project's most important
safety check, and the obvious fix for it was measured to be worse than the defect.

## 1. The defect

`autocircuit.core.validate` implements the linear Kramers-Kronig test: fit the data with a
series of Voigt (parallel RC) elements on a fixed logarithmic time-constant grid, plus a series
resistance, inductance and capacitance, and read the verdict off the *pattern* of the residual.
Every basis element is KK-compliant by construction, so a systematic residual is evidence about
the data.

That reasoning has a hole. The basis has only real poles. A complex **pole** of Z — an
anti-resonance, which is what a parallel resonance is — is unreachable at any order.

[measured] On a Butterworth-Van Dyke resonator, which is KK-compliant by construction because
it is the exact response of a passive circuit, the residual sits at 96.8% of |Z| from M = 3 all
the way to M = 317, flat to four figures. The order scan and Schoenleber's mu criterion are
working correctly; there is nothing to select.

Two things that sound like the same statement are not:

- **A series resonance is fine.** A series R-L-C *is* the basis's three series terms, and it
  passes with a 0.98% residual. It is the pole, not the resonance.
- **The damage depends on Q.** At high Q the model misses so completely that the residual
  magnitude gives it away, and `MODEL_FAILURE_RMS` (25% RMS) already catches that as
  `verdict == "inconclusive"`. At moderate damping it is *half*-reached and the residual is
  small but still systematic: [measured] Q = 2, 3, 5, 10, 15 give 1.3%, 2.6%, 4.6%, 17.6% and
  24.5% RMS with runs z from -5.7 to -17.3. Those report as a plain failure and blame the
  measurement.

Closing that band is what this plan is about.

## 2. The obvious fix, and why it is not the fix

Give the basis complex poles: add a bank of parallel R-L-C blocks whose resonant frequency and
quality factor are **fixed on a grid**, so that only their amplitudes are free and the solve
stays ordinary linear least squares. The block is

    Z(w) = A / (1 + jQ (w/w0 - w0/w))

and with (w0, Q) fixed it is linear in A, which is the whole point of Lin-KK. In pole form it
is A (w0/Q) s / (s^2 + (w0/Q) s + w0^2): a conjugate pole pair at fixed distance from the
imaginary axis, in the left half plane for any Q > 0, and Hermitian, so the sign of A does not
move the poles and a negative amplitude is no less causal than Lin-KK's negative R_k already
are. Two numerator functions per pole pair (band-pass and low-pass) span every residue that
pole pair can carry.

The mathematics works. **The measurement says do not ship it as the test.**

[measured] With a bank of 200 columns added to a 20-element Voigt model, a Randles spectrum
drifting 1000% across the sweep — a gross KK violation — fits to **0.00% residual with random
residual signs**. It would pass. So would every other violation tried.

The reason is not subtle once seen: that spectrum has 61 points, so 122 real equations against
223 unknowns. The system is underdetermined and fits anything. The existing `hard_cap` counts
Voigt elements against `2 * len(spectrum)`; a bank that is not counted in the same budget
destroys the test.

Budgeting the bank as a fraction of the data recovers the trade-off — [measured] at 40% of 2N a
drifting Randles still fails at 10, 30 and 50 points per decade while the resonator passes — but
it turns the model order into a two-dimensional scan (how many relaxations, how many
resonances), needs the mu criterion extended to a second kind of coefficient, and moves every
Lin-KK number this repository has recorded. A prototype allocation that split the budget one
third to relaxations was measured to *fail clean Randles data* at 14.1% residual, because it
starved the relaxation part the existing scan sizes properly.

That is a redesign of the order-selection machinery, and the thing being redesigned is the check
that protects every other result in the project.

## 3. What is implemented instead: a probe, not a replacement

The extended basis is used to ask **one additional question, only of spectra that have already
failed**, and it can only ever weaken a verdict:

1. Run the existing scan, unchanged. Nothing about it moves.
2. `passed` — done, `verdict == "pass"`. The probe never runs.
3. Not passed, and the residual is at or above `MODEL_FAILURE_RMS` — the model never followed
   the data at all, `verdict == "inconclusive"` as before.
4. Not passed, residual below that — **run the probe**: refit at the selected M with a resonant
   bank of about `PROBE_COLUMN_FRACTION` of 2N columns added. If the probe's residual is no
   longer systematic and is itself below `MODEL_FAILURE_RMS`, the plain failure was the basis
   missing an anti-resonance rather than the data being inconsistent, so
   `verdict == "inconclusive"` with a message that says exactly that.
5. Otherwise `verdict == "fail"`.

Three properties make this safe in a way the replacement is not:

- **Nothing that passes today changes**, by construction: the probe is not reached from a pass.
  No recorded number moves.
- **Nothing can become a pass.** The probe's only possible effect is `fail` to `inconclusive`.
  A more flexible KK model fitting the data is weaker evidence than the plain test passing, and
  `inconclusive` is exactly the claim that evidence supports: nothing about the measurement.
- **The probe is bounded by the data, not by the answer it is being asked about.**

The acceptance rule is the runs test, not the residual magnitude. A first version required the
probe to beat the plain residual threefold as well; [measured] that dropped the Q = 2 resonator,
whose plain residual is already only 1.3%, while contributing nothing to safety — the drift
family is separated by the runs test alone, at runs z from -5.0 to -15.3.

## 4. Gates

**K1 — no regression.** Every spectrum that passes today still passes, with the same element
count, mu and residuals. Structural: the probe is unreachable from a pass. Asserted in
`tests/test_validate.py`, and the whole suite is the wider check.

**K2 — the power is preserved.** Multiplicative drift of 40%, 100%, 300% and 1000% at 10, 30
and 50 points per decade must still report `fail`, 12 of 12.

**K3 — the gap closes.** The Butterworth-Van Dyke family at Q = 2, 5 and 15 must move from
`fail` to `inconclusive`; at Q = 100 and 300 it must stay `inconclusive`.

**K4 — nothing becomes a pass.** The probe's effect is one-directional, in code and in a test.

## 5. What is still not fixed, and is not pretended to be

**The test still cannot validate a resonator.** `inconclusive` is the honest verdict, not a
workaround for one. Data with an anti-resonance gets no Kramers-Kronig verdict from this tool,
and the only way to change that is the redesign section 2 rejected — with its own plan, its own
gates and a re-measurement of every Lin-KK number recorded in this repository.

**A spectrum of pure noise still passes.** [measured] Random impedances give a 60.7% residual
with random signs, and `passed` is `max_residual <= limit or not systematic`, so it passes.
That hole predates this work and is untouched by it. It belongs to the `passed` rule rather
than to the basis, and changing `passed` would move numbers this plan deliberately does not.
