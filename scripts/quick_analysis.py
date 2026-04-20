"""Quick analysis of newest wave results."""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

ROOT = Path(r"D:\codeproject\worldquantAlpha-dev")

result_files = [
    'results/wave7_20260420_012250.json',
    'results/wave8_20260420_020243.json',
    'results/wave9_20260420_023724.json',
    'results/wave10_20260420_031801.json',
    'results/batch1_20260420_025805.json',
]

all_new = []
for f in result_files:
    try:
        data = json.loads((ROOT / f).read_text(encoding='utf-8'))
        if isinstance(data, list):
            all_new.extend(data)
    except Exception as e:
        print(f"Skip {f}: {e}")

print(f"New alpha records loaded: {len(all_new)}")

passing = []
failing = {}
errors = 0

for item in all_new:
    alpha = item.get('alpha', {}) if item else {}
    if not alpha or alpha.get('error'):
        errors += 1
        continue
    is_d = alpha.get('is', {}) or {}
    checks = is_d.get('checks', [])
    if not checks:
        continue
    sharpe = is_d.get('sharpe', 0) or 0
    fitness = is_d.get('fitness', 0) or 0
    to_pct = (is_d.get('turnover', 0) or 0) * 100
    ret_pct = (is_d.get('returns', 0) or 0) * 100
    failed = [c['name'] for c in checks if c.get('result') == 'FAIL']
    alpha_id = alpha.get('id', '')
    expr = item.get('expr', '')
    if not failed:
        passing.append({
            'expr': expr, 'sharpe': sharpe, 'fitness': fitness,
            'to': to_pct, 'ret': ret_pct, 'id': alpha_id
        })
    else:
        key = '+'.join(sorted(failed))
        failing[key] = failing.get(key, 0) + 1

print(f"PASS: {len(passing)}  FAIL: {sum(failing.values())}  ERRORS: {errors}")
print()
print("Fail reasons:")
for k, v in sorted(failing.items(), key=lambda x: -x[1]):
    print(f"  [{v:3d}x] {k}")

print()
print("Top 15 passing alphas (by Fitness):")
print(f"  {'Expression':<55} {'Sharpe':>7} {'Fitness':>7} {'TO%':>6}")
print("  " + "-"*80)
for p in sorted(passing, key=lambda x: -x['fitness'])[:15]:
    print(f"  {p['expr'][:55]:<55} {p['sharpe']:>7.3f} {p['fitness']:>7.3f} {p['to']:>6.1f}%")
