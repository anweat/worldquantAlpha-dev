"""monitor_ai_calls.py — AI call frequency monitoring (Phase 1 verification).

Reads ai_calls + manual_calls from data/state.db and detects:
  - Calls/min per (agent_type, mode, dataset_tag) exceeding threshold
  - Repeated identical prompts within 60s (hash-based)
  - Cooldown violations (same agent triggered within < cooldown_min)
  - chain_hook depth > 2 (parent_trace_id chain length violation)

Exits non-zero if any alarm is raised.

Usage:
    python scripts/monitor_ai_calls.py [--window-min N] [--threshold-per-min K] [--json]
    python scripts/monitor_ai_calls.py --window-min 15 --threshold-per-min 3
    python scripts/monitor_ai_calls.py --window-min 30 --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
REPORT_DIR = _ROOT / "test_results"

_COOLDOWN_SEC = 60   # default cooldown between same-agent calls
_PROMPT_DEDUP_SEC = 60  # window for identical-prompt detection
_MAX_CHAIN_DEPTH = 2    # max allowed parent_trace_id chain depth


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_state() -> sqlite3.Connection:
    if not STATE_DB.exists():
        raise FileNotFoundError(f"state.db not found at {STATE_DB}")
    conn = sqlite3.connect(str(STATE_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _hash_prompt(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Data readers
# ---------------------------------------------------------------------------

def _read_ai_calls(conn: sqlite3.Connection, since_ts: float) -> list[dict]:
    """Read ai_calls rows newer than since_ts."""
    try:
        rows = conn.execute(
            """SELECT id, ts, dataset_tag, agent_type, model, depth, provider,
                      n_packed, success, error, trace_id, prompt_text, response_text,
                      mode, package_id, source, strength
               FROM ai_calls WHERE ts >= ?
               ORDER BY ts ASC""",
            (since_ts,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Some columns may be absent on older DBs — fallback to basic columns
        rows = conn.execute(
            """SELECT id, ts, dataset_tag, agent_type, model, provider,
                      n_packed, success, error, trace_id, prompt_text
               FROM ai_calls WHERE ts >= ?
               ORDER BY ts ASC""",
            (since_ts,),
        ).fetchall()
        return [dict(r) for r in rows]


def _read_manual_calls(conn: sqlite3.Connection, since_ts: float) -> list[dict]:
    """Read manual_calls rows newer than since_ts (if table exists)."""
    try:
        rows = conn.execute(
            """SELECT call_id, created_at, dataset_tag, agent_type, mode, strength,
                      source, prompt, response, trace_id, success, error
               FROM manual_calls WHERE created_at >= ?
               ORDER BY created_at ASC""",
            (since_ts,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def _read_trace_table(conn: sqlite3.Connection) -> list[dict]:
    """Read trace table for chain-depth analysis."""
    try:
        rows = conn.execute(
            "SELECT trace_id, parent_trace_id, task_kind, status FROM trace"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _check_call_rate(
    calls: list[dict],
    window_sec: float,
    threshold_per_min: float,
) -> list[dict]:
    """Check calls/min per (agent_type, mode, dataset_tag). Return alarms."""
    alarms: list[dict] = []
    groups: dict[tuple, list[float]] = {}

    for c in calls:
        agent_type = c.get("agent_type") or "unknown"
        mode = c.get("mode") or "auto"
        tag = c.get("dataset_tag") or "unknown"
        key = (agent_type, mode, tag)
        groups.setdefault(key, []).append(float(c.get("ts") or c.get("created_at") or 0))

    window_min = window_sec / 60.0
    for (agent_type, mode, tag), timestamps in groups.items():
        n = len(timestamps)
        calls_per_min = n / window_min if window_min > 0 else n
        if calls_per_min > threshold_per_min:
            alarms.append({
                "alarm_type": "HIGH_CALL_RATE",
                "agent_type": agent_type,
                "mode": mode,
                "dataset_tag": tag,
                "call_count": n,
                "window_min": round(window_min, 2),
                "calls_per_min": round(calls_per_min, 3),
                "threshold_per_min": threshold_per_min,
                "detail": (
                    f"{agent_type}/{mode}/{tag}: {calls_per_min:.2f}/min "
                    f"(threshold={threshold_per_min}/min, n={n} in {window_min:.1f}min)"
                ),
            })

    return alarms


def _check_repeated_prompts(
    calls: list[dict],
    dedup_window_sec: float = _PROMPT_DEDUP_SEC,
) -> list[dict]:
    """Detect identical prompts within dedup_window_sec. Return alarms."""
    alarms: list[dict] = []
    # {prompt_hash: [ts, ...]}
    prompt_occurrences: dict[str, list[float]] = {}

    for c in calls:
        prompt_key = (
            c.get("prompt_text") or
            c.get("prompt") or
            c.get("response_text") or ""
        )
        ph = _hash_prompt(prompt_key)
        if not ph:
            continue
        ts = float(c.get("ts") or c.get("created_at") or 0)
        prompt_occurrences.setdefault(ph, []).append(ts)

    for ph, timestamps in prompt_occurrences.items():
        timestamps.sort()
        # Slide through looking for pairs within window
        for i in range(len(timestamps) - 1):
            gap = timestamps[i + 1] - timestamps[i]
            if gap <= dedup_window_sec:
                alarms.append({
                    "alarm_type": "REPEATED_PROMPT",
                    "prompt_hash": ph,
                    "occurrences": len(timestamps),
                    "min_gap_sec": round(gap, 1),
                    "dedup_window_sec": dedup_window_sec,
                    "detail": (
                        f"Identical prompt (hash={ph}) repeated "
                        f"{len(timestamps)}x, min gap={gap:.1f}s "
                        f"(window={dedup_window_sec}s)"
                    ),
                })
                break  # one alarm per prompt hash

    return alarms


def _check_cooldown_violations(
    calls: list[dict],
    cooldown_sec: float = _COOLDOWN_SEC,
) -> list[dict]:
    """Detect same (agent_type, dataset_tag) triggered within < cooldown_sec."""
    alarms: list[dict] = []
    # Track last call time per (agent_type, dataset_tag)
    last_call: dict[tuple, float] = {}

    # Sort by ts ascending
    sorted_calls = sorted(calls, key=lambda c: float(c.get("ts") or c.get("created_at") or 0))

    for c in sorted_calls:
        agent_type = c.get("agent_type") or "unknown"
        tag = c.get("dataset_tag") or "unknown"
        source = c.get("source") or "auto"
        ts = float(c.get("ts") or c.get("created_at") or 0)
        key = (agent_type, tag)

        if key in last_call:
            gap = ts - last_call[key]
            if gap < cooldown_sec and source != "manual":
                alarms.append({
                    "alarm_type": "COOLDOWN_VIOLATION",
                    "agent_type": agent_type,
                    "dataset_tag": tag,
                    "gap_sec": round(gap, 2),
                    "cooldown_sec": cooldown_sec,
                    "source": source,
                    "detail": (
                        f"{agent_type}/{tag}: triggered {gap:.1f}s after last call "
                        f"(cooldown={cooldown_sec}s, source={source})"
                    ),
                })

        last_call[key] = ts

    return alarms


def _check_chain_depth(trace_rows: list[dict], max_depth: int = _MAX_CHAIN_DEPTH) -> list[dict]:
    """Check chain_hook depth: walk parent_trace_id chain, flag depth > max_depth."""
    alarms: list[dict] = []
    if not trace_rows:
        return alarms

    # Build parent map: trace_id → parent_trace_id
    parent_map: dict[str, str | None] = {
        r["trace_id"]: r.get("parent_trace_id")
        for r in trace_rows
    }

    def _depth(tid: str, visited: set) -> int:
        if tid in visited or tid not in parent_map:
            return 0
        visited.add(tid)
        parent = parent_map.get(tid)
        if not parent:
            return 0
        return 1 + _depth(parent, visited)

    for row in trace_rows:
        tid = row.get("trace_id")
        if not tid:
            continue
        depth = _depth(tid, set())
        if depth > max_depth:
            alarms.append({
                "alarm_type": "CHAIN_DEPTH_EXCEEDED",
                "trace_id": tid,
                "depth": depth,
                "max_depth": max_depth,
                "task_kind": row.get("task_kind"),
                "detail": (
                    f"trace {tid} (kind={row.get('task_kind')}) has chain depth "
                    f"{depth} > max {max_depth}"
                ),
            })

    return alarms


# ---------------------------------------------------------------------------
# Main monitor
# ---------------------------------------------------------------------------

def run_monitor(
    window_min: float = 15.0,
    threshold_per_min: float = 3.0,
    output_json: bool = False,
    exclude_agents: list[str] | None = None,
) -> dict:
    now = time.time()
    since_ts = now - (window_min * 60)

    report: dict[str, Any] = {
        "generated_at": _utcnow(),
        "window_min": window_min,
        "threshold_per_min": threshold_per_min,
        "since_ts": since_ts,
        "alarms": [],
        "stats": {},
        "status": "OK",
    }

    if not STATE_DB.exists():
        report["error"] = f"state.db not found at {STATE_DB}"
        report["status"] = "ERROR"
        return report

    try:
        conn = _open_state()
        ai_calls = _read_ai_calls(conn, since_ts)
        manual_calls = _read_manual_calls(conn, since_ts)
        trace_rows = _read_trace_table(conn)
        conn.close()
    except Exception as e:
        report["error"] = str(e)
        report["status"] = "ERROR"
        return report

    def _parse_ts_str(val: Any) -> float:
        """Parse a ts value which may be POSIX float or ISO string."""
        if not val:
            return 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
        # Try ISO parsing
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                from datetime import datetime, timezone
                dt = datetime.strptime(str(val)[:19], fmt[:len(str(val)[:19])])
                return dt.replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                continue
        return 0.0

    all_calls = ai_calls + [
        {
            "ts": _parse_ts_str(c.get("created_at")),
            "dataset_tag": c.get("dataset_tag"),
            "agent_type": c.get("agent_type"),
            "mode": c.get("mode") or "manual",
            "prompt_text": c.get("prompt"),
            "source": "manual",
        }
        for c in manual_calls
    ]

    # Filter excluded agents (e.g., test fixtures like "test_agent")
    _excl = set(exclude_agents or [])
    if _excl:
        all_calls = [c for c in all_calls if c.get("agent_type") not in _excl]
        ai_calls = [c for c in ai_calls if c.get("agent_type") not in _excl]
        manual_calls = [c for c in manual_calls if c.get("agent_type") not in _excl]
        report["excluded_agents"] = sorted(_excl)

    report["stats"] = {
        "ai_calls_in_window": len(ai_calls),
        "manual_calls_in_window": len(manual_calls),
        "total_calls_in_window": len(all_calls),
        "trace_rows_total": len(trace_rows),
    }

    alarms: list[dict] = []

    # 1. Call rate check
    rate_alarms = _check_call_rate(all_calls, window_min * 60, threshold_per_min)
    alarms.extend(rate_alarms)

    # 2. Repeated prompt check
    prompt_alarms = _check_repeated_prompts(ai_calls, dedup_window_sec=_PROMPT_DEDUP_SEC)
    alarms.extend(prompt_alarms)

    # 3. Cooldown violations (auto calls only)
    auto_calls = [c for c in ai_calls if (c.get("source") or "auto") != "manual"]
    cooldown_alarms = _check_cooldown_violations(auto_calls, cooldown_sec=_COOLDOWN_SEC)
    alarms.extend(cooldown_alarms)

    # 4. Chain depth check
    depth_alarms = _check_chain_depth(trace_rows, max_depth=_MAX_CHAIN_DEPTH)
    alarms.extend(depth_alarms)

    report["alarms"] = alarms
    report["alarm_counts"] = {
        "HIGH_CALL_RATE": sum(1 for a in alarms if a["alarm_type"] == "HIGH_CALL_RATE"),
        "REPEATED_PROMPT": sum(1 for a in alarms if a["alarm_type"] == "REPEATED_PROMPT"),
        "COOLDOWN_VIOLATION": sum(1 for a in alarms if a["alarm_type"] == "COOLDOWN_VIOLATION"),
        "CHAIN_DEPTH_EXCEEDED": sum(1 for a in alarms if a["alarm_type"] == "CHAIN_DEPTH_EXCEEDED"),
        "total": len(alarms),
    }
    report["status"] = "ALARM" if alarms else "OK"

    # Print summary
    print(f"\n[ai_monitor] Window: {window_min}min, Threshold: {threshold_per_min}/min")
    print(f"  AI calls in window: {len(ai_calls)}")
    print(f"  Manual calls: {len(manual_calls)}")
    print(f"  Total traces: {len(trace_rows)}")
    print(f"  Alarms: {len(alarms)}")
    if alarms:
        for alarm in alarms:
            print(f"  [ALARM] {alarm['alarm_type']}: {alarm.get('detail', '')}")
    else:
        print("  [OK] No alarms — call frequency within acceptable bounds")

    # Save report
    REPORT_DIR.mkdir(exist_ok=True)
    out_path = REPORT_DIR / "ai_freq_monitor.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"  Saved: {out_path}")

    if output_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor AI call frequency and detect pathological patterns."
    )
    parser.add_argument("--window-min", type=float, default=15.0,
                        help="Lookback window in minutes (default: 15)")
    parser.add_argument("--threshold-per-min", type=float, default=3.0,
                        help="Alarm threshold: calls/min per group (default: 3)")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Print JSON report to stdout")
    parser.add_argument("--exclude-agent", dest="exclude_agents", action="append",
                        metavar="AGENT_TYPE", default=[],
                        help="Exclude agent_type from alarm checks (repeatable)")
    args = parser.parse_args()

    report = run_monitor(
        window_min=args.window_min,
        threshold_per_min=args.threshold_per_min,
        output_json=args.output_json,
        exclude_agents=args.exclude_agents or [],
    )

    sys.exit(0 if report["status"] == "OK" else 1)


if __name__ == "__main__":
    main()
