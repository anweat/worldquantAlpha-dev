"""sync_wq_submitted.py — Reconcile local alpha statuses with WQ platform truth.

Usage:
    python scripts/sync_wq_submitted.py [--dry-run] [--dataset USA_TOP3000]

Fetches the authenticated user's alpha list from WQ BRAIN API, then:
  - Confirms locally-submitted alphas that WQ also knows about.
  - Degrades alphas WQ does NOT list (local=submitted, WQ=missing) → is_passed.
  - Upgrades alphas WQ lists that we have locally but marked differently.
  - Inserts new rows for alphas WQ knows about but we have no local record.

SAFETY:
  - rows with status='legacy' are NEVER touched.
  - All writes are guarded with --dry-run (show only; no DB changes).
  - Atomic JSON output via tmp+os.replace.

Output: test_results/wq_drift_<timestamp>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TS = time.strftime("%Y%m%d_%H%M%S", time.gmtime())

# Ensure PYTHONIOENCODING=utf-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def _paginate_wq_alphas(client, user_id: str, dataset: str) -> list[dict]:
    """Paginate GET /users/{user_id}/alphas until empty page.

    Returns consolidated list of all alpha dicts from the platform.
    """
    region, universe = _parse_dataset(dataset)
    all_alphas: list[dict] = []
    limit = 100
    offset = 0

    while True:
        params: dict = {"limit": limit, "offset": offset}
        if region:
            params["region"] = region
        if universe:
            params["universe"] = universe

        try:
            page = client.get_user_alphas(user_id=user_id, limit=limit, offset=offset)
        except Exception as exc:
            print(f"[sync] paginate error at offset={offset}: {exc}", file=sys.stderr)
            break

        if not page:
            break

        # get_user_alphas may return list or dict
        if isinstance(page, dict):
            items = page.get("results", page.get("alphas", []))
        else:
            items = page

        if not items:
            break

        all_alphas.extend(items)
        if len(items) < limit:
            break  # last page
        offset += limit

        # Brief pause to avoid hammering the API
        time.sleep(0.5)

    return all_alphas


def _parse_dataset(dataset: str) -> tuple[str, str]:
    """Parse 'USA_TOP3000' → ('USA', 'TOP3000'). Returns ('', '') on unknown format."""
    parts = dataset.split("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", ""


def _get_local_submitted(tag: str) -> dict[str, dict]:
    """Return {alpha_id: row_dict} for all non-legacy rows in local knowledge.db."""
    from wq_bus.data._sqlite import open_knowledge
    with open_knowledge() as conn:
        rows = conn.execute(
            "SELECT alpha_id, status, expression, is_metrics_json FROM alphas "
            "WHERE dataset_tag=? AND status != 'legacy'",
            (tag,),
        ).fetchall()
    return {r["alpha_id"]: dict(r) for r in rows}


def _upsert_wq_alpha(conn, alpha_id: str, tag: str, wq_row: dict, status: str) -> None:
    """Insert or update an alpha row from WQ API data, preserving local expression/metrics."""
    now = time.time()
    raw_reg = wq_row.get("regular")
    if isinstance(raw_reg, dict):
        expr = raw_reg.get("code") or raw_reg.get("expression") or ""
    else:
        expr = raw_reg or wq_row.get("expression") or ""
    if not isinstance(expr, str):
        expr = str(expr) if expr is not None else ""
    settings = wq_row.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    import hashlib as _h
    settings_hash = _h.sha256(
        json.dumps(settings, sort_keys=True).encode()
    ).hexdigest()[:16]

    # Extract IS metrics if present
    is_metrics = wq_row.get("is") or {}
    sharpe = is_metrics.get("sharpe")
    fitness = is_metrics.get("fitness")
    turnover = is_metrics.get("turnover")

    conn.execute(
        """INSERT INTO alphas
           (alpha_id, dataset_tag, expression, settings_json, settings_hash,
            is_metrics_json, status, sharpe, fitness, turnover, created_at, updated_at,
            origin)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(alpha_id, dataset_tag) DO UPDATE SET
               status=excluded.status,
               updated_at=excluded.updated_at,
               sharpe=COALESCE(excluded.sharpe, alphas.sharpe),
               fitness=COALESCE(excluded.fitness, alphas.fitness),
               turnover=COALESCE(excluded.turnover, alphas.turnover)""",
        (
            alpha_id, tag, expr, json.dumps(settings), settings_hash,
            json.dumps(is_metrics) if is_metrics else None,
            status, sharpe, fitness, turnover, now, now,
            "wq_sync",
        ),
    )


def _has_origin_column(conn) -> bool:
    """Check whether alphas table has an 'origin' column (added by wq_sync)."""
    rows = conn.execute("PRAGMA table_info(alphas)").fetchall()
    return any(r[1] == "origin" for r in rows)


def _ensure_origin_column(conn) -> None:
    """Add 'origin' column to alphas if missing (idempotent)."""
    if not _has_origin_column(conn):
        try:
            conn.execute("ALTER TABLE alphas ADD COLUMN origin TEXT")
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync local alpha statuses with WQ platform truth."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report drift without writing to DB.")
    parser.add_argument("--dataset", default="USA_TOP3000",
                        help="Dataset tag (e.g. USA_TOP3000).")
    args = parser.parse_args()

    tag = args.dataset.upper()
    dry_run = args.dry_run

    print(f"[sync_wq] dataset={tag}  dry_run={dry_run}")

    # ---------- 1. Load BrainClient ----------
    try:
        from wq_bus.brain.client import BrainClient
        client = BrainClient(auto_login=True)
    except FileNotFoundError as exc:
        print(
            f"\n[sync_wq] ERROR: session file not found.\n"
            f"  {exc}\n"
            "  → Run the login script to refresh your session cookie.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # ---------- 2. Verify auth ----------
    try:
        auth_ok = client.check_auth()
    except Exception as exc:
        auth_ok = False
        print(f"[sync_wq] auth check error: {exc}", file=sys.stderr)

    if not auth_ok:
        print(
            "\n[sync_wq] ERROR: WQ session is not authenticated (401/expired).\n"
            "  → Refresh your session cookie with the login script, then re-run.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # ---------- 3. Get user id ----------
    try:
        user_info = client._get("/users/self")
        user_id = user_info.get("id") or user_info.get("userId") or "self"
        print(f"[sync_wq] user_id={user_id}")
    except Exception as exc:
        print(f"[sync_wq] Could not get /users/self: {exc}", file=sys.stderr)
        user_id = "self"

    # ---------- 4. Paginate WQ alphas ----------
    print("[sync_wq] Fetching alpha list from WQ...")
    try:
        wq_alphas = _paginate_wq_alphas(client, user_id, tag)
    except Exception as exc:
        print(f"[sync_wq] ERROR fetching alphas: {exc}", file=sys.stderr)
        if "429" in str(exc):
            print("  → WQ is rate-limiting. Wait a few minutes and retry.", file=sys.stderr)
        wq_alphas = []

    wq_ids: set[str] = {a.get("id") or a.get("alpha_id", "") for a in wq_alphas}
    wq_ids.discard("")
    wq_by_id: dict[str, dict] = {
        (a.get("id") or a.get("alpha_id", "")): a for a in wq_alphas
        if (a.get("id") or a.get("alpha_id", ""))
    }
    print(f"[sync_wq] Found {len(wq_ids)} alphas on WQ platform.")

    # ---------- 5. Load local submitted (excluding legacy) ----------
    from wq_bus.data._sqlite import ensure_migrated, open_knowledge
    ensure_migrated()

    with open_knowledge() as conn:
        _ensure_origin_column(conn)

    local_all = _get_local_submitted(tag)
    local_submitted = {aid: row for aid, row in local_all.items() if row["status"] == "submitted"}
    print(f"[sync_wq] Local status='submitted' (non-legacy): {len(local_submitted)}")

    # ---------- 6. Compute drift ----------
    confirmed: list[str] = []
    degraded: list[str] = []   # local=submitted, not in WQ
    upgraded: list[str] = []   # in WQ but local status != submitted
    new_inserts: list[str] = []  # in WQ but not in local at all

    for alpha_id in wq_ids:
        if alpha_id in local_all:
            local_status = local_all[alpha_id]["status"]
            if local_status == "submitted":
                confirmed.append(alpha_id)
            else:
                # WQ knows it as submitted, but our local status differs
                upgraded.append(alpha_id)
        else:
            new_inserts.append(alpha_id)

    for alpha_id, row in local_submitted.items():
        if alpha_id not in wq_ids:
            degraded.append(alpha_id)

    drift = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset_tag": tag,
        "dry_run": dry_run,
        "wq_total": len(wq_ids),
        "local_submitted_total": len(local_submitted),
        "counts": {
            "confirmed": len(confirmed),
            "degraded": len(degraded),
            "upgraded": len(upgraded),
            "new_inserts": len(new_inserts),
        },
        "degraded_ids": degraded,
        "upgraded_ids": upgraded,
        "new_insert_ids": new_inserts,
    }

    print(f"[sync_wq] Drift: confirmed={len(confirmed)} degraded={len(degraded)} "
          f"upgraded={len(upgraded)} new_inserts={len(new_inserts)}")

    # ---------- 7. Apply changes (unless dry-run) ----------
    if not dry_run:
        from wq_bus.data._sqlite import open_knowledge
        with open_knowledge() as conn:
            _ensure_origin_column(conn)

            # Degrade: local=submitted but WQ doesn't list → revert to is_passed
            for alpha_id in degraded:
                conn.execute(
                    "UPDATE alphas SET status='is_passed', updated_at=? "
                    "WHERE alpha_id=? AND dataset_tag=? AND status='submitted'",
                    (time.time(), alpha_id, tag),
                )
                print(f"  DEGRADED  {alpha_id[:20]} → is_passed")

            # Upgrade: in WQ but local status != submitted
            for alpha_id in upgraded:
                conn.execute(
                    "UPDATE alphas SET status='submitted', updated_at=? "
                    "WHERE alpha_id=? AND dataset_tag=? AND status != 'legacy'",
                    (time.time(), alpha_id, tag),
                )
                print(f"  UPGRADED  {alpha_id[:20]} → submitted")

            # New inserts: in WQ but no local row
            for alpha_id in new_inserts:
                wq_row = wq_by_id.get(alpha_id, {})
                _upsert_wq_alpha(conn, alpha_id, tag, wq_row, status="submitted")
                print(f"  INSERTED  {alpha_id[:20]} (origin=wq_sync)")

        print(f"[sync_wq] Applied {len(degraded)+len(upgraded)+len(new_inserts)} changes.")
    else:
        print("[sync_wq] Dry-run: no DB changes written.")

    # ---------- 8. Write drift report (atomic) ----------
    out_dir = _ROOT / "test_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"wq_drift_{_TS}.json"
    tmp_path = out_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(drift, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    os.replace(tmp_path, out_path)
    print(f"[sync_wq] Drift report saved: {out_path}")


if __name__ == "__main__":
    main()
