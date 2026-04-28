"""scripts/migrate_to_bus.py — 一次性迁移：旧 KB + memory 文件 → 新双库 + memory/{tag}/。

运行：
    python scripts/migrate_to_bus.py [--default-tag usa_top3000] [--dry-run]

操作：
  1. 旧 data/unified_kb.db / data/alpha_kb.db / data/crawl_state.db (若存在)
     -> 新 data/knowledge.db (alphas / crawl_docs / learnings)
  2. 旧 memory/*.json + memory/*.md (root)
     -> memory/{default_tag}/*.{json,md}
  3. 完成后把旧 data/*.db 与 memory/*.{json,md} 移到 archive/2026-04-26_pre_bus/data_and_memory/
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wq_bus.data import knowledge_db, state_db  # noqa: E402
from wq_bus.utils.tag_context import with_tag  # noqa: E402

ARCHIVE_DIR = PROJECT_ROOT / "archive" / "2026-04-26_pre_bus" / "data_and_memory"


def _scan_old_alphas(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    out = []
    for tbl in ("alphas", "alpha_records", "alpha_kb"):
        try:
            rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            for r in rows:
                d = dict(r)
                out.append(d)
        except sqlite3.Error:
            continue
    conn.close()
    return out


def migrate_alphas(default_tag: str, dry_run: bool) -> int:
    candidates = [PROJECT_ROOT / "data" / n for n in
                  ("unified_kb.db", "alpha_kb.db", "wq.db")]
    n = 0
    for db in candidates:
        rows = _scan_old_alphas(db)
        for r in rows:
            alpha_id = r.get("alpha_id") or r.get("id")
            expr = r.get("expression") or r.get("expr") or ""
            if not alpha_id or not expr:
                continue
            settings = {}
            for k in ("settings", "settings_json"):
                v = r.get(k)
                if v:
                    try:
                        settings = json.loads(v) if isinstance(v, str) else v
                    except Exception:
                        pass
            is_metrics = {}
            for k in ("is_metrics", "is_metrics_json", "metrics"):
                v = r.get(k)
                if v:
                    try:
                        is_metrics = json.loads(v) if isinstance(v, str) else v
                    except Exception:
                        pass
            status = r.get("status") or "simulated"
            tag = r.get("dataset_tag") or default_tag
            if dry_run:
                n += 1
                continue
            with with_tag(tag):
                knowledge_db.upsert_alpha(
                    str(alpha_id), expr, settings or {}, "",
                    is_metrics=is_metrics or None,
                    status=status,
                )
            n += 1
    return n


def migrate_memory_files(default_tag: str, dry_run: bool) -> list[str]:
    src_mem = PROJECT_ROOT / "memory"
    if not src_mem.exists():
        return []
    moved: list[str] = []
    dest = src_mem / default_tag
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
    for p in src_mem.iterdir():
        if p.is_dir():
            continue
        if p.suffix not in (".json", ".md"):
            continue
        moved.append(p.name)
        if not dry_run:
            target = dest / p.name
            if target.exists():
                target.unlink()
            shutil.move(str(p), str(target))
    return moved


def archive_old_data(dry_run: bool) -> list[str]:
    """Move old data/*.db (except new state.db / knowledge.db) into archive."""
    archived: list[str] = []
    if not dry_run:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    keep = {"state.db", "knowledge.db", "state.db-wal", "state.db-shm",
            "knowledge.db-wal", "knowledge.db-shm"}
    for p in (PROJECT_ROOT / "data").iterdir():
        if p.name in keep:
            continue
        if p.suffix in (".db", ".db-wal", ".db-shm") or "kb" in p.name.lower():
            archived.append(p.name)
            if not dry_run:
                shutil.move(str(p), str(ARCHIVE_DIR / p.name))
    # also archive memory/archive if exists
    mem_arch = PROJECT_ROOT / "memory" / "archive"
    if mem_arch.exists():
        target = ARCHIVE_DIR / "memory_archive"
        if not dry_run:
            shutil.move(str(mem_arch), str(target))
        archived.append("memory/archive/")
    return archived


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--default-tag", default="usa_top3000")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-archive", action="store_true")
    args = ap.parse_args()

    print(f"[migrate] default_tag={args.default_tag} dry_run={args.dry_run}")

    n_alphas = migrate_alphas(args.default_tag, args.dry_run)
    print(f"[migrate] alphas migrated: {n_alphas}")

    moved_mem = migrate_memory_files(args.default_tag, args.dry_run)
    print(f"[migrate] memory files moved into memory/{args.default_tag}/: {len(moved_mem)} -> {moved_mem}")

    if not args.skip_archive:
        archived = archive_old_data(args.dry_run)
        print(f"[migrate] old data archived: {archived}")
    print("[migrate] DONE" + (" (dry-run, no changes)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
