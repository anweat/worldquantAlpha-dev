"""One-off audit script (safe to delete after run)."""
from wq_bus.data import state_db as sdb
from wq_bus.data._sqlite import open_state, open_knowledge, ensure_migrated
from wq_bus.utils.tag_context import with_tag
ensure_migrated()
with with_tag("usa_top3000"):
    print("submitted_today (usa_top3000):", sdb.count_submitted_today())
with open_knowledge() as kc:
    n_alphas = kc.execute("SELECT COUNT(*) FROM alphas").fetchone()[0]
    n_pass = kc.execute("SELECT COUNT(*) FROM alphas WHERE status='is_passed'").fetchone()[0]
    n_subm = kc.execute("SELECT COUNT(*) FROM alphas WHERE status='submitted'").fetchone()[0]
    print(f"alphas total={n_alphas} is_passed={n_pass} submitted={n_subm}")
with open_state() as c:
    rows = list(c.execute(
        "SELECT task_id, name, status, iterations, started_at "
        "FROM task WHERE status IN ('running','paused') "
        "ORDER BY started_at DESC LIMIT 20"
    ).fetchall())
    print("stale running:", len(rows))
    for r in rows[:5]:
        print(" ", dict(r))
    qsz = c.execute("SELECT COUNT(*) FROM submission_queue WHERE status='pending'").fetchone()[0]
    print("submission_queue pending:", qsz)
