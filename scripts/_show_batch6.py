import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = r'D:\codeproject\worldquantAlpha-dev\results'

# Load all results files to build complete lookup
all_items = {}
import os
for fname in os.listdir(ROOT):
    if fname.endswith('.json'):
        try:
            data = json.loads(open(os.path.join(ROOT, fname), encoding='utf-8').read())
            if isinstance(data, list):
                for item in data:
                    if item and item.get('expr'):
                        all_items[item['expr']] = item
        except Exception:
            pass

# All batch6 expressions in order
ALPHAS_BATCH6 = [
    # BLOCK 0
    ("ts_rank(rp_css_earnings, 20)",       "IND",  "rp earnings news 20d [TOP]"),
    ("ts_rank(rp_css_credit_ratings, 63)", "IND",  "rp credit ratings 63d [TOP]"),
    ("ts_rank(rp_css_insider, 20)",        "MKT0", "rp insider news 20d [TOP]"),
    ("group_rank(ts_rank(rp_css_earnings, 20), sector)", "NONE", "rp earnings grp sec [TOP]"),
    ("rank(-pcr_oi_30)",  "IND", "low PCR 30d contrarian [TOP]"),
    ("rank(-pcr_oi_120)", "IND", "low PCR 120d contrarian [TOP]"),
    ("group_rank(-pcr_oi_30, sector)", "NONE", "low PCR 30d grp sec [TOP]"),
    ("rank(snt1_d1_stockrank)", "IND1K", "snt1 stock rank [TOP]"),
    ("ts_rank(snt1_d1_earningsrevision, 63)", "IND1K", "snt1 eps revision [TOP]"),
    # BLOCK 1
    ("rank(fscore_bfl_total)", "MKT",  "fscore BFL total MARKET"),
    ("rank(fscore_bfl_total)", "IND",  "fscore BFL total IND"),
    ("group_rank(fscore_bfl_total, sector)",   "NONE", "fscore BFL grp sector"),
    ("group_rank(fscore_bfl_total, industry)", "NONE", "fscore BFL grp ind"),
    ("rank(fscore_total)", "MKT",  "fscore total MARKET"),
    ("group_rank(fscore_total, sector)",      "NONE", "fscore total grp sector"),
    ("rank(fscore_profitability)",   "IND", "fscore profitability IND"),
    ("rank(fscore_quality)",         "IND", "fscore quality IND"),
    ("rank(fscore_value)",           "IND", "fscore value IND"),
    ("rank(fscore_momentum)",        "IND", "fscore momentum IND"),
    ("rank(fscore_growth)",          "IND", "fscore growth IND"),
    ("rank(fscore_bfl_profitability)", "IND", "fscore BFL profitability"),
    ("rank(fscore_bfl_quality)",     "IND", "fscore BFL quality"),
    ("rank(fscore_bfl_value)",       "IND", "fscore BFL value"),
    ("rank(fscore_bfl_momentum)",    "IND", "fscore BFL momentum"),
    ("rank(fscore_bfl_growth)",      "IND", "fscore BFL growth"),
    ("rank(fscore_surface)",         "IND", "fscore surface IND"),
    ("rank(fscore_bfl_surface)",     "IND", "fscore BFL surface"),
    ("rank(fscore_total + fscore_momentum)", "IND", "fscore total+momentum"),
    ("rank(fscore_quality + fscore_value)",  "IND", "fscore quality+value"),
    ("group_rank(fscore_quality + fscore_value, sector)", "NONE", "fscore Q+V grp"),
    ("group_rank(ts_rank(fscore_total, 63), sector)",    "NONE", "fscore total ts-rank 63"),
    ("group_rank(ts_rank(fscore_total, 126), sector)",   "NONE", "fscore total ts-rank 126"),
    ("group_rank(ts_rank(fscore_bfl_total, 126), sector)", "NONE", "fscore BFL ts-rank 126"),
    # BLOCK 2
    ("ts_rank(rp_css_earnings, 20)",      "IND",   "rp earnings news 20d"),
    ("ts_rank(rp_css_earnings, 63)",      "IND",   "rp earnings news 63d"),
    ("ts_rank(rp_css_equity, 20)",        "IND",   "rp equity news 20d"),
    ("ts_rank(rp_css_credit_ratings, 63)","IND",   "rp credit ratings 63d"),
    ("ts_rank(rp_css_insider, 20)",       "MKT0",  "rp insider news 20d"),
    ("ts_rank(rp_css_mna, 20)",           "IND",   "rp M&A news 20d"),
    ("ts_rank(rp_css_revenue, 20)",       "IND",   "rp revenue news 20d"),
    ("ts_rank(rp_css_ratings, 63)",       "IND",   "rp analyst ratings 63d"),
    ("ts_rank(rp_css_dividends, 63)",     "IND",   "rp dividend news 63d"),
    ("ts_rank(rp_css_price, 10)",         "IND",   "rp price news 10d"),
    ("ts_rank(rp_css_product, 20)",       "IND",   "rp product news 20d"),
    ("ts_rank(rp_css_legal, 63)",         "IND",   "rp legal news 63d"),
    ("ts_rank(rp_css_business, 20)",      "IND",   "rp business news 20d"),
    ("ts_rank(rp_css_earnings + rp_css_revenue, 20)", "IND", "rp earnings+revenue combo"),
    ("group_rank(ts_rank(rp_css_earnings, 20), sector)", "NONE", "rp earnings grp sector"),
    ("group_rank(rp_css_earnings + rp_css_revenue, sector)", "NONE", "rp E+R grp sector"),
    # BLOCK 3
    ("rank(-pcr_oi_30)",   "IND", "low PCR 30d contrarian"),
    ("rank(-pcr_oi_60)",   "IND", "low PCR 60d contrarian"),
    ("rank(-pcr_oi_120)",  "IND", "low PCR 120d contrarian"),
    ("group_rank(-pcr_oi_30, sector)",  "NONE", "low PCR 30d grp sector"),
    ("group_rank(-pcr_oi_120, sector)", "NONE", "low PCR 120d grp sector"),
    ("ts_rank(-pcr_oi_30, 63)",  "IND", "pcr momentum 63d"),
    ("ts_rank(-pcr_oi_120, 126)", "IND", "pcr momentum 126d"),
    ("rank(pcr_oi_120 - pcr_oi_30)", "IND", "PCR term structure slope"),
    # BLOCK 4
    ("ts_rank(snt1_d1_earningsrevision, 63)", "IND1K", "earnings revision 63d"),
    ("ts_rank(snt1_d1_netearningsrevision, 63)", "IND1K", "net EPS revision 63d"),
    ("ts_rank(snt1_d1_earningstorpedo, 20)",     "IND1K", "earnings torpedo 20d"),
    ("rank(snt1_d1_stockrank)",         "IND1K", "snt1 stock rank"),
    ("rank(snt1_d1_fundamentalfocusrank)", "IND1K", "fundamental focus rank"),
    ("rank(snt1_d1_dynamicfocusrank)",    "IND1K", "dynamic focus rank"),
    ("ts_rank(snt1_d1_uptargetpercent, 63)",  "IND1K", "price target upgrade %"),
    ("ts_rank(snt1_d1_nettargetpercent, 63)", "IND1K", "net target pct 63d"),
    ("ts_rank(snt1_d1_netrecpercent, 63)",    "IND1K", "net rec % 63d"),
    ("ts_rank(snt1_d1_longtermepsgrowthest, 126)", "IND1K", "LT eps growth est"),
    # BLOCK 5
    ("implied_volatility_call_30/implied_volatility_call_120", "SEC200", "IV term struct 30/120"),
    ("implied_volatility_call_10/implied_volatility_call_120", "SEC200", "IV term struct 10/120"),
    ("implied_volatility_call_120/implied_volatility_call_360", "SEC200", "IV term struct 120/360"),
    ("ts_rank(call_breakeven_120, 63)", "SEC200", "call BE 120d ts-rank"),
    ("ts_rank(put_breakeven_120, 63)",  "SEC200", "put BE 120d ts-rank"),
    ("forward_price_120/close - 1", "IND", "forward premium 120d"),
    ("ts_rank(forward_price_120/close, 63)", "IND", "forward premium ts-rank"),
]

