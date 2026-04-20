"""
Wave 13: Explore equity growth signal variants + more MARKET-neutral signals
Key insight from wave12b:
- assets_growth_MARKET: selfCorr=0.44 (very orthogonal!)
- OI/equity SUBIND: selfCorr=0.87 (high correlation, may fail SELF_CORRELATION)

So GROWTH SIGNALS (ts_delta based) are much more orthogonal than LEVEL signals.
Focus on:
1. equity_growth with different windows
2. Normalized equity growth rate (percentage change)
3. Debt growth (leverage change)
4. Sales growth with MARKET neutral
5. Retained earnings growth with MARKET neutral
6. Check if combined level+growth signals work

Design principle: group_rank(ts_rank(ts_delta(X, 63), window), sector) with neutralization=MARKET
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
OUT_FILE = RESULTS_DIR / f"wave13_{TIMESTAMP}.json"

P_MKT = {"decay": 0, "neutralization": "MARKET", "truncation": 0.08, "nanHandling": "ON"}

ALPHAS = [
    # ══════════════════════════════════════════════════════════════
    # Group A: Equity growth signal variants (proven base: sh=1.68, fi=1.18)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "equity_growth_ts150_MKT",
        "expr": "group_rank(ts_rank(ts_delta(equity, 63), 150), sector)",
        "settings": P_MKT,
        "hypothesis": "Equity growth with 6-month ts_rank window (base uses 126, testing 150)",
        "category": "equity_growth"
    },
    {
        "name": "equity_growth_ts175_MKT",
        "expr": "group_rank(ts_rank(ts_delta(equity, 63), 175), sector)",
        "settings": P_MKT,
        "hypothesis": "Equity growth with 7-month ts_rank window",
        "category": "equity_growth"
    },
    {
        "name": "equity_growth_ts252_MKT",
        "expr": "group_rank(ts_rank(ts_delta(equity, 63), 252), sector)",
        "settings": P_MKT,
        "hypothesis": "Equity growth with annual ts_rank window: steadier signal",
        "category": "equity_growth"
    },
    {
        "name": "equity_growth_ind_MKT",
        "expr": "group_rank(ts_rank(ts_delta(equity, 63), 126), industry)",
        "settings": P_MKT,
        "hypothesis": "Equity growth, industry-level group_rank (vs sector in base)",
        "category": "equity_growth"
    },
    {
        "name": "equity_growth_rate_MKT",
        "expr": "group_rank(ts_rank(ts_delta(equity, 63) / ts_delay(equity, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Normalized % equity growth rate: like equity_growth but scaled by size",
        "category": "equity_growth"
    },

    # ══════════════════════════════════════════════════════════════
    # Group B: Debt growth signal (inverse quality)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "debt_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(debt, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Debt growth: rapid debt increase = leverage expanding = bearish?",
        "category": "growth"
    },
    {
        "name": "debt_shrink_MKT",
        "expr": "group_rank(ts_rank(-ts_delta(debt, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Debt reduction: companies paying down debt = de-leveraging = bullish",
        "category": "growth"
    },

    # ══════════════════════════════════════════════════════════════
    # Group C: Revenue/sales growth with MARKET neutral (was Sharpe=0.93 with SUBIND)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "revenue_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(revenue, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Revenue growth with MARKET neutral (SUBIND had Sharpe=0.93, MKT may improve)",
        "category": "growth"
    },
    {
        "name": "sales_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(sales, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Sales growth with MARKET neutral",
        "category": "growth"
    },

    # ══════════════════════════════════════════════════════════════
    # Group D: Retained earnings growth with MARKET neutral
    # ══════════════════════════════════════════════════════════════
    {
        "name": "retained_earnings_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(retained_earnings, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Retained earnings accumulation MARKET neutral (SUBIND had Sharpe=0.91, may improve)",
        "category": "growth"
    },
    {
        "name": "retained_earnings_ts126_MKT",
        "expr": "group_rank(ts_rank(retained_earnings, 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Retained earnings level ts_rank: companies with high retained earnings relative to history",
        "category": "quality"
    },

    # ══════════════════════════════════════════════════════════════
    # Group E: Composite: equity growth + profitability
    # ══════════════════════════════════════════════════════════════
    {
        "name": "equity_growth_plus_oi_equity",
        "expr": "group_rank(ts_rank(ts_delta(equity, 63) + operating_income/equity * equity, 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Equity growth weighted by OI/equity: buy companies where BOTH equity is growing AND profitable",
        "category": "composite"
    },
    {
        "name": "assets_growth_rate_MKT_ind",
        "expr": "group_rank(ts_rank(ts_delta(assets, 63) / ts_delay(assets, 63), 126), industry)",
        "settings": P_MKT,
        "hypothesis": "Asset growth rate with MARKET neutral, industry group_rank (vs sector in base)",
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
    print(f"WAVE 13 Alpha Research  —  {TIMESTAMP}")
    print(f"Focus: Growth signal variants (equity, debt, revenue growth)")
    print(f"Key: selfCorr=0.44 for assets_growth → GROWTH signals are orthogonal!")
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
            sub_ch = next((ch for ch in checks if ch.get("name") == "LOW_SUB_UNIVERSE_SHARPE"), {})
            print(f"    {r['name']:<52s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} sub={sub_ch.get('value','?')} fail={fails}")

    if errors:
        print("\n  ── ERRORS ──")
        for r in errors:
            print(f"    {r['name']:<52s} {str(r['alpha'].get('error',''))[:70]}")

    print(f"\n  Results saved to: {OUT_FILE}")


if __name__ == "__main__":
    main()
