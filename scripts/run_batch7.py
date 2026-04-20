"""
Batch 7: Follow-up on near-miss alphas from batch 2 KB results.
Focus: Boost Sharpe on expressions that had Fitness >= 1.0 but LOW_SHARPE.
Key insight: group_rank(operating_income/sales, industry) had Fitness=1.55, Sharpe=0.89
Strategy: Add ts_rank() time-series dimension + try smaller universes + cross-factor combos.
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
S_MKT0 = {"decay":0,"neutralization":"MARKET","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND1K = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
           "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
           "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_NONE1K = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
            "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
            "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND_D4 = {"decay":4,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
            "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
            "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

ALPHAS = [
    # ============================================================
    # BLOCK 1: ts_rank boost for operating_income margin signals
    # The problem: group_rank(oi/sales, ind) → Fitness=1.55, Sharpe=0.89
    # Fix: Add ts_rank to capture time-series dynamics
    # ============================================================
    ("group_rank(ts_rank(operating_income/sales, 63), sector)",     S_NONE, "OI margin ts-rank 63 sec"),
    ("group_rank(ts_rank(operating_income/sales, 126), sector)",    S_NONE, "OI margin ts-rank 126 sec"),
    ("group_rank(ts_rank(operating_income/sales, 252), sector)",    S_NONE, "OI margin ts-rank 252 sec"),
    ("group_rank(ts_rank(operating_income/sales, 63), industry)",   S_NONE, "OI margin ts-rank 63 ind"),
    ("group_rank(ts_rank(operating_income/sales, 126), industry)",  S_NONE, "OI margin ts-rank 126 ind"),
    ("group_rank(ts_rank(operating_income/sales, 63), subindustry)",S_NONE, "OI margin ts-rank 63 sub"),
    ("group_rank(ts_rank(operating_income/assets, 63), sector)",    S_NONE, "ROA ts-rank 63 sec"),
    ("group_rank(ts_rank(operating_income/assets, 126), sector)",   S_NONE, "ROA ts-rank 126 sec"),
    ("group_rank(ts_rank(operating_income/assets, 63), industry)",  S_NONE, "ROA ts-rank 63 ind"),
    ("group_rank(ts_rank(operating_income/assets, 126), industry)", S_NONE, "ROA ts-rank 126 ind"),

    # ============================================================
    # BLOCK 2: ts_zscore variants (similar to ts_rank but more aggressive)
    # ============================================================
    ("group_rank(ts_zscore(operating_income/sales, 252), sector)",    S_NONE, "OI margin zscore 252 sec"),
    ("group_rank(ts_zscore(operating_income/assets, 252), sector)",   S_NONE, "ROA zscore 252 sec"),
    ("group_rank(ts_zscore(operating_income/equity, 252), sector)",   S_NONE, "ROE zscore 252 sec"),
    ("group_rank(ts_zscore(net_income/assets, 252), sector)",         S_NONE, "net ROA zscore 252"),
    ("group_rank(ts_zscore(net_income/sales, 252), sector)",          S_NONE, "net margin zscore 252"),

    # ============================================================
    # BLOCK 3: Fundamental CHANGE signals (delta = momentum of fundamental)
    # ts_delta captures improving vs deteriorating fundamentals
    # ============================================================
    ("group_rank(ts_delta(operating_income/sales, 4), sector)",   S_NONE, "OI margin change 4q sec"),
    ("group_rank(ts_delta(operating_income/assets, 4), sector)",  S_NONE, "ROA change 4q sec"),
    ("group_rank(ts_delta(operating_income/sales, 8), sector)",   S_NONE, "OI margin change 8q sec"),
    ("group_rank(ts_delta(liabilities/assets, 4), sector)",       S_NONE, "leverage change 4q sec"),
    ("group_rank(ts_delta(liabilities/assets, 8), sector)",       S_NONE, "leverage change 8q sec"),
    ("group_rank(ts_delta(assets, 4), sector)",                   S_NONE, "asset growth 4q sec"),

    # ============================================================
    # BLOCK 4: net_income / equity with SAFETY guards
    # Previously errored because equity can be negative
    # Fix: use max(equity, assets*0.01) as denominator
    # ============================================================
    ("group_rank(net_income / max(equity, assets*0.01), sector)",  S_NONE, "ROE safe grp sector"),
    ("group_rank(ts_rank(net_income / max(equity, assets*0.01), 126), sector)", S_NONE, "ROE safe ts-rank 126"),
    ("group_rank(ts_rank(net_income / max(equity, assets*0.01), 63), industry)", S_NONE, "ROE safe ts-rank 63 ind"),
    ("group_rank(ts_rank(net_income / max(equity, assets*0.01), 252), sector)", S_NONE, "ROE safe ts-rank 252"),

    # ============================================================
    # BLOCK 5: Multi-factor composites combining two passing signals
    # Proven: rank(liabilities/assets) works + group_rank(ts_rank(OI/eq,126),sec) works
    # Test: combine them for diversification boost
    # ============================================================
    ("rank(-liabilities/assets) + group_rank(ts_rank(operating_income/equity, 126), sector)", S_NONE, "leverage+ROE combo"),
    ("0.5*rank(-liabilities/assets) + 0.5*group_rank(ts_rank(operating_income/assets, 126), sector)", S_NONE, "lev+ROA equal wt"),
    ("rank(operating_income/assets) + rank(-liabilities/assets)", S_IND, "ROA+lev combo ind"),
    ("group_rank(operating_income/sales + operating_income/assets, sector)", S_NONE, "OI multi-denom grp"),

    # ============================================================
    # BLOCK 6: sales growth + fundamental momentum
    # ============================================================
    ("group_rank(ts_delta(sales, 4) / sales, sector)",   S_NONE, "sales growth 4q sec"),
    ("group_rank(ts_delta(sales, 8) / sales, sector)",   S_NONE, "sales growth 8q sec"),
    ("group_rank(ts_rank(sales / assets, 63), sector)",  S_NONE, "asset turnover ts-rank 63"),
    ("group_rank(ts_rank(sales / assets, 126), sector)", S_NONE, "asset turnover ts-rank 126"),
    ("group_rank(ts_rank(sales / assets, 252), sector)", S_NONE, "asset turnover ts-rank 252"),

    # ============================================================
    # BLOCK 7: Alternative ratio expressions for passing liab/assets
    # The 62 passing alphas are all liabilities/assets variants
    # Explore closely-related ratios
    # ============================================================
    ("group_rank(-liabilities/assets, sector)",    S_NONE, "neg leverage grp sector"),
    ("group_rank(-liabilities/assets, industry)",  S_NONE, "neg leverage grp ind"),
    ("rank(-liabilities/equity)",  S_IND, "debt/equity inv ind"),
    ("rank(assets/liabilities)",   S_IND, "solvency ratio ind"),
    ("group_rank(assets/liabilities, sector)",  S_NONE, "solvency grp sector"),
    ("group_rank(assets/liabilities, industry)",S_NONE, "solvency grp ind"),
    ("group_rank(ts_rank(-liabilities/assets, 126), sector)",  S_NONE, "neg lev ts-rank 126"),
    ("group_rank(ts_rank(-liabilities/assets, 252), sector)",  S_NONE, "neg lev ts-rank 252"),
    ("group_rank(ts_rank(assets/liabilities, 126), sector)",   S_NONE, "solvency ts-rank 126"),

    # ============================================================
    # BLOCK 8: ts_delta on price/volume ratios (technique blend)
    # Use volume-adjusted price signals with fundamentals
    # ============================================================
    ("group_rank(ts_rank(volume, 126), sector)",  S_NONE, "volume ts-rank 126 sec"),
    ("group_rank(ts_rank(volume, 63), sector)",   S_NONE, "volume ts-rank 63 sec"),
    ("group_rank(-ts_corr(close, volume, 63), sector)",  S_NONE, "price-vol corr neg grp"),
    ("group_rank(-ts_corr(close, volume, 126), sector)", S_NONE, "price-vol corr neg 126"),
    ("group_rank(ts_rank(close/ts_mean(close, 252), 63), sector)",  S_NONE, "12m momentum rank 63"),
    ("group_rank(ts_rank(close/ts_mean(close, 126), 63), sector)",  S_NONE, "6m momentum rank 63"),
    ("group_rank(ts_rank(close/ts_mean(close, 252), 126), sector)", S_NONE, "12m momentum rank 126"),
]


def load_tested_exprs():
    tested = set()
    for fpath in (ROOT / 'results').glob('*.json'):
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
    final_path = ROOT / f'results/batch7_{timestamp}.json'
    partial_path = ROOT / f'results/batch7_partial_{timestamp}.json'

    tested = load_tested_exprs()
    print(f"Previously tested: {len(tested)} (will skip duplicates)")

    results = []
    passing = []
    failing_reasons = {}
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
            to_pct = (is_d.get('turnover', 0) or 0) * 100
            alpha_id = result.get('id', '')

            failed = [ch['name'] for ch in checks if ch.get('result') == 'FAIL']
            status = "PASS" if not failed else f"FAIL[{','.join(failed[:2])}]"
            print(f"         {status}  S={sharpe:.3f} F={fitness:.3f} TO={to_pct:.1f}%")

            if not failed:
                passing.append({'name': name, 'expr': expr, 'sharpe': sharpe, 'fitness': fitness, 'to': to_pct})
                sub_status = maybe_submit(alpha_id, checks)
                if sub_status:
                    print(f"         SUBMITTED -> HTTP {sub_status}")
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
    print("BATCH 7 COMPLETE")
    print("=" * 70)
    print(f"Tested: {len(results)}  PASS: {len(passing)}  FAIL: {sum(failing_reasons.values())}  ERROR: {errors}")
    if failing_reasons:
        print("\nFail reasons:")
        for k, v in sorted(failing_reasons.items(), key=lambda x: -x[1]):
            print(f"  [{v}x] {k}")
    if passing:
        print(f"\nTOP PASSING (by Fitness):")
        print(f"  {'Name':<42} {'Sharpe':>7} {'Fitness':>7} {'TO%':>6}")
        print("  " + "-" * 60)
        for p in sorted(passing, key=lambda x: -x['fitness'])[:20]:
            print(f"  {p['name']:<42} {p['sharpe']:>7.3f} {p['fitness']:>7.3f} {p['to']:>6.1f}%")
    print(f"\nSaved: {final_path}")


if __name__ == '__main__':
    run_batch()
