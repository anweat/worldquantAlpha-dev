"""
Batch 5c: Re-run EPS/COGS/CFO/debt/employee/capex/beta blocks from batch 5.
These were wrongly skipped because prior session-expired 401 errors were
counted as 'tested'. Fixed dedup: only skip if alpha has real IS results.
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
    print("SESSION EXPIRED!")
    sys.exit(1)

S_NONE = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND  = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SUB  = {"decay":0,"neutralization":"SUBINDUSTRY","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT0 = {"decay":0,"neutralization":"MARKET","truncation":0.08,"language":"FASTEXPR",
           "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
           "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

ALPHAS = [
    # ============================================================
    # EPS-based signals
    # ============================================================
    ("rank(eps/close)", S_IND, "earnings yield ind"),
    ("rank(eps/close)", S_SUB, "earnings yield sub"),
    ("group_rank(ts_rank(eps/close, 126), sector)",   S_NONE, "eps yield ts-rank sector"),
    ("group_rank(ts_rank(eps/close, 252), industry)", S_NONE, "eps yield ts-rank 1yr"),
    ("group_rank(ts_rank(eps, 126), sector)",          S_NONE, "eps level ts-rank sector"),
    ("group_rank(ts_rank(eps, 252), industry)",        S_NONE, "eps level ts-rank 1yr"),
    ("rank(eps - eps_previous_estimate_value)",        S_IND,  "eps revision signal ind"),
    ("group_rank(ts_rank(eps - eps_previous_estimate_value, 63), sector)", S_NONE, "eps revision ts-rank"),
    ("rank(eps_estimate_value - eps_previous_estimate_value)", S_IND, "est eps revision ind"),

    # ============================================================
    # COGS / margin efficiency
    # ============================================================
    ("rank(-cogs/revenue)", S_SUB, "gross margin sub"),
    ("rank(-cogs/revenue)", S_IND, "gross margin ind"),
    ("group_rank(ts_rank(-cogs/revenue, 126), sector)",   S_NONE, "gross margin ts-rank sector"),
    ("group_rank(ts_rank(-cogs/revenue, 252), industry)", S_NONE, "gross margin 1yr ind"),
    ("group_rank(ts_rank(operating_income/revenue - cogs/revenue, 126), sector)",
     S_NONE, "op minus gross margin spread"),

    # ============================================================
    # Cash flow quality
    # ============================================================
    ("rank(cashflow_op/equity)", S_IND, "CFO/equity yield ind"),
    ("rank(cashflow_op/equity)", S_SUB, "CFO/equity yield sub"),
    ("group_rank(ts_rank(cashflow_op/equity, 126), sector)",   S_NONE, "CFO/equity ts-rank"),
    ("group_rank(ts_rank(cashflow_op/equity, 252), industry)", S_NONE, "CFO/equity 1yr"),
    ("rank(cashflow_op/assets)",  S_IND, "CFO/assets yield"),
    ("group_rank(ts_rank(cashflow_op/assets, 126), sector)", S_NONE, "CFO/assets ts-rank"),
    ("rank(cashflow_op - cashflow_fin)", S_IND, "free cashflow proxy"),
    ("group_rank(ts_rank(cashflow_op - cashflow_fin, 126), sector)", S_NONE, "FCF proxy ts-rank"),

    # ============================================================
    # Debt quality
    # ============================================================
    ("rank(-debt_lt/equity)", S_IND, "LT debt ratio inverse"),
    ("rank(-debt_lt/equity)", S_SUB, "LT debt ratio inverse sub"),
    ("group_rank(ts_rank(-debt_lt/equity, 126), sector)", S_NONE, "LT D/E ts-rank sector"),
    ("rank(-debt_st/assets)", S_IND, "ST debt/assets inverse"),
    ("rank(cash_st/debt_st)", S_IND, "cash ST coverage"),
    ("group_rank(ts_rank(cash_st/debt_st, 126), sector)", S_NONE, "cash coverage ts-rank"),
    ("rank(cashflow_op/debt_lt)", S_IND, "CFO debt coverage"),
    ("group_rank(ts_rank(cashflow_op/debt_lt, 126), sector)", S_NONE, "CFO/debt ts-rank"),

    # ============================================================
    # Employee productivity
    # ============================================================
    ("rank(revenue/employee)", S_IND, "revenue per employee"),
    ("group_rank(ts_rank(revenue/employee, 252), sector)", S_NONE, "rev/employee ts-rank"),
    ("rank(operating_income/employee)", S_IND, "OI per employee"),
    ("group_rank(ts_rank(operating_income/employee, 252), sector)", S_NONE, "OI/employee ts-rank"),

    # ============================================================
    # Capital allocation quality
    # ============================================================
    ("rank(capital_expenditure_amount/assets)", S_IND, "capex intensity"),
    ("rank(-capital_expenditure_amount/cashflow_op)", S_IND, "capex to CFO inverse"),
    ("group_rank(ts_rank(operating_income/capital_expenditure_amount, 126), sector)",
     S_NONE, "OI/capex efficiency ts-rank"),
    ("group_rank(ts_rank(cashflow_op/capital_expenditure_amount, 126), sector)",
     S_NONE, "CFO/capex ts-rank"),
    ("rank(cashflow_op/capital_expenditure_amount)", S_IND, "CFO/capex direct"),

    # ============================================================
    # Beta / market sensitivity
    # ============================================================
    ("rank(-beta_last_90_days_spy)",  S_MKT0, "low beta vs SPY 90d"),
    ("rank(-beta_last_360_days_spy)", S_MKT0, "low beta vs SPY 360d"),
    ("group_rank(-beta_last_90_days_spy, sector)",  S_NONE, "low beta by sector"),
    ("rank(correlation_last_360_days_spy)", S_MKT0, "high corr to SPY 360d"),
    ("rank(-ts_std_dev(beta_last_90_days_spy, 126))", S_MKT0, "stable beta proxy"),

    # ============================================================
    # if_else() safe guards (replaces max() which doesn't work in FE)
    # ============================================================
    ("group_rank(ts_rank(net_income / if_else(equity > 0, equity, assets*0.1), 126), sector)",
     S_NONE, "safe ROE ts-rank 126 sec"),
    ("group_rank(ts_rank(net_income / if_else(equity > 0, equity, assets*0.1), 63), sector)",
     S_NONE, "safe ROE ts-rank 63 sec"),
    ("group_rank(ts_rank(net_income / if_else(equity > 0, equity, assets*0.1), 252), sector)",
     S_NONE, "safe ROE ts-rank 252 sec"),
    ("group_rank(ts_rank(net_income / if_else(equity > 0, equity, assets*0.1), 126), industry)",
     S_NONE, "safe ROE ts-rank 126 ind"),
    ("rank(net_income / if_else(equity > 0, equity, assets*0.1))", S_IND, "safe ROE raw IND"),
]


def load_tested_exprs():
    """Fixed dedup: only skip if real IS result exists (not errors)."""
    tested = set()
    for fpath in (ROOT / 'results').glob('*.json'):
        try:
            data = json.loads(fpath.read_text(encoding='utf-8'))
            if isinstance(data, list):
                for item in data:
                    if not item or not item.get('expr'): continue
                    alpha = item.get('alpha', {}) or {}
                    if alpha.get('is') and not alpha.get('error'):
                        tested.add(item['expr'])
        except Exception:
            pass
    return tested


def maybe_submit(alpha_id, checks):
    failed = [ch for ch in checks if ch.get('result') == 'FAIL']
    if not failed:
        r = c.session.post(
            f"{API_BASE}/alphas/{alpha_id}/submit", json={},
            headers={"Accept": "application/json;version=2.0", "Content-Type": "application/json"}
        )
        return r.status_code
    return None


def run_batch():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = ROOT / f'results/batch5c_{timestamp}.json'
    partial_path = ROOT / f'results/batch5c_partial_{timestamp}.json'

    tested = load_tested_exprs()
    print(f"Real results (will skip): {len(tested)}")

    results, passing, failing_reasons = [], [], {}
    errors = 0

    for i, (expr, settings, name) in enumerate(ALPHAS):
        if expr in tested:
            print(f"[{i+1:02d}/{len(ALPHAS)}] SKIP: {name}")
            continue

        print(f"[{i+1:02d}/{len(ALPHAS)}] {name}")
        print(f"         {expr[:85]}")

        try:
            result = c.simulate_and_get_alpha(expr, settings)
            if result.get('error'):
                print(f"         ERROR: {result['error']}")
                errors += 1
                results.append({'name': name, 'expr': expr, 'settings': settings, 'alpha': result})
                continue

            is_d = result.get('is', {}) or {}
            checks = is_d.get('checks', [])
            sharpe = is_d.get('sharpe', 0) or 0
            fitness = is_d.get('fitness', 0) or 0
            to_pct  = (is_d.get('turnover', 0) or 0) * 100
            alpha_id = result.get('id', '')

            failed = [ch['name'] for ch in checks if ch.get('result') == 'FAIL']
            status = "✅ PASS" if not failed else f"FAIL[{','.join(failed[:2])}]"
            print(f"         {status}  S={sharpe:.3f} F={fitness:.3f} TO={to_pct:.1f}%")

            if not failed:
                passing.append({'name': name, 'expr': expr, 'sharpe': sharpe, 'fitness': fitness, 'to': to_pct})
                sub_status = maybe_submit(alpha_id, checks)
                if sub_status:
                    print(f"         ✅ SUBMITTED → HTTP {sub_status}")
            else:
                key = '+'.join(sorted(failed))
                failing_reasons[key] = failing_reasons.get(key, 0) + 1

            results.append({'name': name, 'expr': expr, 'settings': settings, 'alpha': result})
            tested.add(expr)

        except Exception as e:
            print(f"         EXCEPTION: {e}")
            errors += 1
            results.append({'name': name, 'expr': expr, 'settings': settings, 'alpha': {'error': str(e)}})

        if len(results) % 10 == 0:
            partial_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')

        time.sleep(1)

    final_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    print()
    print("=" * 70)
    print("BATCH 5c COMPLETE")
    print("=" * 70)
    print(f"Tested: {len(results)}  PASS: {len(passing)}  FAIL: {sum(failing_reasons.values())}  ERROR: {errors}")
    if failing_reasons:
        print("\nFail reasons:")
        for k, v in sorted(failing_reasons.items(), key=lambda x: -x[1]):
            print(f"  [{v}x] {k}")
    if passing:
        print(f"\n🏆 PASSING:")
        for p in sorted(passing, key=lambda x: -x['fitness']):
            print(f"  {p['name']:<45} S={p['sharpe']:.3f} F={p['fitness']:.3f} TO={p['to']:.1f}%")
    print(f"\nSaved: {final_path}")


if __name__ == '__main__':
    run_batch()
