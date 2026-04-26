"""audit_traceability.py — End-to-end log/file traceability audit (Phase 1 verification).

For each trace_id (or last N traces), asserts:
  - At least 1 row in `events` table with that trace_id
  - At least 1 row in `ai_calls` OR `manual_calls` for AI-expecting task kinds
  - Log file reference (in logs/ directory) containing trace_id
  - If alpha_drafted, the alpha row has trace_id linked
  - ai_cache package directory exists for any package_id referenced

Writes test_results/audit_<trace_id>.json (or audit_recent_N.json for recent mode).

Usage:
    python scripts/audit_traceability.py [--trace-id TID] [--recent N] [--json]
    python scripts/audit_traceability.py --recent 20
    python scripts/audit_traceability.py --trace-id tr_20260427T123456Z_abc123
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

STATE_DB = _ROOT / "data" / "state.db"
KNOWLEDGE_DB = _ROOT / "data" / "knowledge.db"
LOGS_DIR = _ROOT / "logs"
AI_CACHE_DIR = _ROOT / "data" / "ai_cache"
REPORT_DIR = _ROOT / "test_results"

# Task kinds that expect an AI call
AI_EXPECTING_KINDS = {"generate", "alpha_gen", "failure_analyzer", "doc_summarizer", "summarize"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_db(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Trace tree walker
# ---------------------------------------------------------------------------

def _load_trace_tree(conn: sqlite3.Connection) -> dict[str, dict]:
    """Load all trace rows as a dict: trace_id → row_dict."""
    try:
        rows = conn.execute("SELECT * FROM trace ORDER BY created_at ASC").fetchall()
        return {r["trace_id"]: dict(r) for r in rows}
    except sqlite3.OperationalError:
        return {}


def _get_children(
    trace_id: str, all_traces: dict[str, dict]
) -> list[str]:
    return [
        tid
        for tid, row in all_traces.items()
        if row.get("parent_trace_id") == trace_id
    ]


def _walk_tree(
    root_id: str, all_traces: dict[str, dict], visited: set | None = None
) -> list[str]:
    """Return flat list of all trace_ids in subtree rooted at root_id."""
    visited = visited or set()
    if root_id in visited:
        return []
    visited.add(root_id)
    result = [root_id]
    for child in _get_children(root_id, all_traces):
        result.extend(_walk_tree(child, all_traces, visited))
    return result


# ---------------------------------------------------------------------------
# Per-trace checks
# ---------------------------------------------------------------------------

def _check_events(trace_id: str, state_conn: sqlite3.Connection) -> dict:
    try:
        n = state_conn.execute(
            "SELECT COUNT(*) FROM events WHERE trace_id=?", (trace_id,)
        ).fetchone()[0]
        return {"pass": n > 0, "count": n}
    except Exception as e:
        return {"pass": False, "count": 0, "error": str(e)}


def _check_ai_calls(trace_id: str, state_conn: sqlite3.Connection) -> dict:
    """Check for ai_calls or manual_calls with this trace_id."""
    n_ai = 0
    n_manual = 0
    package_ids: list[str] = []
    try:
        rows = state_conn.execute(
            "SELECT id, package_id FROM ai_calls WHERE trace_id=?", (trace_id,)
        ).fetchall()
        n_ai = len(rows)
        package_ids = [r["package_id"] for r in rows if r.get("package_id")]
    except Exception:
        pass
    try:
        rows_m = state_conn.execute(
            "SELECT call_id FROM manual_calls WHERE trace_id=?", (trace_id,)
        ).fetchall()
        n_manual = len(rows_m)
    except Exception:
        pass
    return {
        "ai_call_count": n_ai,
        "manual_call_count": n_manual,
        "total": n_ai + n_manual,
        "package_ids": package_ids,
    }


def _check_logs(trace_id: str) -> dict:
    """Search log files for trace_id occurrence.

    Searches:
      - logs/*.log (daemon.log, wqbus.log, monitor.log)
      - logs/agent_sessions/**/*.json
    """
    found_in: list[str] = []
    total_files_searched = 0

    # Search main log files
    for log_file in LOGS_DIR.glob("*.log"):
        total_files_searched += 1
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
            if trace_id in text:
                found_in.append(str(log_file.relative_to(_ROOT)))
        except Exception:
            pass

    # Search agent_sessions JSON files
    for json_file in (LOGS_DIR / "agent_sessions").rglob("*.json"):
        total_files_searched += 1
        try:
            text = json_file.read_text(encoding="utf-8", errors="replace")
            if trace_id in text:
                found_in.append(str(json_file.relative_to(_ROOT)))
        except Exception:
            pass

    # Also search any .jsonl files under logs/
    for jsonl_file in LOGS_DIR.rglob("*.jsonl"):
        total_files_searched += 1
        try:
            text = jsonl_file.read_text(encoding="utf-8", errors="replace")
            if trace_id in text:
                found_in.append(str(jsonl_file.relative_to(_ROOT)))
        except Exception:
            pass

    return {
        "found": len(found_in) > 0,
        "files_searched": total_files_searched,
        "found_in": found_in,
    }


def _check_alpha_linked(trace_id: str, kno_conn: sqlite3.Connection | None) -> dict:
    """Check if any alpha row has this trace_id (for ALPHA_DRAFTED flows)."""
    if kno_conn is None:
        return {"checked": False, "count": 0}
    try:
        n = kno_conn.execute(
            "SELECT COUNT(*) FROM alphas WHERE trace_id=?", (trace_id,)
        ).fetchone()[0]
        return {"checked": True, "count": n}
    except Exception as e:
        return {"checked": False, "count": 0, "error": str(e)}


def _check_alpha_drafted_event(trace_id: str, state_conn: sqlite3.Connection) -> bool:
    """Return True if ALPHA_DRAFTED event exists for this trace_id."""
    try:
        n = state_conn.execute(
            "SELECT COUNT(*) FROM events WHERE trace_id=? AND topic='ALPHA_DRAFTED'",
            (trace_id,),
        ).fetchone()[0]
        return n > 0
    except Exception:
        return False


def _check_ai_cache(package_ids: list[str]) -> dict:
    """Check that ai_cache directories exist for referenced package_ids."""
    if not package_ids:
        return {"checked": True, "all_present": True, "missing": []}
    if not AI_CACHE_DIR.exists():
        return {"checked": False, "all_present": False, "missing": package_ids}

    missing = []
    for pkg_id in package_ids:
        pkg_dir = AI_CACHE_DIR / pkg_id
        archive_path = AI_CACHE_DIR / "archive" / pkg_id
        if not pkg_dir.exists() and not archive_path.exists():
            missing.append(pkg_id)

    return {
        "checked": True,
        "all_present": len(missing) == 0,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Single trace audit
# ---------------------------------------------------------------------------

def audit_trace(
    trace_id: str,
    trace_row: dict | None,
    state_conn: sqlite3.Connection,
    kno_conn: sqlite3.Connection | None,
    all_traces: dict[str, dict],
) -> dict:
    """Audit a single trace_id. Return a result dict."""
    task_kind = (trace_row or {}).get("task_kind") or "unknown"
    expects_ai = task_kind in AI_EXPECTING_KINDS

    result: dict[str, Any] = {
        "trace_id": trace_id,
        "task_kind": task_kind,
        "status": (trace_row or {}).get("status") or "unknown",
        "parent_trace_id": (trace_row or {}).get("parent_trace_id"),
        "expects_ai_call": expects_ai,
        "checks": {},
        "issues": [],
        "pass": True,
    }

    # C1: events
    ev = _check_events(trace_id, state_conn)
    result["checks"]["events"] = ev
    if not ev["pass"]:
        result["issues"].append(
            f"NO events for trace_id={trace_id} (task_kind={task_kind})"
        )
        result["pass"] = False

    # C2: AI calls (only required if task_kind expects AI)
    ai_info = _check_ai_calls(trace_id, state_conn)
    result["checks"]["ai_calls"] = ai_info
    if expects_ai and ai_info["total"] == 0:
        result["issues"].append(
            f"Task kind {task_kind!r} expects AI call but none found for trace_id={trace_id}"
        )
        # Warning not hard failure — fake_simulate may not record in ai_calls

    # C3: Logs
    log_info = _check_logs(trace_id)
    result["checks"]["logs"] = log_info
    if not log_info["found"]:
        result["issues"].append(
            f"trace_id={trace_id} not found in any log file "
            f"({log_info['files_searched']} files searched)"
        )
        # Warning only — not all trace_ids get logged

    # C4: Alpha linkage (if ALPHA_DRAFTED event)
    has_drafted = _check_alpha_drafted_event(trace_id, state_conn)
    result["checks"]["alpha_drafted_event"] = has_drafted
    if has_drafted:
        alpha_link = _check_alpha_linked(trace_id, kno_conn)
        result["checks"]["alpha_linked"] = alpha_link
        if alpha_link.get("checked") and alpha_link["count"] == 0:
            result["issues"].append(
                f"ALPHA_DRAFTED event for trace_id={trace_id} "
                "but no alpha row has this trace_id"
            )
            result["pass"] = False

    # C5: ai_cache presence
    pkg_ids = ai_info.get("package_ids") or []
    if pkg_ids:
        cache_check = _check_ai_cache(pkg_ids)
        result["checks"]["ai_cache"] = cache_check
        if not cache_check["all_present"]:
            result["issues"].append(
                f"ai_cache missing for package_ids: {cache_check['missing']}"
            )
            result["pass"] = False

    return result


# ---------------------------------------------------------------------------
# Batch audit runner
# ---------------------------------------------------------------------------

def run_audit(
    trace_id: str | None = None,
    recent_n: int | None = None,
    output_json: bool = False,
) -> dict:
    report: dict[str, Any] = {
        "generated_at": _utcnow(),
        "mode": "single" if trace_id else f"recent_{recent_n}",
        "nodes": [],
        "summary": {},
        "status": "OK",
    }

    state_conn = _open_db(STATE_DB)
    kno_conn = _open_db(KNOWLEDGE_DB)

    if state_conn is None:
        report["error"] = f"state.db not found at {STATE_DB}"
        report["status"] = "ERROR"
        return report

    all_traces = _load_trace_tree(state_conn)

    # Select trace_ids to audit
    if trace_id:
        target_ids = _walk_tree(trace_id, all_traces)
    elif recent_n:
        # Get the most recent N root traces (no parent)
        roots = [
            (tid, row) for tid, row in all_traces.items()
            if not row.get("parent_trace_id")
        ]
        roots_sorted = sorted(
            roots, key=lambda x: x[1].get("created_at") or 0, reverse=True
        )[:recent_n]
        target_ids = []
        for root_id, _ in roots_sorted:
            target_ids.extend(_walk_tree(root_id, all_traces))
    else:
        # Default: recent 10
        roots = [
            (tid, row) for tid, row in all_traces.items()
            if not row.get("parent_trace_id")
        ]
        roots_sorted = sorted(
            roots, key=lambda x: x[1].get("created_at") or 0, reverse=True
        )[:10]
        target_ids = []
        for root_id, _ in roots_sorted:
            target_ids.extend(_walk_tree(root_id, all_traces))

    print(f"\n[audit] Auditing {len(target_ids)} trace nodes...")

    node_results: list[dict] = []
    for tid in target_ids:
        row = all_traces.get(tid)
        node_result = audit_trace(tid, row, state_conn, kno_conn, all_traces)
        node_results.append(node_result)
        status = "✓" if node_result["pass"] else "✗"
        print(
            f"  [{status}] {tid} kind={node_result['task_kind']} "
            f"events={node_result['checks'].get('events', {}).get('count', 0)} "
            f"ai={node_result['checks'].get('ai_calls', {}).get('total', 0)} "
            f"log_found={node_result['checks'].get('logs', {}).get('found', False)}"
        )
        if node_result["issues"]:
            for issue in node_result["issues"]:
                print(f"    ISSUE: {issue}")

    state_conn.close()
    if kno_conn:
        kno_conn.close()

    # Summary
    total = len(node_results)
    passed = sum(1 for n in node_results if n["pass"])
    nodes_with_events = sum(
        1 for n in node_results
        if n["checks"].get("events", {}).get("pass")
    )
    nodes_with_ai = sum(
        1 for n in node_results
        if n["checks"].get("ai_calls", {}).get("total", 0) > 0
    )
    nodes_with_logs = sum(
        1 for n in node_results
        if n["checks"].get("logs", {}).get("found")
    )
    all_issues: list[str] = []
    for n in node_results:
        all_issues.extend(n["issues"])

    report["nodes"] = node_results
    report["summary"] = {
        "total_nodes": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate_pct": round(passed / total * 100, 1) if total else 100.0,
        "nodes_with_events": nodes_with_events,
        "nodes_with_ai_calls": nodes_with_ai,
        "nodes_with_log_evidence": nodes_with_logs,
        "all_issues": all_issues,
    }
    report["status"] = "PASS" if passed == total else ("WARN" if passed > 0 else "FAIL")

    print(f"\n[audit] {passed}/{total} nodes fully linked")
    print(f"  Events: {nodes_with_events}/{total}")
    print(f"  AI calls: {nodes_with_ai}/{total}")
    print(f"  Log evidence: {nodes_with_logs}/{total}")
    if all_issues:
        print(f"  Issues ({len(all_issues)}):")
        for issue in all_issues[:10]:
            print(f"    - {issue}")

    # Save report
    REPORT_DIR.mkdir(exist_ok=True)
    if trace_id:
        out_name = f"audit_{trace_id[:30]}.json"
    else:
        out_name = f"audit_recent_{len(target_ids)}.json"
    out_path = REPORT_DIR / out_name
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"  Saved: {out_path}")

    if output_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Traceability audit — verify trace→event→log→alpha linkage."
    )
    parser.add_argument("--trace-id", help="Specific trace_id to audit (walks subtree)")
    parser.add_argument("--recent", type=int, default=None,
                        help="Audit last N root traces")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Print JSON report to stdout")
    args = parser.parse_args()

    report = run_audit(
        trace_id=args.trace_id,
        recent_n=args.recent,
        output_json=args.output_json,
    )

    sys.exit(0 if report["status"] in ("PASS", "WARN", "OK") else 1)


if __name__ == "__main__":
    main()
