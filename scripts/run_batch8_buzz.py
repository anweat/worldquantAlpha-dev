"""
Batch 8: URGENT follow-up on scl12_buzz breakthrough signal.
-ts_std_dev(scl12_buzz, 10) → Sharpe=1.82, Fitness=1.70, TO=21.7%
FAILS only LOW_SUB_UNIVERSE_SHARPE → fix with group_rank() sector neutralization.
Also explore full scl12 field family.
"""
import sys, json, time, re
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
S_MKT  = {"decay":4,"neutralization":"MARKET","truncation":0.05,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT0 = {"decay":0,"neutralization":"MARKET","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_NONE_D2 = {"decay":2,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_NONE_1K = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND_1K  = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_NONE_500 = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
              "instrumentType":"EQUITY","region":"USA","universe":"TOP500","delay":1,
              "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

ALPHAS = [
    # ============================================================
    # BLOCK 1: Direct fix for the breakthrough signal
    # Original: -ts_std_dev(scl12_buzz, 10) → S=1.82, F=1.70 FAIL[LOW_SUB_UNIVERSE_SHARPE]
    # Fix: group_rank() removes sub-universe dependency
    # ============================================================
    ("group_rank(-ts_std_dev(scl12_buzz, 10), sector)",      S_NONE, "buzz std sector [FIX]"),
    ("group_rank(-ts_std_dev(scl12_buzz, 10), industry)",    S_NONE, "buzz std industry [FIX]"),
    ("group_rank(-ts_std_dev(scl12_buzz, 10), subindustry)", S_NONE, "buzz std subind [FIX]"),
    ("-ts_std_dev(scl12_buzz, 10)",  S_IND,  "buzz std raw IND"),
    ("-ts_std_dev(scl12_buzz, 10)",  S_SUB,  "buzz std raw SUB"),
    ("-ts_std_dev(scl12_buzz, 10)",  S_MKT,  "buzz std raw MKT"),
    # TOP1000/500 universe (sub-universe concern may go away)
    ("group_rank(-ts_std_dev(scl12_buzz, 10), sector)",   S_NONE_1K,  "buzz std sec TOP1000"),
    ("group_rank(-ts_std_dev(scl12_buzz, 10), industry)", S_NONE_1K,  "buzz std ind TOP1000"),
    ("-ts_std_dev(scl12_buzz, 10)",  S_IND_1K, "buzz std IND TOP1000"),

    # ============================================================
    # BLOCK 2: Window variations on the winning formula
    # ============================================================
    ("group_rank(-ts_std_dev(scl12_buzz, 5),  sector)", S_NONE, "buzz std 5d sector"),
    ("group_rank(-ts_std_dev(scl12_buzz, 20), sector)", S_NONE, "buzz std 20d sector"),
    ("group_rank(-ts_std_dev(scl12_buzz, 63), sector)", S_NONE, "buzz std 63d sector"),
    ("group_rank(-ts_std_dev(scl12_buzz, 5),  industry)", S_NONE, "buzz std 5d industry"),
    ("group_rank(-ts_std_dev(scl12_buzz, 20), industry)", S_NONE, "buzz std 20d industry"),
    ("-ts_std_dev(scl12_buzz, 5)",   S_IND, "buzz std 5d IND"),
    ("-ts_std_dev(scl12_buzz, 20)",  S_IND, "buzz std 20d IND"),

    # ============================================================
    # BLOCK 3: Alternative operators on scl12_buzz
    # ============================================================
    ("group_rank(ts_rank(scl12_buzz, 10), sector)",  S_NONE, "buzz ts_rank 10d sec"),
    ("group_rank(ts_rank(scl12_buzz, 20), sector)",  S_NONE, "buzz ts_rank 20d sec"),
    ("group_rank(ts_rank(scl12_buzz, 63), sector)",  S_NONE, "buzz ts_rank 63d sec"),
    ("group_rank(ts_rank(-scl12_buzz, 10), sector)", S_NONE, "neg buzz ts_rank 10d sec"),
    ("group_rank(ts_rank(-scl12_buzz, 20), sector)", S_NONE, "neg buzz ts_rank 20d sec"),
    ("group_rank(ts_zscore(scl12_buzz, 20), sector)",  S_NONE, "buzz zscore 20d sec"),
    ("group_rank(ts_zscore(scl12_buzz, 63), sector)",  S_NONE, "buzz zscore 63d sec"),
    ("group_rank(ts_zscore(-scl12_buzz, 20), sector)", S_NONE, "neg buzz zscore 20d sec"),
    ("group_rank(-ts_mean(scl12_buzz, 10), sector)",   S_NONE, "neg buzz mean 10d sec"),
    ("group_rank(-ts_mean(scl12_buzz, 20), sector)",   S_NONE, "neg buzz mean 20d sec"),
    ("group_rank(scl12_buzz, sector)",   S_NONE, "buzz raw grp sec"),
    ("group_rank(-scl12_buzz, sector)",  S_NONE, "neg buzz raw grp sec"),

    # ============================================================
    # BLOCK 4: Other scl12 fields (full scl12 family exploration)
    # scl12 = short-selling / crowding dataset
    # Known: scl12_buzz. Explore related fields.
    # ============================================================
    ("group_rank(ts_rank(scl12_short_interest, 10), sector)",   S_NONE, "short int ts_rank 10d"),
    ("group_rank(ts_rank(scl12_short_interest, 20), sector)",   S_NONE, "short int ts_rank 20d"),
    ("group_rank(-ts_std_dev(scl12_short_interest, 10), sector)", S_NONE, "short int std 10d"),
    ("group_rank(ts_rank(scl12_short_interest_ratio, 20), sector)", S_NONE, "short int ratio 20d"),
    ("group_rank(-ts_std_dev(scl12_short_interest_ratio, 10), sector)", S_NONE, "short int ratio std"),
    ("group_rank(ts_rank(scl12_days_to_cover, 20), sector)",    S_NONE, "days to cover 20d"),
    ("group_rank(-ts_std_dev(scl12_days_to_cover, 10), sector)",S_NONE, "days to cover std"),
    ("group_rank(ts_rank(scl12_utilization, 20), sector)",      S_NONE, "short util 20d"),
    ("group_rank(-ts_std_dev(scl12_utilization, 10), sector)",  S_NONE, "short util std 10d"),
    ("group_rank(ts_rank(scl12_fee_rate, 20), sector)",         S_NONE, "borrow fee 20d"),
    ("group_rank(-ts_std_dev(scl12_fee_rate, 10), sector)",     S_NONE, "borrow fee std 10d"),
    ("group_rank(ts_rank(scl12_active_utilization, 20), sector)",S_NONE, "active util 20d"),
    ("group_rank(ts_rank(scl12_lendable, 20), sector)",         S_NONE, "lendable shares 20d"),
    # Composite short-selling signals
    ("group_rank(-ts_std_dev(scl12_buzz, 10) - ts_rank(scl12_short_interest, 20), sector)",
     S_NONE, "buzz+short combo grp"),

    # ============================================================
    # BLOCK 5: Combine buzz signal with fundamental anchor
    # (Higher Fitness, potentially solve sub-universe issue)
    # ============================================================
    ("group_rank(-ts_std_dev(scl12_buzz, 10) + rank(-liabilities/assets), sector)",
     S_NONE, "buzz+lev combo grp sec"),
    ("group_rank(-ts_std_dev(scl12_buzz, 10), sector) + group_rank(-liabilities/assets, sector)",
     S_NONE, "buzz grp + lev grp sum"),
    # Existing winner combined with buzz
    ("-ts_std_dev(scl12_buzz, 10) + rank(-liabilities/assets)", S_IND, "buzz+lev raw IND"),
    ("-ts_std_dev(scl12_buzz, 10) + rank(operating_income/equity)", S_IND, "buzz+ROE raw IND"),
]


def load_tested_exprs():
    """Only skip expressions that have actual simulation results (not errors)."""
    tested = set()
    results_dir = ROOT / 'results'
    for fpath in results_dir.glob('*.json'):
        try:
            data = json.loads(fpath.read_text(encoding='utf-8'))
            if isinstance(data, list):
                for item in data:
                    if not item or not item.get('expr'):
                        continue
                    alpha = item.get('alpha', {}) or {}
                    # Only skip if there's a real IS result (not an error)
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
    final_path = ROOT / f'results/batch8_buzz_{timestamp}.json'
    partial_path = ROOT / f'results/batch8_partial_{timestamp}.json'

    tested = load_tested_exprs()
    print(f"Previously tested (with real results): {len(tested)}")

    results, passing, failing_reasons = [], [], {}
    errors = 0

    for i, (expr, settings, name) in enumerate(ALPHAS):
        if expr in tested:
            print(f"[{i+1:02d}/{len(ALPHAS)}] SKIP: {name}")
            continue

        print(f"[{i+1:02d}/{len(ALPHAS)}] {name}")
        print(f"         {expr[:90]}")

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
    print("BATCH 8 (BUZZ) COMPLETE")
    print("=" * 70)
    print(f"Tested: {len(results)}  PASS: {len(passing)}  FAIL: {sum(failing_reasons.values())}  ERROR: {errors}")
    if failing_reasons:
        print("\nFail reasons:")
        for k, v in sorted(failing_reasons.items(), key=lambda x: -x[1]):
            print(f"  [{v}x] {k}")
    if passing:
        print(f"\n🏆 PASSING ALPHAS:")
        for p in sorted(passing, key=lambda x: -x['fitness']):
            print(f"  {p['name']:<45} S={p['sharpe']:.3f} F={p['fitness']:.3f} TO={p['to']:.1f}%")
    print(f"\nSaved: {final_path}")


if __name__ == '__main__':
    run_batch()
