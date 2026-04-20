"""
Batch 1 - 50 diverse alpha expressions
Fundamental + group_rank + ts_rank variants
"""
import sys, json, time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\codeproject\worldquantAlpha-dev\src')
from brain_client import BrainClient

c = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')
auth = c.check_auth()
print(f"Auth: {auth['status']}")
if auth['status'] != 200:
    print("AUTH FAILED - aborting")
    sys.exit(1)

settings_fund = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08}
settings_ind  = {"decay": 0, "neutralization": "INDUSTRY",    "truncation": 0.08}

ALPHAS = [
    # (expr, settings, hypothesis, category)
    # --- leverage / solvency ---
    ("rank(-equity/assets)",                                          settings_fund, "equity-to-assets leverage", "leverage"),
    ("rank(total_debt/equity)",                                       settings_fund, "debt-to-equity ratio",       "leverage"),
    ("rank(-cash_and_equivalents/liabilities)",                       settings_fund, "cash covers liabilities",    "liquidity"),
    ("rank(cash_and_equivalents/assets)",                             settings_fund, "cash-to-assets",             "liquidity"),
    # --- profitability ---
    ("rank(operating_income/assets)",                                 settings_fund, "ROA (operating)",            "profitability"),
    ("rank(operating_income/sales)",                                  settings_fund, "operating margin",           "profitability"),
    ("rank(net_income/assets)",                                       settings_fund, "ROA (net)",                  "profitability"),
    ("rank(net_income/equity)",                                       settings_fund, "ROE",                        "profitability"),
    ("rank(gross_profit/assets)",                                     settings_fund, "gross profitability",        "profitability"),
    ("rank(book_value/market_cap)",                                   settings_fund, "book-to-market",             "value"),
    # --- efficiency ---
    ("rank(sales/assets)",                                            settings_fund, "asset turnover",             "efficiency"),
    ("rank(retained_earnings/assets)",                                settings_fund, "retained earnings quality",  "quality"),
    ("rank(-total_debt/ebitda)",                                      settings_fund, "debt-to-ebitda",             "leverage"),
    ("rank(ebitda/assets)",                                           settings_fund, "EBITDA yield",               "profitability"),
    ("rank(cash_flow_from_operations/liabilities)",                   settings_fund, "CFO covers liabilities",     "quality"),
    ("rank(cash_flow_from_operations/assets)",                        settings_fund, "CFO ROA",                    "quality"),
    ("rank(operating_income/liabilities)",                            settings_fund, "operating income vs debt",   "quality"),
    ("rank(revenue/assets)",                                          settings_fund, "revenue / assets",           "efficiency"),
    ("rank(-liabilities/equity)",                                     settings_fund, "debt-to-equity (neg)",       "leverage"),
    # --- composite ---
    ("rank(operating_income/assets - liabilities/equity)",            settings_fund, "quality minus leverage",     "composite"),
    ("rank(net_income/sales * sales/assets)",                         settings_fund, "DuPont decomposed ROA",      "composite"),
    ("rank(operating_income/sales - liabilities/assets)",             settings_fund, "margin minus leverage",      "composite"),
    # --- group_rank industry ---
    ("group_rank(operating_income/assets, industry)",                 settings_fund, "ROA within industry",        "group_profitability"),
    ("group_rank(net_income/equity, industry)",                       settings_fund, "ROE within industry",        "group_profitability"),
    ("group_rank(operating_income/sales, industry)",                  settings_fund, "op margin within industry",  "group_profitability"),
    ("group_rank(-liabilities/assets, industry)",                     settings_fund, "leverage within industry",   "group_leverage"),
    ("group_rank(cash_and_equivalents/assets, industry)",             settings_fund, "cash ratio within industry", "group_liquidity"),
    ("group_rank(book_value/market_cap, industry)",                   settings_fund, "BtM within industry",        "group_value"),
    ("group_rank(ebitda/assets, industry)",                           settings_fund, "EBITDA yield industry",      "group_profitability"),
    ("group_rank(retained_earnings/assets, industry)",                settings_fund, "RE quality industry",        "group_quality"),
    # --- group_rank sector ---
    ("group_rank(operating_income/assets, sector)",                   settings_fund, "ROA within sector",          "group_profitability"),
    ("group_rank(net_income/equity, sector)",                         settings_fund, "ROE within sector",          "group_profitability"),
    ("group_rank(-liabilities/assets, sector)",                       settings_fund, "leverage within sector",     "group_leverage"),
    # --- industry neutral (settings_ind) ---
    ("rank(-equity/assets)",                                          settings_ind,  "equity leverage industry-neut","leverage"),
    ("rank(operating_income/assets)",                                 settings_ind,  "ROA industry-neut",          "profitability"),
    ("rank(net_income/equity)",                                       settings_ind,  "ROE industry-neut",          "profitability"),
    ("rank(book_value/market_cap)",                                   settings_ind,  "BtM industry-neut",          "value"),
    ("rank(ebitda/assets)",                                           settings_ind,  "EBITDA yield industry-neut", "profitability"),
    ("rank(cash_flow_from_operations/assets)",                        settings_ind,  "CFO ROA industry-neut",      "quality"),
    # --- ts_rank composites ---
    ("group_rank(ts_rank(operating_income/assets, 63), industry)",    settings_fund, "ROA momentum 63d industry",  "ts_momentum"),
    ("group_rank(ts_rank(operating_income/assets, 252), industry)",   settings_fund, "ROA momentum 252d industry", "ts_momentum"),
    ("group_rank(ts_rank(net_income/equity, 63), industry)",          settings_fund, "ROE momentum 63d industry",  "ts_momentum"),
    ("group_rank(ts_rank(net_income/equity, 252), industry)",         settings_fund, "ROE momentum 252d industry", "ts_momentum"),
    ("group_rank(ts_rank(operating_income/sales, 63), industry)",     settings_fund, "op-margin mom 63d industry", "ts_momentum"),
    ("group_rank(ts_rank(operating_income/sales, 252), industry)",    settings_fund, "op-margin mom 252d industry","ts_momentum"),
    ("group_rank(ts_zscore(operating_income/assets, 252), industry)", settings_fund, "ROA zscore 252d industry",   "ts_zscore"),
    ("group_rank(ts_zscore(net_income/equity, 252), industry)",       settings_fund, "ROE zscore 252d industry",   "ts_zscore"),
    ("rank(ts_rank(operating_income/assets, 252))",                   settings_fund, "ROA momentum 252d global",   "ts_momentum"),
    ("rank(ts_rank(net_income/equity, 252))",                         settings_fund, "ROE momentum 252d global",   "ts_momentum"),
    ("rank(ts_zscore(operating_income/sales, 252))",                  settings_fund, "op-margin zscore 252d",      "ts_zscore"),
]

