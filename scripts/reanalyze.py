"""Re-analyze all results with corrected passes() logic (PENDING != FAIL)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from run_batch import passes

ROOT = Path(__file__).parent.parent
qualifying = []
all_results = []
seen_ids = set()

for f in sorted(ROOT.glob('results/**/*.json')):
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            data = [data]
        for r in data:
            alpha_id = r.get('alpha', {}).get('id') or r.get('id')
            if alpha_id and alpha_id in seen_ids:
                continue
            if alpha_id:
                seen_ids.add(alpha_id)
            is_ = r.get('alpha', {}).get('is', {}) if 'alpha' in r else r.get('is', {})
            sh = is_.get('sharpe') or 0
            fi = is_.get('fitness') or 0
            to = (is_.get('turnover') or 0) * 100
            ok = passes(is_)
            all_results.append({'name': r.get('name', '?'), 'sharpe': sh, 'fitness': fi, 'to': to, 'passes': ok, 'id': alpha_id})
            if ok:
                qualifying.append({'name': r.get('name', '?'), 'id': alpha_id, 'sharpe': sh, 'fitness': fi, 'to': to})
    except Exception as e:
        pass

print(f"\n{'='*65}")
print(f"TOP RESULTS BY SHARPE")
print(f"{'='*65}")
for r in sorted(all_results, key=lambda x: -(x['sharpe'] or 0))[:20]:
    mark = 'PASS' if r['passes'] else '    '
    print(f"  {mark}  {r['name'][:30]:<30} sh={r['sharpe']:.2f} fi={r['fitness']:.2f} to={r['to']:.1f}%")

print(f"\n{'='*65}")
print(f"QUALIFYING ALPHAS: {len(qualifying)}/60 target")
print(f"{'='*65}")
for q in qualifying:
    print(f"  * {q['name']} (id={q['id']}) sh={q['sharpe']:.2f} fi={q['fitness']:.2f} to={q['to']:.1f}%")
