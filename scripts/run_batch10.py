"""
Batch 10: scl12 signal family sweep
Based on confirmed: -ts_std_dev(scl12_buzz, 20) + INDUSTRY → S=1.46 F=1.71 PASS

Strategy:
1. scl12_buzz window sweep (5-63d) with tight truncation + INDUSTRY/SUBINDUSTRY
2. scl12_sentiment family (same pattern)
3. scl12_buzz_fast_d1 / scl12_sentiment_fast_d1
4. Combination of buzz + sentiment
5. ts_rank based patterns (different from std_dev)
"""
import sys, os, json, time, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from brain_client import BrainClient, API_BASE

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
SAVE_FILE = os.path.join(RESULTS_DIR, f"batch10_scl12_{TIMESTAMP}.json")

# Settings templates
S_IND    = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND05  = {"decay":0,"neutralization":"INDUSTRY","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SUB    = {"decay":0,"neutralization":"SUBINDUSTRY","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SUB05  = {"decay":0,"neutralization":"SUBINDUSTRY","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT    = {"decay":0,"neutralization":"MARKET","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT05  = {"decay":4,"neutralization":"MARKET","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

def load_tested_exprs():
    tested = {}
    for fname in os.listdir(RESULTS_DIR):
        if not fname.endswith('.json'): continue
        try:
            data = json.loads(open(os.path.join(RESULTS_DIR, fname), encoding='utf-8').read())
            if not isinstance(data, list): continue
            for item in data:
                if not item or not item.get('expr'): continue
                alpha = item.get('alpha') or {}
                # Only skip if real IS result exists (not error)
                if alpha.get('is') and not alpha.get('error'):
                    key = (item['expr'].strip(), json.dumps(item.get('settings', {}), sort_keys=True))
                    tested[key] = alpha
        except Exception:
            pass
    return tested

def build_alphas():
    alphas = []

    # BLOCK 0: Fix buzz 5d CONCENTRATED_WEIGHT (tighter truncation + both neutralizations)
    for neut, trunc, tag in [("INDUSTRY", 0.05, "IND05"), ("SUBINDUSTRY", 0.05, "SUB05"), ("INDUSTRY", 0.03, "IND03")]:
        s = dict(S_IND05); s["neutralization"] = neut; s["truncation"] = trunc
        alphas.append({"name": f"buzz_5d_{tag}_fix", "expr": "-ts_std_dev(scl12_buzz, 5)", "settings": s,
                       "hypothesis": f"buzz short-term vol 5d {neut} truncation={trunc}"})

    # BLOCK 1: buzz window sweep around winner (20d) — INDUSTRY
    for w in [10, 12, 15, 18, 20, 25, 30, 40, 63]:
        if w == 20: continue  # Already tested and passed
        alphas.append({"name": f"buzz_std_{w}d_IND", "expr": f"-ts_std_dev(scl12_buzz, {w})",
                       "settings": S_IND, "hypothesis": f"buzz std_dev {w}d INDUSTRY"})

    # BLOCK 2: buzz window sweep — SUBINDUSTRY
    for w in [10, 15, 20, 25, 30, 63]:
        alphas.append({"name": f"buzz_std_{w}d_SUB", "expr": f"-ts_std_dev(scl12_buzz, {w})",
                       "settings": S_SUB, "hypothesis": f"buzz std_dev {w}d SUBINDUSTRY"})

    # BLOCK 3: buzz window sweep — MARKET
    for w in [10, 20, 30, 63]:
        alphas.append({"name": f"buzz_std_{w}d_MKT", "expr": f"-ts_std_dev(scl12_buzz, {w})",
                       "settings": S_MKT, "hypothesis": f"buzz std_dev {w}d MARKET"})

    # BLOCK 4: scl12_sentiment family
    for w in [5, 10, 15, 20, 25, 30, 63]:
        for neut, stag, sett in [("INDUSTRY", "IND", S_IND), ("SUBINDUSTRY", "SUB", S_SUB)]:
            alphas.append({"name": f"sent_std_{w}d_{stag}", "expr": f"-ts_std_dev(scl12_sentiment, {w})",
                           "settings": sett, "hypothesis": f"sentiment std_dev {w}d {neut}"})
    # Also try positive sentiment signal
    for w in [10, 20]:
        alphas.append({"name": f"sent_pos_{w}d_IND", "expr": f"ts_std_dev(scl12_sentiment, {w})",
                       "settings": S_IND, "hypothesis": f"+sentiment std_dev {w}d INDUSTRY"})

    # BLOCK 5: scl12_buzz_fast_d1 (derivative series)
    for w in [5, 10, 15, 20]:
        for neut, stag, sett in [("INDUSTRY", "IND", S_IND), ("SUBINDUSTRY", "SUB", S_SUB)]:
            alphas.append({"name": f"buzzd1_std_{w}d_{stag}", "expr": f"-ts_std_dev(scl12_buzz_fast_d1, {w})",
                           "settings": sett, "hypothesis": f"buzz_d1 std_dev {w}d {neut}"})

    # BLOCK 6: scl12_sentiment_fast_d1
    for w in [5, 10, 15, 20]:
        for neut, stag, sett in [("INDUSTRY", "IND", S_IND), ("SUBINDUSTRY", "SUB", S_SUB)]:
            alphas.append({"name": f"sentd1_std_{w}d_{stag}", "expr": f"-ts_std_dev(scl12_sentiment_fast_d1, {w})",
                           "settings": sett, "hypothesis": f"sentiment_d1 std_dev {w}d {neut}"})

    # BLOCK 7: ts_rank patterns (different operator)
    for w in [20, 30, 63, 126]:
        for neut, stag, sett in [("INDUSTRY", "IND", S_IND), ("SUBINDUSTRY", "SUB", S_SUB)]:
            alphas.append({"name": f"buzz_tsrank_{w}d_{stag}", "expr": f"-ts_rank(scl12_buzz, {w})",
                           "settings": sett, "hypothesis": f"buzz ts_rank {w}d {neut}"})

    # BLOCK 8: buzz combination expressions
    # Combine buzz + sentiment
    for w in [10, 20]:
        alphas.append({"name": f"buzz_sent_combo_{w}d_IND",
                       "expr": f"-ts_std_dev(scl12_buzz + scl12_sentiment, {w})",
                       "settings": S_IND, "hypothesis": f"buzz+sentiment combined std_dev {w}d"})
        alphas.append({"name": f"buzz_sent_rank_{w}d_IND",
                       "expr": f"rank(-ts_std_dev(scl12_buzz, {w})) + rank(-ts_std_dev(scl12_sentiment, {w}))",
                       "settings": S_IND, "hypothesis": f"buzz+sentiment ranked sum {w}d"})

    # BLOCK 9: ts_zscore patterns for buzz
    for w in [20, 30]:
        for neut, stag, sett in [("INDUSTRY", "IND", S_IND), ("SUBINDUSTRY", "SUB", S_SUB)]:
            alphas.append({"name": f"buzz_zscore_{w}d_{stag}", "expr": f"-ts_zscore(scl12_buzz, {w})",
                           "settings": sett, "hypothesis": f"buzz ts_zscore {w}d {neut}"})

    # BLOCK 10: scl12_buzz with rank (normalized via rank)
    for w in [10, 15, 20, 30]:
        alphas.append({"name": f"buzz_rank_std_{w}d_IND", "expr": f"rank(-ts_std_dev(scl12_buzz, {w}))",
                       "settings": S_IND, "hypothesis": f"rank(buzz std_dev) {w}d INDUSTRY"})
        alphas.append({"name": f"buzz_rank_std_{w}d_SUB", "expr": f"rank(-ts_std_dev(scl12_buzz, {w}))",
                       "settings": S_SUB, "hypothesis": f"rank(buzz std_dev) {w}d SUBINDUSTRY"})

    return alphas


def save_results(results):
    with open(SAVE_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def main():
    client = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')
    auth = client.check_auth()
    if auth.get('status') != 200:
        print("AUTH FAILED:", auth)
        return

    tested = load_tested_exprs()
    print(f"Already tested: {len(tested)} expr-settings pairs")

    alphas = build_alphas()
    print(f"Total planned: {len(alphas)}")

    results = []
    passed = []
    failed_reasons = {}
    errors = 0

    for i, item in enumerate(alphas):
        key = (item['expr'].strip(), json.dumps(item.get('settings', {}), sort_keys=True))
        if key in tested:
            print(f"  SKIP [{i+1}/{len(alphas)}] {item['name']}")
            continue

        print(f"\n[{i+1}/{len(alphas)}] {item['name']}: {item['expr'][:70]}")
        result = client.simulate_and_get_alpha(item['expr'], item['settings'])

        record = {
            "name": item['name'],
            "expr": item['expr'],
            "settings": item['settings'],
            "hypothesis": item.get('hypothesis', ''),
            "alpha": result
        }

        if result.get('error'):
            errors += 1
            print(f"  ERROR: {result['error']}")
        else:
            is_d = result.get('is', {}) or {}
            checks = is_d.get('checks', [])
            failed = [c['name'] for c in checks if c.get('result') == 'FAIL']
            s = is_d.get('sharpe', 0) or 0
            f_val = is_d.get('fitness', 0) or 0
            to = (is_d.get('turnover', 0) or 0) * 100
            print(f"  S={s:.3f} F={f_val:.3f} TO={to:.1f}%  {'PASS' if not failed else 'FAIL:'+','.join(failed)}")

            if not failed:
                passed.append(item['name'])
                print(f"  *** PASS #{len(passed)} ***")
                # Auto-submit
                alpha_id = result.get('id')
                if alpha_id:
                    try:
                        sub = client.session.post(f"{API_BASE}/alphas/{alpha_id}/submit")
                        print(f"  Submitted: {sub.status_code}")
                    except Exception as e:
                        print(f"  Submit error: {e}")
            else:
                k = '+'.join(sorted(set(failed)))
                failed_reasons[k] = failed_reasons.get(k, 0) + 1

        results.append(record)
        save_results(results)
        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"BATCH 10 COMPLETE: {len(results)} tested, {len(passed)} passing, {errors} errors")
    print(f"Passing: {passed}")
    print(f"Fail reasons: {failed_reasons}")


if __name__ == '__main__':
    main()
