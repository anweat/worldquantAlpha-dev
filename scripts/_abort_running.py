"""Abort all currently 'running' or 'paused' tasks (clean slate before daemon)."""
from wq_bus.data import task_db
from wq_bus.utils.tag_context import with_tag

def main() -> None:
    with with_tag("_global"):
        rows = task_db.list_tasks()
        n = 0
        for r in rows:
            if r.get("status") in ("running", "paused"):
                task_db.finish_task(r["task_id"], "aborted", error="manual_clean_slate")
                n += 1
                print(f"  aborted {r['task_id']}  {r.get('name')}  {r.get('status')}")
        print(f"aborted {n} task(s)")

if __name__ == "__main__":
    main()
