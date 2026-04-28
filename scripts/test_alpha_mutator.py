"""Boundary tests for alpha_mutator.expand / expand_batch.

Run: python scripts/test_alpha_mutator.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wq_bus.agents.alpha_mutator import expand, expand_batch  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, cond: bool, *, info: str = "") -> None:
    global PASS, FAIL
    tag = "PASS" if cond else "FAIL"
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  {tag}  {label}  {info}")


# ─── T1 expand returns seed first, then variants ───────────────────────────
print("[T1] expand returns seed at index 0 + up-to-K variants")
out = expand(
    "rank(ts_corr(ts_rank(volume, 60), ts_rank(close, 60), 60))",
    {"decay": 0, "neutralization": "MARKET", "truncation": 0.05},
    factor=5,
    seed=42,
)
check("seed at index 0",
      out[0][0].startswith("rank(ts_corr"),
      info=f"expr={out[0][0][:40]}")
check("≤ factor variants",
      1 <= len(out) <= 5,
      info=f"got={len(out)}")
check("variants are distinct",
      len({(e, str(s)) for e, s in out}) == len(out),
      info=f"unique={len({(e,str(s)) for e,s in out})}/{len(out)}")

# ─── T2 expand handles expression with no ts_* operators ──────────────────
print("[T2] expand handles expr with no ts_* (settings-only mutation)")
out2 = expand(
    "rank(operating_income / (assets + 1))",
    {"decay": 0, "neutralization": "MARKET"},
    factor=4,
    seed=1,
)
# Should still produce 2-4 variants via settings rotation
check("≥ 2 variants from settings rotation",
      len(out2) >= 2,
      info=f"got={len(out2)}")

# ─── T3 expand with factor=1 is passthrough ────────────────────────────────
print("[T3] factor=1 is passthrough")
out3 = expand("rank(x)", {"decay": 0}, factor=1, seed=1)
check("exactly one item == seed",
      len(out3) == 1 and out3[0] == ("rank(x)", {"decay": 0}),
      info=str(out3))

# ─── T4 window perturbation respects bounds ────────────────────────────────
print("[T4] window perturbation stays in [2, 504]")
windows_seen = set()
for i in range(50):
    o = expand("rank(ts_mean(close, 5))", {}, factor=5, seed=i)
    for e, _ in o:
        # extract N
        import re
        m = re.search(r"ts_mean\(close,\s*(\d+)\)", e)
        if m:
            windows_seen.add(int(m.group(1)))
check("all windows in [2, 504]",
      all(2 <= w <= 504 for w in windows_seen),
      info=f"windows={sorted(windows_seen)}")

# ─── T5 expand_batch preserves parent_idx ──────────────────────────────────
print("[T5] expand_batch tags variants with parent_idx")
seeds = [
    ("rank(operating_income/equity)", {"decay": 0}),
    ("rank(ts_mean(close, 60))", {"decay": 4}),
]
flat = expand_batch(seeds, factor=3, seed=100)
parent_indices = {p for _, _, p in flat}
check("parent_idx ∈ {0,1}",
      parent_indices == {0, 1},
      info=f"got={parent_indices}")
check("seed[0] appears as variant of parent 0",
      any(e == seeds[0][0] and p == 0 for e, _, p in flat),
      info="ok" if any(e == seeds[0][0] and p == 0 for e, _, p in flat) else "MISSING")
check("flat list size ≤ len(seeds)*factor",
      len(flat) <= len(seeds) * 3,
      info=f"size={len(flat)}")

# ─── T6 deterministic with same seed ───────────────────────────────────────
print("[T6] deterministic given seed parameter")
a = expand("rank(ts_corr(volume, close, 30))", {"decay": 2}, factor=5, seed=99)
b = expand("rank(ts_corr(volume, close, 30))", {"decay": 2}, factor=5, seed=99)
check("two runs with seed=99 produce identical output",
      a == b,
      info=f"a_len={len(a)} b_len={len(b)}")

print(f"\n=== {PASS} passed / {FAIL} failed ===")
sys.exit(0 if FAIL == 0 else 1)
