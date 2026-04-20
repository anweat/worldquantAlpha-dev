"""Targeted retry: submit only the 16 throttled (429) alphas with longer delay."""
import json, sys, time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from brain_client import BrainClient

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# Load all submission logs, deduplicate
seen = {}
for log in sorted(DATA.glob("submission_log_*.json")):
    for e in json.loads(log.read_text(encoding="utf-8")):
        if e.get("id"):
            seen[e["id"]] = e

throttled = [e for e in seen.values() if "429" in str(e.get("submit_result", ""))]
print(f"Throttled alphas to retry: {len(throttled)}")
for e in throttled:
    print(f"  {e['id']}  {e['name']}  sh={e.get('sharpe',0):.2f}  fi={e.get('fitness',0):.2f}")

client = BrainClient()
auth = client.check_auth()
if auth["status"] != 200:
    print("AUTH FAILED — refresh session first")
    sys.exit(1)

print(f"\nSubmitting {len(throttled)} throttled alphas (20s delay)...\n")
results = []
success = 0
for i, alpha in enumerate(throttled, 1):
    print(f"[{i}/{len(throttled)}] {alpha['name']} [{alpha['id']}]")
    try:
        resp = client.submit_alpha(alpha["id"])
        status = resp.get("status", 0)
        body = resp.get("body", {})
        if status in (200, 201, 202):
            print(f"  => SUCCESS (HTTP {status})")
            results.append({**alpha, "submit_result": "SUCCESS"})
            success += 1
        elif status == 409:
            print(f"  => Already submitted (409)")
            results.append({**alpha, "submit_result": "ALREADY_SUBMITTED"})
            success += 1
        elif status == 403:
            corr_val = None
            checks = body.get("is", {}).get("checks", [])
            for c in checks:
                if c.get("name") == "SELF_CORRELATION":
                    corr_val = c.get("value")
            print(f"  => BLOCKED 403 SELF_CORR={corr_val}")
            results.append({**alpha, "submit_result": f"FAILED_403", "submit_response": resp})
        else:
            print(f"  => FAILED HTTP {status}: {str(body)[:100]}")
            results.append({**alpha, "submit_result": f"FAILED_{status}"})
    except Exception as e:
        print(f"  => ERROR: {e}")
        results.append({**alpha, "submit_result": f"ERROR:{e}"})

    if i < len(throttled):
        print(f"  Waiting 20s...")
        time.sleep(20)

# Save retry log
ts = time.strftime("%Y%m%d_%H%M%S")
out = DATA / f"submission_retry_{ts}.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n{'='*50}")
print(f"RETRY COMPLETE: {success}/{len(throttled)} submitted")
print(f"Log: {out}")
