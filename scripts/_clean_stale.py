"""Mark stale running tasks aborted."""
import sqlite3, time
con = sqlite3.connect("data/state.db")
cur = con.cursor()
n = cur.execute(
    "UPDATE task SET status='aborted', ended_at=?, error='stale_cleanup' "
    "WHERE status='running' AND started_at < ?",
    (time.time(), time.time() - 3600)
).rowcount
print("aborted:", n)
con.commit(); con.close()
