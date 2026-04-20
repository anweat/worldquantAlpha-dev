"""
Batch 12: rp_css with proper decay + anl4 consensus + nws12 news volume signals
Focus:
1. rp_css topics with decay=8 in settings (MARKET neutralization)
2. anl4 consensus/revision signals (EPS estimates, analyst counts)
3. nws12 news volume ratio signals
4. OI/equity ts_rank family on new ratio variations
5. pcr_oi with truncation fix (0.05)
"""
import sys, os, json, time, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from brain_client import BrainClient

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
SAVE_FILE = os.path.join(RESULTS_DIR, f"batch12_rpanl_{TIMESTAMP}.json")

# Settings
S_IND  = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SUB  = {"decay":0,"neutralization":"SUBINDUSTRY","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_NONE = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND05 = {"decay":0,"neutralization":"INDUSTRY","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
# rp_css needs decay in settings to reduce turnover
S_MKT8 = {"decay":8,"neutralization":"MARKET","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND8 = {"decay":8,"neutralization":"INDUSTRY","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT4 = {"decay":4,"neutralization":"MARKET","truncation":0.05,"language":"FASTEXPR","instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,"pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

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

    # BLOCK 1: rp_css with proper decay in settings
    rp_topics = ['rp_css_equity', 'rp_css_earnings', 'rp_css_revenue', 'rp_css_credit',
                 'rp_css_price', 'rp_css_product', 'rp_css_mna', 'rp_css_ratings',
                 'rp_css_labor', 'rp_css_dividends', 'rp_css_insider', 'rp_css_ptg']
    for topic in rp_topics:
        short = topic.replace('rp_css_', '')
        # decay=8 MARKET (high-turnover signal needs strong decay)
        alphas.append({"name": f"rp_{short}_d8_MKT", "expr": f"rank({topic})",
                       "settings": S_MKT8, "hypothesis": f"rp_css {short} rank decay=8 MARKET"})
        alphas.append({"name": f"rp_{short}_d8_IND", "expr": f"rank({topic})",
                       "settings": S_IND8, "hypothesis": f"rp_css {short} rank decay=8 INDUSTRY"})
    # ts_rank within decay
    for topic in ['rp_css_equity', 'rp_css_earnings', 'rp_css_revenue']:
        short = topic.replace('rp_css_', '')
        for w in [20, 63]:
            alphas.append({"name": f"rp_{short}_ts{w}_d8", "expr": f"rank(ts_rank({topic}, {w}))",
                           "settings": S_MKT8, "hypothesis": f"rp_css {short} ts_rank {w}d decay=8"})

    # BLOCK 2: anl4 EPS consensus signals
    alphas += [
        # Analyst consensus EPS mean (annual, quarterly, long-term)
        {"name": "anl4_eps_mean_IND", "expr": "rank(anl4_afv4_eps_mean)", "settings": S_IND,
         "hypothesis": "analyst EPS mean consensus rank INDUSTRY"},
        {"name": "anl4_eps_surprise_IND", "expr": "rank(anl4_afv4_dts_spe)", "settings": S_IND,
         "hypothesis": "EPS surprise (actual vs estimate) rank INDUSTRY"},
        {"name": "anl4_eps_range_neg_IND", "expr": "rank(-(anl4_afv4_eps_high - anl4_afv4_eps_low))",
         "settings": S_IND, "hypothesis": "low EPS dispersion (analyst agreement) INDUSTRY"},
        {"name": "anl4_eps_coverage_IND", "expr": "rank(anl4_afv4_eps_number)", "settings": S_IND,
         "hypothesis": "analyst coverage count rank"},
        {"name": "anl4_cfps_mean_IND", "expr": "rank(anl4_afv4_cfps_mean)", "settings": S_IND,
         "hypothesis": "analyst CFPS mean rank INDUSTRY"},
    ]
    # Consensus annual/quarterly: mean, number, up/down revisions
    for suffix, desc in [('afv110', 'annual'), ('qfv110', 'quarterly'), ('ltv110', 'longterm')]:
        alphas += [
            {"name": f"anl4_con_{suffix}_mean_IND",
             "expr": f"rank(anl4_basiccon{suffix}_mean)", "settings": S_IND,
             "hypothesis": f"consensus {desc} estimate mean INDUSTRY"},
            {"name": f"anl4_con_{suffix}_pu_IND",
             "expr": f"rank(anl4_basiccon{suffix}_pu)", "settings": S_IND,
             "hypothesis": f"consensus {desc} % upgrades INDUSTRY"},
            {"name": f"anl4_con_{suffix}_down_neg_IND",
             "expr": f"rank(-anl4_basiccon{suffix}_down)", "settings": S_IND,
             "hypothesis": f"consensus {desc} low downgrades INDUSTRY"},
            {"name": f"anl4_con_{suffix}_revision_IND",
             "expr": f"rank(anl4_basiccon{suffix}_pu - anl4_basiccon{suffix}_down)",
             "settings": S_IND, "hypothesis": f"net revision score {desc} INDUSTRY"},
        ]

    # BLOCK 3: anl4 analyst buy/sell/hold
    alphas += [
        {"name": "anl4_buy_rank_IND", "expr": "rank(anl4_buy)", "settings": S_IND,
         "hypothesis": "analyst buy recommendations rank"},
        {"name": "anl4_hold_neg_IND", "expr": "rank(-anl4_hold)", "settings": S_IND,
         "hypothesis": "low hold (high conviction) rank"},
        {"name": "anl4_buy_hold_ratio_IND", "expr": "rank(anl4_buy / (anl4_buy + anl4_hold))",
         "settings": S_IND, "hypothesis": "buy/(buy+hold) ratio rank"},
    ]

    # BLOCK 4: nws12 news volume signals
    nws_sessions = ['mainz', 'prez', 'afterhsz']
    for session in nws_sessions:
        alphas += [
            {"name": f"nws_{session}_vol_IND", 
             "expr": f"-ts_std_dev(nws12_{session}_curr_vol, 20)",
             "settings": S_IND, "hypothesis": f"news {session} volume std_dev INDUSTRY"},
            {"name": f"nws_{session}_ratio_IND",
             "expr": f"rank(-nws12_{session}_vol_ratio)", "settings": S_IND,
             "hypothesis": f"news {session} volume ratio rank INDUSTRY"},
        ]
    # nws12 vol_ratio ts patterns
    alphas += [
        {"name": "nws_main_volratio_ts20_IND", "expr": "-ts_std_dev(nws12_mainz_vol_ratio, 20)",
         "settings": S_IND, "hypothesis": "news main vol_ratio std 20d INDUSTRY"},
        {"name": "nws_main_volratio_ts20_SUB", "expr": "-ts_std_dev(nws12_mainz_vol_ratio, 20)",
         "settings": S_SUB, "hypothesis": "news main vol_ratio std 20d SUBINDUSTRY"},
    ]

    # BLOCK 5: OI/equity ts_rank new ratio variations with ts_rank 126
    alphas += [
        # Cash flow variations
        {"name": "cfo_equity_ts126_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(cash_flow_from_operations/equity, 126), sector)",
         "hypothesis": "CFO/equity ts_rank 126 sector"},
        {"name": "cfo_equity_ts126_IND", "settings": S_NONE,
         "expr": "group_rank(ts_rank(cash_flow_from_operations/equity, 126), industry)",
         "hypothesis": "CFO/equity ts_rank 126 industry"},
        # Sales-based
        {"name": "oi_sales_ts126_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/sales, 126), sector)",
         "hypothesis": "OI/sales ts_rank 126 sector (operating margin momentum)"},
        {"name": "oi_sales_ts126_IND", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/sales, 126), industry)",
         "hypothesis": "OI/sales ts_rank 126 industry"},
        # Liabilities-based
        {"name": "oi_liab_ts126_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/liabilities, 126), sector)",
         "hypothesis": "OI/liabilities ts_rank 126 sector"},
        # Invested capital
        {"name": "oi_ic_ts126_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/invested_capital, 126), sector)",
         "hypothesis": "OI/invested_capital (ROIC) ts_rank 126 sector"},
        {"name": "oi_ic_ts126_IND", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/invested_capital, 126), industry)",
         "hypothesis": "ROIC ts_rank 126 industry"},
        # Different windows on OI/equity
        {"name": "oi_eq_ts200_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/equity, 200), sector)",
         "hypothesis": "OI/equity ts_rank 200d sector"},
        {"name": "oi_eq_ts300_SEC", "settings": S_NONE,
         "expr": "group_rank(ts_rank(operating_income/equity, 300), sector)",
         "hypothesis": "OI/equity ts_rank 300d sector"},
    ]

    # BLOCK 6: pcr_oi with truncation=0.05 fix
    for days in [20, 30, 60, 90]:
        field = f"pcr_oi_{days}"
        alphas += [
            {"name": f"pcr_{days}d_IND05", "expr": f"rank(-{field})",
             "settings": S_IND05, "hypothesis": f"low put/call ratio {days}d INDUSTRY trunc=0.05"},
        ]
    alphas.append({"name": "pcr_all_IND05", "expr": "rank(-pcr_oi_all)",
                   "settings": S_IND05, "hypothesis": "low all-term put/call ratio INDUSTRY trunc=0.05"})

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
    print(f"BATCH 12 COMPLETE: {len(results)} tested, {len(passed)} passing, {errors} errors")
    print(f"Passing: {passed}")
    print(f"Fail reasons: {fail_reasons}")

if __name__ == '__main__':
    main()
