# Real-fit gate for `motif_rate = 0.30`

## par6 (pool=('R', 'C', 'L', 'CPE'), n=30 seeds)

- throughput: median rate ratio (motif/base) = 1.230, paired sign test p=0.0000 (27 higher / 3 lower) -> PASS
- best score (lower better): motif better on 9/30, base better on 2/30, median delta +0.000, p=0.0654 -> PASS
- reported: base 30/30, motif 30/30, discordant=0 (only-base=0/only-motif=0), p=1.0000 -- fewer than 10 discordant pairs, not resolvable
- on_front: base 30/30, motif 30/30, discordant=0 (only-base=0/only-motif=0), p=1.0000 -- fewer than 10 discordant pairs, not resolvable
- recommended: base 30/30, motif 30/30, discordant=0 (only-base=0/only-motif=0), p=1.0000 -- fewer than 10 discordant pairs, not resolvable
- mutate calls per evaluated candidate (proxy for retry rate): base 263.72, motif 202.12

## ser6 (pool=('R', 'C', 'L'), n=30 seeds)

- throughput: median rate ratio (motif/base) = 1.189, paired sign test p=0.0001 (26 higher / 4 lower) -> PASS
- best score (lower better): motif better on 11/30, base better on 11/30, median delta +0.000, p=1.0000 -> PASS
- reported: base 27/30, motif 25/30, discordant=6 (only-base=4/only-motif=2), p=0.6875 -- fewer than 10 discordant pairs, not resolvable
- on_front: base 2/30, motif 1/30, discordant=3 (only-base=2/only-motif=1), p=1.0000 -- fewer than 10 discordant pairs, not resolvable
- recommended: base 0/30, motif 0/30, discordant=0 (only-base=0/only-motif=0), p=1.0000 -- fewer than 10 discordant pairs, not resolvable
- mutate calls per evaluated candidate (proxy for retry rate): base 404.72, motif 308.98

## Verdict

Per the pre-registered rule: an unresolved recovery clause (fewer than 10 discordant pairs) is not read as a failure -- it defers that arena's verdict to throughput and score alone.

- par6: throughput=PASS, score=PASS, recovery=UNRESOLVED -> SHIP-ELIGIBLE (recovery unresolved at this n -- deferred to throughput+score, both PASS)
- ser6: throughput=PASS, score=PASS, recovery=UNRESOLVED -> SHIP-ELIGIBLE (recovery unresolved at this n -- deferred to throughput+score, both PASS)

**Ships**, on the throughput+score fallback basis for at least one arena -- the recovery clause could not resolve at this n and is not part of the basis (pre-registered).
Pending the win reading and the `PROPOSE_RETRY_CAP`/duplicate-rate check named as secondary in the module docstring.
