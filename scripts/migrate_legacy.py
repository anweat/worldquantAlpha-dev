"""migrate_legacy.py — One-time legacy data migration (Phase 1 verification).

Discovers and migrates pre-bus artifacts from archive/ into the new wq-bus schema.

Jobs:
  A. Discover legacy artifacts (DBs, JSONs, MDs, PDFs).
  B. Migrate alphas from legacy DBs → new alphas table.
  C. Migrate session/cookie files → .state/.
  D. Migrate crawler docs → crawl_docs table + crawl_summaries placeholder.
  E. Output test_results/legacy_migration_report.{json,md}.

Usage:
    python scripts/migrate_legacy.py [--dry-run] [--json]
    python scripts/migrate_legacy.py --dry-run   # sanity check first
    python scripts/migrate_legacy.py             # run for real
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

ARCHIVE_ROOT = _ROOT / "archive"
DATA_DIR = _ROOT / "data"
STATE_DIR = _ROOT / ".state"
MEMORY_ROOT = _ROOT / "memory"
REPORT_DIR = _ROOT / "test_results"
LEGACY_MEM_DIR = MEMORY_ROOT / "_legacy"
LEGACY_PDFS_DIR = DATA_DIR / "legacy" / "pdfs"

DEFAULT_TAG = "USA_TOP3000"
MIGRATION_TRACE_ID = f"tr_legacy_migration_{int(time.time())}"

# Default simulation settings (matches BrainClient.DEFAULT_SETTINGS)
_DEFAULTS: dict[str, Any] = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 4,
    "neutralization": "MARKET",
    "truncation": 0.05,
    "pasteurization": "ON",
    "nanHandling": "OFF",
    "unitHandling": "VERIFY",
    "language": "FASTEXPR",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _settings_hash(settings: dict) -> str:
    canonical = json.dumps(settings, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode()).hexdigest()


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def _tag_from_settings(settings: dict) -> str:
    region = str(settings.get("region", "USA")).upper()
    universe = str(settings.get("universe", "TOP3000")).upper().replace(" ", "")
    tag = f"{region}_{universe}"
    # Validate tag regex
    if re.match(r"^[A-Z]+_[A-Z0-9]+$", tag):
        return tag
    return DEFAULT_TAG


# ---------------------------------------------------------------------------
# JSON file bucket classification
# ---------------------------------------------------------------------------

def _bucket_json(path: Path, data: Any) -> str:
    """Classify a JSON file by its likely content type."""
    name = path.name.lower()
    # Name-based fast paths
    if any(k in name for k in ("crawl_summary", "crawl2", "crawl3", "crawl_partial")):
        return "crawl-doc"
    if any(k in name for k in ("failure_pattern",)):
        return "failure"
    if any(k in name for k in ("submission_log", "submission_retry", "submission_queue")):
        return "submission-queue"
    if any(k in name for k in ("daily_context",)):
        return "pipeline-state"
    if any(k in name for k in ("portfolio", "unsubmitted_analysis")):
        return "portfolio"
    if any(k in name for k in ("wave", "alpha_result", "agent_analyst", "unsubmitted_alpha")):
        return "alpha-list"
    # Content-based
    if isinstance(data, list) and data and isinstance(data[0], dict):
        keys = set(data[0].keys())
        if "id" in keys and ("regular" in keys or "expr" in keys or "expression" in keys):
            return "alpha-list"
        if "alpha_id" in keys or "expr" in keys:
            return "alpha-list"
    if isinstance(data, dict):
        keys = set(data.keys())
        if keys & {"generated", "source_sample_size", "fail_counts_top", "patterns"}:
            return "failure"
        if keys & {"report_date", "today_stats", "kb_stats"}:
            return "pipeline-state"
        if keys & {"crawled_at", "pages_crawled", "new_alpha_examples"}:
            return "crawl-doc"
        if keys & {"alpha_id", "sharpe", "fitness", "status"}:
            return "submission-queue"
        if keys & {"portfolio", "directions", "gap_analysis"}:
            return "portfolio"
        if "url" in keys and "raw_text" in keys:
            return "crawl-doc"
    return "unknown"


# ---------------------------------------------------------------------------
# Crawl topic classification
# ---------------------------------------------------------------------------

_TOPIC_KEYWORDS = {
    "alpha": [
        r"group_rank", r"ts_rank", r"rank\(", r"fastexpr", r"sharpe", r"fitness",
        r"alpha\s+expression", r"investment logic",
    ],
    "dataset": [
        r"data\s*field", r"dataset", r"universe", r"top3000", r"top500", r"market\s*cap",
    ],
    "fundamentals": [
        r"revenue", r"assets", r"liabilities", r"eps", r"earnings", r"fundamental",
        r"cash_flow", r"operating_income",
    ],
    "momentum": [
        r"momentum", r"trend", r"moving.average", r"price\s+action", r"breakout",
    ],
    "volatility": [
        r"volatility", r"std_dev", r"beta", r"vix", r"drawdown", r"atr",
    ],
    "news": [
        r"news", r"sentiment", r"nlp", r"language\s+model", r"text\s+mining",
    ],
}


def _classify_crawl_topic(url: str, text: str = "") -> str:
    content = (url + " " + text).lower()
    for topic, patterns in _TOPIC_KEYWORDS.items():
        if any(re.search(p, content) for p in patterns):
            return topic
    return "unknown"


# ---------------------------------------------------------------------------
# A. Discovery
# ---------------------------------------------------------------------------

def discover_artifacts(dry_run: bool, log: list) -> dict:
    """Discover all legacy artifacts in archive/."""
    dbs: list[Path] = []
    jsons: list[Path] = []
    mds: list[Path] = []
    pdfs: list[Path] = []

    for f in ARCHIVE_ROOT.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext == ".db":
            dbs.append(f)
        elif ext == ".json":
            jsons.append(f)
        elif ext == ".md":
            mds.append(f)
        elif ext == ".pdf":
            pdfs.append(f)

    # DB info
    db_info: list[dict] = []
    for db_path in dbs:
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            tbl_info = []
            for tbl in tables:
                tname = tbl[0]
                if tname.startswith("sqlite_"):
                    continue
                try:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
                except Exception:
                    count = -1
                tbl_info.append({"table": tname, "rows": count})
            conn.close()
            db_info.append({"path": str(db_path.relative_to(_ROOT)), "tables": tbl_info})
        except Exception as e:
            db_info.append({"path": str(db_path.relative_to(_ROOT)), "error": str(e)})

    # JSON bucket counts
    json_buckets: dict[str, int] = {}
    json_file_info: list[dict] = []
    for jp in jsons:
        try:
            data = json.loads(jp.read_text(encoding="utf-8", errors="replace"))
            bucket = _bucket_json(jp, data)
        except Exception:
            bucket = "unreadable"
        json_buckets[bucket] = json_buckets.get(bucket, 0) + 1
        json_file_info.append({
            "path": str(jp.relative_to(_ROOT)),
            "bucket": bucket,
        })

    log.append(f"Discovered {len(dbs)} DBs, {len(jsons)} JSONs, {len(mds)} MDs, {len(pdfs)} PDFs")

    return {
        "dbs": db_info,
        "json_files": json_file_info,
        "json_buckets": json_buckets,
        "md_paths": [str(p.relative_to(_ROOT)) for p in mds],
        "pdf_paths": [str(p.relative_to(_ROOT)) for p in pdfs],
        "counts": {
            "dbs": len(dbs),
            "jsons": len(jsons),
            "mds": len(mds),
            "pdfs": len(pdfs),
        },
        "_raw_dbs": dbs,
        "_raw_jsons": jsons,
        "_raw_mds": mds,
        "_raw_pdfs": pdfs,
        "_raw_json_info": json_file_info,
    }


# ---------------------------------------------------------------------------
# B. Alpha migration
# ---------------------------------------------------------------------------

def _merge_settings(legacy_partial: dict) -> dict:
    """Merge legacy partial settings with full defaults."""
    merged = dict(_DEFAULTS)
    # Override with legacy values (keep partial settings)
    for key, val in legacy_partial.items():
        # Map old key names
        if key == "region":
            merged["region"] = val
        elif key == "universe":
            merged["universe"] = val
        else:
            merged[key] = val
    return merged


def _migrate_alpha_row(
    alpha_id: str,
    expression: str,
    settings: dict,
    *,
    sharpe: float | None,
    fitness: float | None,
    turnover: float | None,
    returns: float | None = None,
    drawdown: float | None = None,
    submitted: bool = False,
    checks_pass: bool = False,
    tag: str = DEFAULT_TAG,
    conn_kno: sqlite3.Connection,
    dry_run: bool,
    errors: list,
) -> bool:
    """Insert one alpha into the new alphas table. Returns True if inserted."""
    try:
        full_settings = _merge_settings(settings)
        sh = _settings_hash(full_settings)

        # Feature vector + direction_id via dimensions
        try:
            from wq_bus.domain import dimensions
            is_metrics_for_classify = {
                "sharpe": sharpe, "fitness": fitness, "turnover": turnover
            } if any(v is not None for v in [sharpe, fitness, turnover]) else None
            fv = dimensions.classify(expression, full_settings, is_metrics_for_classify)
            direction_id = dimensions.project_id(fv)
            fv_json = json.dumps(fv, default=str)
        except Exception as e:
            direction_id = "unknown"
            fv_json = "{}"
            errors.append(f"classify error for {alpha_id}: {e}")

        # Themes via recipes
        try:
            from wq_bus.domain import recipes
            tc = recipes.themes_csv(expression)
        except Exception:
            tc = None

        # Status
        if submitted:
            status = "submitted"
        elif checks_pass:
            status = "is_passed"
        else:
            status = "simulated"

        # IS metrics
        is_metrics: dict[str, Any] = {}
        if sharpe is not None:
            is_metrics["sharpe"] = sharpe
        if fitness is not None:
            is_metrics["fitness"] = fitness
        if turnover is not None:
            is_metrics["turnover"] = turnover
        if returns is not None:
            is_metrics["returns"] = returns
        if drawdown is not None:
            is_metrics["drawdown"] = drawdown
        is_json = json.dumps(is_metrics) if is_metrics else None

        now = time.time()

        if not dry_run:
            conn_kno.execute(
                """INSERT OR IGNORE INTO alphas
                   (alpha_id, dataset_tag, expression, settings_json, settings_hash,
                    is_metrics_json, status, sharpe, fitness, turnover, sc_value,
                    created_at, updated_at, direction_id, feature_vector_json,
                    themes_csv, trace_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?)""",
                (
                    alpha_id, tag, expression,
                    json.dumps(full_settings, ensure_ascii=False),
                    sh, is_json, status,
                    sharpe, fitness, turnover,
                    now, now,
                    direction_id, fv_json, tc,
                    MIGRATION_TRACE_ID,
                ),
            )
            return True
        else:
            return True  # dry-run: count as would-be-inserted
    except Exception as e:
        errors.append(f"Error migrating alpha {alpha_id}: {e}")
        return False


def _get_or_open_knowledge() -> sqlite3.Connection:
    from wq_bus.data._sqlite import open_knowledge, ensure_migrated
    ensure_migrated()
    return open_knowledge()


def migrate_alphas_from_db(
    db_path: Path,
    dry_run: bool,
    log: list,
    errors: list,
) -> dict:
    """Migrate alphas from a legacy alpha_kb.db / unified_kb.db."""
    result = {
        "source": str(db_path.relative_to(_ROOT)),
        "found": 0,
        "inserted": 0,
        "skipped": 0,
        "errors": [],
    }
    try:
        src_conn = sqlite3.connect(str(db_path))
        src_conn.row_factory = sqlite3.Row

        # Check which table name contains alphas
        tables = [r[0] for r in src_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]

        if "alphas" not in tables:
            log.append(f"  No 'alphas' table in {db_path.name} — skipping")
            src_conn.close()
            return result

        rows = src_conn.execute("SELECT * FROM alphas").fetchall()
        result["found"] = len(rows)
        log.append(f"  {db_path.name}: found {len(rows)} alpha rows")

        if not dry_run:
            kno_conn = _get_or_open_knowledge()
        else:
            kno_conn = None

        # Workspace ensure (for pool stats + direction tables)
        if not dry_run:
            from wq_bus.data import workspace
            workspace.ensure(DEFAULT_TAG)

        direction_counts: dict[str, int] = {}

        for row in rows:
            row_dict = dict(row)
            alpha_id = row_dict.get("id") or row_dict.get("alpha_id")
            expression = row_dict.get("expr") or row_dict.get("expression") or ""
            if not alpha_id or not expression:
                result["skipped"] += 1
                continue

            # Parse legacy settings
            try:
                partial_settings = json.loads(row_dict.get("settings_json") or "{}")
            except Exception:
                partial_settings = {}

            full_settings = _merge_settings(partial_settings)
            tag = _tag_from_settings(full_settings)

            sharpe = _safe_float(row_dict.get("sharpe"))
            fitness = _safe_float(row_dict.get("fitness"))
            turnover = _safe_float(row_dict.get("turnover"))
            returns = _safe_float(row_dict.get("returns"))
            drawdown = _safe_float(row_dict.get("drawdown"))
            submitted = bool(row_dict.get("submitted"))
            checks_pass = bool(row_dict.get("checks_pass"))

            if not dry_run and kno_conn is not None:
                ok = _migrate_alpha_row(
                    alpha_id, expression, partial_settings,
                    sharpe=sharpe, fitness=fitness, turnover=turnover,
                    returns=returns, drawdown=drawdown,
                    submitted=submitted, checks_pass=checks_pass,
                    tag=tag, conn_kno=kno_conn,
                    dry_run=False, errors=errors,
                )
                if ok:
                    result["inserted"] += 1
                    # Track direction_id for pool stats
                    try:
                        from wq_bus.domain import dimensions
                        fv = dimensions.classify(expression, full_settings)
                        did = dimensions.project_id(fv)
                        direction_counts[did] = direction_counts.get(did, 0) + 1
                    except Exception:
                        pass
                else:
                    result["skipped"] += 1
            else:
                result["inserted"] += 1  # dry-run count

        # Bump pool stats per direction
        if not dry_run:
            kno_conn.close()
            kno_conn2 = _get_or_open_knowledge()
            for did, count in direction_counts.items():
                try:
                    from wq_bus.domain import dimensions
                    # Build a sample fv from the direction_id
                    parts = did.split("|")
                    if len(parts) >= 4:
                        fv = {
                            "data_field_class": parts[0],
                            "operator_class": parts[1],
                            "neutralization": parts[2],
                            "decay_band": parts[3],
                            "turnover_band": "5-30%",
                        }
                        sem = dimensions.semantic_name(did)
                        from wq_bus.data import workspace
                        workspace.upsert_direction(
                            DEFAULT_TAG, did, fv,
                            semantic_name=sem,
                            origin="legacy_migration",
                        )
                        workspace.bump_stats(
                            DEFAULT_TAG, did,
                            alphas_tried=count,
                        )
                except Exception as e:
                    errors.append(f"pool_stats bump error for {did}: {e}")
            kno_conn2.close()

        src_conn.close()

    except Exception as e:
        result["errors"].append(str(e))
        errors.append(f"DB migration error {db_path.name}: {e}")

    return result


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def migrate_alphas_from_brain_json(
    json_path: Path,
    dry_run: bool,
    log: list,
    errors: list,
) -> dict:
    """Migrate BRAIN-format alpha list JSONs (unsubmitted_alphas*.json)."""
    result = {
        "source": str(json_path.relative_to(_ROOT)),
        "found": 0,
        "inserted": 0,
        "skipped": 0,
    }
    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list):
            return result

        result["found"] = len(data)

        if not dry_run:
            kno_conn = _get_or_open_knowledge()
            from wq_bus.data import workspace
            workspace.ensure(DEFAULT_TAG)

        for item in data:
            if not isinstance(item, dict):
                result["skipped"] += 1
                continue
            alpha_id = item.get("id")
            regular = item.get("regular") or {}
            expression = regular.get("code") or item.get("expr") or item.get("expression")
            if not alpha_id or not expression:
                result["skipped"] += 1
                continue

            settings = item.get("settings") or {}
            is_data = item.get("is") or {}
            sharpe = _safe_float(is_data.get("sharpe"))
            fitness = _safe_float(is_data.get("fitness"))
            turnover = _safe_float(is_data.get("turnover"))
            returns = _safe_float(is_data.get("returns"))
            drawdown = _safe_float(is_data.get("drawdown"))
            submitted = item.get("dateSubmitted") is not None
            stage = item.get("stage", "")
            checks_pass = stage in ("SELF_CORRELATION", "SUBMISSION")

            tag = _tag_from_settings(settings)

            if not dry_run:
                ok = _migrate_alpha_row(
                    alpha_id, expression, settings,
                    sharpe=sharpe, fitness=fitness, turnover=turnover,
                    returns=returns, drawdown=drawdown,
                    submitted=submitted, checks_pass=checks_pass,
                    tag=tag, conn_kno=kno_conn,
                    dry_run=False, errors=errors,
                )
                if ok:
                    result["inserted"] += 1
                else:
                    result["skipped"] += 1
            else:
                result["inserted"] += 1

        if not dry_run:
            kno_conn.close()

    except Exception as e:
        result["errors"] = [str(e)]
        errors.append(f"JSON alpha migration error {json_path.name}: {e}")

    return result


# ---------------------------------------------------------------------------
# C. Session/cookie migration
# ---------------------------------------------------------------------------

def migrate_session(dry_run: bool, log: list, errors: list) -> dict:
    """Migrate session/credential files to .state/."""
    result: dict[str, Any] = {
        "actions": [],
        "auth_check": "skipped",
    }

    STATE_DIR.mkdir(exist_ok=True)

    # Files to migrate: check test_results/ and other legacy locations
    candidates = [
        (_ROOT / "test_results" / "session.json", STATE_DIR / "session.json"),
        (_ROOT / "test_results" / "credentials.json", STATE_DIR / "credentials.json"),
    ]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    for src, dst in candidates:
        if not src.exists():
            if dst.exists():
                result["actions"].append(
                    f"{src.name}: already in .state/ (legacy source not found)"
                )
                log.append(f"  {src.name}: already at .state/ — no action needed")
            else:
                result["actions"].append(f"{src.name}: not found in test_results/ or .state/")
                log.append(f"  WARN: {src.name} not found anywhere")
            continue

        if dst.exists():
            # Backup legacy to .state/legacy_<ts>_*
            backup = STATE_DIR / f"legacy_{ts}_{src.name}"
            if not dry_run:
                shutil.copy2(src, backup)
            result["actions"].append(
                f"{src.name}: .state/ already exists; backed up legacy to {backup.name}"
            )
            log.append(f"  {src.name}: existing .state/ preserved; legacy backed up")
        else:
            if not dry_run:
                shutil.move(str(src), str(dst))
            result["actions"].append(
                f"{src.name}: moved test_results/{src.name} → .state/{src.name}"
            )
            log.append(f"  {src.name}: moved to .state/")

    # Validate session (don't call real API — just check file readability)
    session_file = STATE_DIR / "session.json"
    if session_file.exists():
        try:
            sess_data = json.loads(session_file.read_text(encoding="utf-8"))
            has_cookies = bool(sess_data.get("cookies") or sess_data.get("cookie"))
            result["auth_check"] = (
                "session_file_readable_with_cookies" if has_cookies
                else "session_file_readable_no_cookies"
            )
            log.append(f"  Session file readable; has_cookies={has_cookies}")
        except Exception as e:
            result["auth_check"] = f"session_file_unreadable: {e}"
            log.append(f"  WARN: session file unreadable: {e}")
    else:
        result["auth_check"] = "session_file_missing"
        log.append("  WARN: no session file found in .state/")

    return result


# ---------------------------------------------------------------------------
# D. Crawl doc migration
# ---------------------------------------------------------------------------

def migrate_crawl_docs(
    artifacts: dict,
    dry_run: bool,
    log: list,
    errors: list,
) -> dict:
    """Migrate crawler docs from legacy DBs and JSON crawl files into crawl_docs."""
    result = {
        "from_db": {"found": 0, "inserted": 0, "errors": []},
        "from_json": {"found": 0, "inserted": 0, "errors": []},
        "crawl_summaries_inserted": 0,
        "md_crawl_docs": {"found": 0, "inserted": 0},
    }

    if not dry_run:
        from wq_bus.data._sqlite import open_knowledge, ensure_migrated
        ensure_migrated()
        kno_conn = open_knowledge()
        from wq_bus.data import workspace
        workspace.ensure(DEFAULT_TAG)

    now = time.time()
    batch_url_hashes: list[str] = []

    # --- From crawl_state.db ---
    crawl_db_paths = [
        ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "crawl_state.db",
        ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "unified_kb.db",
    ]

    seen_url_hashes: set[str] = set()

    for db_path in crawl_db_paths:
        if not db_path.exists():
            continue
        try:
            src = sqlite3.connect(str(db_path))
            src.row_factory = sqlite3.Row
            tables = [r[0] for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]

            if "crawl_queue" in tables:
                rows = src.execute("SELECT * FROM crawl_queue").fetchall()
                for row in rows:
                    rd = dict(row)
                    url = rd.get("url") or rd.get("url_hash") or ""
                    if not url:
                        continue
                    uh = _url_hash(url)
                    if uh in seen_url_hashes:
                        continue
                    seen_url_hashes.add(uh)
                    result["from_db"]["found"] += 1

                    title = rd.get("title") or url[:80]
                    body_md = f"[Legacy crawl archive — content_path: {rd.get('content_path', 'N/A')}]"
                    fetched_at = _parse_ts(rd.get("crawled_at"))
                    topic = _classify_crawl_topic(url)
                    meta = {
                        "legacy_source": db_path.name,
                        "topic": topic,
                        "status": rd.get("status"),
                        "depth": rd.get("depth"),
                    }

                    if not dry_run:
                        try:
                            kno_conn.execute(
                                """INSERT OR IGNORE INTO crawl_docs
                                   (url_hash, dataset_tag, source, url, title, body_md,
                                    fetched_at, summarized, meta_json)
                                   VALUES (?,?,?,?,?,?,?,?,?)""",
                                (uh, DEFAULT_TAG, "legacy_archive", url, title, body_md,
                                 fetched_at, "pending",
                                 json.dumps(meta, ensure_ascii=False)),
                            )
                            result["from_db"]["inserted"] += 1
                            batch_url_hashes.append(uh)
                        except Exception as e:
                            result["from_db"]["errors"].append(f"{url[:60]}: {e}")
                    else:
                        result["from_db"]["inserted"] += 1
                        batch_url_hashes.append(uh)

            src.close()
        except Exception as e:
            result["from_db"]["errors"].append(f"{db_path.name}: {e}")
            errors.append(f"crawl_db error: {e}")

    # --- From crawl_manual/*.json and spa_crawl/*.json ---
    crawl_json_dirs = [
        ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "crawl_manual",
        ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "spa_crawl",
    ]

    for crawl_dir in crawl_json_dirs:
        if not crawl_dir.exists():
            continue
        for jp in crawl_dir.glob("*.json"):
            try:
                data = json.loads(jp.read_text(encoding="utf-8", errors="replace"))
                if not isinstance(data, dict):
                    continue
                url = data.get("url") or jp.stem
                uh = _url_hash(url)
                if uh in seen_url_hashes:
                    continue
                seen_url_hashes.add(uh)
                result["from_json"]["found"] += 1

                title = data.get("title") or jp.stem
                raw_text = data.get("raw_text") or data.get("body_md") or ""
                # Compose body_md from available fields
                expressions_found = data.get("alpha_expressions_found") or []
                operators = data.get("operators_mentioned") or []
                fields = data.get("data_fields_mentioned") or []
                body_md = f"# {title}\n\n**URL**: {url}\n\n"
                if raw_text:
                    body_md += f"## Content\n{raw_text[:4000]}\n\n"
                if expressions_found:
                    body_md += f"## Alpha Expressions Found\n"
                    for expr in expressions_found[:10]:
                        body_md += f"- `{expr}`\n"
                    body_md += "\n"
                if operators:
                    body_md += f"## Operators Mentioned\n{', '.join(str(o) for o in operators[:20])}\n\n"
                if fields:
                    body_md += f"## Data Fields Mentioned\n{', '.join(str(f) for f in fields[:20])}\n\n"

                crawled_at_str = data.get("crawled_at") or ""
                fetched_at = _parse_ts(crawled_at_str)
                topic = _classify_crawl_topic(url, raw_text)
                meta = {
                    "legacy_source": f"{crawl_dir.name}/{jp.name}",
                    "topic": topic,
                    "expressions_count": len(expressions_found),
                }

                if not dry_run:
                    try:
                        kno_conn.execute(
                            """INSERT OR IGNORE INTO crawl_docs
                               (url_hash, dataset_tag, source, url, title, body_md,
                                fetched_at, summarized, meta_json)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (uh, DEFAULT_TAG, "legacy_archive", url, title, body_md,
                             fetched_at, "pending",
                             json.dumps(meta, ensure_ascii=False)),
                        )
                        result["from_json"]["inserted"] += 1
                        batch_url_hashes.append(uh)
                    except Exception as e:
                        result["from_json"]["errors"].append(f"{jp.name}: {e}")
                else:
                    result["from_json"]["inserted"] += 1
                    batch_url_hashes.append(uh)

            except Exception as e:
                result["from_json"]["errors"].append(f"{jp.name}: {e}")

    # --- Crawl JSON summary files (crawl2_summary.json, etc.) ---
    for json_info in artifacts.get("_raw_json_info", []):
        if json_info.get("bucket") != "crawl-doc":
            continue
        jp = _ROOT / json_info["path"]
        if not jp.exists() or jp.parent.name in ("crawl_manual", "spa_crawl"):
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, dict):
                continue
            url = data.get("url") or f"legacy://archive/{jp.name}"
            uh = _url_hash(url)
            if uh in seen_url_hashes:
                continue
            seen_url_hashes.add(uh)
            result["from_json"]["found"] += 1

            body_parts = [f"# {jp.stem} (Legacy Crawl Summary)\n"]
            for key, val in data.items():
                if isinstance(val, (str, int, float)):
                    body_parts.append(f"**{key}**: {val}\n")
                elif isinstance(val, list) and val:
                    body_parts.append(f"## {key}\n")
                    for item in val[:10]:
                        body_parts.append(f"- {item}\n")
                elif isinstance(val, dict):
                    body_parts.append(f"## {key}\n```json\n{json.dumps(val, indent=2)[:500]}\n```\n")
            body_md = "".join(body_parts)[:8000]

            fetched_at = _parse_ts(data.get("generated_at") or data.get("crawled_at") or "")
            topic = _classify_crawl_topic(url, body_md)
            meta = {"legacy_source": str(jp.relative_to(_ROOT)), "topic": topic}

            if not dry_run:
                try:
                    kno_conn.execute(
                        """INSERT OR IGNORE INTO crawl_docs
                           (url_hash, dataset_tag, source, url, title, body_md,
                            fetched_at, summarized, meta_json)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (uh, DEFAULT_TAG, "legacy_archive", url, jp.stem, body_md,
                         fetched_at, "pending",
                         json.dumps(meta, ensure_ascii=False)),
                    )
                    result["from_json"]["inserted"] += 1
                    batch_url_hashes.append(uh)
                except Exception as e:
                    result["from_json"]["errors"].append(f"{jp.name}: {e}")
            else:
                result["from_json"]["inserted"] += 1
                batch_url_hashes.append(uh)

        except Exception as e:
            result["from_json"]["errors"].append(f"{jp.name}: {e}")

    # --- MD files containing "crawl" keyword ---
    for md_rel in artifacts.get("md_paths", []):
        md_path = _ROOT / md_rel
        try:
            content = md_path.read_text(encoding="utf-8", errors="replace")
            if "crawl" not in content.lower():
                continue
            url = f"legacy://archive/md/{md_path.name}"
            uh = _url_hash(url)
            if uh in seen_url_hashes:
                continue
            seen_url_hashes.add(uh)
            result["md_crawl_docs"]["found"] += 1

            topic = _classify_crawl_topic(url, content)
            meta = {"legacy_source": md_rel, "topic": topic, "file_type": "markdown"}

            if not dry_run:
                try:
                    kno_conn.execute(
                        """INSERT OR IGNORE INTO crawl_docs
                           (url_hash, dataset_tag, source, url, title, body_md,
                            fetched_at, summarized, meta_json)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (uh, DEFAULT_TAG, "legacy_archive", url, md_path.name,
                         content[:8000], now, "pending",
                         json.dumps(meta, ensure_ascii=False)),
                    )
                    result["md_crawl_docs"]["inserted"] += 1
                    batch_url_hashes.append(uh)
                except Exception as e:
                    errors.append(f"MD crawl doc error {md_path.name}: {e}")
            else:
                result["md_crawl_docs"]["inserted"] += 1
                batch_url_hashes.append(uh)
        except Exception:
            pass

    # Insert crawl_summaries placeholder per batch
    total_crawl = len(batch_url_hashes)
    if total_crawl > 0 and not dry_run:
        try:
            scope = f"legacy-migration-{int(now)}"
            summary_md = (
                f"# Legacy Migration Placeholder\n\n"
                f"Batch: {scope}\n"
                f"Docs: {total_crawl} ingested from archive/ on {_utcnow()}\n\n"
                f"**To summarize**: Run `wqbus drain-docs --dataset {DEFAULT_TAG} --max-batches 5`\n"
            )
            kno_conn.execute(
                """INSERT INTO crawl_summaries
                   (dataset_tag, scope, summary_md, doc_ids_json, created_at)
                   VALUES (?,?,?,?,?)""",
                (DEFAULT_TAG, scope, summary_md,
                 json.dumps(batch_url_hashes[:50]),  # first 50 for brevity
                 now),
            )
            result["crawl_summaries_inserted"] = 1
        except Exception as e:
            errors.append(f"crawl_summaries placeholder error: {e}")

    if not dry_run:
        kno_conn.close()

    log.append(
        f"  Crawl docs: {result['from_db']['inserted']} from DB, "
        f"{result['from_json']['inserted']} from JSON/MD"
    )
    return result


