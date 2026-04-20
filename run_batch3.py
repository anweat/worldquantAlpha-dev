"""
Batch 3 Alpha Testing Script
Pattern: group_rank(ts_rank(RATIO, WINDOW), GROUP) with neutralization=NONE
60 expressions across 6 blocks.
"""
import sys, json, glob, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'src'))
from brain_client import BrainClient

# ── Settings templates ────────────────────────────────────────────────────────
S_NONE = {
    "decay": 0, "neutralization": "NONE", "truncation": 0.08,
    "language": "FASTEXPR", "instrumentType": "EQUITY", "region": "USA",
    "universe": "TOP3000", "delay": 1, "pasteurization": "ON",
    "nanHandling": "OFF", "unitHandling": "VERIFY"
}
S_SUB = {
    "decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08,
    "language": "FASTEXPR", "instrumentType": "EQUITY", "region": "USA",
    "universe": "TOP3000", "delay": 1, "pasteurization": "ON",
    "nanHandling": "OFF", "unitHandling": "VERIFY"
}
S_IND = {
    "decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08,
    "language": "FASTEXPR", "instrumentType": "EQUITY", "region": "USA",
    "universe": "TOP3000", "delay": 1, "pasteurization": "ON",
    "nanHandling": "OFF", "unitHandling": "VERIFY"
}
S_MKT = {
    "decay": 0, "neutralization": "MARKET", "truncation": 0.08,
    "language": "FASTEXPR", "instrumentType": "EQUITY", "region": "USA",
    "universe": "TOP3000", "delay": 1, "pasteurization": "ON",
    "nanHandling": "OFF", "unitHandling": "VERIFY"
}

