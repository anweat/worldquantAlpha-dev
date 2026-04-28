import sqlite3
c = sqlite3.connect('data/state.db'); c.row_factory=sqlite3.Row
rows = list(c.execute("SELECT prompt_kind, provider, prompt_text, response_text FROM ai_calls WHERE ts > strftime('%s','now')-1500 AND prompt_kind LIKE 'alpha_gen%' ORDER BY ts DESC LIMIT 1"))
if rows:
    r = rows[0]
    p = r['prompt_text'] or ''
    print('LEN=', len(p), 'kind=', r['prompt_kind'], 'provider=', r['provider'])
    print('--- FIRST 1500 ---'); print(p[:1500])
    print('--- LAST 1500 ---'); print(p[-1500:])
    print('--- CONTAINS ts_min:', 'ts_min' in p, ' do NOT exist:', 'do NOT exist' in p, ' 66 valid:', '66 valid' in p)
    print('--- RESP[:1200]:'); print((r['response_text'] or '')[:1200])
else:
    print('no alpha_gen calls in last 1500s')
    # try any time
    rows2 = list(c.execute("SELECT prompt_kind, provider, ts FROM ai_calls ORDER BY ts DESC LIMIT 6"))
    for r in rows2: print(dict(r))
