"""
Wave 9: Exploit the confirmed winning structure with new denominators
Pattern that PASSES:  group_rank(ts_rank(operating_income/assets, 126), sector/industry)
Pattern that FAILS:   group_rank(ts_rank(operating_income, 126), sector)  → Fitness=0.90

Hypothesis: The /assets normalization removes size bias → higher Sharpe (1.72 vs 1.43).
Testing other balance-sheet denominators:
 - operating_income/equity   (ROE via OI)
 - operating_income/liabilities  (coverage ratio)
 - operating_income/debt    (interest coverage analog)
Also explore:
 - subindustry grouping for operating_income  (already sector works at Fitness=0.90, sub might be closer to 0.95+)
 - operating_income/assets with ts_rank window variants (95, 105, 115) → might give diff results
"""
import sys
import json
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r'D:\codeproject\worldquantAlpha-dev\src')
from brain_client import BrainClient

RESULTS_DIR = Path(r'D:\codeproject\worldquantAlpha-dev\results')
RESULTS_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_FILE = RESULTS_DIR / f"wave9_{TIMESTAMP}.json"

# PROVEN recipe (from wave4/5 successes)
P = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}

ALPHAS = [
    # ── OI / equity (ROE using operating income) ──
    {
        "name": "oi_equity_ts126_sect",
        "expr": "group_rank(ts_rank(operating_income/equity, 126), sector)",
        "settings": P,
        "hypothesis": "ROE momentum (OI-based): normalizing by equity removes size+leverage bias",
        "category": "profitability"
    },
    {
        "name": "oi_equity_ts126_ind",
        "expr": "group_rank(ts_rank(operating_income/equity, 126), industry)",
        "settings": P,
        "hypothesis": "Industry-neutral ROE momentum",
        "category": "profitability"
    },
    {
        "name": "oi_equity_ts126_subind",
        "expr": "group_rank(ts_rank(operating_income/equity, 126), subindustry)",
        "settings": P,
        "hypothesis": "Subindustry-neutral ROE momentum",
        "category": "profitability"
    },

    # ── OI / liabilities (coverage ratio) ──
    {
        "name": "oi_liab_ts126_sect",
        "expr": "group_rank(ts_rank(operating_income/liabilities, 126), sector)",
        "settings": P,
        "hypothesis": "OI/liabilities: interest coverage analog; high coverage = strong signal",
        "category": "profitability"
    },
    {
        "name": "oi_liab_ts126_ind",
        "expr": "group_rank(ts_rank(operating_income/liabilities, 126), industry)",
        "settings": P,
        "hypothesis": "Industry-neutral OI coverage momentum",
        "category": "profitability"
    },

    # ── OI / debt (pure interest coverage) ──
    {
        "name": "oi_debt_ts126_sect",
        "expr": "group_rank(ts_rank(operating_income/debt, 126), sector)",
        "settings": P,
        "hypothesis": "OI / debt: classic interest coverage signal; diversifies from OI/assets",
        "category": "profitability"
    },

    # ── Subindustry version of near-passing signals (might boost Fitness slightly) ──
    {
        "name": "oi_ts126_subind",
        "expr": "group_rank(ts_rank(operating_income, 126), subindustry)",
        "settings": P,
        "hypothesis": "Subindustry-neutral OI momentum (wave8 sector=0.90, sub might be ≥0.95)",
        "category": "profitability"
    },
    {
        "name": "oi_margin_ts126_subind",
        "expr": "group_rank(ts_rank(operating_income/sales, 126), subindustry)",
        "settings": P,
        "hypothesis": "Subindustry-neutral OI margin momentum",
        "category": "profitability"
    },

    # ── Vary ts_rank window for operating_income/assets (adjacent windows) ──
    # wave4: window=126 → PASS; window=252 → FAIL (Fitness=0.87); window=63 → FAIL (Fitness=0.66)
    # Are there windows between 63 and 126 or between 126 and 252 that still pass?
    {
        "name": "oi_assets_ts95_sect",
        "expr": "group_rank(ts_rank(operating_income/assets, 95), sector)",
        "settings": P,
        "hypothesis": "Shorter ~4-month window for OI/assets; between 63 (fail) and 126 (pass)",
        "category": "profitability"
    },
    {
        "name": "oi_assets_ts150_sect",
        "expr": "group_rank(ts_rank(operating_income/assets, 150), sector)",
        "settings": P,
        "hypothesis": "Slightly longer window than 126 for OI/assets; between 126 (pass) and 252 (fail)",
        "category": "profitability"
    },
    {
        "name": "oi_assets_ts175_sect",
        "expr": "group_rank(ts_rank(operating_income/assets, 175), sector)",
        "settings": P,
        "hypothesis": "7-month window; test if passing range extends beyond 126",
        "category": "profitability"
    },

    # ── Combine OI/assets signals (different normalizers together) ──
    {
        "name": "oi_assets_plus_margin_ts126",
        "expr": "group_rank(ts_rank(operating_income/assets + operating_income/sales, 126), sector)",
        "settings": P,
        "hypothesis": "Composite ROA+margin ts_rank: blends capital and revenue efficiency",
        "category": "composite"
    },
    {
        "name": "oi_assets_times_margin_ts126",
        "expr": "group_rank(ts_rank(operating_income/assets * operating_income/sales, 126), sector)",
        "settings": P,
        "hypothesis": "Product ROA×margin: DuPont-inspired; higher for high-quality firms",
        "category": "composite"
    },

    # ── ebitda/assets with different windows (close to subindustry threshold) ──
    {
        "name": "ebitda_assets_ts95_sect",
        "expr": "group_rank(ts_rank(ebitda/assets, 95), sector)",
        "settings": P,
        "hypothesis": "EBITDA/assets with 4-month window; wave8 showed Sharpe=1.16 at 126, may improve",
        "category": "profitability"
    },
]


