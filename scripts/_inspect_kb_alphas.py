from wq_bus.data._sqlite import open_knowledge
with open_knowledge() as c:
    print('cols:', [r[1] for r in c.execute('PRAGMA table_info(alphas)')])
    print('counts by status:')
    for r in c.execute('SELECT status, COUNT(*) FROM alphas GROUP BY status'):
        print(' ', dict(r))
    print('recent is_passed/submitted/queued:')
    for r in c.execute("SELECT alpha_id, status, sharpe, fitness, turnover, sc_value, dataset_tag FROM alphas WHERE status IN ('is_passed','submitted','queued') ORDER BY rowid DESC LIMIT 10"):
        print(' ', dict(r))
    print('recent any:')
    for r in c.execute("SELECT alpha_id, status, sharpe, fitness, turnover, dataset_tag FROM alphas ORDER BY rowid DESC LIMIT 5"):
        print(' ', dict(r))
