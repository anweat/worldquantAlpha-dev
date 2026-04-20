"""
Batch 11: Multi-factor combos + snt1 analyst sentiment + pcr_oi options data
Focus:
1. Combine proven winners (OI/equity ts_rank + equity/assets rank)
2. snt1 analyst sentiment signals  
3. pcr_oi options put/call ratio (different windows)
4. fn_* accruals quality signals
5. fscore boost via multi-factor (combine with buzz)
"""
import sys, os, json, time, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from brain_client import BrainClient, API_BASE

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
SAVE_FILE = os.path.join(RESULTS_DIR, f"batch11_combo_{TIMESTAMP}.json")

# Settings
S_NONE = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND  = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SUB  = {"decay":0,"neutralization":"SUBINDUSTRY","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT  = {"decay":4,"neutralization":"MARKET","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT0 = {"decay":0,"neutralization":"MARKET","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND_D2 = {"decay":2,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

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

    # BLOCK 1: Multi-factor combo of proven winners
    # OI/equity ts_rank (best signal) + equity/assets quality
    alphas += [
        {"name": "combo_OI_equity_quality_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/equity, 126), sector) + rank(-equity/assets)",
         "hypothesis": "OI ts_rank + equity/assets quality combo sector"},
        {"name": "combo_OI_equity_quality_IND", "settings": S_IND,
         "expr": "rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)",
         "hypothesis": "OI ts_rank 126 + equity quality INDUSTRY"},
        {"name": "combo_OI_equity_quality_SUB", "settings": S_SUB,
         "expr": "rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)",
         "hypothesis": "OI ts_rank 126 + equity quality SUBINDUSTRY"},
        {"name": "combo_OI_assets_quality_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/assets, 150), sector) + rank(-equity/assets)",
         "hypothesis": "OI/assets ts_rank + equity quality combo"},
        {"name": "combo_OI_buzz_SEC", "settings": S_IND,
         "expr": "rank(ts_rank(operating_income/equity, 126)) + rank(-ts_std_dev(scl12_buzz, 20))",
         "hypothesis": "OI fundamentals + buzz sentiment combo INDUSTRY"},
        {"name": "combo_fscore_OI_SEC", "settings": S_IND,
         "expr": "rank(ts_rank(operating_income/equity, 126)) + rank(fscore_bfl_total)",
         "hypothesis": "OI momentum + fscore quality combo INDUSTRY"},
    ]

    # BLOCK 2: snt1 analyst signals (all fields)
    for field in ['snt1_d1_earningsrevision', 'snt1_d1_netearningsrevision', 
                  'snt1_d1_earningssurprise', 'snt1_d1_earningstorpedo',
                  'snt1_d1_buyrecpercent', 'snt1_d1_netrecpercent', 'snt1_d1_nettargetpercent',
                  'snt1_d1_stockrank', 'snt1_d1_fundamentalfocusrank', 'snt1_d1_dynamicfocusrank',
                  'snt1_cored1_score']:
        short = field.replace('snt1_d1_','').replace('snt1_','')
        alphas += [
            {"name": f"snt_{short}_IND", "expr": f"rank({field})",
             "settings": S_IND, "hypothesis": f"snt1 {short} rank INDUSTRY"},
            {"name": f"snt_{short}_grp_sec", "expr": f"group_rank({field}, sector)",
             "settings": S_NONE, "hypothesis": f"snt1 {short} group_rank sector"},
        ]
    # snt1 uptarget/downtarget
    alphas += [
        {"name": "snt_uptarget_IND", "expr": "rank(snt1_d1_uptargetpercent)", "settings": S_IND,
         "hypothesis": "analyst up-target % INDUSTRY"},
        {"name": "snt_downtarget_neg_IND", "expr": "rank(-snt1_d1_downtargetpercent)", "settings": S_IND,
         "hypothesis": "negative analyst down-target INDUSTRY"},
        {"name": "snt_longgrowth_IND", "expr": "rank(snt1_d1_longtermepsgrowthest)", "settings": S_IND,
         "hypothesis": "long-term EPS growth estimate rank INDUSTRY"},
    ]

    # BLOCK 3: pcr_oi options data (put/call ratio open interest)
    for days in [10, 20, 30, 60, 90, 120, 180, 360]:
        field = f"pcr_oi_{days}"
        alphas += [
            {"name": f"pcr_{days}d_IND", "expr": f"rank(-{field})",
             "settings": S_IND, "hypothesis": f"low put/call ratio (bullish) {days}d INDUSTRY"},
            {"name": f"pcr_{days}d_ts_IND", "expr": f"-ts_std_dev({field}, 20)",
             "settings": S_IND, "hypothesis": f"pcr_oi {days}d volatility INDUSTRY"},
        ]
    # pcr_oi momentum (ts_rank)
    for days in [20, 30, 60]:
        alphas.append({"name": f"pcr_{days}d_tsrank_IND", 
                       "expr": f"rank(-ts_rank({field}, 63))",
                       "settings": S_IND, "hypothesis": f"pcr_oi {days}d ts_rank INDUSTRY"})

    # BLOCK 4: fn_ accruals and quality (detailed balance sheet)
    accruals_fields = [
        ('fn_accrued_liab_q', 'accrued_liab_q'),
        ('fn_accrued_liab_curr_q', 'accrued_curr_q'),
    ]
    for field, short in accruals_fields:
        alphas += [
            {"name": f"fn_{short}_norm_IND", 
             "expr": f"rank(-{field}/assets)", "settings": S_IND,
             "hypothesis": f"fn {short} normalized by assets INDUSTRY"},
            {"name": f"fn_{short}_chg_IND",
             "expr": f"rank(-ts_delta({field}, 4))", "settings": S_IND,
             "hypothesis": f"fn {short} quarterly change rank INDUSTRY"},
        ]

    # BLOCK 5: Accruals-based quality (operating_cashflow vs income)
    alphas += [
        {"name": "accruals_ratio_IND", "settings": S_IND,
         "expr": "rank(-(operating_income - cash_flow_from_operations) / assets)",
         "hypothesis": "accruals quality ratio (low accruals = high quality) INDUSTRY"},
        {"name": "accruals_ratio_SUB", "settings": S_SUB,
         "expr": "rank(-(operating_income - cash_flow_from_operations) / assets)",
         "hypothesis": "accruals quality ratio SUBINDUSTRY"},
        {"name": "cash_oi_ratio_IND", "settings": S_IND,
         "expr": "rank(cash_flow_from_operations / operating_income)",
         "hypothesis": "cash earnings quality ratio INDUSTRY"},
        {"name": "cfo_assets_IND", "settings": S_IND,
         "expr": "rank(cash_flow_from_operations / assets)",
         "hypothesis": "CFO/assets cash return on assets"},
        {"name": "cfo_assets_ts_IND", "settings": S_IND,
         "expr": "group_rank(ts_rank(cash_flow_from_operations / assets, 126), sector)",
         "settings_override": S_NONE,
         "hypothesis": "ts_rank CFO/assets 126d sector"},
    ]

    # BLOCK 6: invested_capital efficiency
    alphas += [
        {"name": "roic_IND", "settings": S_IND,
         "expr": "rank(operating_income / invested_capital)",
         "hypothesis": "ROIC rank INDUSTRY"},
        {"name": "roic_ts_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income / invested_capital, 126), sector)",
         "hypothesis": "ROIC ts_rank 126d sector group_rank"},
        {"name": "roic_ts_IND", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income / invested_capital, 126), industry)",
         "hypothesis": "ROIC ts_rank 126d industry group_rank"},
    ]

    # BLOCK 7: capex quality
    alphas += [
        {"name": "capex_intensity_neg_IND", "settings": S_IND,
         "expr": "rank(-capex / assets)",
         "hypothesis": "low capex intensity (asset-light) INDUSTRY"},
        {"name": "capex_oi_ratio_IND", "settings": S_IND,
         "expr": "rank(operating_income / capex)",
         "hypothesis": "operating income per capex dollar"},
        {"name": "fcf_proxy_IND", "settings": S_IND,
         "expr": "rank((cash_flow_from_operations - capex) / assets)",
         "hypothesis": "FCF proxy (CFO - capex) / assets INDUSTRY"},
        {"name": "fcf_ts_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank((cash_flow_from_operations - capex) / assets, 126), sector)",
         "hypothesis": "FCF ts_rank 126d sector"},
    ]

    # Fix duplicate settings bug in BLOCK 5
    for a in alphas:
        if 'settings_override' in a:
            a['settings'] = a.pop('settings_override')

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
                        sub = client.session.post(f"{API_BASE}/alphas/{alpha_id}/submit")
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
    print(f"BATCH 11 COMPLETE: {len(results)} tested, {len(passed)} passing, {errors} errors")
    print(f"Passing: {passed}")
    print(f"Fail reasons: {fail_reasons}")

if __name__ == '__main__':
    main()
