"""
Wave 11: FCF signals (orthogonal to OI), price momentum, asset growth normalization
Key goal: Find signals with LOW self-correlation vs the profitability/leverage cluster

Insight: selfCorrelation=0.87 for OI/equity suggests we need signals from:
1. FCF family (free_cash_flow_reported_value): different economic concept
2. Price momentum (orthogonal to fundamentals)
3. Growth rates (ts_delta normalized) vs level signals

Available confirmed fields: assets, liabilities, equity, debt, operating_income, ebitda,
revenue, sales, cash_flow_from_operations, free_cash_flow_reported_value, retained_earnings,
returns, close, news_short_interest
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
OUT_FILE = RESULTS_DIR / f"wave11_{TIMESTAMP}.json"

P = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}
P_MKTNEUT = {"decay": 0, "neutralization": "MARKET", "truncation": 0.08, "nanHandling": "ON"}

ALPHAS = [
    # ══════════════════════════════════════════════════════════════
    # Group A: FCF signals (free_cash_flow_reported_value)
    # FCF = cash available after capital expenditures; ~orthogonal to OI
    # ══════════════════════════════════════════════════════════════
    {
        "name": "fcf_equity_ts126_sect",
        "expr": "group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), sector)",
        "settings": P,
        "hypothesis": "FCF yield to equity: free cash flow quality; different from OI which ignores CapEx",
        "category": "fcf"
    },
    {
        "name": "fcf_equity_ts126_ind",
        "expr": "group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), industry)",
        "settings": P,
        "hypothesis": "Industry-neutral FCF/equity momentum",
        "category": "fcf"
    },
    {
        "name": "fcf_assets_ts126_sect",
        "expr": "group_rank(ts_rank(free_cash_flow_reported_value/assets, 126), sector)",
        "settings": P,
        "hypothesis": "FCF/assets momentum: like ROA but using free cash flow",
        "category": "fcf"
    },
    {
        "name": "fcf_equity_ts252_sect",
        "expr": "group_rank(ts_rank(free_cash_flow_reported_value/equity, 252), sector)",
        "settings": P,
        "hypothesis": "Annual FCF/equity ts_rank: steadier signal vs quarterly",
        "category": "fcf"
    },
    {
        "name": "fcf_equity_ts150_sect",
        "expr": "group_rank(ts_rank(free_cash_flow_reported_value/equity, 150), sector)",
        "settings": P,
        "hypothesis": "6-month FCF/equity momentum (window between 126 and 175)",
        "category": "fcf"
    },

    # ══════════════════════════════════════════════════════════════
    # Group B: Price-based momentum (sector-neutral)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "price_momentum_252_sect",
        "expr": "group_rank(ts_rank(close, 252), sector)",
        "settings": P,
        "hypothesis": "12-month price momentum rank: stocks at 52-week high outperform; sector-neutral",
        "category": "momentum"
    },
    {
        "name": "price_momentum_126_sect",
        "expr": "group_rank(ts_rank(close, 126), sector)",
        "settings": P,
        "hypothesis": "6-month price momentum rank: shorter-term technical signal",
        "category": "momentum"
    },
    {
        "name": "returns_momentum_252_sect",
        "expr": "group_rank(ts_rank(returns, 252), sector)",
        "settings": P,
        "hypothesis": "12-month return momentum: similar to close rank but using daily returns data",
        "category": "momentum"
    },

    # ══════════════════════════════════════════════════════════════
    # Group C: Growth rate signals (normalize by own size)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "oi_growth_ts126_sect",
        "expr": "group_rank(ts_rank(ts_delta(operating_income, 63), 126), sector)",
        "settings": P,
        "hypothesis": "OI growth momentum: quarterly OI change ts_ranked over 6 months",
        "category": "growth"
    },
    {
        "name": "revenue_growth2_ts126_sect",
        "expr": "group_rank(ts_rank(ts_delta(revenue, 63), 126), sector)",
        "settings": P,
        "hypothesis": "Revenue growth acceleration: quarterly revenue change, sector-neutral",
        "category": "growth"
    },
    {
        "name": "retained_earnings_growth_sect",
        "expr": "group_rank(ts_rank(ts_delta(retained_earnings, 63), 126), sector)",
        "settings": P,
        "hypothesis": "Retained earnings accumulation: increasing retained earnings = profitable + reinvesting",
        "category": "growth"
    },

    # ══════════════════════════════════════════════════════════════
    # Group D: Fix assets_growth (try different settings for sub-universe)
    # assets_growth fails LOW_SUB_UNIVERSE_SHARPE (0.68 < 0.74) with SUBINDUSTRY
    # ══════════════════════════════════════════════════════════════
    {
        "name": "assets_growth_MARKET",
        "expr": "group_rank(ts_rank(ts_delta(assets, 63), 126), sector)",
        "settings": P_MKTNEUT,
        "hypothesis": "Asset growth with MARKET neutral: may improve sub-universe Sharpe vs SUBINDUSTRY",
        "category": "growth"
    },
    {
        "name": "assets_growth_annual",
        "expr": "group_rank(ts_rank(ts_delta(assets, 252), 252), sector)",
        "settings": P,
        "hypothesis": "Annual asset change ts_ranked over 1 year: more stable than quarterly change",
        "category": "growth"
    },
    {
        "name": "assets_growth_rate_sect",
        "expr": "group_rank(ts_rank(ts_delta(assets, 63) / ts_delay(assets, 63), 126), sector)",
        "settings": P,
        "hypothesis": "Percentage asset growth rate: normalized by own asset base, more comparable large vs small",
        "category": "growth"
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
    print(f"WAVE 11 Alpha Research  —  {TIMESTAMP}")
    print(f"Goal: FCF signals (orthogonal to OI), price momentum, growth rates")
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
                print(f"  [FIELD_ERROR] {err_str[:100]}\n")
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
            print(f"    {r['name']:<52s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} TO={float(is_d.get('turnover',0)):.1%} "
                  f"id={alpha_id}")

    if near:
        print("\n  ── NEAR-PASS ──")
        for r in near:
            is_d   = r["alpha"]["is"]
            checks = is_d.get("checks", [])
            fails  = [ch["name"] for ch in checks if ch.get("result") not in ("PASS", "PENDING")]
            print(f"    {r['name']:<52s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} fail={fails}")

    if errors:
        print("\n  ── ERRORS ──")
        for r in errors:
            print(f"    {r['name']:<52s} {str(r['alpha'].get('error',''))[:70]}")

    print(f"\n  Results saved to: {OUT_FILE}")


if __name__ == "__main__":
    main()
