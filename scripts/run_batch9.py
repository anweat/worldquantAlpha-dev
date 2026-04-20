"""
Batch 9: Follow-up on two major near-misses from batch 6b:
1. group_rank(fscore_bfl_total, sector): S=1.04, F=1.93 → FAIL only LOW_SHARPE (+0.21 needed)
2. rp_css_equity: S=1.13, F=0.17, TO=162% → too high turnover, needs decay
Strategy:
- fscore_bfl: combine with other signals, try TOP1000, multi-factor combos
- rp_css: add heavy decay to cut turnover to <70%
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

def S(neut="NONE", decay=0, trunc=0.08, universe="TOP3000"):
    return {"decay":decay,"neutralization":neut,"truncation":trunc,"language":"FASTEXPR",
            "instrumentType":"EQUITY","region":"USA","universe":universe,"delay":1,
            "pasteurization":"ON","nanHandling":"OFF","unitHandling":"VERIFY"}

ALPHAS = [
    # ============================================================
    # BLOCK 1: fscore_bfl_total Sharpe boost strategies
    # Current best: group_rank(fscore_bfl_total, sector) → S=1.04, F=1.93
    # Need: S>=1.25. Try TOP1000, sub-scores combo, multi-factor
    # ============================================================
    # TOP1000 universe — smaller, more concentrated, potentially higher Sharpe
    ("group_rank(fscore_bfl_total, sector)",   S("NONE",0,.08,"TOP1000"), "fscore_bfl grp sec TOP1K"),
    ("group_rank(fscore_bfl_total, industry)", S("NONE",0,.08,"TOP1000"), "fscore_bfl grp ind TOP1K"),
    ("group_rank(ts_rank(fscore_bfl_total, 126), sector)",   S("NONE",0,.08,"TOP1000"), "fscore_bfl ts126 TOP1K"),
    ("group_rank(ts_rank(fscore_bfl_total, 63), sector)",    S("NONE",0,.08,"TOP1000"), "fscore_bfl ts63 TOP1K"),
    ("group_rank(ts_rank(fscore_bfl_total, 252), sector)",   S("NONE",0,.08,"TOP1000"), "fscore_bfl ts252 TOP1K"),

    # TOP500
    ("group_rank(fscore_bfl_total, sector)",   S("NONE",0,.08,"TOP500"), "fscore_bfl grp sec TOP500"),
    ("group_rank(ts_rank(fscore_bfl_total, 126), sector)", S("NONE",0,.08,"TOP500"), "fscore_bfl ts126 TOP500"),

    # Multi-factor: fscore_bfl + proven winner (-liabilities/assets)
    ("group_rank(fscore_bfl_total, sector) + rank(-liabilities/assets)",
     S("NONE",0,.08,"TOP3000"), "fscore_bfl + leverage TOP3K"),
    ("group_rank(fscore_bfl_total, sector) + rank(-liabilities/assets)",
     S("NONE",0,.08,"TOP1000"), "fscore_bfl + leverage TOP1K"),
    # Weighted combo (fscore heavier)
    ("2*group_rank(fscore_bfl_total, sector) + rank(-liabilities/assets)",
     S("NONE",0,.08,"TOP3000"), "2x fscore_bfl + lev"),
    ("group_rank(fscore_bfl_total + fscore_bfl_profitability, sector)",
     S("NONE",0,.08,"TOP3000"), "fscore_bfl total+profit"),
    ("group_rank(fscore_bfl_total + fscore_bfl_quality, sector)",
     S("NONE",0,.08,"TOP3000"), "fscore_bfl total+quality"),
    ("group_rank(fscore_bfl_total + fscore_bfl_value, sector)",
     S("NONE",0,.08,"TOP3000"), "fscore_bfl total+value"),
    ("group_rank(fscore_bfl_total + fscore_bfl_momentum, sector)",
     S("NONE",0,.08,"TOP3000"), "fscore_bfl total+momentum"),
    ("group_rank(fscore_bfl_total * fscore_bfl_profitability, sector)",
     S("NONE",0,.08,"TOP3000"), "fscore_bfl total x profit"),

    # ts_rank window sweep (current 126 best, try others)
    ("group_rank(ts_rank(fscore_bfl_total, 21), sector)",  S("NONE"), "fscore_bfl ts21 sec"),
    ("group_rank(ts_rank(fscore_bfl_total, 42), sector)",  S("NONE"), "fscore_bfl ts42 sec"),
    ("group_rank(ts_rank(fscore_bfl_total, 63), sector)",  S("NONE"), "fscore_bfl ts63 sec"),
    ("group_rank(ts_rank(fscore_bfl_total, 252), sector)", S("NONE"), "fscore_bfl ts252 sec"),
    ("group_rank(ts_rank(fscore_bfl_total, 504), sector)", S("NONE"), "fscore_bfl ts504 sec"),

    # fscore_bfl sub-scores individually
    ("group_rank(fscore_bfl_profitability, sector)", S("NONE"), "fscore_bfl profit grp sec"),
    ("group_rank(fscore_bfl_quality, sector)",       S("NONE"), "fscore_bfl quality grp sec"),
    ("group_rank(fscore_bfl_value, sector)",         S("NONE"), "fscore_bfl value grp sec"),
    ("group_rank(fscore_bfl_momentum, sector)",      S("NONE"), "fscore_bfl momentum grp sec"),
    ("group_rank(fscore_bfl_growth, sector)",        S("NONE"), "fscore_bfl growth grp sec"),
    ("group_rank(fscore_bfl_surface, sector)",       S("NONE"), "fscore_bfl surface grp sec"),
    ("group_rank(fscore_bfl_surface_accel, sector)", S("NONE"), "fscore_bfl surface_accel grp"),

    # fscore_bfl combined with ts_rank(OI/equity, 126) — the proven winner
    ("group_rank(fscore_bfl_total, sector) + group_rank(ts_rank(operating_income/equity, 126), sector)",
     S("NONE"), "fscore_bfl + OI/eq ts126"),
    ("group_rank(fscore_bfl_total + ts_rank(operating_income/equity, 126), sector)",
     S("NONE"), "fscore_bfl + OI/eq ts126 combined"),

    # ============================================================
    # BLOCK 2: rp_css signals with heavy decay to fix TO=162%
    # Need decay=8-12 to bring TO from 162% to <70%
    # ============================================================
    ("ts_rank(rp_css_equity, 20)",    S("INDUSTRY",8,.05,"TOP3000"),  "rp equity IND d8"),
    ("ts_rank(rp_css_equity, 20)",    S("INDUSTRY",10,.05,"TOP3000"), "rp equity IND d10"),
    ("ts_rank(rp_css_equity, 20)",    S("MARKET",8,.05,"TOP3000"),    "rp equity MKT d8"),
    ("ts_rank(rp_css_earnings, 20)",  S("INDUSTRY",8,.05,"TOP3000"),  "rp earnings IND d8"),
    ("ts_rank(rp_css_earnings, 20)",  S("INDUSTRY",10,.05,"TOP3000"), "rp earnings IND d10"),
    ("ts_rank(rp_css_earnings, 63)",  S("INDUSTRY",5,.08,"TOP3000"),  "rp earnings 63d IND d5"),
    ("ts_rank(rp_css_insider, 20)",   S("MARKET",8,.05,"TOP3000"),    "rp insider MKT d8"),
    ("ts_rank(rp_css_credit_ratings, 63)", S("INDUSTRY",5,.08,"TOP3000"), "rp credit 63d IND d5"),
    ("ts_rank(rp_css_mna, 20)",       S("INDUSTRY",8,.05,"TOP3000"),  "rp M&A IND d8"),
    ("ts_rank(rp_css_ratings, 63)",   S("INDUSTRY",5,.08,"TOP3000"),  "rp ratings 63d IND d5"),
    # rp_css group_rank with decay
    ("group_rank(ts_rank(rp_css_earnings, 20), sector)", S("NONE",8,.05), "rp earnings grp d8"),
    ("group_rank(ts_rank(rp_css_equity, 20), sector)",   S("NONE",8,.05), "rp equity grp d8"),
    ("group_rank(ts_rank(rp_css_equity, 20), sector)",   S("NONE",10,.05), "rp equity grp d10"),

    # ============================================================
    # BLOCK 3: pcr_oi Sharpe boost (S=0.74, F=1.25 near-miss)
    # ============================================================
    ("group_rank(-pcr_oi_30, sector)",  S("NONE",0,.08,"TOP1000"), "low PCR 30d grp TOP1K"),
    ("group_rank(-pcr_oi_60, sector)",  S("NONE",0,.08,"TOP3000"), "low PCR 60d grp sec"),
    ("group_rank(-pcr_oi_120, sector)", S("NONE",0,.08,"TOP3000"), "low PCR 120d grp sec"),
    ("group_rank(-pcr_oi_30, sector) + rank(-liabilities/assets)",
     S("NONE"), "PCR + leverage combo"),
    ("group_rank(-pcr_oi_30, sector) + group_rank(fscore_bfl_total, sector)",
     S("NONE"), "PCR + fscore_bfl combo"),
    # ts_rank on pcr (momentum of put/call)
    ("group_rank(ts_rank(-pcr_oi_30, 63), sector)",  S("NONE"), "PCR ts-rank 63 sec"),
    ("group_rank(ts_rank(-pcr_oi_30, 126), sector)", S("NONE"), "PCR ts-rank 126 sec"),
    ("group_rank(ts_rank(-pcr_oi_120, 63), sector)", S("NONE"), "PCR 120 ts-rank 63 sec"),
]


def load_tested_exprs():
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
            headers={"Accept":"application/json;version=2.0","Content-Type":"application/json"}
        )
        return r.status_code
    return None


def run_batch():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path   = ROOT / f'results/batch9_{timestamp}.json'
    partial_path = ROOT / f'results/batch9_partial_{timestamp}.json'

    tested = load_tested_exprs()
    print(f"Real results (skipping): {len(tested)}")

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
                results.append({'name':name,'expr':expr,'settings':settings,'alpha':result})
                continue

            is_d   = result.get('is', {}) or {}
            checks = is_d.get('checks', [])
            sharpe = is_d.get('sharpe', 0) or 0
            fitness= is_d.get('fitness', 0) or 0
            to_pct = (is_d.get('turnover', 0) or 0) * 100
            alpha_id = result.get('id', '')

            failed = [ch['name'] for ch in checks if ch.get('result') == 'FAIL']
            status = "✅ PASS" if not failed else f"FAIL[{','.join(failed[:2])}]"
            print(f"         {status}  S={sharpe:.3f} F={fitness:.3f} TO={to_pct:.1f}%")

            if not failed:
                passing.append({'name':name,'expr':expr,'sharpe':sharpe,'fitness':fitness,'to':to_pct})
                sub_status = maybe_submit(alpha_id, checks)
                if sub_status:
                    print(f"         ✅ SUBMITTED → HTTP {sub_status}")
            else:
                key = '+'.join(sorted(failed))
                failing_reasons[key] = failing_reasons.get(key, 0) + 1

            results.append({'name':name,'expr':expr,'settings':settings,'alpha':result})
            tested.add(expr)

        except Exception as e:
            print(f"         EXCEPTION: {e}")
            errors += 1
            results.append({'name':name,'expr':expr,'settings':settings,'alpha':{'error':str(e)}})

        if len(results) % 10 == 0:
            partial_path.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
        time.sleep(1)

    final_path.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    print()
    print("=" * 70)
    print("BATCH 9 COMPLETE")
    print("=" * 70)
    print(f"Tested:{len(results)} PASS:{len(passing)} FAIL:{sum(failing_reasons.values())} ERR:{errors}")
    if failing_reasons:
        print("\nFail reasons:")
        for k,v in sorted(failing_reasons.items(),key=lambda x:-x[1]):
            print(f"  [{v}x] {k}")
    if passing:
        print("\n🏆 PASSING:")
        for p in sorted(passing,key=lambda x:-x['fitness']):
            print(f"  {p['name']:<45} S={p['sharpe']:.3f} F={p['fitness']:.3f} TO={p['to']:.1f}%")
    else:
        print("\nTop 10 near-misses by Sharpe:")
        near = [(r.get('alpha',{}).get('is',{}) or {}, r.get('name',''), r.get('expr',''))
                for r in results if (r.get('alpha',{}).get('is',{}) or {})]
        near.sort(key=lambda x:-(x[0].get('sharpe',0) or 0))
        for is_d,name,expr in near[:10]:
            s=is_d.get('sharpe',0) or 0
            f=is_d.get('fitness',0) or 0
            t=(is_d.get('turnover',0) or 0)*100
            print(f"  S={s:.3f} F={f:.3f} TO={t:.1f}% | {name[:35]} | {expr[:50]}")
    print(f"\nSaved: {final_path}")


if __name__ == '__main__':
    run_batch()
