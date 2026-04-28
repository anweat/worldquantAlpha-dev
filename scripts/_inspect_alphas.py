import sqlite3
c = sqlite3.connect('data/state.db'); c.row_factory=sqlite3.Row
print('--- alphas with status is_passed ---')
cols = [r[1] for r in c.execute('PRAGMA table_info(alphas)')]
print('columns:', cols)
for r in c.execute("SELECT * FROM alphas WHERE status IN ('is_passed','submitted','queued') ORDER BY updated_at DESC LIMIT 10"):
    d = dict(r)
    print({k: d.get(k) for k in ('alpha_id','status','sharpe','fitness','turnover','self_corr','dataset_tag','ts','expression')})
print()
print('--- submission_queue ---')
qcols = [r[1] for r in c.execute('PRAGMA table_info(submission_queue)')]
print('cols:', qcols)
for r in c.execute('SELECT * FROM submission_queue ORDER BY enqueued_at DESC LIMIT 10'):
    print(dict(r))
print()
print('--- alphas counts by status ---')
for r in c.execute('SELECT status, COUNT(*) c FROM alphas GROUP BY status'):
    print(dict(r))
