"""
Batch 6: Pre-built quality scores (fscore), RavenPack sentiment (rp_css),
put/call ratio (pcr_oi), and extended snt1 signals.
HIGHEST PRIORITY - these are premium pre-computed signals.
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

# Settings
S_MKT  = {"decay":4,"neutralization":"MARKET","truncation":0.05,"language":"FASTEXPR",
           "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
           "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_MKT0 = {"decay":0,"neutralization":"MARKET","truncation":0.08,"language":"FASTEXPR",
           "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
           "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND  = {"decay":0,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_SUB  = {"decay":0,"neutralization":"SUBINDUSTRY","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_NONE = {"decay":0,"neutralization":"NONE","truncation":0.08,"language":"FASTEXPR",
          "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
          "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND_D2 = {"decay":2,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
            "instrumentType":"EQUITY","region":"USA","universe":"TOP3000","delay":1,
            "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND_1K = {"decay":2,"neutralization":"INDUSTRY","truncation":0.08,"language":"FASTEXPR",
            "instrumentType":"EQUITY","region":"USA","universe":"TOP1000","delay":1,
            "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}
S_IND1K = S_IND_1K  # alias
S_SEC_200 = {"decay":0,"neutralization":"SECTOR","truncation":0.08,"language":"FASTEXPR",
             "instrumentType":"EQUITY","region":"USA","universe":"TOP200","delay":1,
             "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

ALPHAS_BATCH6 = [
    # ============================================================
    # BLOCK 0: RavenPack CSS — moved to TOP (highest expected alpha)
    # fscore_total known weak (S=0.68 sector grp). Test rp_css first.
    # ============================================================
    ("ts_rank(rp_css_earnings, 20)",       S_IND,  "rp earnings news 20d [TOP]"),
    ("ts_rank(rp_css_credit_ratings, 63)", S_IND,  "rp credit ratings 63d [TOP]"),
    ("ts_rank(rp_css_insider, 20)",        S_MKT0, "rp insider news 20d [TOP]"),
    ("group_rank(ts_rank(rp_css_earnings, 20), sector)", S_NONE, "rp earnings grp sec [TOP]"),
    ("rank(-pcr_oi_30)",  S_IND, "low PCR 30d contrarian [TOP]"),
    ("rank(-pcr_oi_120)", S_IND, "low PCR 120d contrarian [TOP]"),
    ("group_rank(-pcr_oi_30, sector)", S_NONE, "low PCR 30d grp sec [TOP]"),
    ("rank(snt1_d1_stockrank)", S_IND1K, "snt1 stock rank [TOP]"),
    ("ts_rank(snt1_d1_earningsrevision, 63)", S_IND1K, "snt1 eps revision [TOP]"),
    # ============================================================
    # BLOCK 1: fscore_* fields
    # fscore_total: MARKET S=-0.30, grp_sector S=0.68 — both fail
    # Try BFL variant and sub-scores (may differ significantly)
    # ============================================================
    ("rank(fscore_bfl_total)", S_MKT,  "fscore BFL total MARKET"),
    ("rank(fscore_bfl_total)", S_IND,  "fscore BFL total IND"),
    ("group_rank(fscore_bfl_total, sector)",   S_NONE, "fscore BFL grp sector"),
    ("group_rank(fscore_bfl_total, industry)", S_NONE, "fscore BFL grp ind"),
    ("rank(fscore_total)", S_MKT,  "fscore total MARKET"),
    ("group_rank(fscore_total, sector)",      S_NONE, "fscore total grp sector"),

    ("rank(fscore_profitability)",   S_IND, "fscore profitability IND"),
    ("rank(fscore_quality)",         S_IND, "fscore quality IND"),
    ("rank(fscore_value)",           S_IND, "fscore value IND"),
    ("rank(fscore_momentum)",        S_IND, "fscore momentum IND"),
    ("rank(fscore_growth)",          S_IND, "fscore growth IND"),
    ("rank(fscore_bfl_profitability)", S_IND, "fscore BFL profitability"),
    ("rank(fscore_bfl_quality)",     S_IND, "fscore BFL quality"),
    ("rank(fscore_bfl_value)",       S_IND, "fscore BFL value"),
    ("rank(fscore_bfl_momentum)",    S_IND, "fscore BFL momentum"),
    ("rank(fscore_bfl_growth)",      S_IND, "fscore BFL growth"),
    ("rank(fscore_surface)",         S_IND, "fscore surface IND"),
    ("rank(fscore_bfl_surface)",     S_IND, "fscore BFL surface"),

    # fscore combinations
    ("rank(fscore_total + fscore_momentum)", S_IND, "fscore total+momentum"),
    ("rank(fscore_quality + fscore_value)",  S_IND, "fscore quality+value"),
    ("group_rank(fscore_quality + fscore_value, sector)", S_NONE, "fscore Q+V grp"),

    # ts_rank on fscore (to get momentum of quality)
    ("group_rank(ts_rank(fscore_total, 63), sector)",    S_NONE, "fscore total ts-rank 63"),
    ("group_rank(ts_rank(fscore_total, 126), sector)",   S_NONE, "fscore total ts-rank 126"),
    ("group_rank(ts_rank(fscore_bfl_total, 126), sector)", S_NONE, "fscore BFL ts-rank 126"),

    # ============================================================
    # BLOCK 2: RavenPack CSS news sentiment (event-driven signals)
    # ============================================================
    ("ts_rank(rp_css_earnings, 20)",      S_IND,   "rp earnings news 20d"),
    ("ts_rank(rp_css_earnings, 63)",      S_IND,   "rp earnings news 63d"),
    ("ts_rank(rp_css_equity, 20)",        S_IND,   "rp equity news 20d"),
    ("ts_rank(rp_css_credit_ratings, 63)",S_IND,   "rp credit ratings 63d"),
    ("ts_rank(rp_css_insider, 20)",       S_MKT0,  "rp insider news 20d"),
    ("ts_rank(rp_css_mna, 20)",           S_IND,   "rp M&A news 20d"),
    ("ts_rank(rp_css_revenue, 20)",       S_IND,   "rp revenue news 20d"),
    ("ts_rank(rp_css_ratings, 63)",       S_IND,   "rp analyst ratings 63d"),
    ("ts_rank(rp_css_dividends, 63)",     S_IND,   "rp dividend news 63d"),
    ("ts_rank(rp_css_price, 10)",         S_IND,   "rp price news 10d"),
    ("ts_rank(rp_css_product, 20)",       S_IND,   "rp product news 20d"),
    ("ts_rank(rp_css_legal, 63)",         S_IND,   "rp legal news 63d"),
    ("ts_rank(rp_css_business, 20)",      S_IND,   "rp business news 20d"),

    # Composite CSS signals
    ("ts_rank(rp_css_earnings + rp_css_revenue, 20)", S_IND, "rp earnings+revenue combo"),
    ("group_rank(ts_rank(rp_css_earnings, 20), sector)", S_NONE, "rp earnings grp sector"),
    ("group_rank(rp_css_earnings + rp_css_revenue, sector)", S_NONE, "rp E+R grp sector"),

    # ============================================================
    # BLOCK 3: Put/call ratio (contrarian signals)
    # ============================================================
    ("rank(-pcr_oi_30)",   S_IND, "low PCR 30d contrarian"),
    ("rank(-pcr_oi_60)",   S_IND, "low PCR 60d contrarian"),
    ("rank(-pcr_oi_120)",  S_IND, "low PCR 120d contrarian"),
    ("group_rank(-pcr_oi_30, sector)",  S_NONE, "low PCR 30d grp sector"),
    ("group_rank(-pcr_oi_120, sector)", S_NONE, "low PCR 120d grp sector"),
    ("ts_rank(-pcr_oi_30, 63)",  S_IND, "pcr momentum 63d"),
    ("ts_rank(-pcr_oi_120, 126)", S_IND, "pcr momentum 126d"),
    # PCR term structure: 30d vs 120d
    ("rank(pcr_oi_120 - pcr_oi_30)", S_IND, "PCR term structure slope"),

    # ============================================================
    # BLOCK 4: Extended snt1 signals
    # ============================================================
    ("ts_rank(snt1_d1_earningsrevision, 63)", S_IND_1K, "earnings revision 63d"),
    ("ts_rank(snt1_d1_netearningsrevision, 63)", S_IND_1K, "net EPS revision 63d"),
    ("ts_rank(snt1_d1_earningstorpedo, 20)",     S_IND_1K, "earnings torpedo 20d"),
    ("rank(snt1_d1_stockrank)",         S_IND_1K, "snt1 stock rank"),
    ("rank(snt1_d1_fundamentalfocusrank)", S_IND_1K, "fundamental focus rank"),
    ("rank(snt1_d1_dynamicfocusrank)",    S_IND_1K, "dynamic focus rank"),
    ("ts_rank(snt1_d1_uptargetpercent, 63)",  S_IND_1K, "price target upgrade %"),
    ("ts_rank(snt1_d1_nettargetpercent, 63)", S_IND_1K, "net target pct 63d"),
    ("ts_rank(snt1_d1_netrecpercent, 63)",    S_IND_1K, "net rec % 63d"),
    ("ts_rank(snt1_d1_longtermepsgrowthest, 126)", S_IND_1K, "LT eps growth est"),

    # ============================================================
    # BLOCK 5: Options volatility term structure alphas
    # ============================================================
    # Vol term structure: near vs far implied vol
    ("implied_volatility_call_30/implied_volatility_call_120", S_SEC_200, "IV term struct 30/120"),
    ("implied_volatility_call_10/implied_volatility_call_120", S_SEC_200, "IV term struct 10/120"),
    ("implied_volatility_call_120/implied_volatility_call_360", S_SEC_200, "IV term struct 120/360"),
    # Options breakeven momentum
    ("ts_rank(call_breakeven_120, 63)", S_SEC_200, "call BE 120d ts-rank"),
    ("ts_rank(put_breakeven_120, 63)",  S_SEC_200, "put BE 120d ts-rank"),
    # Forward price vs close
    ("forward_price_120/close - 1", S_IND, "forward premium 120d"),
    ("ts_rank(forward_price_120/close, 63)", S_IND, "forward premium ts-rank"),
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
    final_path = ROOT / f'results/batch6_{timestamp}.json'
    partial_path = ROOT / f'results/batch6_partial_{timestamp}.json'

    tested = load_tested_exprs()
    print(f"Previously tested: {len(tested)} (will skip duplicates)")

    results = []
    passing = []
    failing_reasons = {}
    errors = 0
    field_errors = {}

    for i, (expr, settings, name) in enumerate(ALPHAS_BATCH6):
        if expr in tested:
            print(f"[{i+1:02d}/{len(ALPHAS_BATCH6)}] SKIP: {name}")
            continue

        print(f"[{i+1:02d}/{len(ALPHAS_BATCH6)}] {name}")
        print(f"         {expr[:80]}")

        try:
            result = c.simulate_and_get_alpha(expr, settings)
            if result.get('error'):
                if '400' in str(result.get('error', '')):
                    print(f"         FIELD_ERROR: field unavailable")
                    # Detect which field caused 400
                    import re
                    for m in re.finditer(r'\b([a-z][a-z0-9_]+)\b', expr):
                        w = m.group(1)
                        if '_' in w and not any(o in w for o in ['ts_rank','ts_zscore','ts_std','ts_corr','ts_delta','ts_decay','group_rank','group_mean','group_zscore','signed_power','ts_backfill']):
                            field_errors[w] = field_errors.get(w, 0) + 1
                else:
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
            print(f"         {status}  Sharpe={sharpe:.3f} Fitness={fitness:.3f} TO={to_pct:.1f}%")

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
            print(f"  [Saved: {len(results)} results]")

        time.sleep(1)

    final_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')

    print()
    print("=" * 70)
    print("BATCH 6 COMPLETE")
    print("=" * 70)
    print(f"Tested: {len(results)}  PASS: {len(passing)}  FAIL: {sum(failing_reasons.values())}  ERROR: {errors}")
    if field_errors:
        top_fe = sorted(field_errors.items(), key=lambda x: -x[1])[:10]
        print(f"\nUnavailable fields (400): {dict(top_fe)}")
    if failing_reasons:
        print("\nFail reasons:")
        for k, v in sorted(failing_reasons.items(), key=lambda x: -x[1]):
            print(f"  [{v}x] {k}")
    if passing:
        print(f"\nTOP PASSING (by Fitness):")
        print(f"  {'Name':<40} {'Sharpe':>7} {'Fitness':>7} {'TO%':>6}")
        print("  " + "-" * 60)
        for p in sorted(passing, key=lambda x: -x['fitness'])[:20]:
            print(f"  {p['name']:<40} {p['sharpe']:>7.3f} {p['fitness']:>7.3f} {p['to']:>6.1f}%")
    print(f"\nSaved: {final_path}")


if __name__ == '__main__':
    run_batch()
