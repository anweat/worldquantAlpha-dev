"""
Batch 13: Implied volatility signal family
KEY NEAR-MISS: implied_volatility_call_120/parkinson_volatility_120
  TOP200 SECTOR decay=0 → S=1.26 F=1.25 CONCENTRATED_WEIGHT only!
  Fix: truncation=0.05 OR larger universe (TOP500/TOP1000)

Strategy:
1. Fix the near-miss (truncation=0.05, different universes)
2. Systematic IV/HV ratio sweep (all window combos)
3. IV skew signals (put-call spread)
4. Vol-of-vol (ts_std_dev of implied vol)
5. IV momentum (ts_rank of implied_vol)
6. IV mean vs realized vol ratio
"""
import sys, os, json, time, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from brain_client import BrainClient

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
SAVE_FILE = os.path.join(RESULTS_DIR, f"batch13_vol_{TIMESTAMP}.json")

BASE = {"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","delay":1,
        "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

def S(neut, univ="TOP3000", decay=0, trunc=0.08):
    return {**BASE, "neutralization": neut, "universe": univ, "decay": decay, "truncation": trunc}

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
                if alpha.get('is') and not alpha.get('error'):
                    key = (item['expr'].strip(), json.dumps(item.get('settings', {}), sort_keys=True))
                    tested[key] = alpha
        except Exception:
            pass
    return tested

def build_alphas():
    alphas = []

    # BLOCK 0: Direct fix of near-miss
    # Original: TOP200 SECTOR trunc=0.08 → CONCENTRATED_WEIGHT
    near_miss_expr = "implied_volatility_call_120/parkinson_volatility_120"
    for univ, neut, trunc, tag in [
        ("TOP200",  "SECTOR",      0.05, "TOP200_SEC_05"),  # fix truncation
        ("TOP500",  "SECTOR",      0.08, "TOP500_SEC"),     # more stocks
        ("TOP500",  "INDUSTRY",    0.08, "TOP500_IND"),
        ("TOP1000", "SECTOR",      0.08, "TOP1K_SEC"),
        ("TOP1000", "INDUSTRY",    0.08, "TOP1K_IND"),
        ("TOP3000", "INDUSTRY",    0.08, "TOP3K_IND"),
        ("TOP3000", "SUBINDUSTRY", 0.08, "TOP3K_SUB"),
        ("TOP200",  "SECTOR",      0.03, "TOP200_SEC_03"),  # even tighter
    ]:
        alphas.append({"name": f"iv_hv_120_fix_{tag}", "expr": near_miss_expr,
                       "settings": S(neut, univ, 0, trunc),
                       "hypothesis": f"IV/HV 120d ratio {neut} {univ} trunc={trunc}"})

    # group_rank version (different approach)
    alphas.append({"name": "iv_hv_120_grp_sec", "settings": S("NONE"),
                   "expr": "group_rank(implied_volatility_call_120/parkinson_volatility_120, sector)",
                   "hypothesis": "IV/HV 120d group_rank sector NONE"})
    alphas.append({"name": "iv_hv_120_grp_ind", "settings": S("NONE"),
                   "expr": "group_rank(implied_volatility_call_120/parkinson_volatility_120, industry)",
                   "hypothesis": "IV/HV 120d group_rank industry NONE"})

    # BLOCK 1: IV/HV ratio sweep - different window combos
    iv_windows   = [20, 30, 60, 90, 120]
    hvol_windows = [20, 30, 60, 90, 120]
    for iv_w in iv_windows:
        for hv_w in hvol_windows:
            if iv_w == hv_w == 120: continue  # already in block 0
            if abs(iv_w - hv_w) > 90: continue  # skip very mismatched windows
            alphas.append({
                "name": f"iv_hv_c{iv_w}_p{hv_w}_SEC05",
                "expr": f"implied_volatility_call_{iv_w}/parkinson_volatility_{hv_w}",
                "settings": S("SECTOR", "TOP500", 0, 0.05),
                "hypothesis": f"IV call {iv_w}d / parkinson {hv_w}d TOP500 SECTOR"
            })

    # IV mean / historical vol
    for w in [20, 30, 60, 90, 120]:
        hv_w = w
        alphas.append({
            "name": f"iv_mean_hv_{w}_IND05",
            "expr": f"implied_volatility_mean_{w}/historical_volatility_{hv_w}",
            "settings": S("INDUSTRY", "TOP3000", 0, 0.05),
            "hypothesis": f"IV mean/HV {w}d ratio INDUSTRY"
        })

    # BLOCK 2: IV skew (put - call spread = fear premium)
    for w in [20, 30, 60, 90, 120]:
        alphas.append({
            "name": f"iv_skew_neg_{w}_IND",
            "expr": f"rank(-(implied_volatility_put_{w} - implied_volatility_call_{w}))",
            "settings": S("INDUSTRY", "TOP3000", 0, 0.08),
            "hypothesis": f"low put-call vol spread (low fear) {w}d INDUSTRY"
        })
        alphas.append({
            "name": f"iv_skew_mean_{w}_IND",
            "expr": f"rank(-implied_volatility_mean_skew_{w})",
            "settings": S("INDUSTRY", "TOP3000", 0, 0.08),
            "hypothesis": f"low IV skew {w}d INDUSTRY"
        })

    # BLOCK 3: Vol-of-vol (ts_std_dev of implied vol level)
    for w_inner in [20, 30, 60]:
        for w_outer in [20, 30]:
            alphas.append({
                "name": f"vov_{w_inner}_{w_outer}_IND",
                "expr": f"-ts_std_dev(implied_volatility_mean_{w_inner}, {w_outer})",
                "settings": S("INDUSTRY", "TOP3000", 0, 0.08),
                "hypothesis": f"vol-of-vol: std_dev of IV mean {w_inner}d over {w_outer}d"
            })

    # BLOCK 4: IV momentum (ts_rank of implied vol level)
    for w in [20, 30, 60, 90]:
        # LOW iv = low fear = bullish
        alphas.append({
            "name": f"iv_rank_neg_{w}_IND",
            "expr": f"-ts_rank(implied_volatility_mean_{w}, {w})",
            "settings": S("INDUSTRY", "TOP3000", 0, 0.08),
            "hypothesis": f"low IV rank (falling vol) {w}d INDUSTRY"
        })
        # ts_std_dev of IV rank
        alphas.append({
            "name": f"iv_zscore_{w}_IND",
            "expr": f"-ts_zscore(implied_volatility_mean_{w}, {w})",
            "settings": S("INDUSTRY", "TOP3000", 0, 0.08),
            "hypothesis": f"negative IV zscore (reverting to low) {w}d INDUSTRY"
        })

    # BLOCK 5: IV ratio with ts_rank (momentum of IV/HV ratio)
    for w in [30, 63, 90]:
        alphas.append({
            "name": f"iv_hv_ratio_ts{w}_IND",
            "expr": f"ts_rank(implied_volatility_call_120/parkinson_volatility_120, {w})",
            "settings": S("INDUSTRY", "TOP3000", 0, 0.08),
            "hypothesis": f"IV/HV 120d ratio ts_rank {w}d INDUSTRY"
        })

    # BLOCK 6: Put/call IV ratio (different from spread)
    for w in [30, 60, 120]:
        alphas.append({
            "name": f"iv_put_call_ratio_{w}_IND",
            "expr": f"rank(-(implied_volatility_put_{w}/implied_volatility_call_{w}))",
            "settings": S("INDUSTRY", "TOP3000", 0, 0.05),
            "hypothesis": f"low put/call IV ratio (bullish options market) {w}d INDUSTRY"
        })

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
    print(f"Already tested: {len(tested)} pairs")
    alphas = build_alphas()
    print(f"Total planned: {len(alphas)}")

    results = []
    passed = []
    fail_reasons = {}
    errors = 0

    for i, item in enumerate(alphas):
        key = (item['expr'].strip(), json.dumps(item.get('settings', {}), sort_keys=True))
        if key in tested:
            print(f"  SKIP [{i+1}/{len(alphas)}] {item['name']}")
            continue

        print(f"\n[{i+1}/{len(alphas)}] {item['name']}: {item['expr'][:70]}")
        result = client.simulate_and_get_alpha(item['expr'], item['settings'])
        record = {"name": item['name'], "expr": item['expr'],
                  "settings": item['settings'], "hypothesis": item.get('hypothesis',''), "alpha": result}

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
                alpha_id = result.get('id')
                if alpha_id:
                    try:
                        sub = client.session.post(f"{client.API_BASE}/alphas/{alpha_id}/submit")
                        print(f"  Submitted: {sub.status_code}")
                    except Exception as e:
                        print(f"  Submit error: {e}")
            else:
                k = '+'.join(sorted(set(failed)))
                fail_reasons[k] = fail_reasons.get(k, 0) + 1

        results.append(record)
        save_results(results)
        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"BATCH 13 COMPLETE: {len(results)} tested, {len(passed)} passing, {errors} errors")
    print(f"Passing: {passed}")
    print(f"Fail reasons: {fail_reasons}")

if __name__ == '__main__':
    main()
