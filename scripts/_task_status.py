from wq_bus.data._sqlite import open_state
import json
with open_state() as c:
    for r in c.execute("SELECT task_id, status, iterations, progress_json, error FROM task WHERE name='daily_alpha_loop' ORDER BY started_at DESC LIMIT 4"):
        d = dict(r)
        try:
            d['progress'] = json.loads(d.pop('progress_json') or '{}')
        except Exception:
            pass
        print(d)
