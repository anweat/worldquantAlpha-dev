from wq_bus.data.state_db import open_state
conn = open_state()
print("--- ai_calls cols ---")
cols = [r["name"] for r in conn.execute("PRAGMA table_info(ai_calls)")]
print(cols)
total = conn.execute("SELECT COUNT(*) FROM ai_calls WHERE date(ts,'unixepoch','localtime')=date('now','localtime')").fetchone()[0]
print(f"total today: {total}")
print("--- recent 8 ---")
for r in conn.execute("SELECT * FROM ai_calls ORDER BY ts DESC LIMIT 8"):
    print({k: (str(r[k])[:80] if r[k] is not None else None) for k in cols})

