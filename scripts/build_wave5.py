"""Build wave5: final push to 60 qualifying alphas.
Need 10 more. Testing 15 alphas (10 leverage + 5 ROA 126d variants).
"""
import json
from pathlib import Path

wave5 = []

# BLOCK 1: More leverage SUBINDUSTRY combos with higher decay values (6 alphas)
for decay, trunc in [
    (6, 0.03), (6, 0.09),
    (8, 0.05), (8, 0.08),
    (10, 0.05), (10, 0.08),
]:
    tstr = str(trunc).replace(".", "")
    wave5.append({
        "name": f"W5L_sub_d{decay}_t{tstr}",
        "expr": "rank(liabilities/assets)",
        "hypothesis": f"Leverage SUBINDUSTRY decay={decay} trunc={trunc}: high-decay smoothing variant.",
        "batch_id": "wave5",
        "settings": {"decay": decay, "neutralization": "SUBINDUSTRY", "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 2: More leverage INDUSTRY combos (4 alphas)
for decay, trunc in [(4, 0.06), (4, 0.09), (6, 0.05), (6, 0.08)]:
    tstr = str(trunc).replace(".", "")
    wave5.append({
        "name": f"W5L_ind_d{decay}_t{tstr}",
        "expr": "rank(liabilities/assets)",
        "hypothesis": f"Leverage INDUSTRY decay={decay} trunc={trunc}: proven INDUSTRY neutralization variant.",
        "batch_id": "wave5",
        "settings": {"decay": decay, "neutralization": "INDUSTRY", "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 3: ROA 126-day variants — proven sh=1.72-1.75, try different settings/groupings (5 alphas)
roa_variants = [
    # Same expr as W4R_roa_126d_subind but INDUSTRY neutralization -> different alpha ID
    ("group_rank(ts_rank(operating_income/assets, 126), industry)", "W5R_roa126_ind_neut",
     "ROA 126d industry-grouped, INDUSTRY neutralization: proven signal with different portfolio construction.",
     {"decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08, "nanHandling": "ON"}),
    # Same as W4R_roa_126_sector but INDUSTRY neutralization
    ("group_rank(ts_rank(operating_income/assets, 126), sector)", "W5R_roa126_sec_indneut",
     "ROA 126d sector-grouped, INDUSTRY neutralization: best signal (sh=1.75) with different neutralization.",
     {"decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08, "nanHandling": "ON"}),
    # Subindustry grouping (finer than industry)
    ("group_rank(ts_rank(operating_income/assets, 126), subindustry)", "W5R_roa126_subind_grp",
     "ROA 126d subindustry-grouped: tightest peer comparison for short-cycle ROA signal.",
     {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}),
    # 63-day (quarterly) window — more responsive
    ("group_rank(ts_rank(operating_income/assets, 63), industry)", "W5R_roa63_ind",
     "ROA 63d (quarterly) industry-grouped: faster cycle than 126d, captures quarterly earnings trends.",
     {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}),
    # CFO/assets with 126d window — cash flow analog
    ("group_rank(ts_rank(cash_flow_from_operations/assets, 126), industry)", "W5R_cforoa126_ind",
     "CFO ROA 126d industry-grouped: cash-based ROA percentile cycle, less susceptible to accrual manipulation.",
     {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}),
]
for expr, name, hyp, settings in roa_variants:
    wave5.append({"name": name, "expr": expr, "hypothesis": hyp, "batch_id": "wave5", "settings": settings})

print(f"Wave5 total: {len(wave5)} alphas")
for a in wave5:
    print(f"  {a['name']}: {a['expr'][:65]}")
Path("data/wave5_all.json").write_text(json.dumps(wave5, ensure_ascii=False, indent=2), encoding="utf-8")
print("Saved data/wave5_all.json")