def _parse_ts(val: Any) -> float:
    """Parse a timestamp string or float to POSIX float."""
    if not val:
        return time.time()
    if isinstance(val, (int, float)):
        return float(val)
    # Try ISO format
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            from datetime import datetime, timezone
            dt = datetime.strptime(str(val)[:19], fmt[:len(str(val)[:19])])
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            continue
    return time.time()


# ---------------------------------------------------------------------------
# MD / PDF file copies
# ---------------------------------------------------------------------------

def copy_md_files(artifacts: dict, dry_run: bool, log: list) -> dict:
    """Copy legacy MD files to memory/_legacy/ preserving relative path."""
    result = {"copied": 0, "skipped": 0, "paths": []}
    LEGACY_MEM_DIR.mkdir(parents=True, exist_ok=True)

    archive_str = str(ARCHIVE_ROOT)
    for md_rel in artifacts.get("md_paths", []):
        md_src = _ROOT / md_rel
        # Compute relative path from archive root
        try:
            rel_from_archive = Path(md_rel).relative_to("archive")
        except ValueError:
            rel_from_archive = Path(md_src.name)
        dst = LEGACY_MEM_DIR / rel_from_archive
        if dst.exists():
            result["skipped"] += 1
            continue
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(md_src, dst)
        result["copied"] += 1
        result["paths"].append(str(dst.relative_to(_ROOT)))

    log.append(f"  MD files: {result['copied']} copied to memory/_legacy/")
    return result