print(f"Total unique expressions in batch6: {len(set(e for e,_,_ in ALPHAS_BATCH6))}")
print(f"Total records across all result files: {len(all_items)}")
print()

seen_exprs = set()
rows = []
for expr, sett, name in ALPHAS_BATCH6:
    if expr in seen_exprs:
        continue  # skip true duplicates (same expr, tested once)
    seen_exprs.add(expr)
    item = all_items.get(expr)
    if not item:
        rows.append((name, expr, sett, "NOT_FOUND", 0, 0, 0, ""))
        continue
    alpha = item.get('alpha', {}) or {}
    err = alpha.get('error', '')
    if err:
        rows.append((name, expr, sett, "FIELD_ERROR", 0, 0, 0, str(err)[:60]))
        continue
    is_d = alpha.get('is', {}) or {}
    sharpe = is_d.get('sharpe', 0) or 0
    fitness = is_d.get('fitness', 0) or 0
    to_pct = (is_d.get('turnover', 0) or 0) * 100
    checks = is_d.get('checks', [])
    failed = [ch['name'] for ch in checks if ch.get('result') == 'FAIL']
    status = 'PASS' if not failed else 'FAIL[' + ','.join(failed[:2]) + ']'
    rows.append((name, expr, sett, status, sharpe, fitness, to_pct, ""))