# ── Alpha list ────────────────────────────────────────────────────────────────
ALPHAS_BATCH3 = [
    # === BLOCK A: operating_income/equity variations (PROVEN WINNER) ===
    ("group_rank(ts_rank(operating_income/equity, 63), sector)",      S_NONE, "OI/equity 3mo sector"),
    ("group_rank(ts_rank(operating_income/equity, 63), industry)",    S_NONE, "OI/equity 3mo industry"),
    ("group_rank(ts_rank(operating_income/equity, 63), subindustry)", S_NONE, "OI/equity 3mo subind"),
    ("group_rank(ts_rank(operating_income/equity, 200), sector)",     S_NONE, "OI/equity 200d sector"),
    ("group_rank(ts_rank(operating_income/equity, 200), industry)",   S_NONE, "OI/equity 200d industry"),
    ("group_rank(ts_rank(operating_income/equity, 504), sector)",     S_NONE, "OI/equity 2yr sector"),
    ("group_rank(ts_rank(operating_income/equity, 504), industry)",   S_NONE, "OI/equity 2yr industry"),
    ("group_rank(ts_zscore(operating_income/equity, 126), sector)",   S_NONE, "OI/equity zscore sector"),
    ("group_rank(ts_zscore(operating_income/equity, 126), industry)", S_NONE, "OI/equity zscore industry"),
    ("group_rank(ts_zscore(operating_income/equity, 252), sector)",   S_NONE, "OI/equity zscore 1yr sec"),
    ("rank(ts_rank(operating_income/equity, 126))",                   S_SUB,  "OI/equity rank-tsrank sub"),
    ("rank(ts_zscore(operating_income/equity, 252))",                 S_SUB,  "OI/equity zscore rank sub"),

    # === BLOCK B: Analogous ratio variations ===
    ("group_rank(ts_rank(net_income/equity, 126), sector)",           S_NONE, "NI/equity 126 sector"),
    ("group_rank(ts_rank(net_income/equity, 126), industry)",         S_NONE, "NI/equity 126 industry"),
    ("group_rank(ts_rank(net_income/equity, 252), sector)",           S_NONE, "NI/equity 252 sector"),
    ("group_rank(ts_rank(net_income/equity, 252), industry)",         S_NONE, "NI/equity 252 industry"),
    ("group_rank(ts_rank(ebitda/equity, 126), sector)",               S_NONE, "EBITDA/equity sector"),
    ("group_rank(ts_rank(ebitda/equity, 126), industry)",             S_NONE, "EBITDA/equity industry"),
    ("group_rank(ts_rank(cash_flow_from_operations/equity, 126), sector)",   S_NONE, "CFO/equity sector"),
    ("group_rank(ts_rank(cash_flow_from_operations/equity, 126), industry)", S_NONE, "CFO/equity industry"),
    ("group_rank(ts_rank(cash_flow_from_operations/equity, 252), sector)",   S_NONE, "CFO/equity 1yr sector"),
    ("group_rank(ts_rank(gross_profit/equity, 126), sector)",         S_NONE, "GP/equity sector"),
    ("group_rank(ts_rank(gross_profit/equity, 126), industry)",       S_NONE, "GP/equity industry"),
    ("group_rank(ts_rank(revenue/equity, 126), sector)",              S_NONE, "Rev/equity sector"),
    ("group_rank(ts_rank(revenue/equity, 252), industry)",            S_NONE, "Rev/equity 1yr industry"),
    ("group_rank(ts_rank(operating_income/liabilities, 126), sector)",   S_NONE, "OI/liab sector"),
    ("group_rank(ts_rank(operating_income/liabilities, 252), industry)", S_NONE, "OI/liab 1yr industry"),
    ("group_rank(ts_rank(ebit/assets, 126), sector)",                 S_NONE, "EBIT/assets sector"),
    ("group_rank(ts_rank(ebit/assets, 252), industry)",               S_NONE, "EBIT/assets industry"),

    # === BLOCK C: Pure rank(ratio) explorations ===
    ("rank(operating_income/equity)",                                  S_SUB,  "OI/equity direct rank sub"),
    ("rank(operating_income/equity)",                                  S_IND,  "OI/equity direct rank ind"),
    ("rank(net_income/equity)",                                        S_SUB,  "NI/equity direct rank sub"),
    ("rank(ebitda/equity)",                                            S_SUB,  "EBITDA/equity direct rank"),
    ("rank(cash_flow_from_operations/equity)",                         S_SUB,  "CFO/equity direct rank"),
    ("rank(gross_profit/equity)",                                      S_SUB,  "GP/equity direct rank"),
    ("rank(ebit/assets)",                                              S_IND,  "EBIT/assets rank ind"),
    ("rank(ebit/equity)",                                              S_SUB,  "EBIT/equity rank sub"),

    # === BLOCK D: ts_rank on absolute fundamentals (no ratio) ===
    ("group_rank(ts_rank(operating_income, 126), sector)",            S_NONE, "ts_rank OI sector"),
    ("group_rank(ts_rank(operating_income, 252), sector)",            S_NONE, "ts_rank OI 1yr sector"),
    ("group_rank(ts_rank(net_income, 126), sector)",                  S_NONE, "ts_rank NI sector"),
    ("group_rank(ts_rank(net_income, 252), sector)",                  S_NONE, "ts_rank NI 1yr sector"),
    ("group_rank(ts_rank(ebitda, 126), sector)",                      S_NONE, "ts_rank EBITDA sector"),
    ("group_rank(ts_rank(revenue, 252), sector)",                     S_NONE, "ts_rank Revenue 1yr"),
    ("group_rank(ts_rank(gross_profit, 126), sector)",                S_NONE, "ts_rank GP sector"),

    # === BLOCK E: Composite scores ===
    ("group_rank(ts_rank(operating_income/equity + operating_income/assets, 126), sector)", S_NONE, "OI quality composite"),
    ("group_rank(ts_rank(net_income/equity - liabilities/assets, 252), sector)",            S_NONE, "ROE - leverage"),
    ("group_rank(ts_rank(operating_income/equity * (1 - liabilities/assets), 126), sector)", S_NONE, "ROE x solvency"),

    # === BLOCK F: New analyst/sentiment fields ===
    ("ts_rank(operating_income, 252)",                                S_SUB,  "ts_rank OI sub (doc example)"),
    ("-ts_rank(fn_liab_fair_val_l1_a, 252)",                          S_SUB,  "fair value liab inverse"),
    ("group_rank(ts_rank(est_eps/close, 60), industry)",              S_NONE, "est_eps yield ts-rank"),
    ("ts_zscore(est_eps, 252)",                                        S_IND,  "EPS estimate zscore"),
    ("group_rank(-ts_zscore(enterprise_value/cashflow, 63), industry)", S_NONE, "EV/CF zscore doc example"),
    ("rank(ebit/capex)",                                               S_IND,  "EBIT/capex capital eff"),
    ("group_rank(ts_rank(ebit/capex, 126), sector)",                   S_NONE, "EBIT/capex ts-rank sector"),
    ("-ts_std_dev(scl12_buzz, 10)",                                    S_IND,  "sentiment buzz vol inverse"),
    ("-ts_corr(est_ptp, est_fcf, 252)",                                S_MKT,  "analyst estimate divergence"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def passes(is_data):
    if not is_data:
        return False
    sh = is_data.get('sharpe', 0)
    fi = is_data.get('fitness', 0)
    to = is_data.get('turnover', 1)
    if not (sh >= 1.25 and fi >= 1.0 and 0.01 <= to <= 0.70):
        return False
    for c in is_data.get('checks', []):
        if c.get('result') == 'FAIL':
            return False
    return True


def load_tested_keys():
    """Return set of (expr, neutralization) pairs already tested in results/."""
    keys = set()
    results_dir = ROOT / 'results'
    if not results_dir.exists():
        return keys
    for fp in results_dir.glob('*.json'):
        try:
            data = json.loads(fp.read_text(encoding='utf-8'))
            if not isinstance(data, list):
                continue
            for rec in data:
                expr = rec.get('expr', '')
                neut = rec.get('settings', {}).get('neutralization', '')
                if expr:
                    keys.add((expr, neut))
        except Exception:
            pass
    return keys


def save_results(results, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  [saved {len(results)} records → {out_path.name}]")


def try_submit(client, alpha_result, expr):
    alpha_id = alpha_result.get('id')
    if not alpha_id:
        return
    try:
        resp = client.submit_alpha(alpha_id)
        print(f"  => SUBMITTED alpha_id={alpha_id}  resp={resp}")
    except Exception as e:
        print(f"  => SUBMIT ERROR: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = ROOT / 'results' / f'batch3_{ts}.json'

    # Auth check
    client = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')
    auth = client.check_auth()
    status_code = auth.get('status') if isinstance(auth, dict) else auth
    print(f"Auth check: status={status_code}")
    assert status_code == 200, f"Auth failed (status={status_code}). Refresh session first."

    # Load already-tested keys to skip duplicates
    tested_keys = load_tested_keys()
    print(f"Loaded {len(tested_keys)} previously tested (expr, neut) pairs to skip.")

    total = len(ALPHAS_BATCH3)
    results = []
    n_pass = n_fail = n_error = n_skip = 0

    for i, (expr, settings, label) in enumerate(ALPHAS_BATCH3):
        neut = settings.get('neutralization', '')
        key = (expr, neut)

        if key in tested_keys:
            print(f"[{i+1:02d}/{total}] SKIP (already tested) — {label}: {expr[:70]}")
            n_skip += 1
            continue

        print(f"[{i+1:02d}/{total}] Testing — {label}")
        print(f"          {expr}")

        try:
            result = client.simulate_and_get_alpha(expr, settings)

            # Mid-batch auth expiry
            if isinstance(result, dict) and result.get('error') in (401, 403):
                print(f"  => AUTH EXPIRED mid-batch. Aborting.")
                save_results(results, out_path)
                sys.exit(1)

            is_ = result.get('is', {}) if isinstance(result, dict) else {}
            ok = passes(is_)
            checks_fail    = [c['name'] for c in is_.get('checks', []) if c.get('result') == 'FAIL']
            checks_pending = [c['name'] for c in is_.get('checks', []) if c.get('result') == 'PENDING']

            sh = is_.get('sharpe', 0)
            fi = is_.get('fitness', 0)
            to = is_.get('turnover', 0)

            status_str = 'PASS ✓' if ok else f"FAIL [{','.join(checks_fail) or 'metrics'}]"
            if checks_pending:
                status_str += f" PENDING[{','.join(checks_pending)}]"
            print(f"  => {status_str} | Sharpe={sh:.3f} Fitness={fi:.3f} TO={to*100:.1f}%")

            if ok:
                n_pass += 1
                try_submit(client, result, expr)
            else:
                n_fail += 1

            results.append({
                'name': label,
                'expr': expr,
                'settings': settings,
                'passes': ok,
                'fail_reasons': checks_fail,
                'pending_checks': checks_pending,
                'alpha': result
            })
            tested_keys.add(key)

        except Exception as e:
            print(f"  => ERROR: {e}")
            n_error += 1
            results.append({
                'name': label,
                'expr': expr,
                'settings': settings,
                'passes': False,
                'error': str(e)
            })

        # Save every 10 alphas
        if len(results) % 10 == 0:
            save_results(results, out_path)

    # Final save
    save_results(results, out_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("=== BATCH 3 RESULTS ===")
    print(f"Tested: {len(results)}  PASS: {n_pass}  FAIL: {n_fail}  ERROR: {n_error}  SKIPPED: {n_skip}")
    print(f"Output: {out_path}")
    print()

    passing = [r for r in results if r.get('passes')]
    if passing:
        passing_sorted = sorted(
            passing,
            key=lambda r: r.get('alpha', {}).get('is', {}).get('fitness', 0),
            reverse=True
        )
        print("TOP PASSING (by Fitness):")
        for r in passing_sorted:
            is_ = r.get('alpha', {}).get('is', {})
            sh = is_.get('sharpe', 0)
            fi = is_.get('fitness', 0)
            to = is_.get('turnover', 0)
            neut = r.get('settings', {}).get('neutralization', '?')
            print(f"  [{neut:12s}] {r['expr'][:65]}")
            print(f"               Sharpe={sh:.3f} Fitness={fi:.3f} TO={to*100:.1f}%  [{r['name']}]")
    else:
        print("No alphas passed in this batch.")

    print()
    print("ALL RESULTS (sorted by Fitness desc):")
    print(f"  {'#':>2}  {'Fitness':>7}  {'Sharpe':>6}  {'TO%':>5}  {'Status':<8}  Label")
    print("  " + "-" * 65)
    all_sorted = sorted(
        [r for r in results if 'alpha' in r],
        key=lambda r: r.get('alpha', {}).get('is', {}).get('fitness', 0),
        reverse=True
    )
    for idx, r in enumerate(all_sorted, 1):
        is_ = r.get('alpha', {}).get('is', {})
        sh = is_.get('sharpe', 0)
        fi = is_.get('fitness', 0)
        to = is_.get('turnover', 0)
        status = 'PASS' if r.get('passes') else 'FAIL'
        print(f"  {idx:>2}  {fi:>7.3f}  {sh:>6.3f}  {to*100:>5.1f}%  {status:<8}  {r['name']}")

    print("=" * 70)


if __name__ == '__main__':
    main()
