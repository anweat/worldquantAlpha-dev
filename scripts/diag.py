import sqlite3
for db in ['data/state.db','data/knowledge.db']:
    print('===',db,'===')
    c=sqlite3.connect(db)
    for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        t=r[0]
        cols=[x[1] for x in c.execute(f'PRAGMA table_info({t})')]
        print(f'  {t}: {cols}')
