"""Idea 2d, actually measured (not desk analysis): does the residual left by an undersized
candidate point at *where* the missing element belongs?

Method: for `mw5` (5 series p(R,C) blocks), drop one block at a time from the topology string,
fit the resulting 4-block circuit to the *full 5-block* data with the production `fit()`, and
check whether the frequency at which the residual's magnitude peaks matches the dropped block's
own relaxation frequency `1/(2*pi*R*C)`. If a real signal exists, the residual-peak frequency
should track the dropped block's true relaxation frequency across all five blocks and several
noise seeds; if it does not, a mutation operator guided by "insert near the residual peak" has no
real signal to use on a spectrum shaped like this project's own multi-block references, which
directly checks the desk-analysis argument (that this collides with
`docs/POOL_FROM_SPECTRUM_PLAN.md` section 3's failed diffusion-branch detector on composite
spectra) instead of resting on the analogy alone.

Decision rule, fixed before running: worth building a mutation-guidance heuristic only if the
residual-peak frequency is within one decade of the true dropped-block frequency on a clear
majority of (block, seed) pairs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from truths import MW5, spectrum_for  # noqa: E402

from autocircuit.core.fit import fit  # noqa: E402

SEEDS = range(5)


def drop_block(circuit_text: str, block_index: int) -> str:
    """Remove the block_index-th 'p(R_i,C_i)' block (0-based) from a '-' joined chain."""
    blocks = circuit_text.split("-")
    remaining = blocks[:block_index] + blocks[block_index + 1 :]
    return "-".join(remaining)


def block_frequency(params: dict[str, float], r_label: str, c_label: str) -> float:
    r = params[f"{r_label}.R"]
    c = params[f"{c_label}.C"]
    return 1.0 / (2.0 * np.pi * r * c)


def main() -> None:
    truth = MW5
    blocks = re.findall(r"R(\d+),C(\d+)", truth.circuit)
    n_blocks = len(blocks)

    within_one_decade = 0
    total = 0
    for block_idx, (r_label_num, c_label_num) in enumerate(blocks):
        true_freq = block_frequency(truth.params, f"R{r_label_num}", f"C{c_label_num}")
        reduced_circuit = drop_block(truth.circuit, block_idx)

        for seed in SEEDS:
            spectrum = spectrum_for(truth, seed=seed)
            result = fit(reduced_circuit, spectrum, seed=seed)
            residual_mag = np.abs(result.z_model - spectrum.z)
            peak_idx = int(np.argmax(residual_mag))
            peak_freq = spectrum.f[peak_idx]

            decades_off = abs(np.log10(peak_freq) - np.log10(true_freq))
            hit = decades_off <= 1.0
            within_one_decade += int(hit)
            total += 1
            print(
                f"block {block_idx} (true f0={true_freq:.4g} Hz), seed {seed}: "
                f"residual peak at {peak_freq:.4g} Hz, {decades_off:.2f} decades off, "
                f"{'HIT' if hit else 'miss'}"
            )

    frac = within_one_decade / total
    print(f"\nwithin 1 decade: {within_one_decade}/{total} ({frac * 100:.1f}%)")
    print(f"decision rule (clear majority, e.g. >=60%): {'PASS' if frac >= 0.6 else 'FAIL'}")


if __name__ == "__main__":
    main()
