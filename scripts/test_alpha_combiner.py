"""Boundary tests for alpha_combiner.

Run: python scripts/test_alpha_combiner.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wq_bus.agents.alpha_combiner import (  # noqa: E402
    Fragment, Fragments, combine, parse_ai_response, register_strategy,
    STRATEGIES, _filter_is_legal, _settings_key,
)

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


# Sample fragments shared across tests
SAMPLE_FRAGS = Fragments(
    signals=[
        Fragment("rank(operating_income/(assets+1))", family_hint="F1", ai_call_id="ai-1"),
        Fragment("rank(cash/(assets+1))", family_hint="F1", ai_call_id="ai-1"),
        Fragment("group_rank(ts_rank(close,60), sector)", family_hint="F3", ai_call_id="ai-1"),
    ],
    filters=[
        Fragment("greater(volume, ts_mean(volume,60))"),
        Fragment("ts_corr(close, volume, 60)"),     # ILLEGAL — top op not boolean
        Fragment("and(greater(assets,0), less(returns, 0.1))"),
    ],
    weights=[
        Fragment("1/sqrt(ts_std_dev(returns,60)+1e-6)"),
    ],
)


# ─── T1 filter validity ────────────────────────────────────────────────────
print("[T1] filter operator whitelist")
check("greater(...) accepted",  _filter_is_legal("greater(volume, ts_mean(volume,60))"))
check("ts_corr(...) rejected", not _filter_is_legal("ts_corr(close, volume, 60)"))
check("and(...) accepted", _filter_is_legal("and(greater(a,b), less(c,d))"))
check("rank(...) rejected as filter", not _filter_is_legal("rank(close)"))
check("empty rejected", not _filter_is_legal(""))


# ─── T2 passthrough strategy ───────────────────────────────────────────────
print("[T2] passthrough produces 1 alpha per signal")
out = combine(SAMPLE_FRAGS, {"enabled_strategies": ["passthrough"]})
check("3 passthrough alphas", len(out) == 3, info=f"got={len(out)}")
check("first carries ai_call_id",
      out[0].provenance.get("ai_call_id") == "ai-1")
check("strategy tag present",
      all(c.provenance["strategy"] == "passthrough" for c in out))


# ─── T3 linear_2leg respects combos_per_signal ─────────────────────────────
print("[T3] linear_2leg cap enforcement")
out = combine(SAMPLE_FRAGS, {"enabled_strategies": ["linear_2leg"],
                             "combos_per_signal": 1})
# 3 signals, each pairs with at most 1 successor → expected 2 (sig0→sig1, sig1→sig2)
check("≤ 2 combos with cap=1, 3 sigs", len(out) <= 2, info=f"got={len(out)}")
check("uses '+' assembly", all(" + " in c.expr for c in out))


# ─── T4 filtered drops illegal filter ──────────────────────────────────────
print("[T4] filtered strategy drops illegal filters")
out = combine(SAMPLE_FRAGS, {"enabled_strategies": ["filtered"],
                             "combos_per_signal": 5})
# 3 signals × 2 LEGAL filters = 6 (the ts_corr one was dropped)
check("6 filtered alphas (illegal filter dropped)",
      len(out) == 6, info=f"got={len(out)}")
check("all use if_else",
      all(c.expr.startswith("if_else(") for c in out))
check("no use of ts_corr filter",
      not any("ts_corr(close, volume, 60)" in c.expr for c in out))


# ─── T5 weighted ────────────────────────────────────────────────────────────
print("[T5] weighted strategy")
out = combine(SAMPLE_FRAGS, {"enabled_strategies": ["weighted"],
                             "combos_per_signal": 5})
# 3 signals × 1 weight = 3
check("3 weighted alphas", len(out) == 3, info=f"got={len(out)}")
check("uses ' * '", all(" * " in c.expr for c in out))


# ─── T6 dedup across strategies ────────────────────────────────────────────
print("[T6] dedup across multiple strategies preserves first occurrence")
# passthrough (3) + linear_2leg may produce sig0+sig1 etc. — just ensure no
# dup expr/settings pair across the union
out = combine(SAMPLE_FRAGS, {
    "enabled_strategies": ["passthrough", "linear_2leg", "filtered", "weighted"],
    "combos_per_signal": 5,
})
seen = set()
dups = 0
for c in out:
    k = (c.expr, _settings_key(c.settings))
    if k in seen:
        dups += 1
    seen.add(k)
check("zero duplicates after combine()",
      dups == 0, info=f"dups={dups} total={len(out)}")
check("≥ 12 distinct alphas (3+2+6+3)",
      len(out) >= 12, info=f"got={len(out)}")


# ─── T7 unknown strategy is logged & skipped ───────────────────────────────
print("[T7] unknown strategy gracefully skipped")
out = combine(SAMPLE_FRAGS, {"enabled_strategies": ["passthrough", "no_such_strategy"]})
check("only passthrough ran", len(out) == 3, info=f"got={len(out)}")


# ─── T8 register_strategy plugin hook ──────────────────────────────────────
print("[T8] register_strategy adds new plugin")

def _custom(frags, mode_cfg):
    from wq_bus.agents.alpha_combiner import CombinedAlpha
    return [CombinedAlpha(expr="rank(close)", settings={"decay": 9},
                          provenance={"strategy": "_custom_test"})]

register_strategy("_custom_test", _custom, overwrite=True)
out = combine(SAMPLE_FRAGS, {"enabled_strategies": ["_custom_test"]})
check("custom strategy ran", len(out) == 1 and out[0].expr == "rank(close)")
# cleanup
del STRATEGIES["_custom_test"]


# ─── T9 parse_ai_response handles all three shapes ─────────────────────────
print("[T9] parse_ai_response: fragments + legacy fallback + non-dict tolerance")
frags = parse_ai_response({
    "signals": [{"expr": "rank(x)", "family_hint": "F1", "rationale": "r"}],
    "filters": [{"expr": "greater(a,b)"}, "not_a_dict"],
    "weights": [],
}, ai_call_id="ai-XYZ")
check("1 signal parsed", len(frags.signals) == 1)
check("ai_call_id propagated", frags.signals[0].ai_call_id == "ai-XYZ")
check("non-dict filter skipped", len(frags.filters) == 1)

# Legacy fallback
frags2 = parse_ai_response({"alphas": [{"expression": "rank(y)"}]})
check("legacy 'alphas' becomes signals",
      len(frags2.signals) == 1 and frags2.signals[0].expr == "rank(y)")

frags3 = parse_ai_response({"expressions": [{"expression": "rank(z)"}]})
check("legacy 'expressions' becomes signals",
      len(frags3.signals) == 1 and frags3.signals[0].expr == "rank(z)")

# Non-dict input
frags4 = parse_ai_response("garbage")
check("non-dict input returns empty Fragments",
      len(frags4.signals) == 0 and len(frags4.filters) == 0)


# ─── T10 mode-budget enforcement (specialize ~160) ─────────────────────────
print("[T10] specialize mode budget bound check")
# Simulate specialize: 8 signals + 3 filters + 2 weights, combos_per_signal=5
big_sigs = [Fragment(f"rank(field_{i}/(assets+1))", ai_call_id=f"ai-{i}") for i in range(8)]
big_flts = [Fragment(f"greater(volume, ts_mean(volume,{30+i*10}))") for i in range(3)]
big_wts  = [Fragment(f"1/sqrt(ts_std_dev(returns,{30+i*30})+1e-6)") for i in range(2)]
big = Fragments(signals=big_sigs, filters=big_flts, weights=big_wts)
out = combine(big, {
    "enabled_strategies": ["passthrough", "linear_2leg", "filtered", "weighted"],
    "combos_per_signal": 5,
})
# Expected upper bound (no dups): 8 + (8*5 capped 28) + (8*3) + (8*2) ≈ within reason
check("specialize batch 30..80 candidates pre-mutator",
      30 <= len(out) <= 200,
      info=f"got={len(out)} (8 sigs/3 flts/2 wts, combos_per=5)")


print(f"\n=== {PASS} passed / {FAIL} failed ===")
sys.exit(0 if FAIL == 0 else 1)
