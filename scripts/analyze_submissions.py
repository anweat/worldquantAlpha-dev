"""Analyze submission logs and generate retry config for throttled alphas."""
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent
logs = sorted((ROOT / "data").glob("submission_log_*.json"))
print(f"Found {len(logs)} submission log(s)")

# Merge all logs, deduplicate by alpha ID (keep latest result)
seen = {}
for log in logs:
    data = json.loads(log.read_text(encoding="utf-8"))
    for entry in data:
        aid = entry.get("id")
        if aid:
            seen[aid] = entry  # later logs override earlier

all_entries = list(seen.values())
results = Counter(e.get("submit_result", "?") for e in all_entries)
print(f"\nTotal unique alphas: {len(all_entries)}")
print("Result breakdown:", dict(results))

throttled = [e for e in all_entries if "429" in str(e.get("submit_result", ""))]
rejected = [e for e in all_entries if "403" in str(e.get("submit_result", ""))]
success = [e for e in all_entries if e.get("submit_result") in ("SUCCESS", "ALREADY_SUBMITTED")]

print(f"\n✅ Submitted (SUCCESS + 409): {len(success)}")
print(f"⏳ Throttled 429 (retry needed): {len(throttled)}")
print(f"🚫 Rejected 403 (correlation?): {len(rejected)}")

if throttled:
    print("\n=== Throttled (need retry) ===")
    for e in throttled:
        print(f"  {e['id']}  {e['name']}  sh={e.get('sharpe',0):.2f}  fi={e.get('fitness',0):.2f}")

if rejected:
    print("\n=== Rejected 403 ===")
    for e in rejected:
        resp = e.get("submit_response", {})
        body = resp.get("body", {}) if isinstance(resp, dict) else {}
        print(f"  {e['id']}  {e['name']}  reason={body}")
