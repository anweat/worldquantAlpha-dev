"""
Auto-orchestrator: runs waves sequentially until TARGET qualifying alphas reached.
Each wave's results are analyzed and the next wave is launched automatically.

Usage:
  python src/orchestrate.py                      # runs all waves in data/wave*.json
  python src/orchestrate.py --target 60          # stop when 60 qualifying found
  python src/orchestrate.py --waves 1 2 3        # only run specific wave numbers
"""
import sys, json, glob, argparse, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from run_batch import run_batch, passes


def load_all_results():
    """Load and deduplicate all results from results/ directory."""
    all_results = []
    seen_ids = set()
    for f in sorted(ROOT.glob('results/**/*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if not isinstance(data, list):
                data = [data]
            for r in data:
                alpha_id = r.get('alpha', {}).get('id')
                if alpha_id and alpha_id not in seen_ids:
                    seen_ids.add(alpha_id)
                    all_results.append(r)
                elif not alpha_id:
                    all_results.append(r)
        except Exception:
            pass
    return all_results


def count_qualifying(results):
    return sum(1 for r in results if r.get('passes') or passes(r.get('alpha', {}).get('is', {})))


def analyze_wave(results):
    """Print a summary of wave results and return key learnings."""
    passed = [r for r in results if r.get('passes')]
    failed = [r for r in results if not r.get('passes') and r.get('alpha')]
    
    print(f"\n  Passed: {len(passed)}/{len(results)}")
    
    # Fail reason breakdown
    fail_counts = {}
    for r in failed:
        for reason in r.get('fail_reasons', []):
            fail_counts[reason] = fail_counts.get(reason, 0) + 1
    if fail_counts:
        print("  Top fail reasons:", ", ".join(f"{k}({v})" for k, v in 
              sorted(fail_counts.items(), key=lambda x: -x[1])[:5]))
    
    # Near-misses (sharpe > 0.8)
    near = sorted(
        [r for r in failed if r.get('alpha', {}).get('is', {}).get('sharpe', 0) > 0.8],
        key=lambda r: r.get('alpha', {}).get('is', {}).get('fitness', 0),
        reverse=True
    )
    if near:
        print("  Near-misses (sharpe>0.8):")
        for r in near[:3]:
            is_ = r['alpha']['is']
            print(f"    {r['name']}: sharpe={is_.get('sharpe',0):.3f} "
                  f"fitness={is_.get('fitness',0):.3f} to={is_.get('turnover',0)*100:.1f}% "
                  f"fails={r.get('fail_reasons',[])}")
    
    return {'passed': len(passed), 'near_misses': near, 'fail_counts': fail_counts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=int, default=60, help='Stop when this many qualifying alphas found')
    parser.add_argument('--waves', nargs='+', type=int, default=None, help='Only run these wave numbers')
    args = parser.parse_args()

    # Find all wave config files
    wave_files = sorted(ROOT.glob('data/wave*_all.json'))
    if args.waves:
        wave_files = [f for f in wave_files 
                      if any(f'wave{n}' in f.name for n in args.waves)]

    print(f"Orchestrator starting. Target: {args.target} qualifying alphas")
    print(f"Wave files found: {[f.name for f in wave_files]}")
    
    for wave_file in wave_files:
        # Check current progress
        all_results = load_all_results()
        current_qualifying = count_qualifying(all_results)
        print(f"\n{'='*65}")
        print(f"Starting {wave_file.name} | Currently qualifying: {current_qualifying}/{args.target}")
        print(f"{'='*65}")

        if current_qualifying >= args.target:
            print(f"Target {args.target} reached! Stopping.")
            break

        # Auth refresh is handled inside run_batch via ensure_session()
        alphas = json.loads(wave_file.read_text(encoding='utf-8'))
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        out = ROOT / 'results' / f'{wave_file.stem}_{ts}.json'
        
        wave_results = run_batch(alphas, out_path=out)
        analyze_wave(wave_results)

    # Final summary
    all_results = load_all_results()
    final_q = count_qualifying(all_results)
    print(f"\n{'='*65}")
    print(f"ORCHESTRATION COMPLETE")
    print(f"Total qualifying alphas: {final_q}/{args.target}")
    if final_q >= args.target:
        print("TARGET REACHED!")
    else:
        print(f"Still need {args.target - final_q} more.")
    print(f"{'='*65}")


if __name__ == '__main__':
    main()
