"""
Wave 8: Apply the PROVEN recipe to new metrics
Confirmed pattern: group_rank(ts_rank(X, 126), group)
Confirmed settings: decay=0, SUBINDUSTRY, truncation=0.08, nanHandling=ON
Target: find diverse metrics that match the operating_income/assets success pattern
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
OUT_FILE = RESULTS_DIR / f"wave8_{TIMESTAMP}.json"

# THE PROVEN RECIPE settings from wave4/5
PROVEN = {
    "decay": 0,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "nanHandling": "ON"
}

# Alternative groupings to diversify
PROVEN_IND = {
    "decay": 0,
    "neutralization": "INDUSTRY",
    "truncation": 0.08,
    "nanHandling": "ON"
}

# Expressions to test — all use ts_rank(X, 126) pattern
# From wave4/5 we know: group_rank(ts_rank(operating_income/assets, 126), ...)
# → Sharpe=1.66-1.75, Fitness=1.01-1.17 with SUBINDUSTRY/INDUSTRY/SECTOR neutralization
ALPHAS = [
    # ── Asset turnover momentum ──
    {
        "name": "sales_assets_ts126_sect",
        "expr": "group_rank(ts_rank(sales/assets, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Asset turnover momentum: firms growing revenue relative to assets",
        "category": "efficiency"
    },
    {
        "name": "sales_assets_ts126_ind",
        "expr": "group_rank(ts_rank(sales/assets, 126), industry)",
        "settings": PROVEN,
        "hypothesis": "Industry-neutral asset turnover momentum",
        "category": "efficiency"
    },

    # ── EBITDA momentum ──
    {
        "name": "ebitda_assets_ts126_sect",
        "expr": "group_rank(ts_rank(ebitda/assets, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "EBITDA/assets momentum: like ROA but includes D&A expense",
        "category": "profitability"
    },
    {
        "name": "ebitda_assets_ts126_ind",
        "expr": "group_rank(ts_rank(ebitda/assets, 126), industry)",
        "settings": PROVEN,
        "hypothesis": "Industry-neutral EBITDA margin momentum",
        "category": "profitability"
    },

    # ── Operating income absolute momentum ──
    {
        "name": "oi_ts126_sect",
        "expr": "group_rank(ts_rank(operating_income, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Half-year OI rank (vs 252 which had Sharpe=1.31 only); 126 might work like assets ratio",
        "category": "profitability"
    },
    {
        "name": "oi_ts126_ind",
        "expr": "group_rank(ts_rank(operating_income, 126), industry)",
        "settings": PROVEN,
        "hypothesis": "Industry-neutral 6-month operating income momentum",
        "category": "profitability"
    },

    # ── Cash flow momentum ──
    {
        "name": "cfo_assets_ts126_sect",
        "expr": "group_rank(ts_rank(cash_flow_from_operations/assets, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Cash flow yield momentum: operating cashflow vs assets, sector-neutral",
        "category": "cash_flow"
    },
    {
        "name": "cfo_assets_ts126_ind",
        "expr": "group_rank(ts_rank(cash_flow_from_operations/assets, 126), industry)",
        "settings": PROVEN,
        "hypothesis": "Industry-neutral cash flow yield momentum",
        "category": "cash_flow"
    },

    # ── Leverage momentum (ts_rank is different from cross-section!) ──
    {
        "name": "liab_assets_ts126_sect",
        "expr": "group_rank(ts_rank(liabilities/assets, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Time-series leverage rank: firms with rising L/A relative to OWN 6-month history",
        "category": "leverage_momentum"
    },

    # ── Retained earnings momentum ──
    {
        "name": "retained_ts126_sect",
        "expr": "group_rank(ts_rank(retained_earnings/assets, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Retained earnings accumulation momentum within sector",
        "category": "quality"
    },

    # ── Equity ratio momentum ──
    {
        "name": "equity_assets_ts126_sect",
        "expr": "group_rank(ts_rank(equity/assets, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Capitalization ratio momentum: firms improving their equity buffer",
        "category": "leverage"
    },

    # ── Operating margin momentum ──
    {
        "name": "oi_margin_ts126_sect",
        "expr": "group_rank(ts_rank(operating_income/sales, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Operating margin momentum: improving margin firms; 126 vs 252 (Sharpe=1.14) tested",
        "category": "profitability"
    },
    {
        "name": "oi_margin_ts126_ind",
        "expr": "group_rank(ts_rank(operating_income/sales, 126), industry)",
        "settings": PROVEN,
        "hypothesis": "Industry-neutral margin momentum with 6-month window",
        "category": "profitability"
    },

    # ── Debt ratio momentum ──
    {
        "name": "debt_assets_ts126_sect",
        "expr": "group_rank(ts_rank(debt/assets, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Debt-to-assets momentum (subset of liabilities); different rank if non-debt liabilities vary",
        "category": "leverage_momentum"
    },
    {
        "name": "debt_equity_ts126_sect",
        "expr": "group_rank(ts_rank(debt/equity, 126), sector)",
        "settings": PROVEN,
        "hypothesis": "Debt/equity momentum: measures leverage CHANGE direction within sector",
        "category": "leverage_momentum"
    },
]


def fmt_checks(checks):
    if not checks:
        return "  (no checks)"
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
    print(f"WAVE 8 Alpha Research  —  {TIMESTAMP}")
    print(f"Recipe: group_rank(ts_rank(X, 126), group)")
    print(f"Settings: decay=0, SUBINDUSTRY, nanHandling=ON, truncation=0.08")
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
                print(f"  [FIELD_ERROR] invalid field in expression\n")
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

        fails    = [ch["name"] for ch in checks if ch.get("result") not in ("PASS", "PENDING")]
        pending  = [ch["name"] for ch in checks if ch.get("result") == "PENDING"]
        all_pass = len(fails) == 0

        if all_pass and not pending:
            status_str = "✓ ALL PASS"
        elif all_pass and pending:
            status_str = "~ PENDING  [" + ",".join(pending) + "]"
        else:
            status_str = "✗ FAIL     [" + ",".join(fails) + "]"

        print(f"  {status_str}")
        print(f"  Sharpe={sharpe:.3f}  Fitness={fitness:.3f}  TO={turnover:.1%}  "
              f"Returns={returns:.3f}  ({elapsed:.0f}s)")
        print(fmt_checks(checks))
        print()

        entry = {
            "name": alpha_def["name"],
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
    print(f"  Field/other errors                 : {len(errors)}")

    if passing:
        print("\n  ── PASSING ──")
        for r in passing:
            is_d = r["alpha"]["is"]
            print(f"    {r['name']:<50s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} TO={float(is_d.get('turnover',0)):.1%}")

    if near:
        print("\n  ── NEAR-PASS ──")
        for r in near:
            is_d   = r["alpha"]["is"]
            checks = is_d.get("checks", [])
            fails  = [ch["name"] for ch in checks if ch.get("result") not in ("PASS", "PENDING")]
            print(f"    {r['name']:<50s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} fail={fails}")

    if errors:
        print("\n  ── ERRORS ──")
        for r in errors:
            print(f"    {r['name']:<50s} {str(r['alpha'].get('error',''))[:60]}")

    print(f"\n  Results saved to: {OUT_FILE}")


if __name__ == "__main__":
    main()
