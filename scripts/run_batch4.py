"""
Batch 4: Analyst estimates, sentiment fields, options, and advanced factor combos.
Focus: PROVEN pattern group_rank(ts_rank(RATIO, W), GROUP) + new data fields
"""
import sys, json, time
from pathlib import Path
from datetime import datetime

ROOT = Path(r"D:\codeproject\worldquantAlpha-dev")
sys.path.insert(0, str(ROOT / 'src'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from brain_client import BrainClient, API_BASE

c = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')
auth = c.check_auth()
print(f"Auth: {auth['status']}")
if auth['status'] != 200:
    print("SESSION EXPIRED! Run: cd auth-reptile && python save_session.py")
    sys.exit(1)

# Settings templates
S_NONE = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND  = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SUB  = {"decay":0,"neutralization":"SUBINDUSTRY","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT  = {"decay":4,"neutralization":"MARKET","truncation":0.05,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_NONE_1K = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND_1K  = {"decay":2,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SEC_200 = {"decay":0,"neutralization":"SECTOR","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP200","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SEC_500 = {"decay":0,"neutralization":"SECTOR","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP500","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND_D2  = {"decay":2,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

ALPHAS_BATCH4 = [
    # ============================================================
    # BLOCK 1: Analyst estimates - conditional on field availability
    # ============================================================
    ("ts_zscore(est_eps, 252)", S_SUB, "EPS est zscore sub"),
    ("ts_zscore(est_eps, 126)", S_IND, "EPS est zscore ind"),
    ("group_rank(ts_rank(est_eps, 126), sector)", S_NONE, "EPS est ts-rank sector"),
    ("group_rank(ts_rank(est_eps, 252), industry)", S_NONE, "EPS est ts-rank ind"),
    ("group_rank(ts_rank(est_revenue, 252), industry)", S_NONE, "Rev est ts-rank ind"),
    ("group_rank(ts_rank(est_ebitda, 126), sector)", S_NONE, "EBITDA est ts-rank sector"),
    ("rank(-ts_std_dev(est_eps, 63))", S_IND, "low EPS volatility"),
    ("group_rank(ts_rank(est_eps/close, 60), industry)", S_NONE, "EPS yield ts-rank"),

    # ============================================================
    # BLOCK 2: Earnings surprise / sentiment (TOP1000 for coverage)
    # ============================================================
    ("ts_rank(snt1_d1_earningssurprise, 20)",
     {"decay":2,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
      "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
      "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"},
     "earnings surprise ts-rank"),
    ("ts_rank(snt1_cored1_score, 20)",
     {"decay":2,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
      "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
      "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"},
     "sentiment score ts-rank"),
    ("-ts_std_dev(scl12_buzz, 10)", S_IND, "buzz vol inverse ind"),
    ("-ts_std_dev(scl12_buzz, 20)", S_SUB, "buzz vol inverse sub"),
    ("ts_rank(snt1_d1_buyrecpercent, 63)", S_IND_1K, "buy reco ts-rank TOP1K"),

    # ============================================================
    # BLOCK 3: Fair value liabilities (fn_liab_fair_val_l1_a)
    # ============================================================
    ("-ts_rank(fn_liab_fair_val_l1_a, 252)", S_SUB, "fair val liab inverse sub"),
    ("-ts_rank(fn_liab_fair_val_l1_a, 126)", S_IND, "fair val liab inverse ind"),
    ("group_rank(-ts_rank(fn_liab_fair_val_l1_a, 252), sector)", S_NONE, "fair val liab grp-rank"),

    # ============================================================
    # BLOCK 4: EV/cashflow (bronze doc example)
    # ============================================================
    ("group_rank(-ts_zscore(enterprise_value/cashflow, 63), industry)", S_NONE, "EV/CF zscore bronze"),
    ("group_rank(-ts_zscore(enterprise_value/cashflow, 126), sector)", S_NONE, "EV/CF zscore sector"),
    ("group_rank(-ts_rank(enterprise_value/cashflow, 126), industry)", S_NONE, "EV/CF ts-rank ind"),
    ("rank(-enterprise_value/cashflow)", S_IND, "EV/CF inverse rank"),

    # ============================================================
    # BLOCK 5: EBIT/capex - capital efficiency
    # ============================================================
    ("rank(ebit/capex)", S_IND, "EBIT/capex ind"),
    ("rank(ebit/capex)", S_SUB, "EBIT/capex sub"),
    ("group_rank(ts_rank(ebit/capex, 126), sector)", S_NONE, "EBIT/capex ts-rank sector"),
    ("group_rank(ts_rank(ebit/capex, 252), industry)", S_NONE, "EBIT/capex ts-rank ind"),

    # ============================================================
    # BLOCK 6: Options volatility (TOP200/TOP500)
    # ============================================================
    ("implied_volatility_call_120/parkinson_volatility_120", S_SEC_200, "IV/HV ratio TOP200"),
    ("-implied_volatility_call_120/parkinson_volatility_120", S_SEC_200, "IV/HV inverse TOP200"),
    ("ts_rank(implied_volatility_call_120, 63)", S_SEC_500, "IV_call ts-rank TOP500"),
    ("rank(-implied_volatility_call_120)", S_SEC_200, "low implied vol TOP200"),

    # ============================================================
    # BLOCK 7: Cash flow quality ratios
    # ============================================================
    ("group_rank(ts_rank(cash_flow_from_operations/liabilities, 126), sector)", S_NONE, "CFO/liab ts-rank"),
    ("group_rank(ts_rank(cash_flow_from_operations/liabilities, 252), industry)", S_NONE, "CFO/liab 1yr"),
    ("rank(cash_flow_from_operations/liabilities)", S_SUB, "CFO/liab direct sub"),
    ("rank(cash_flow_from_operations/assets)", S_IND, "CFO/assets ind"),
    ("group_rank(ts_rank(cash_flow_from_operations/assets, 126), sector)", S_NONE, "CFO/assets ts-rank"),

    # ============================================================
    # BLOCK 8: Margin analysis
    # ============================================================
    ("group_rank(ts_rank(gross_profit/revenue, 126), sector)", S_NONE, "gross margin ts-rank"),
    ("group_rank(ts_rank(gross_profit/revenue, 252), industry)", S_NONE, "gross margin 1yr"),
    ("rank(gross_profit/revenue)", S_SUB, "gross margin direct"),
    ("group_rank(ts_rank(operating_income/revenue, 126), sector)", S_NONE, "op margin ts-rank"),
    ("group_rank(ts_rank(operating_income/revenue, 252), industry)", S_NONE, "op margin 1yr"),
    ("rank(operating_income/revenue)", S_SUB, "op margin direct"),

    # ============================================================
    # BLOCK 9: Balance sheet / solvency
    # ============================================================
    ("rank(-liabilities/equity)", S_IND, "inverse D/E"),
    ("group_rank(ts_rank(-liabilities/equity, 126), sector)", S_NONE, "inverse D/E ts-rank"),
    ("rank(retained_earnings/equity)", S_SUB, "retained earnings ratio"),
    ("group_rank(ts_rank(retained_earnings/equity, 252), sector)", S_NONE, "retained earn ts-rank"),
    ("rank(cash_and_equivalents/liabilities)", S_IND, "cash coverage"),
    ("group_rank(ts_rank(cash_and_equivalents/liabilities, 126), sector)", S_NONE, "cash coverage ts-rank"),

    # ============================================================
    # BLOCK 10: Multi-factor quality composites
    # ============================================================
    ("rank(operating_income/equity + gross_profit/revenue)", S_SUB, "ROE + margin"),
    ("group_rank(ts_rank(operating_income/equity + gross_profit/revenue, 126), sector)", S_NONE, "quality composite"),
    ("rank(operating_income/equity - liabilities/equity)", S_IND, "ROE - D/E"),
    ("group_rank(ts_rank(operating_income/equity - liabilities/equity, 126), sector)", S_NONE, "ROE - D/E ts-rank"),

    # ============================================================
    # BLOCK 11: Change / momentum on ratios
    # ============================================================
    ("group_rank(ts_delta(operating_income/equity, 63), sector)", S_NONE, "ROE change sector"),
    ("rank(ts_delta(gross_profit/revenue, 252))", S_SUB, "margin improvement 1yr"),
    ("group_rank(ts_rank(ts_delta(operating_income, 63) / ts_std_dev(operating_income, 252), 126), sector)", S_NONE, "OI momentum z-ranked"),
]

# ============================================================
# Helper functions
# ============================================================

def load_tested_exprs():
    """Load all previously tested expressions to skip duplicates."""
    tested = set()
    results_dir = ROOT / 'results'
    for fpath in results_dir.glob('*.json'):
        try:
            data = json.loads(fpath.read_text(encoding='utf-8'))
            if isinstance(data, list):
                for item in data:
                    if item and item.get('expr'):
                        tested.add(item['expr'])
        except Exception:
            pass
    return tested


def maybe_submit(alpha_id, checks):
    """Auto-submit if no check failures."""
    failed = [c for c in checks if c.get('result') == 'FAIL']
    if not failed:
        r = c.session.post(
            f"{API_BASE}/alphas/{alpha_id}/submit",
            json={},
            headers={"Accept": "application/json;version=2.0", "Content-Type": "application/json"}
        )
        return r.status_code
    return None


def run_batch():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    partial_path = ROOT / f'results/batch4_partial_{timestamp}.json'
    final_path = ROOT / f'results/batch4_{timestamp}.json'

    tested = load_tested_exprs()
    print(f"Previously tested: {len(tested)} expressions (will skip duplicates)")

    results = []
    passing = []
    failing_reasons = {}
    errors = 0

    for i, (expr, settings, name) in enumerate(ALPHAS_BATCH4):
        if expr in tested:
            print(f"[{i+1:02d}/{len(ALPHAS_BATCH4)}] SKIP (already tested): {name}")
            continue

        print(f"[{i+1:02d}/{len(ALPHAS_BATCH4)}] Testing: {name}")
        print(f"         Expr: {expr[:80]}")

        try:
            result = c.simulate_and_get_alpha(expr, settings)
            if result.get('error'):
                print(f"         ERROR: {result['error']}")
                errors += 1
                rec = {'name': name, 'expr': expr, 'settings': settings, 'alpha': result}
                results.append(rec)
                continue

            alpha_data = result
            is_d = alpha_data.get('is', {}) or {}
            checks = is_d.get('checks', [])
            sharpe = is_d.get('sharpe', 0) or 0
            fitness = is_d.get('fitness', 0) or 0
            to_pct = (is_d.get('turnover', 0) or 0) * 100
            alpha_id = alpha_data.get('id', '')

            failed = [ch['name'] for ch in checks if ch.get('result') == 'FAIL']
            status = "PASS" if not failed else f"FAIL[{','.join(failed[:2])}]"

            print(f"         {status}  Sharpe={sharpe:.3f} Fitness={fitness:.3f} TO={to_pct:.1f}%")

            if not failed:
                passing.append({'expr': expr, 'sharpe': sharpe, 'fitness': fitness, 'to': to_pct})
                sub_status = maybe_submit(alpha_id, checks)
                if sub_status:
                    print(f"         SUBMITTED → HTTP {sub_status}")

            else:
                key = '+'.join(sorted(failed))
                failing_reasons[key] = failing_reasons.get(key, 0) + 1

            rec = {'name': name, 'expr': expr, 'settings': settings, 'alpha': alpha_data}
            results.append(rec)
            tested.add(expr)

        except Exception as e:
            print(f"         EXCEPTION: {e}")
            errors += 1
            results.append({'name': name, 'expr': expr, 'settings': settings, 'alpha': {'error': str(e)}})

        # Save partial every 10
        if len(results) % 10 == 0:
            partial_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f"  [Saved partial: {len(results)} results]")

        time.sleep(1)

    # Final save
    final_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')

    # Summary
    print()
    print("=" * 60)
    print(f"BATCH 4 COMPLETE")
    print("=" * 60)
    print(f"Tested: {len(results)}  PASS: {len(passing)}  FAIL: {sum(failing_reasons.values())}  ERROR: {errors}")
    print()
    if failing_reasons:
        print("Fail reasons:")
        for k, v in sorted(failing_reasons.items(), key=lambda x: -x[1]):
            print(f"  [{v}x] {k}")
    print()
    if passing:
        print(f"TOP PASSING (by Fitness):")
        print(f"  {'Expression':<60} {'Sharpe':>7} {'Fitness':>7} {'TO%':>6}")
        print("  " + "-" * 85)
        for p in sorted(passing, key=lambda x: -x['fitness'])[:15]:
            print(f"  {p['expr']:<60} {p['sharpe']:>7.3f} {p['fitness']:>7.3f} {p['to']:>6.1f}%")
    print()
    print(f"Saved to: {final_path}")


if __name__ == '__main__':
    run_batch()
