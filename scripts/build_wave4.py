"""Build wave4: more leverage settings combos + ROA variants + international regions."""
import json
from pathlib import Path

# Already tested (do not repeat):
# SUBINDUSTRY d0: t0.03-0.10 (all 8), d1: t0.05/t0.08, d2: t0.05/t0.08
# d3: t0.05/t0.08, d4: t0.08, d5: t0.05
# INDUSTRY d0: t0.05/t0.06/t0.08, d1: t0.08, d2: t0.08, d4: t0.05/t0.08

wave4 = []

# BLOCK 1: SUBINDUSTRY d1-d5 untested truncation combos (18 alphas)
sub_new = [
    (1, 0.03), (1, 0.06), (1, 0.09),
    (2, 0.03), (2, 0.06), (2, 0.09),
    (3, 0.03), (3, 0.06), (3, 0.09),
    (4, 0.04), (4, 0.06), (4, 0.09),
    (5, 0.03), (5, 0.06), (5, 0.08), (5, 0.09),
    (6, 0.05), (6, 0.08),
]
for decay, trunc in sub_new:
    tstr = str(trunc).replace(".", "")
    wave4.append({
        "name": f"W4L_sub_d{decay}_t{tstr}",
        "expr": "rank(liabilities/assets)",
        "hypothesis": f"Leverage SUBINDUSTRY decay={decay} trunc={trunc}: unexplored settings combo.",
        "batch_id": "wave4",
        "settings": {"decay": decay, "neutralization": "SUBINDUSTRY", "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 2: INDUSTRY untested combos (9 alphas)
ind_new = [
    (0, 0.07), (0, 0.09), (0, 0.10),
    (1, 0.05), (1, 0.06),
    (2, 0.05), (2, 0.06),
    (3, 0.08),
    (5, 0.08),
]
for decay, trunc in ind_new:
    tstr = str(trunc).replace(".", "")
    wave4.append({
        "name": f"W4L_ind_d{decay}_t{tstr}",
        "expr": "rank(liabilities/assets)",
        "hypothesis": f"Leverage INDUSTRY decay={decay} trunc={trunc}: unexplored settings combo.",
        "batch_id": "wave4",
        "settings": {"decay": decay, "neutralization": "INDUSTRY", "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 3: ROA signal variants — push W3G_roa_ind (sh=1.37, fi=0.87) past fi=1.0
# ROA = operating_income/assets; need ~7% returns, currently at 5%
# Try window 126 (more responsive → higher returns), truncation 0.10, INDUSTRY neutralization
roa_variants = [
    ("group_rank(ts_rank(operating_income/assets, 126), industry)", "W4R_roa_126d_subind",
     "ROA 6-month percentile in industry: faster cycle, potentially higher returns than 252d.", "SUBINDUSTRY", 0.08, 0),
    ("group_rank(ts_rank(operating_income/assets, 252), industry)", "W4R_roa_trunc010",
     "ROA percentile industry trunc=0.10: more concentration boosts annual returns.", "SUBINDUSTRY", 0.10, 0),
    ("group_rank(ts_rank(operating_income/assets, 252), sector)", "W4R_roa_sector_grp",
     "ROA percentile within sector (coarser grouping): different signal profile.", "SUBINDUSTRY", 0.08, 0),
    ("group_rank(ts_rank(operating_income/assets, 126), sector)", "W4R_roa_126_sector",
     "ROA 6-month percentile sector-grouped: faster cycle + coarser grouping combo.", "SUBINDUSTRY", 0.08, 0),
]
for expr, name, hyp, neut, trunc, decay in roa_variants:
    wave4.append({
        "name": name, "expr": expr, "hypothesis": hyp, "batch_id": "wave4",
        "settings": {"decay": decay, "neutralization": neut, "truncation": trunc, "nanHandling": "ON"}
    })

# BLOCK 4: International leverage — completely new alpha pool
# rank(liabilities/assets) proven in USA; test CHN, EUR, JPN
# Settings dict is passed to brain_client.simulate() which does base.update(settings)
# so region/universe keys here override the USA defaults
for region, universe in [("CHN", "TOP3000"), ("EUR", "TOP3000"), ("JPN", "TOP3000")]:
    wave4.append({
        "name": f"W4I_leverage_{region.lower()}",
        "expr": "rank(liabilities/assets)",
        "hypothesis": f"Leverage factor in {region}: completely separate alpha pool, different stocks.",
        "batch_id": "wave4",
        "settings": {
            "region": region, "universe": universe,
            "decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"
        }
    })

print(f"Wave4 total: {len(wave4)} alphas")
for a in wave4:
    print(f"  {a['name']}")
Path("data/wave4_all.json").write_text(json.dumps(wave4, ensure_ascii=False, indent=2), encoding="utf-8")
print("Saved data/wave4_all.json")
