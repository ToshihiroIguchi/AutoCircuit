"""Idea 2e/F, actually measured (not desk analysis): does memoizing `canonical_form()` itself
(not the already-cached per-level enumeration) cut real time during mw5/mw6's own enumeration?

**What is already shipped, found before this was written.** `enumerate.py`'s `_level()` already
memoises whole materialised levels in a module-level `_LEVELS` dict keyed by `(pool, size)`, so
a smaller sub-network level is never re-enumerated once built -- that half of the "subtree
memoization" idea already exists. What is *not* cached is `canonical_form(node)` itself, called
once per candidate combination in `_compose()`'s dedup loop (`seen: set[str]`) -- every combo,
duplicate or not, pays the full recursive string-building cost.

**Method.** Monkeypatch `enumerate.canonical_form` with a counting, memoizing wrapper (keyed by
`id(node)` is wrong since nodes are frozen dataclasses built fresh each time -- keyed by the
node's *own* `repr()`-free structural content via a cheap pre-hash), run the real
`enumerate_topologies` for mw5's pool at a representative size, and compare wall time and output
with and without the memoization, confirming byte-identical results.

Decision rule, fixed before running: worth shipping only if memoized `canonical_form` cuts wall
time by a clearly measurable amount (>10%) while producing byte-identical output, and the cache
hit rate is high enough to explain why.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_SPEEDUP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SPEEDUP_DIR))

from autocircuit.core import circuit as circuit_mod
from autocircuit.core import enumerate as enum_mod
from autocircuit.core.circuit import Circuit

POOL = ("R", "C", "L", "CPE")
SIZES = (4, 5)


def run_baseline(pool, n) -> tuple[list[str], float]:
    t0 = time.time()
    texts = [Circuit(node).to_string() for node in enum_mod.enumerate_topologies(pool, n)]
    t1 = time.time()
    return texts, t1 - t0


def run_memoized(pool, n) -> tuple[list[str], float, int, int]:
    original = circuit_mod.canonical_form
    cache: dict[int, str] = {}
    calls = 0
    hits = 0

    def memoized(node):
        nonlocal calls, hits
        calls += 1
        key = repr(node)  # exact structural key (not hash(), which showed collisions in
        # practice -- the first version of this script keyed on hash(node) and produced a
        # non-identical topology set, i.e. a false cache hit from a genuine collision or a
        # __hash__/__eq__ mismatch on these frozen dataclasses; repr() is slower per call but
        # exact, which is what a correctness-sensitive dedup key needs).
        cached = cache.get(key)
        if cached is not None:
            hits += 1
            return cached
        result = original(node)
        cache[key] = result
        return result

    enum_mod.canonical_form = memoized
    try:
        t0 = time.time()
        texts = [Circuit(node).to_string() for node in enum_mod.enumerate_topologies(pool, n)]
        t1 = time.time()
    finally:
        enum_mod.canonical_form = original
    return texts, t1 - t0, calls, hits


def main() -> None:
    for n in SIZES:
        print(f"\npool={POOL}, n={n}")
        baseline_texts, t_baseline = run_baseline(POOL, n)
        memo_texts, t_memo, calls, hits = run_memoized(POOL, n)

        identical = sorted(baseline_texts) == sorted(memo_texts)
        speedup = (t_baseline - t_memo) / t_baseline * 100 if t_baseline > 0 else 0.0
        print(f"  {len(baseline_texts)} topologies, canonical_form calls={calls}, "
              f"cache hits={hits} ({hits / max(calls, 1) * 100:.1f}%)")
        print(f"  baseline: {t_baseline:.3f}s, memoized: {t_memo:.3f}s, "
              f"speedup: {speedup:.1f}%, byte-identical output: {identical}")


if __name__ == "__main__":
    main()