def copy_pdf_files(artifacts: dict, dry_run: bool, log: list) -> dict:
    """Copy PDFs to data/legacy/pdfs/ and emit LEGACY_DOC_INGESTED records."""
    result = {"copied": 0, "events_emitted": 0, "paths": []}
    LEGACY_PDFS_DIR.mkdir(parents=True, exist_ok=True)

    for pdf_rel in artifacts.get("pdf_paths", []):
        pdf_src = _ROOT / pdf_rel
        dst = LEGACY_PDFS_DIR / pdf_src.name
        if not dry_run and not dst.exists():
            shutil.copy2(pdf_src, dst)
        result["copied"] += 1
        result["paths"].append(str(dst.relative_to(_ROOT)))

        # Emit LEGACY_DOC_INGESTED event
        if not dry_run:
            try:
                from wq_bus.data.state_db import record_event
                from wq_bus.utils.tag_context import with_tag, with_trace
                with with_tag(DEFAULT_TAG):
                    with with_trace(MIGRATION_TRACE_ID):
                        record_event(
                            "LEGACY_DOC_INGESTED",
                            {
                                "source_path": pdf_rel,
                                "dest_path": str(dst.relative_to(_ROOT)),
                                "filename": pdf_src.name,
                                "size_bytes": pdf_src.stat().st_size,
                                "origin": "legacy_migration",
                            },
                            dataset_tag=DEFAULT_TAG,
                            trace_id=MIGRATION_TRACE_ID,
                        )
                result["events_emitted"] += 1
            except Exception as e:
                pass  # Non-fatal

    log.append(f"  PDFs: {result['copied']} copied to data/legacy/pdfs/")
    return result


