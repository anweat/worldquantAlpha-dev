"""
Wave 12: Apply MARKET neutralization to near-misses and new signals
Key insight: MARKET neutralization dramatically improves sub-universe Sharpe
 - assets_growth_SUBIND: Sharpe=1.72, sub_sh=0.68 → FAIL
 - assets_growth_MARKET: Sharpe=1.65, sub_sh=0.89 → PASS!
 
Plan:
1. assets_growth_rate with MARKET neutral (was sub=0.65, need 0.70)  
2. FCF/equity variants with MARKET neutral
3. More ts_delta growth signals with MARKET neutral
4. OI/equity variants with MARKET neutral (gold standard)
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
OUT_FILE = RESULTS_DIR / f"wave12_{TIMESTAMP}.json"

P_SUB = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}
P_MKT = {"decay": 0, "neutralization": "MARKET", "truncation": 0.08, "nanHandling": "ON"}
P_IND = {"decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08, "nanHandling": "ON"}

ALPHAS = [
    # ═══════════════════════════════════════════════════════════════
    # Group A: Apply MARKET neutral to near-pass signals from wave11
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "assets_growth_rate_MKT",
        "expr": "group_rank(ts_rank(ts_delta(assets, 63) / ts_delay(assets, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Normalized asset growth rate w/ MARKET neutral (was sub=0.65, MARKET should fix to ~0.85)",
        "category": "growth"
    },
    {
        "name": "fcf_equity_ts126_MKT",
        "expr": "group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), sector)",
        "settings": P_MKT,
        "hypothesis": "FCF/equity MARKET neutral (SUBIND gave Sharpe=1.31 Fitness=0.84, MKT may boost Returns)",
        "category": "fcf"
    },
    {
        "name": "fcf_equity_ts252_MKT",
        "expr": "group_rank(ts_rank(free_cash_flow_reported_value/equity, 252), sector)",
        "settings": P_MKT,
        "hypothesis": "Annual FCF/equity w/ MARKET neutral",
        "category": "fcf"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group B: OI/equity with MARKET neutral (best signal, test neutralization)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "oi_equity_ts126_MKT",
        "expr": "group_rank(ts_rank(operating_income/equity, 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Gold-standard ROE momentum with MARKET neutral: should also easily pass",
        "category": "profitability"
    },
    {
        "name": "oi_equity_ts252_MKT",
        "expr": "group_rank(ts_rank(operating_income/equity, 252), sector)",
        "settings": P_MKT,
        "hypothesis": "Annual ROE momentum with MARKET neutral",
        "category": "profitability"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group C: New ts_delta signals with MARKET neutral
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "liab_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(liabilities, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Liabilities growth with MARKET neutral: rapid leverage increase = bearish signal",
        "category": "growth"
    },
    {
        "name": "equity_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(equity, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Equity growth with MARKET neutral: captures buybacks/issuances/retained earnings",
        "category": "growth"
    },
    {
        "name": "ebitda_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(ebitda, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "EBITDA growth momentum with MARKET neutral: earnings quality improvement",
        "category": "growth"
    },
    {
        "name": "oi_growth_MKT",
        "expr": "group_rank(ts_rank(ts_delta(operating_income, 63), 126), sector)",
        "settings": P_MKT,
        "hypothesis": "OI growth with MARKET neutral (SUBIND had Sharpe=0.80, MARKET may improve)",
        "category": "growth"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group D: INDUSTRY neutralization as intermediate option
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "assets_growth_rate_IND",
        "expr": "group_rank(ts_rank(ts_delta(assets, 63) / ts_delay(assets, 63), 126), sector)",
        "settings": P_IND,
        "hypothesis": "Asset growth rate w/ INDUSTRY neutral (between MARKET and SUBINDUSTRY)",
        "category": "growth"
    },
    {
        "name": "assets_growth_ts126_IND",
        "expr": "group_rank(ts_rank(ts_delta(assets, 63), 126), sector)",
        "settings": P_IND,
        "hypothesis": "Absolute asset growth with INDUSTRY neutral",
        "category": "growth"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group E: Composite signals (combine two metrics)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "oi_equity_plus_fcf_equity",
        "expr": "group_rank(ts_rank(operating_income/equity + free_cash_flow_reported_value/equity, 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Composite OI+FCF to equity: combines profitability and cash generation quality",
        "category": "composite"
    },
    {
        "name": "oi_assets_minus_liab_growth",
        "expr": "group_rank(ts_rank(operating_income/assets - ts_delta(liabilities, 63)/assets, 126), sector)",
        "settings": P_MKT,
        "hypothesis": "Profitability net of leverage increase: buy profitable firms NOT rapidly leveraging up",
        "category": "composite"
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
    print(f"WAVE 12 Alpha Research  —  {TIMESTAMP}")
    print(f"Focus: MARKET neutralization to fix sub-universe Sharpe")
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
