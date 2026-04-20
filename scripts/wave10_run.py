"""
Wave 10: More diverse signals to avoid SELF_CORRELATION failure
- selfCorrelation=0.87 for OI/equity suggests potential HIGH_SELF_CORRELATION check failure
- Need signals from different FACTOR FAMILIES:
  (a) Revenue-based: sales momentum, revenue growth acceleration
  (b) EBITDA/equity variant of the ROE signal
  (c) OI/equity with window variants (150, 175, 252) for separate SELF_CORR evaluation
  (d) Size/market_cap signal (verify field, new factor family)
  (e) Fundamental growth: ts_delta of revenue, assets growth
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
OUT_FILE = RESULTS_DIR / f"wave10_{TIMESTAMP}.json"

P = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}

ALPHAS = [
    # ═══════════════════════════════════════════════════════════════
    # Group A: OI/equity window variants (diversify from 126-window version)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "oi_equity_ts150_sect",
        "expr": "group_rank(ts_rank(operating_income/equity, 150), sector)",
        "settings": P,
        "hypothesis": "ROE momentum with 6-month window; diversifies from submitted 126-version",
        "category": "profitability"
    },
    {
        "name": "oi_equity_ts175_sect",
        "expr": "group_rank(ts_rank(operating_income/equity, 175), sector)",
        "settings": P,
        "hypothesis": "ROE momentum with 7-month window; tests if passing range extends past 126",
        "category": "profitability"
    },
    {
        "name": "oi_equity_ts252_sect",
        "expr": "group_rank(ts_rank(operating_income/equity, 252), sector)",
        "settings": P,
        "hypothesis": "Annual ROE ts_rank; lower Sharpe expected but highly independent signal",
        "category": "profitability"
    },
    {
        "name": "oi_equity_ts95_sect",
        "expr": "group_rank(ts_rank(operating_income/equity, 95), sector)",
        "settings": P,
        "hypothesis": "4-month ROE momentum; shorter than passing 126-version",
        "category": "profitability"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group B: EBITDA/equity (D&A-adjusted ROE) — new metric
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "ebitda_equity_ts126_sect",
        "expr": "group_rank(ts_rank(ebitda/equity, 126), sector)",
        "settings": P,
        "hypothesis": "EBITDA/equity momentum: like ROE but before D&A, captures capital structure quality",
        "category": "profitability"
    },
    {
        "name": "ebitda_equity_ts126_ind",
        "expr": "group_rank(ts_rank(ebitda/equity, 126), industry)",
        "settings": P,
        "hypothesis": "Industry-neutral EBITDA/equity momentum",
        "category": "profitability"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group C: Revenue/equity (Price/Sales analog) — very different from OI factors
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "revenue_equity_ts126_sect",
        "expr": "group_rank(ts_rank(revenue/equity, 126), sector)",
        "settings": P,
        "hypothesis": "Revenue/equity momentum: like Price/Book but using revenue; growth signal",
        "category": "growth"
    },
    {
        "name": "sales_equity_ts126_sect",
        "expr": "group_rank(ts_rank(sales/equity, 126), sector)",
        "settings": P,
        "hypothesis": "Sales/equity momentum: similar to revenue/equity, potential data availability diff",
        "category": "growth"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group D: Market cap as size factor (verify field, new factor family)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "market_cap_size",
        "expr": "rank(-market_cap)",
        "settings": P,
        "hypothesis": "Small-cap premium: buy small firms, sell large firms; orthogonal to profitability",
        "category": "size"
    },
    {
        "name": "market_cap_sector_neutral",
        "expr": "group_rank(-market_cap, sector)",
        "settings": P,
        "hypothesis": "Sector-neutral size: buy small caps within each sector",
        "category": "size"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group E: Fundamental growth signals (very different from level signals)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "revenue_growth_ts126_sect",
        "expr": "group_rank(ts_rank(ts_delta(sales, 63), 126), sector)",
        "settings": P,
        "hypothesis": "Revenue growth acceleration: ts_rank of quarterly revenue change, sector-neutral",
        "category": "growth"
    },
    {
        "name": "assets_growth_ts126_sect",
        "expr": "group_rank(ts_rank(ts_delta(assets, 63), 126), sector)",
        "settings": P,
        "hypothesis": "Asset growth momentum: firms investing more (or shrinking) relative to history",
        "category": "growth"
    },

    # ═══════════════════════════════════════════════════════════════
    # Group F: Cash flow / equity (CFO-based ROE, different from OI/equity)
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "cfo_equity_ts126_sect",
        "expr": "group_rank(ts_rank(cash_flow_from_operations/equity, 126), sector)",
        "settings": P,
        "hypothesis": "Cash ROE: CFO/equity momentum; complements accruals-based OI/equity",
        "category": "cash_flow"
    },
    {
        "name": "cfo_equity_ts126_ind",
        "expr": "group_rank(ts_rank(cash_flow_from_operations/equity, 126), industry)",
        "settings": P,
        "hypothesis": "Industry-neutral cash ROE momentum",
        "category": "cash_flow"
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
    print(f"WAVE 10 Alpha Research  —  {TIMESTAMP}")
    print(f"Diverse factors: OI/equity windows, EBITDA/equity, revenue/equity,")
    print(f"market_cap size, fundamental growth, CFO/equity")
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