def fmt_checks(checks):
    lines = []
    for ch in checks:
        status = ch.get("result", "?")
        name   = ch.get("name", "?")
        val    = ch.get("value", "")
        lim    = ch.get("limit", "")
        lines.append(f"  {status:8s} {name:<35s} val={val} lim={lim}")
    return "\n".join(lines)


def _save(results, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


def main():
    print(f"{'='*70}")
    print(f"WAVE 9 Alpha Research  —  {TIMESTAMP}")
    print(f"Goal: find MORE diverse signals that PASS all checks")
    print(f"Recipe: group_rank(ts_rank(X, 126), group), decay=0 SUBINDUSTRY nanHandling=ON")
    print(f"{'='*70}\n")

    c = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')
    auth = c.check_auth()
    if auth["status"] != 200:
        print(f"[ERROR] Auth failed: {auth}")
        sys.exit(1)
    user = auth["body"]
    print(f"[AUTH OK] user={user.get('id','?')}  {user.get('email','')}\n")

    results = []
    print(f"Testing {len(ALPHAS)} expressions\n")

    for i, alpha_def in enumerate(ALPHAS, 1):
        name  = alpha_def["name"]
        expr  = alpha_def["expr"]
        setts = alpha_def["settings"]
        print(f"[{i:02d}/{len(ALPHAS)}] {name}")
        print(f"  expr : {expr}")

        t0 = time.time()
        try:
            alpha = c.simulate_and_get_alpha(expr, setts)
        except Exception as e:
            print(f"  [EXCEPTION] {e}\n")
            results.append({**alpha_def, "alpha": {"error": str(e)}})
            _save(results, OUT_FILE)
            continue

        elapsed = time.time() - t0

        if "error" in alpha:
            err_str = str(alpha)
            if "unknown variable" in err_str or "Invalid data field" in err_str:
                print(f"  [FIELD_ERROR] invalid field\n")
            else:
                print(f"  [ERROR] {err_str[:120]}\n")
            results.append({**alpha_def, "alpha": alpha})
            _save(results, OUT_FILE)
            continue

        is_data  = alpha.get("is", {})
        sharpe   = float(is_data.get("sharpe",   0) or 0)
        fitness  = float(is_data.get("fitness",  0) or 0)
        turnover = float(is_data.get("turnover", 0) or 0)
        returns  = float(is_data.get("returns",  0) or 0)
        checks   = is_data.get("checks",   [])

        fails   = [ch["name"] for ch in checks if ch.get("result") not in ("PASS", "PENDING")]
        pending = [ch["name"] for ch in checks if ch.get("result") == "PENDING"]
        all_ok  = len(fails) == 0

        if all_ok and not pending:
            tag = "✓ ALL PASS"
        elif all_ok:
            tag = "~ PENDING  [" + ",".join(pending) + "]"
        else:
            tag = "✗ FAIL     [" + ",".join(fails) + "]"

        print(f"  {tag}")
        print(f"  Sharpe={sharpe:.3f}  Fitness={fitness:.3f}  TO={turnover:.1%}  "
              f"Returns={returns:.3f}  ({elapsed:.0f}s)")
        print(fmt_checks(checks))
        print()

        entry = {
            "name": name,
            "expr": expr,
            "settings": setts,
            "hypothesis": alpha_def["hypothesis"],
            "category": alpha_def.get("category", ""),
            "alpha": {
                "id": alpha.get("id", ""),
                "is": {
                    "sharpe":   sharpe,
                    "fitness":  fitness,
                    "turnover": turnover,
                    "returns":  returns,
                    "checks":   checks
                }
            }
        }
        results.append(entry)
        _save(results, OUT_FILE)

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passing = []
    near    = []
    failing = []
    errors  = []

    for r in results:
        a    = r.get("alpha", {})
        is_d = a.get("is", {})
        checks = is_d.get("checks", [])
        sh = float(is_d.get("sharpe", 0) or 0)
        if "error" in a:
            errors.append(r)
        elif checks and all(ch.get("result") in ("PASS", "PENDING") for ch in checks):
            passing.append(r)
        elif sh >= 1.1:
            near.append(r)
        else:
            failing.append(r)

    print(f"\n  Passing (all checks PASS/PENDING) : {len(passing)}")
    print(f"  Near-pass (Sharpe >= 1.1, failing): {len(near)}")
    print(f"  Clearly failing                    : {len(failing)}")
    print(f"  Errors                             : {len(errors)}")

    if passing:
        print("\n  ── PASSING ──")
        for r in passing:
            is_d = r["alpha"]["is"]
            alpha_id = r["alpha"].get("id", "")
            print(f"    {r['name']:<50s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} TO={float(is_d.get('turnover',0)):.1%} "
                  f"id={alpha_id}")

    if near:
        print("\n  ── NEAR-PASS ──")
        for r in near:
            is_d   = r["alpha"]["is"]
            checks = is_d.get("checks", [])
            fails  = [ch["name"] for ch in checks if ch.get("result") not in ("PASS", "PENDING")]
            print(f"    {r['name']:<50s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} TO={float(is_d.get('turnover',0)):.1%} "
                  f"fail={fails}")

    if errors:
        print("\n  ── ERRORS ──")
        for r in errors:
            print(f"    {r['name']:<50s} {str(r['alpha'].get('error',''))[:70]}")

    print(f"\n  Results saved to: {OUT_FILE}")


if __name__ == "__main__":
    main()
