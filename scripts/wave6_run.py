"""
Wave 6: Submit passing alphas + test new diverse fundamental expressions
Phase 1: Submit known-passing alphas to trigger SELF_CORRELATION check
Phase 2: Test new alpha expressions
Phase 3: Save results
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
OUT_FILE = RESULTS_DIR / f"wave6_{TIMESTAMP}.json"

# Settings variants
FUND_SUB = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08}
FUND_IND  = {"decay": 2, "neutralization": "INDUSTRY",    "truncation": 0.08}

# New alpha expressions to test (Phase 2)
NEW_ALPHAS = [
    # --- Balance-sheet leverage (inverse of liabilities/assets, but different) ---
    {
        "name": "neg_debt_equity_subind",
        "expr": "rank(-debt/equity)",
        "settings": FUND_SUB,
        "hypothesis": "Low leverage firms outperform; inverse debt/equity avoids liabilities/assets correlation",
        "category": "leverage"
    },
    {
        "name": "cash_liabilities_subind",
        "expr": "rank(cash_and_equivalents/liabilities)",
        "settings": FUND_SUB,
        "hypothesis": "High cash-to-liabilities = strong liquidity, low default risk",
        "category": "liquidity"
    },
    {
        "name": "retained_earnings_assets_subind",
        "expr": "rank(retained_earnings/assets)",
        "settings": FUND_SUB,
        "hypothesis": "Retained earnings accumulation signals profitability quality",
        "category": "quality"
    },
    # --- Profitability ratios ---
    {
        "name": "operating_margin_subind",
        "expr": "rank(operating_income/revenue)",
        "settings": FUND_SUB,
        "hypothesis": "Operating margin is a durable quality signal",
        "category": "profitability"
    },
    {
        "name": "roa_subind",
        "expr": "rank(net_income/assets)",
        "settings": FUND_SUB,
        "hypothesis": "Return on assets (ROA) captures asset efficiency",
        "category": "profitability"
    },
    {
        "name": "gross_profit_assets_subind",
        "expr": "rank(gross_profit/assets)",
        "settings": FUND_SUB,
        "hypothesis": "Gross profit / assets (Novy-Marx factor) predicts returns",
        "category": "profitability"
    },
    # --- Cash flow ---
    {
        "name": "cfo_assets_subind",
        "expr": "rank(cash_flow_from_operations/assets)",
        "settings": FUND_SUB,
        "hypothesis": "Operating cash yield distinguishes earnings quality",
        "category": "cash_flow"
    },
    # --- Value ---
    {
        "name": "book_to_market_subind",
        "expr": "rank(book_value/market_cap)",
        "settings": FUND_SUB,
        "hypothesis": "Classic book-to-market value factor with SUBINDUSTRY neutralization",
        "category": "value"
    },
    # --- Debt coverage ---
    {
        "name": "neg_debt_ebitda_subind",
        "expr": "rank(-total_debt/ebitda)",
        "settings": FUND_SUB,
        "hypothesis": "Debt/EBITDA coverage; low ratio (negative rank) = safer firms",
        "category": "leverage"
    },
    # --- Group-rank variants for diversity ---
    {
        "name": "op_margin_sector_grp",
        "expr": "group_rank(operating_income/sales, sector)",
        "settings": FUND_SUB,
        "hypothesis": "Sector-neutral operating margin; removes industry effects",
        "category": "profitability"
    },
    {
        "name": "roa_industry_grp",
        "expr": "group_rank(net_income/assets, industry)",
        "settings": FUND_IND,
        "hypothesis": "Industry-neutral ROA; captures relative profitability within peers",
        "category": "profitability"
    },
    {
        "name": "neg_liab_assets_industry_grp",
        "expr": "group_rank(-liabilities/assets, industry)",
        "settings": FUND_IND,
        "hypothesis": "Industry-neutral leverage; different from SUBINDUSTRY version",
        "category": "leverage"
    },
    # --- Earnings quality ---
    {
        "name": "sales_assets_subind",
        "expr": "rank(sales/assets)",
        "settings": FUND_SUB,
        "hypothesis": "Asset turnover ratio; high turnover firms are more efficient",
        "category": "efficiency"
    },
    {
        "name": "ebitda_assets_subind",
        "expr": "rank(ebitda/assets)",
        "settings": FUND_SUB,
        "hypothesis": "EBITDA yield on assets; captures pre-tax operating efficiency",
        "category": "profitability"
    },
    {
        "name": "neg_total_debt_assets_ind",
        "expr": "rank(-total_debt/assets)",
        "settings": FUND_IND,
        "hypothesis": "Total debt ratio (industry-neutral); different from liabilities/assets",
        "category": "leverage"
    },
]

# Passing alpha IDs to submit (Phase 1)
PASSING_IDS = ["zqJJnkxV", "6XYYLzOG", "2rnnoRxP", "O055XeoY", "xAmmEYaW"]


def fmt_checks(checks):
    if not checks:
        return "  (no checks)"
    lines = []
    for ch in checks:
        status = ch.get("result", "?")
        name   = ch.get("name", "?")
        val    = ch.get("value", "")
        lim    = ch.get("limit", "")
        lines.append(f"  {status:5s} {name:<35s} val={val} lim={lim}")
    return "\n".join(lines)


def main():
    print(f"{'='*70}")
    print(f"WAVE 6 Alpha Research  —  {TIMESTAMP}")
    print(f"{'='*70}\n")

    c = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')

    # ── Auth check ──────────────────────────────────────────────────────────
    auth = c.check_auth()
    if auth["status"] != 200:
        print(f"[ERROR] Auth failed: {auth}")
        sys.exit(1)
    user = auth["body"]
    print(f"[AUTH OK] user={user.get('id','?')}  {user.get('email','')}\n")

    results = []

    # ── PHASE 1: Submit passing alphas ───────────────────────────────────────
    print("=" * 70)
    print("PHASE 1: Submitting passing alphas to trigger SELF_CORRELATION check")
    print("=" * 70)

    submission_results = []
    for alpha_id in PASSING_IDS:
        print(f"\n  Submitting alpha {alpha_id} ...")
        resp = c.submit_alpha(alpha_id)
        status = resp.get("status")
        body   = resp.get("body", {})
        print(f"  → HTTP {status}")
        if isinstance(body, dict):
            checks = body.get("checks", [])
            if checks:
                print(fmt_checks(checks))
            else:
                print(f"  body: {json.dumps(body)[:200]}")
        else:
            print(f"  body: {str(body)[:200]}")
        submission_results.append({"alpha_id": alpha_id, "status": status, "body": body})
        time.sleep(2)

    print(f"\n  Submitted {len(submission_results)} alphas.\n")

    # ── PHASE 2: Test new alpha expressions ──────────────────────────────────
    print("=" * 70)
    print(f"PHASE 2: Testing {len(NEW_ALPHAS)} new alpha expressions")
    print("=" * 70)

    for i, alpha_def in enumerate(NEW_ALPHAS, 1):
        name  = alpha_def["name"]
        expr  = alpha_def["expr"]
        setts = alpha_def["settings"]
        print(f"\n[{i:02d}/{len(NEW_ALPHAS)}] {name}")
        print(f"  expr     : {expr}")
        print(f"  settings : {setts}")
        print(f"  Running simulation ...")
        t0 = time.time()

        try:
            alpha = c.simulate_and_get_alpha(expr, setts)
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            results.append({**alpha_def, "alpha": {"error": str(e)}})
            _save(results, OUT_FILE)
            continue

        elapsed = time.time() - t0

        if "error" in alpha:
            print(f"  [ERROR] {alpha}")
            results.append({**alpha_def, "alpha": alpha})
            _save(results, OUT_FILE)
            continue

        is_data  = alpha.get("is", {})
        sharpe   = is_data.get("sharpe",   "?")
        fitness  = is_data.get("fitness",  "?")
        turnover = is_data.get("turnover", "?")
        returns  = is_data.get("returns",  "?")
        checks   = is_data.get("checks",   [])

        # Determine overall pass/fail
        all_pass = all(ch.get("result") == "PASS" for ch in checks) if checks else False
        status_str = "✓ PASS" if all_pass else "✗ FAIL"

        print(f"  {status_str}  Sharpe={sharpe:.3f}  Fitness={fitness:.3f}  "
              f"TO={turnover:.1%}  Returns={returns:.3f}  ({elapsed:.0f}s)")
        if checks:
            print(fmt_checks(checks))

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

    # ── PHASE 3: Summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PHASE 3: Summary")
    print("=" * 70)

    passing = []
    failing = []
    for r in results:
        a = r.get("alpha", {})
        is_d = a.get("is", {})
        checks = is_d.get("checks", [])
        if checks and all(ch.get("result") == "PASS" for ch in checks):
            passing.append(r)
        elif "error" not in a:
            failing.append(r)

    print(f"\n  Total tested : {len(results)}")
    print(f"  Passing      : {len(passing)}")
    print(f"  Failing      : {len(failing)}")

    if passing:
        print("\n  ── PASSING ALPHAS ──")
        for r in passing:
            is_d = r["alpha"]["is"]
            print(f"    {r['name']:<40s}  "
                  f"Sharpe={is_d.get('sharpe','?'):.3f}  "
                  f"Fitness={is_d.get('fitness','?'):.3f}  "
                  f"TO={is_d.get('turnover','?'):.1%}")

    if failing:
        print("\n  ── FAILING ALPHAS (with reasons) ──")
        for r in failing:
            is_d   = r["alpha"].get("is", {})
            checks = is_d.get("checks", [])
            fails  = [ch["name"] for ch in checks if ch.get("result") != "PASS"]
            print(f"    {r['name']:<40s}  "
                  f"Sharpe={is_d.get('sharpe','?')}  "
                  f"Fitness={is_d.get('fitness','?')}  "
                  f"fail={fails}")

    print(f"\n  Results saved to: {OUT_FILE}")

    # Also save submission results
    sub_file = RESULTS_DIR / f"wave6_submissions_{TIMESTAMP}.json"
    with open(sub_file, "w", encoding="utf-8") as f:
        json.dump(submission_results, f, indent=2, ensure_ascii=False)
    print(f"  Submissions saved to: {sub_file}")


def _save(results, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
