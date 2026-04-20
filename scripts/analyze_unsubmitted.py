"""
analyze_unsubmitted.py - Analyze unsubmitted alphas from BRAIN API
"""
import sys, json
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).parent.parent

with open(ROOT / 'data/unsubmitted_alphas_all.json', encoding='utf-8') as f:
    alphas = json.load(f)

failing = []
passing = []

for a in alphas:
    is_data = a.get('is', {}) or {}
    checks = is_data.get('checks', [])
    sharpe = is_data.get('sharpe', 0) or 0
    fitness = is_data.get('fitness', 0) or 0
    turnover = (is_data.get('turnover', 0) or 0) * 100
    returns = (is_data.get('returns', 0) or 0) * 100
    settings = a.get('settings', {})

    failed_checks = [c for c in checks if c.get('result') == 'FAIL']
    all_pass = all(c.get('result') in ('PASS', 'PENDING') for c in checks) if checks else False

    reg = a.get('regular', {})
    expr_str = reg.get('code', '?') if isinstance(reg, dict) else str(reg)

    entry = {
        'id': a['id'],
        'expr': expr_str,
        'sharpe': sharpe,
        'fitness': fitness,
        'to': turnover,
        'ret': returns,
        'neutralization': settings.get('neutralization', '?'),
        'decay': settings.get('decay', '?'),
        'fails': [c['name'] for c in failed_checks],
        'check_values': {c['name']: {'value': c.get('value'), 'limit': c.get('limit'), 'result': c['result']} for c in checks},
    }

    if all_pass and checks:
        passing.append(entry)
    else:
        failing.append(entry)

print(f"=== PASSING ({len(passing)}) - Top by Fitness ===")
for p in sorted(passing, key=lambda x: -x['fitness'])[:15]:
    print(f"  [{p['id']}] Sharpe={p['sharpe']:.3f} Fitness={p['fitness']:.3f} TO={p['to']:.1f}% Ret={p['ret']:.1f}%")
    print(f"    {p['expr'][:80]}")

print()
print(f"=== FAILING ({len(failing)}) - Grouped by Reason ===")
by_reason = defaultdict(list)
for f in failing:
    key = '+'.join(sorted(f['fails'])) if f['fails'] else 'NO_CHECKS'
    by_reason[key].append(f)

for reason, items in sorted(by_reason.items(), key=lambda x: -len(x[1])):
    print(f"\n  [{len(items)}x] FAIL: {reason}")
    for item in items[:3]:
        cv = item['check_values']
        vals = []
        for name in item['fails']:
            info = cv.get(name, {})
            vals.append(f"{name}={info.get('value','?'):.3f}" if isinstance(info.get('value'), float) else f"{name}=?")
        print(f"    Sharpe={item['sharpe']:.2f} Fitness={item['fitness']:.2f} TO={item['to']:.1f}% | {', '.join(vals)}")
        print(f"    Expr: {item['expr'][:70]}")

print()
print("=== SUMMARY ===")
print(f"Total unsubmitted: {len(alphas)}")
print(f"Passing all checks: {len(passing)}")
print(f"Failing: {len(failing)}")
print()
print("Fail reason distribution:")
for reason, items in sorted(by_reason.items(), key=lambda x: -len(x[1])):
    print(f"  {reason}: {len(items)}")

# Save analysis
out = {
    'total': len(alphas),
    'passing': len(passing),
    'failing': len(failing),
    'passing_alphas': sorted(passing, key=lambda x: -x['fitness'])[:20],
    'fail_reasons': {r: len(i) for r, i in by_reason.items()},
    'failing_sample': failing[:30],
}
with open(ROOT / 'data/unsubmitted_analysis.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\nSaved to data/unsubmitted_analysis.json")
