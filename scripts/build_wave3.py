"""Build redesigned wave3 config: leverage settings sweep + W2X03 variants + A09-style."""
import json
from pathlib import Path

wave3 = []

# BLOCK 1: Leverage SUBINDUSTRY decay variants
for decay in [1, 2, 3, 5]:
    for trunc in [0.05, 0.08]:
        if decay == 5 and trunc == 0.08:
            continue  # W2D04 was decay=4/0.08; decay=5/0.08 is new
        tstr = str(trunc).replace(".", "")
        wave3.append({
            "name": f"W3L_sub_d{decay}_t{tstr}",
            "expr": "rank(liabilities/assets)",
            "hypothesis": f"Leverage decay={decay} trunc={trunc} SUBINDUSTRY: settings variant.",
            "batch_id": "wave3",
            "settings": {"decay": decay, "neutralization": "SUBINDUSTRY", "truncation": trunc, "nanHandling": "ON"}
        })

# BLOCK 2: Leverage SUBINDUSTRY truncation variants (decay=0)
for trunc in [0.04, 0.06, 0.07, 0.09, 0.10]:
    tstr = str(trunc).replace(".", "")
    wave3.append({
        "name": f"W3L_sub_d0_t{tstr}",
        "expr": "rank(liabilities/assets)",
        "hypothesis": f"Leverage decay=0 trunc={trunc} SUBINDUSTRY: truncation sensitivity.",
        "batch_id": "wave3",
        "settings": {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 3: Leverage INDUSTRY variants (W2D03 proved INDUSTRY works)
for decay, trunc in [(0, 0.05), (0, 0.06), (1, 0.08), (2, 0.08), (4, 0.05)]:
    tstr = str(trunc).replace(".", "")
    wave3.append({
        "name": f"W3L_ind_d{decay}_t{tstr}",
        "expr": "rank(liabilities/assets)",
        "hypothesis": f"Leverage INDUSTRY decay={decay} trunc={trunc}: INDUSTRY neutralization proven.",
        "batch_id": "wave3",
        "settings": {"decay": decay, "neutralization": "INDUSTRY", "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 4: W2X03 boost variants — push sh=1.31 signal (6% returns) past fi=1.0 target
# Need Returns >= 7.3%; different settings may boost returns
for neut, trunc, decay in [
    ("MARKET", 0.08, 0),
    ("INDUSTRY", 0.08, 0),
    ("SUBINDUSTRY", 0.10, 0),
    ("SUBINDUSTRY", 0.08, 2),
]:
    tstr = str(trunc).replace(".", "")
    wave3.append({
        "name": f"W3X_sector_{neut.lower()}_d{decay}_t{tstr}",
        "expr": "group_rank(ts_rank(operating_income, 252), sector)",
        "hypothesis": f"W2X03 variant neut={neut} decay={decay} trunc={trunc}: push sh=1.31/fi=0.91 past 1.0.",
        "batch_id": "wave3",
        "settings": {"decay": decay, "neutralization": neut, "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 5: A09-style signals on other fundamentals
for expr, name, hyp in [
    ("group_rank(ts_rank(cash_flow_from_operations, 252), industry)", "W3G_cfo_ind",
     "CFO percentile within industry: cash generation cycle position vs peers."),
    ("group_rank(ts_rank(operating_income/assets, 252), industry)", "W3G_roa_ind",
     "ROA percentile within industry: profitability efficiency cycle."),
    ("group_rank(ts_rank(operating_income/sales, 252), industry)", "W3G_margin_ind",
     "Operating margin cycle within industry: pricing power at historical highs."),
    ("group_rank(ts_rank(sales, 252), industry)", "W3G_sales_ind",
     "Revenue cycle within industry: top-line momentum vs peers."),
    ("group_rank(ts_rank(operating_income, 252), subindustry)", "W3G_oi_subind_mkt",
     "Income percentile within subindustry with MARKET neutralization."),
    ("group_rank(ts_rank(operating_income, 756), industry)", "W3G_oi_3yr_ind",
     "Operating income 3-year percentile within industry: structural cycle."),
]:
    wave3.append({
        "name": name, "expr": expr, "hypothesis": hyp, "batch_id": "wave3",
        "settings": {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}
    })

print(f"Wave3 total: {len(wave3)} alphas")
for a in wave3:
    print(f"  {a['name']}: {a['expr'][:60]}")
Path("data/wave3_all.json").write_text(json.dumps(wave3, ensure_ascii=False, indent=2), encoding="utf-8")
print("Saved data/wave3_all.json")
