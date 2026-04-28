from wq_bus.data.state_db import open_state
import sys, time
window = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
conn = open_state()
cur = conn.execute(
    "SELECT topic, COUNT(*) c FROM events WHERE ts > ? GROUP BY topic ORDER BY c DESC",
    (time.time() - window,),
)
for r in cur:
    print(f"{r['topic']:<32} {r['c']}")
print("---recent traces---")
cur = conn.execute(
    "SELECT trace_id, task_kind, status, started_at FROM traces ORDER BY started_at DESC LIMIT 10"
)
for r in cur:
    print(tuple(r))