# Print table
print(f"{'#':<3} {'Name':<42} {'Neut':<6} {'Status':<32} {'Sharpe':>7} {'Fitness':>7} {'TO%':>6}")
print('-' * 105)
blocks = {0: "BLOCK 0: RavenPack CSS & PCR & snt1 [TOP PRIORITY]",
          9: "BLOCK 1: fscore_* fields",
          33: "BLOCK 2: RavenPack CSS full suite",
          49: "BLOCK 3: Put/call ratio",
          57: "BLOCK 4: snt1 analyst sentiment (TOP1000)",
          67: "BLOCK 5: Options vol / breakeven (TOP200)"}

idx = 0
for i, row in enumerate(rows):
    name, expr, sett, status, sharpe, fitness, to_pct, err = row
    # block header
    actual_i = i  # approximate
    hdr = blocks.get(i)
    if hdr:
        print(f"\n  [{hdr}]")
    errstr = f" ({err})" if err else ""
    print(f"{i+1:<3} {name:<42} {sett:<6} {status:<32} {sharpe:>7.3f} {fitness:>7.3f} {to_pct:>6.1f}%{errstr}")
    idx += 1

print()
print("=" * 105)
# Summary
passing = [r for r in rows if r[3] == 'PASS']
field_err = [r for r in rows if r[3] == 'FIELD_ERROR']
not_found = [r for r in rows if r[3] == 'NOT_FOUND']
failing = [r for r in rows if r[3].startswith('FAIL[')]

print(f"SUMMARY: Total={len(rows)}  PASS={len(passing)}  FAIL={len(failing)}  FIELD_ERROR={len(field_err)}  NOT_FOUND={len(not_found)}")
print()

if field_err:
    print("UNAVAILABLE FIELDS (HTTP 400):")
    for r in field_err:
        print(f"  {r[0]}: {r[7]}")
    print()

if passing:
    print("PASSING ALPHAS (Sharpe>=1.25, Fitness>=1.0):")
    print(f"  {'Name':<42} {'Sharpe':>7} {'Fitness':>7} {'TO%':>6}")
    print("  " + "-"*64)
    for r in sorted(passing, key=lambda x: -x[5]):
        print(f"  {r[0]:<42} {r[4]:>7.3f} {r[5]:>7.3f} {r[6]:>6.1f}%")
