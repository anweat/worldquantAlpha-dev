"""fix_legacy_status.py — Idempotent: reclassify legacy-migrated alphas.

Finds all alphas with trace_id LIKE 'tr_legacy_migration_%' AND status='submitted'
and sets their status to 'legacy'.  Safe to re-run; already-legacy rows are counted
but not re-touched.

Usage:
    python scripts/fix_legacy_status.py [--dataset TAG] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LEGACY_TRACE_PREFIX = "tr_legacy_migration_%"
LEGACY_STATUS = "legacy"


def main() -> None:
    parser = argparse.ArgumentParser(description="Reclassify legacy-migrated alphas to status='legacy'")
    parser.add_argument("--dataset", default=None, help="Restrict to a specific dataset_tag (default: all).")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing.")
    args = parser.parse_args()

    from wq_bus.data._sqlite import ensure_migrated, open_knowledge
    ensure_migrated()

    with open_knowledge() as conn:
        # Count already-legacy rows
        already_params: list = [LEGACY_TRACE_PREFIX]
        already_sql = (
            "SELECT COUNT(*) AS n FROM alphas "
            "WHERE trace_id LIKE ? AND status=?"
        )
        already_params.append(LEGACY_STATUS)
        if args.dataset:
            already_sql += " AND dataset_tag=?"
            already_params.append(args.dataset)
        already_count = int(conn.execute(already_sql, already_params).fetchone()[0])

        # Find rows to change
        find_params: list = [LEGACY_TRACE_PREFIX, "submitted"]
        find_sql = (
            "SELECT alpha_id, dataset_tag, status, trace_id FROM alphas "
            "WHERE trace_id LIKE ? AND status=?"
        )
        if args.dataset:
            find_sql += " AND dataset_tag=?"
            find_params.append(args.dataset)
        rows = conn.execute(find_sql, find_params).fetchall()
        to_fix = [dict(r) for r in rows]

        if args.dry_run:
            print(f"[dry-run] would fix {len(to_fix)} rows (already legacy: {already_count})")
            for r in to_fix[:20]:
                print(f"  alpha_id={r['alpha_id']} tag={r['dataset_tag']} trace={r['trace_id']}")
            if len(to_fix) > 20:
                print(f"  ... and {len(to_fix) - 20} more")
            return

        import time as _time
        updated = 0
        for r in to_fix:
            conn.execute(
                "UPDATE alphas SET status=?, updated_at=? WHERE alpha_id=? AND dataset_tag=?",
                (LEGACY_STATUS, _time.time(), r["alpha_id"], r["dataset_tag"]),
            )
            updated += 1

    print(f"[fix_legacy_status] Done.")
    print(f"  Rows updated to 'legacy': {updated}")
    print(f"  Already-legacy rows skipped: {already_count}")
    total_legacy = updated + already_count
    print(f"  Total legacy rows now: {total_legacy}")


if __name__ == "__main__":
    main()
