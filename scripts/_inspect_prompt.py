import sqlite3
c = sqlite3.connect('data/state.db')
c.row_factory = sqlite3.Row
rows = list(c.execute(
    "SELECT prompt_kind, provider, prompt_text, response_text, ts "
    "FROM ai_calls WHERE ts > strftime('%s','now')-1500 ORDER BY ts DESC LIMIT 4"
))
for r in rows:
    print(f"=== {r['prompt_kind']} via {r['provider']} @ {r['ts']} ===")
    print("PROMPT[:2500]:")
    print((r['prompt_text'] or '')[:2500])
    print("RESP[:800]:")
    print((r['response_text'] or '')[:800])
    print()