# ---------------------------------------------------------------------------
# Main migration runner
# ---------------------------------------------------------------------------

def run_migration(dry_run: bool) -> dict:
    log: list[str] = []
    errors: list[str] = []
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "migration_trace_id": MIGRATION_TRACE_ID,
        "started_at": _utcnow(),
        "log": log,
        "errors": errors,
    }

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Legacy migration started — trace_id={MIGRATION_TRACE_ID}")

    # Ensure migrations applied
    if not dry_run:
        from wq_bus.data._sqlite import ensure_migrated
        ensure_migrated()

    # A. Discover
    print("\n[A] Discovering artifacts...")
    artifacts = discover_artifacts(dry_run, log)
    report["discovery"] = {
        "counts": artifacts["counts"],
        "db_info": artifacts["dbs"],
        "json_buckets": artifacts["json_buckets"],
        "md_count": len(artifacts["md_paths"]),
        "pdf_count": len(artifacts["pdf_paths"]),
    }
    print(
        f"  DBs:{artifacts['counts']['dbs']} "
        f"JSONs:{artifacts['counts']['jsons']} "
        f"MDs:{artifacts['counts']['mds']} "
        f"PDFs:{artifacts['counts']['pdfs']}"
    )
    print(f"  JSON buckets: {artifacts['json_buckets']}")

    # B. Migrate alphas from DBs
    print("\n[B] Migrating alphas from legacy DBs...")
    alpha_results: list[dict] = []
    seen_alpha_ids: set[str] = set()

    # Primary: alpha_kb.db (most complete with all columns)
    alpha_db = ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "alpha_kb.db"
    if alpha_db.exists():
        r = migrate_alphas_from_db(alpha_db, dry_run, log, errors)
        alpha_results.append(r)
        print(f"  alpha_kb.db: found={r['found']}, inserted={r['inserted']}, skipped={r['skipped']}")

    # unified_kb.db also has alphas — likely duplicates, dedup handled by INSERT OR IGNORE
    unified_db = ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "unified_kb.db"
    if unified_db.exists():
        r = migrate_alphas_from_db(unified_db, dry_run, log, errors)
        alpha_results.append(r)
        print(f"  unified_kb.db: found={r['found']}, inserted={r['inserted']}, skipped={r['skipped']}")

    # Migrate BRAIN-format JSON alpha lists
    brain_json_files = [
        ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "unsubmitted_alphas_all.json",
        ARCHIVE_ROOT / "2026-04-26_pre_bus" / "data_and_memory" / "unsubmitted_alphas.json",
    ]
    for bjf in brain_json_files:
        if bjf.exists():
            r = migrate_alphas_from_brain_json(bjf, dry_run, log, errors)
            alpha_results.append(r)
            print(f"  {bjf.name}: found={r['found']}, inserted={r['inserted']}")

    report["alpha_migration"] = alpha_results

    # C. Session migration
    print("\n[C] Migrating session files...")
    session_result = migrate_session(dry_run, log, errors)
    report["session_migration"] = session_result
    for action in session_result["actions"]:
        print(f"  {action}")

    # D. Crawl docs
    print("\n[D] Migrating crawl docs...")
    crawl_result = migrate_crawl_docs(artifacts, dry_run, log, errors)
    report["crawl_migration"] = crawl_result
    total_crawl = (
        crawl_result["from_db"]["inserted"] +
        crawl_result["from_json"]["inserted"] +
        crawl_result["md_crawl_docs"]["inserted"]
    )
    print(f"  Total crawl docs inserted: {total_crawl}")

    # MD + PDF copies
    print("\n[E] Copying MD/PDF files...")
    md_result = copy_md_files(artifacts, dry_run, log)
    pdf_result = copy_pdf_files(artifacts, dry_run, log)
    report["md_copy"] = md_result
    report["pdf_copy"] = pdf_result
    print(f"  MDs copied: {md_result['copied']}, PDFs: {pdf_result['copied']}")

    # Finalize
    report["finished_at"] = _utcnow()
    report["summary"] = {
        "total_alphas_inserted": sum(r.get("inserted", 0) for r in alpha_results),
        "total_crawl_docs_inserted": total_crawl,
        "crawl_summaries_placeholder": crawl_result.get("crawl_summaries_inserted", 0),
        "md_files_copied": md_result["copied"],
        "pdf_files_copied": pdf_result["copied"],
        "total_errors": len(errors),
    }
    report["drain_docs_instruction"] = (
        "To summarize legacy crawl docs: "
        f"run `wqbus drain-docs --dataset {DEFAULT_TAG} --max-batches 5`"
    )

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Migration complete!")
    print(f"  Alphas: {report['summary']['total_alphas_inserted']}")
    print(f"  Crawl docs: {report['summary']['total_crawl_docs_inserted']}")
    print(f"  Errors: {report['summary']['total_errors']}")
    if errors:
        for e in errors[:5]:
            print(f"  ERROR: {e}")

    return report


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_reports(report: dict) -> None:
    """Write JSON and Markdown reports to test_results/."""
    REPORT_DIR.mkdir(exist_ok=True)

    # JSON
    json_path = REPORT_DIR / "legacy_migration_report.json"
    # Remove internal _raw_* keys
    clean = {k: v for k, v in report.items() if not k.startswith("_")}
    json_path.write_text(
        json.dumps(clean, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\nReport saved: {json_path}")

    # Markdown
    md_path = REPORT_DIR / "legacy_migration_report.md"
    s = report.get("summary", {})
    disc = report.get("discovery", {})
    dry_note = " **(DRY RUN)**" if report.get("dry_run") else ""

    lines = [
        f"# Legacy Migration Report{dry_note}",
        "",
        f"**Generated**: {report.get('finished_at', _utcnow())}  ",
        f"**Trace ID**: `{report.get('migration_trace_id')}`  ",
        f"**Mode**: {'DRY RUN' if report.get('dry_run') else 'LIVE'}  ",
        "",
        "---",
        "",
        "## Discovery Summary",
        "",
        f"| Type | Count |",
        "| --- | --- |",
        f"| SQLite DBs | {disc.get('counts', {}).get('dbs', 0)} |",
        f"| JSON files | {disc.get('counts', {}).get('jsons', 0)} |",
        f"| Markdown files | {disc.get('counts', {}).get('mds', 0)} |",
        f"| PDF files | {disc.get('counts', {}).get('pdfs', 0)} |",
        "",
        "### JSON Bucket Breakdown",
        "",
        "| Bucket | Count |",
        "| --- | --- |",
    ]
    for bucket, count in sorted(disc.get("json_buckets", {}).items()):
        lines.append(f"| {bucket} | {count} |")

    lines += [
        "",
        "### DB Contents",
        "",
    ]
    for db in disc.get("db_info", []):
        lines.append(f"**{db['path']}**")
        for tbl in db.get("tables", []):
            lines.append(f"- `{tbl['table']}`: {tbl['rows']} rows")
        lines.append("")

    lines += [
        "---",
        "",
        "## Alpha Migration",
        "",
        "| Source | Found | Inserted | Skipped |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.get("alpha_migration", []):
        src = Path(r.get("source", "?")).name
        lines.append(f"| {src} | {r.get('found',0)} | {r.get('inserted',0)} | {r.get('skipped',0)} |")

    lines += [
        "",
        "**Total alphas inserted**: " + str(s.get("total_alphas_inserted", 0)),
        "",
        "---",
        "",
        "## Crawl Doc Migration",
        "",
    ]
    cm = report.get("crawl_migration", {})
    lines += [
        f"| Source | Found | Inserted |",
        "| --- | --- | --- |",
        f"| Legacy DBs (crawl_queue) | {cm.get('from_db', {}).get('found', 0)} | {cm.get('from_db', {}).get('inserted', 0)} |",
        f"| JSON crawl files | {cm.get('from_json', {}).get('found', 0)} | {cm.get('from_json', {}).get('inserted', 0)} |",
        f"| MD files (crawl keyword) | {cm.get('md_crawl_docs', {}).get('found', 0)} | {cm.get('md_crawl_docs', {}).get('inserted', 0)} |",
        "",
        f"**crawl_summaries placeholders**: {cm.get('crawl_summaries_inserted', 0)}  ",
        f"**Next step**: `wqbus drain-docs --dataset {DEFAULT_TAG} --max-batches 5`",
        "",
        "---",
        "",
        "## Session Migration",
        "",
    ]
    sm = report.get("session_migration", {})
    for action in sm.get("actions", []):
        lines.append(f"- {action}")
    lines.append(f"- Auth check: `{sm.get('auth_check', 'N/A')}`")

    lines += [
        "",
        "---",
        "",
        "## File Copies",
        "",
        f"- Markdown files copied to `memory/_legacy/`: {s.get('md_files_copied', 0)}",
        f"- PDF files copied to `data/legacy/pdfs/`: {s.get('pdf_files_copied', 0)}",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        "| --- | --- |",
        f"| Alphas inserted | {s.get('total_alphas_inserted', 0)} |",
        f"| Crawl docs inserted | {s.get('total_crawl_docs_inserted', 0)} |",
        f"| Crawl summary placeholders | {s.get('crawl_summaries_placeholder', 0)} |",
        f"| MD files copied | {s.get('md_files_copied', 0)} |",
        f"| PDF files copied | {s.get('pdf_files_copied', 0)} |",
        f"| Total errors | {s.get('total_errors', 0)} |",
        "",
    ]
    if report.get("errors"):
        lines += ["## Errors", ""]
        for err in report["errors"][:20]:
            lines.append(f"- `{err}`")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved: {md_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Legacy data migration for wq-bus Phase 1.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover and count without writing anything")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Print JSON report to stdout")
    args = parser.parse_args()

    report = run_migration(dry_run=args.dry_run)
    generate_reports(report)

    if args.output_json:
        clean = {k: v for k, v in report.items() if not k.startswith("_")}
        print(json.dumps(clean, indent=2, ensure_ascii=False, default=str))

    sys.exit(0 if not report["errors"] else 1)


if __name__ == "__main__":
    main()