results = []
results_file = Path(r"D:\codeproject\worldquantAlpha-dev\results") / f"batch1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def save_results():
    results_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [saved {len(results)} results → {results_file.name}]")

TOTAL = len(ALPHAS)
passed = []
failed_list = []

print(f"\nStarting Batch 1 — {TOTAL} expressions\n{'='*60}")

for i, (expr, settings, hyp, cat) in enumerate(ALPHAS):
    print(f"\n[{i+1}/{TOTAL}] {expr[:70]}")
    print(f"  settings: decay={settings.get('decay')} neut={settings.get('neutralization')}")

    try:
        result = c.simulate_and_get_alpha(expr, settings)
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        results.append({"expr": expr, "settings": settings, "hypothesis": hyp,
                        "category": cat, "alpha": {"error": str(e)}})
        if (i + 1) % 10 == 0:
            save_results()
        continue

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        results.append({"expr": expr, "settings": settings, "hypothesis": hyp,
                        "category": cat, "alpha": result})
        if (i + 1) % 10 == 0:
            save_results()
        continue

    is_data = result.get("is", {}) or {}
    sharpe  = is_data.get("sharpe", 0) or 0
    fitness = is_data.get("fitness", 0) or 0
    to      = (is_data.get("turnover", 0) or 0) * 100
    checks  = is_data.get("checks", [])
    failed_checks = [ch["name"] for ch in checks if ch.get("result") == "FAIL"]
    status = "PASS" if not failed_checks else "FAIL"

    print(f"  {status}  Sharpe={sharpe:.3f}  Fitness={fitness:.3f}  TO={to:.1f}%")
    if failed_checks:
        print(f"  Fails: {failed_checks}")

    entry = {"expr": expr, "settings": settings, "hypothesis": hyp,
             "category": cat, "alpha": result}
    results.append(entry)

    # Auto-submit passing alphas
    alpha_id = result.get("id")
    if status == "PASS" and alpha_id:
        try:
            sub = c.submit_alpha(alpha_id)
            print(f"  → Submitted: status={sub.get('status')}")
            passed.append((expr, sharpe, fitness, to))
        except Exception as e:
            print(f"  → Submit error: {e}")
    elif status == "FAIL":
        failed_list.append((expr, sharpe, fitness, to, failed_checks))

    # Incremental save every 10
    if (i + 1) % 10 == 0:
        save_results()

# Final save
save_results()

# ── Summary table ──────────────────────────────────────────────────
print("\n\n=== BATCH 1 RESULTS ===")
print(f"{'Expression':<55} {'Sharpe':>7} {'Fitness':>8} {'TO%':>6}  Status")
print("-" * 85)
for r in results:
    expr_s  = r["expr"][:54]
    is_data = (r.get("alpha") or {}).get("is") or {}
    sharpe  = is_data.get("sharpe", 0) or 0
    fitness = is_data.get("fitness", 0) or 0
    to      = (is_data.get("turnover", 0) or 0) * 100
    checks  = is_data.get("checks", [])
    failed  = [ch["name"] for ch in checks if ch.get("result") == "FAIL"]
    err     = (r.get("alpha") or {}).get("error")
    if err:
        status_str = f"ERROR({err})"
    elif not failed:
        status_str = "PASS ✓"
    else:
        short = ",".join(f[:12] for f in failed[:2])
        status_str = f"FAIL ({short})"
    print(f"{expr_s:<55} {sharpe:>7.3f} {fitness:>8.3f} {to:>6.1f}%  {status_str}")

print("-" * 85)
pass_count = sum(1 for r in results
    if not any(ch.get("result") == "FAIL"
               for ch in ((r.get("alpha") or {}).get("is") or {}).get("checks", [])))
print(f"\nTOTAL: {pass_count}/{len(results)} PASS")
print(f"Results file: {results_file.name}")
