"""
Dynamic batch runner. Called by background agents with a JSON config.
Usage:
  python src/run_batch.py --config path/to/batch.json
  python src/run_batch.py --config path/to/batch.json --out results/my_batch.json

Config format:
  [{"name": "...", "expr": "...", "settings": {...}, "hypothesis": "..."}]
"""
import sys, json, argparse, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from brain_client import BrainClient
from session_guard import ensure_session

FUND_SETTINGS = {
    "decay": 0, "neutralization": "SUBINDUSTRY",
    "truncation": 0.08, "nanHandling": "ON"
}
TECH_SETTINGS = {
    "decay": 20, "neutralization": "MARKET",
    "truncation": 0.05, "nanHandling": "OFF"
}

def passes(is_data):
    """Check if alpha meets submission criteria. PENDING checks are treated as PASS (resolved later)."""
    if not is_data:
        return False
    sh = is_data.get('sharpe', 0)
    fi = is_data.get('fitness', 0)
    to = is_data.get('turnover', 1)
    # Must meet numeric thresholds
    if not (sh >= 1.25 and fi >= 1.0 and 0.01 <= to <= 0.70):
        return False
    # Check all checks: PASS or PENDING are acceptable; FAIL is not
    for c in is_data.get('checks', []):
        if c.get('result') == 'FAIL':
            return False
    return True

def run_batch(alphas, out_path=None):
    # Auto-refresh session if expired before starting
    ensure_session(verbose=True)
    client = BrainClient()

    results = []
    passed = 0

    for i, alpha in enumerate(alphas):
        name = alpha.get('name', f'ALPHA_{i:02d}')
        expr = alpha['expr']
        settings = alpha.get('settings', FUND_SETTINGS)
        print(f"[{i+1}/{len(alphas)}] Testing {name}: {expr[:60]}")
        try:
            result = client.simulate_and_get_alpha(expr, settings)
            # Detect auth error mid-batch
            if isinstance(result, dict) and result.get('error') in (401, 403):
                print(f"  => AUTH ERROR mid-batch: {result.get('body','')}")
                print("Session expired during batch. Aborting. Run `python src/login.py` to refresh.")
                sys.exit(1)
            is_ = result.get('is', {})
            ok = passes(is_)
            if ok:
                passed += 1
            checks_fail = [c['name'] for c in is_.get('checks', []) if c.get('result') == 'FAIL']
            checks_pending = [c['name'] for c in is_.get('checks', []) if c.get('result') == 'PENDING']
            status = 'PASS' if ok else f"FAIL({','.join(checks_fail)})"
            if checks_pending:
                status += f" PENDING({','.join(checks_pending)})"
            print(f"  => {status} | sharpe={is_.get('sharpe',0):.3f} fitness={is_.get('fitness',0):.3f} to={is_.get('turnover',0)*100:.1f}%")
            results.append({
                'name': name,
                'expr': expr,
                'settings': settings,
                'hypothesis': alpha.get('hypothesis', ''),
                'passes': ok,
                'fail_reasons': checks_fail,
                'pending_checks': checks_pending,
                'alpha': result
            })
        except Exception as e:
            print(f"  => ERROR: {e}")
            results.append({'name': name, 'expr': expr, 'settings': settings, 'error': str(e), 'passes': False})

    # Save results
    if out_path is None:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        batch_name = Path(alphas[0].get('batch_id', 'batch') if alphas else 'batch').stem
        out_path = ROOT / 'results' / f'{batch_name}_{ts}.json'
    else:
        out_path = Path(out_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

    # Print summary
    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE: {passed}/{len(results)} passed")
    print(f"Saved to: {out_path}")
    print(f"{'='*60}")
    # Machine-readable summary for the orchestrating agent
    summary = {
        'total': len(results),
        'passed': passed,
        'out_file': str(out_path),
        'results': [
            {'name': r['name'], 'passes': r.get('passes', False),
             'sharpe': r.get('alpha', {}).get('is', {}).get('sharpe'),
             'fitness': r.get('alpha', {}).get('is', {}).get('fitness'),
             'turnover': r.get('alpha', {}).get('is', {}).get('turnover'),
             'fail_reasons': r.get('fail_reasons', []),
             'error': r.get('error')}
            for r in results
        ]
    }
    print(f"\nSUMMARY_JSON:{json.dumps(summary)}")
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, help='JSON file with alpha specs')
    parser.add_argument('--out', default=None, help='Output file path')
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        sys.exit(1)

    alphas = json.loads(config_path.read_text(encoding='utf-8'))
    print(f"Loaded {len(alphas)} alphas from {config_path}")
    run_batch(alphas, args.out)

if __name__ == '__main__':
    main()
