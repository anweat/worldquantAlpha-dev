"""
Wave 7: Targeted refinement of near-passing signals + novel fundamentals
- Near-passing: ts_rank(operating_income/assets, ...) series (Sharpe 1.3-1.4, Fitness 0.87)
- Near-passing: ts_delta(-news_short_interest, 63) (Sharpe 1.49, Fitness 0.86)
- Novel: liabilities/ebitda, liabilities/revenue (distinct from liabilities/assets cross-section)
- Novel: ts_rank(liabilities/assets, 252) - time-series rank (measures leverage momentum)
- Avoid: monotonic transforms of liabilities/assets (same rank = SELF_CORR fail)
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
OUT_FILE = RESULTS_DIR / f"wave7_{TIMESTAMP}.json"

# Settings variants
FUND_SUB   = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08}
FUND_IND   = {"decay": 4, "neutralization": "INDUSTRY",    "truncation": 0.08}
FUND_IND0  = {"decay": 0, "neutralization": "INDUSTRY",    "truncation": 0.08}
FUND_SECT  = {"decay": 4, "neutralization": "SECTOR",      "truncation": 0.08}
DEFAULT    = {}  # use simulate() defaults

# New alpha expressions — Wave 7
# Target: Sharpe >= 1.25, Fitness >= 1.0, TO 1-15%
ALPHAS = [
    # ═══════════════════════════════════════════════════════════════════
    # Group A: operating_income/assets with finer settings
    # Wave3: sector/industry gave Sharpe=1.37 Fitness=0.87 — try subindustry & longer windows
    # ═══════════════════════════════════════════════════════════════════
    {
        "name": "oi_assets_ts252_subind",
        "expr": "group_rank(ts_rank(operating_income/assets, 252), subindustry)",
        "settings": FUND_IND,  # decay=4, INDUSTRY neutralization
        "hypothesis": "Subindustry-neutral quality rank — finer grouping vs sector/industry variants",
        "category": "quality"
    },
    {
        "name": "oi_assets_ts504_ind",
        "expr": "group_rank(ts_rank(operating_income/assets, 504), industry)",
        "settings": FUND_IND,
        "hypothesis": "Longer 2yr ts_rank window for operating ROA — smoother, lower TO",
        "category": "quality"
    },
    {
        "name": "oi_assets_ts252_ind_d0",
        "expr": "group_rank(ts_rank(operating_income/assets, 252), industry)",
        "settings": FUND_IND0,  # decay=0 vs prior decay=4
        "hypothesis": "No decay version of near-passing alpha; quarterly data needs no smoothing",
        "category": "quality"
    },
    {
        "name": "oi_assets_ts252_sect_d0",
        "expr": "group_rank(ts_rank(operating_income/assets, 252), sector)",
        "settings": FUND_IND0,
        "hypothesis": "Sector-neutral ROA rank with decay=0; sector = coarser but broader group",
        "category": "quality"
    },
    {
        "name": "oi_ts252_sect_d0",
        "expr": "group_rank(ts_rank(operating_income, 252), sector)",
        "settings": FUND_IND0,
        "hypothesis": "Absolute operating income time-series rank, sector-neutral, decay=0",
        "category": "quality"
    },

    # ═══════════════════════════════════════════════════════════════════
    # Group B: news_short_interest variants
    # Wave2: ts_delta(-news_short_interest, 63) → Sharpe=1.49 Fitness=0.86
    # Need to boost returns or change settings to hit Fitness ≥ 1.0
    # ═══════════════════════════════════════════════════════════════════
    {
        "name": "news_si_delta63_subind",
        "expr": "rank(ts_delta(-news_short_interest, 63))",
        "settings": FUND_SUB,  # different from wave2's default settings
        "hypothesis": "Short-squeeze signal with SUBINDUSTRY neutralization; higher idiosyncratic return",
        "category": "sentiment"
    },
    {
        "name": "news_si_delta126_default",
        "expr": "rank(ts_delta(-news_short_interest, 126))",
        "settings": DEFAULT,
        "hypothesis": "Longer 6-month short interest delta; smoother + higher returns than 63-day",
        "category": "sentiment"
    },
    {
        "name": "news_si_delta63_grp_sect",
        "expr": "group_rank(ts_delta(-news_short_interest, 63), sector)",
        "settings": DEFAULT,
        "hypothesis": "Sector-neutral short squeeze momentum; removes sector-level short interest bias",
        "category": "sentiment"
    },
    {
        "name": "news_si_delta252_subind",
        "expr": "rank(ts_delta(-news_short_interest, 252))",
        "settings": FUND_SUB,
        "hypothesis": "Annual change in short interest; captures long-term de-risking signal",
        "category": "sentiment"
    },

    # ═══════════════════════════════════════════════════════════════════
    # Group C: Novel fundamental ratios (distinct from liabilities/assets)
    # liabilities/ebitda and liabilities/revenue have different rank ordering
    # ═══════════════════════════════════════════════════════════════════
    {
        "name": "liab_ebitda_subind",
        "expr": "rank(liabilities/ebitda)",
        "settings": FUND_SUB,
        "hypothesis": "Debt/EBITDA equivalent using 'liabilities'; different rank order from L/assets",
        "category": "leverage"
    },
    {
        "name": "liab_revenue_subind",
        "expr": "rank(liabilities/revenue)",
        "settings": FUND_SUB,
        "hypothesis": "Liabilities-to-sales: captures operating leverage vs revenue-generating capacity",
        "category": "leverage"
    },

    # ═══════════════════════════════════════════════════════════════════
    # Group D: Time-series rank of liabilities/assets (leverage momentum)
    # NOT a monotonic transform of current L/A — measures relative to own history
    # ═══════════════════════════════════════════════════════════════════
    {
        "name": "ts_rank_liab_assets_subind",
        "expr": "rank(ts_rank(liabilities/assets, 252))",
        "settings": FUND_SUB,
        "hypothesis": "Time-series rank of leverage: buys firms where leverage is HIGH vs own history",
        "category": "leverage_momentum"
    },
    {
        "name": "ts_rank_liab_assets_ind",
        "expr": "group_rank(ts_rank(liabilities/assets, 252), industry)",
        "settings": FUND_IND,
        "hypothesis": "Industry-neutral leverage momentum: cross-sectional + time-series double sort",
        "category": "leverage_momentum"
    },

    # ═══════════════════════════════════════════════════════════════════
    # Group E: Composite signals (leverage + profitability blend)
    # Adds a quality tilt to the core leverage signal for diversification
    # ═══════════════════════════════════════════════════════════════════
    {
        "name": "liab_assets_plus_oi_margin",
        "expr": "rank(liabilities/assets + 0.5 * operating_income/revenue)",
        "settings": FUND_SUB,
        "hypothesis": "Leverage + margin combo: high leverage AND high margin firms favored",
        "category": "composite"
    },
    {
        "name": "oi_assets_scaled_liab",
        "expr": "rank(operating_income/assets * liabilities/assets)",
        "settings": FUND_SUB,
        "hypothesis": "ROA × leverage: favors profitable but also highly-leveraged firms",
        "category": "composite"
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
    print(f"WAVE 7 Alpha Research  —  {TIMESTAMP}")
    print(f"Target: near-passing signals + novel fundamentals")
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
        print(f"  sett : {setts or '(defaults)'}")

        t0 = time.time()
        try:
            alpha = c.simulate_and_get_alpha(expr, setts if setts else None)
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            results.append({**alpha_def, "alpha": {"error": str(e)}})
            _save(results, OUT_FILE)
            continue

        elapsed = time.time() - t0

        if "error" in alpha:
            err_str = str(alpha)
            if "unknown variable" in err_str or "Invalid data field" in err_str:
                print(f"  [FIELD_ERROR] invalid field in expression")
            else:
                print(f"  [ERROR] {err_str[:120]}")
            results.append({**alpha_def, "alpha": alpha})
            _save(results, OUT_FILE)
            continue

        is_data  = alpha.get("is", {})
        sharpe   = is_data.get("sharpe",   0)
        fitness  = is_data.get("fitness",  0)
        turnover = is_data.get("turnover", 0)
        returns  = is_data.get("returns",  0)
        checks   = is_data.get("checks",   [])

        fails    = [ch["name"] for ch in checks if ch.get("result") not in ("PASS", "PENDING")]
        pending  = [ch["name"] for ch in checks if ch.get("result") == "PENDING"]
        all_pass = len(fails) == 0

        if all_pass and not pending:
            status_str = "✓ ALL PASS"
        elif all_pass and pending:
            status_str = "~ PENDING " + ",".join(pending)
        else:
            status_str = "✗ FAIL    [" + ",".join(fails) + "]"

        print(f"  {status_str}")
        print(f"  Sharpe={sharpe:.3f}  Fitness={fitness:.3f}  TO={float(turnover):.1%}  "
              f"Returns={float(returns):.3f}  ({elapsed:.0f}s)")
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
    near    = []  # Sharpe >= 1.1 but fail
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
            print(f"    {r['name']:<45s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} TO={float(is_d.get('turnover',0)):.1%}")

    if near:
        print("\n  ── NEAR-PASS ──")
        for r in near:
            is_d   = r["alpha"]["is"]
            checks = is_d.get("checks", [])
            fails  = [ch["name"] for ch in checks if ch.get("result") not in ("PASS", "PENDING")]
            print(f"    {r['name']:<45s} Sharpe={float(is_d.get('sharpe',0)):.3f} "
                  f"Fitness={float(is_d.get('fitness',0)):.3f} fail={fails}")

    if errors:
        print("\n  ── ERRORS ──")
        for r in errors:
            print(f"    {r['name']:<45s} {str(r['alpha'].get('error',''))[:60]}")

    print(f"\n  Results saved to: {OUT_FILE}")


if __name__ == "__main__":
    main()
