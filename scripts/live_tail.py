"""live_tail.py — Continuous monitor for wq-bus activity.

Tails logs/*.log (incremental reads), polls state.db.ai_calls and events every
30 seconds, and highlights anomalies.  Writes 10-minute snapshots to
test_results/realrun_snapshots/.

Usage:
    python scripts/live_tail.py [--snap-interval 600] [--no-color]
    Ctrl-C exits cleanly with a final snapshot.

ANOMALIES highlighted:
    RED     - same agent×mode called >5 times in last 60s
    YELLOW  - prompt identical to previous call (md5 dedup)
    MAGENTA - duration > 60s

Windows-safe: no curses, ANSI codes only when stdout is a TTY (or forced on).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# ANSI colour helpers (Windows-safe: only emit if stdout is a TTY)
# ---------------------------------------------------------------------------

def _ansi(code: str, text: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"

RED     = lambda t, e: _ansi("31;1", t, enabled=e)
YELLOW  = lambda t, e: _ansi("33;1", t, enabled=e)
MAGENTA = lambda t, e: _ansi("35;1", t, enabled=e)
CYAN    = lambda t, e: _ansi("36", t, enabled=e)
DIM     = lambda t, e: _ansi("2", t, enabled=e)


# ---------------------------------------------------------------------------
# Log file tailer (incremental reads)
# ---------------------------------------------------------------------------

class LogTailer:
    """Reads new lines from a log file since last read."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._pos: int = 0
        # Seek to end on start so we don't replay old history
        if path.exists():
            self._pos = path.stat().st_size

    def read_new(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self._pos)
                data = f.read()
                self._pos = f.tell()
            return [l for l in data.splitlines() if l.strip()]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# DB polling
# ---------------------------------------------------------------------------

def _open_state():
    from wq_bus.data._sqlite import open_state
    return open_state()


def _poll_ai_calls(since_id: int, limit: int = 10) -> list[dict]:
    try:
        with _open_state() as conn:
            rows = conn.execute(
                "SELECT id, ts, agent_type, mode, strength, duration_ms, success, "
                "prompt_text, dataset_tag FROM ai_calls "
                "WHERE id > ? ORDER BY id DESC LIMIT ?",
                (since_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def _poll_events(since_id: int, limit: int = 5) -> list[dict]:
    try:
        with _open_state() as conn:
            rows = conn.execute(
                "SELECT id, ts, topic, dataset_tag, payload_json FROM events "
                "WHERE id > ? ORDER BY id DESC LIMIT ?",
                (since_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def _pool_counters(tag: str) -> dict:
    """Return basic pool stats from knowledge.db."""
    try:
        from wq_bus.data._sqlite import open_knowledge
        with open_knowledge() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as n, status FROM alphas WHERE dataset_tag=? "
                "GROUP BY status",
                (tag,),
            ).fetchall()
            return {r["status"]: r["n"] for r in row}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Anomaly detector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    def __init__(self) -> None:
        # Recent calls: deque of (ts, agent_type, mode)
        self._recent: deque = deque()
        # Last prompt md5 per (agent, mode)
        self._last_md5: dict[tuple, str] = {}

    def check(self, call: dict) -> list[str]:
        """Return list of anomaly strings for this call."""
        anomalies = []
        agent = call.get("agent_type", "?")
        mode = call.get("mode") or "?"
        ts = float(call.get("ts") or time.time())
        duration_ms = call.get("duration_ms") or 0
        prompt = call.get("prompt_text") or ""

        # Prune old entries
        cutoff = ts - 60
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()

        self._recent.append((ts, agent, mode))
        count_same = sum(1 for t, a, m in self._recent if a == agent and m == mode)
        if count_same > 5:
            anomalies.append(f"FREQ: {agent}x{mode} called {count_same}x in 60s")

        if duration_ms and duration_ms > 60_000:
            anomalies.append(f"SLOW: duration={duration_ms}ms")

        if prompt:
            md5 = hashlib.md5(prompt.encode("utf-8", errors="replace")).hexdigest()
            key = (agent, mode)
            if key in self._last_md5 and self._last_md5[key] == md5:
                anomalies.append("DUP: identical prompt repeated")
            self._last_md5[key] = md5

        return anomalies


# ---------------------------------------------------------------------------
# Snapshot writer (atomic)
# ---------------------------------------------------------------------------

def _write_snapshot(
    snap_dir: Path,
    run_id: str,
    counters: dict,
    ai_calls: list[dict],
    events: list[dict],
    pool_stats: dict,
    start_pool_stats: dict,
) -> Path:
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    out_path = snap_dir / f"snap_{run_id}_{ts_str}.json"
    tmp = out_path.with_suffix(".tmp")

    # Compute pool delta from start
    pool_delta = {
        k: pool_stats.get(k, 0) - start_pool_stats.get(k, 0)
        for k in set(pool_stats) | set(start_pool_stats)
    }

    snap = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": run_id,
        "counters": counters,
        "last_50_ai_calls": ai_calls[-50:],
        "last_50_events": events[-50:],
        "pool_stats": pool_stats,
        "pool_stats_delta_from_start": pool_delta,
    }
    tmp.write_text(
        json.dumps(snap, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    os.replace(tmp, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Live monitor for wq-bus activity.")
    parser.add_argument("--snap-interval", type=int, default=600,
                        help="Seconds between JSON snapshots (default 600).")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI colour output.")
    parser.add_argument("--dataset", default="USA_TOP3000",
                        help="Dataset tag for pool counters.")
    args = parser.parse_args()

    color = not args.no_color and sys.stdout.isatty()
    tag = args.dataset.upper()
    snap_interval = args.snap_interval
    run_id = time.strftime("%Y%m%d_%H%M%S", time.gmtime())

    snap_dir = _ROOT / "test_results" / "realrun_snapshots"
    log_dir = _ROOT / "logs"

    print(f"[live_tail] run_id={run_id}  dataset={tag}  snap_interval={snap_interval}s")
    print("[live_tail] Press Ctrl-C to exit. Watching logs/ + state.db ...")
    print("-" * 72)

    # Init tailers for all .log files present (and rescan periodically)
    tailers: dict[Path, LogTailer] = {}

    def _refresh_tailers():
        for p in log_dir.glob("*.log"):
            if p not in tailers:
                tailers[p] = LogTailer(p)

    _refresh_tailers()

    # DB cursors
    last_ai_id = 0
    last_event_id = 0

    # Get starting IDs so we only show NEW activity
    try:
        with _open_state() as conn:
            row = conn.execute("SELECT MAX(id) AS m FROM ai_calls").fetchone()
            if row and row["m"]:
                last_ai_id = int(row["m"])
            row = conn.execute("SELECT MAX(id) AS m FROM events").fetchone()
            if row and row["m"]:
                last_event_id = int(row["m"])
    except Exception:
        pass

    anomaly_detector = AnomalyDetector()
    start_pool_stats = _pool_counters(tag)

    # Accumulated history for snapshots
    all_ai_calls: list[dict] = []
    all_events: list[dict] = []

    counters: dict[str, int] = defaultdict(int)
    last_snap_ts = time.time()
    last_log_scan_ts = time.time()
    POLL_INTERVAL = 30  # seconds

    def _ts_str(ts: float) -> str:
        return time.strftime("%H:%M:%S", time.localtime(ts))

    def _format_call(call: dict, anomalies: list[str], color_on: bool) -> str:
        agent = (call.get("agent_type") or "?")[:14].ljust(14)
        mode = (call.get("mode") or "?")[:12].ljust(12)
        strength = (call.get("strength") or "?")[:6].ljust(6)
        dur = call.get("duration_ms")
        dur_str = f"{dur}ms".rjust(8) if dur else "    ?ms"
        status = "OK" if call.get("success") else "FAIL"
        ts = float(call.get("ts") or 0)
        ts_str_v = _ts_str(ts) if ts else "??:??:??"
        prompt = (call.get("prompt_text") or "")[:80].replace("\n", " ")

        line = f"{ts_str_v} {agent}| {mode}| {strength}| {dur_str} | {status} | {prompt}"

        if anomalies:
            tags = " ".join(f"[{a}]" for a in anomalies)
            if any("FREQ" in a for a in anomalies):
                line = RED(f"{line}  {tags}", color_on)
            elif any("DUP" in a for a in anomalies):
                line = YELLOW(f"{line}  {tags}", color_on)
            elif any("SLOW" in a for a in anomalies):
                line = MAGENTA(f"{line}  {tags}", color_on)
        return line

    try:
        while True:
            now = time.time()

            # ---- tail log files ----
            if now - last_log_scan_ts >= 5:
                _refresh_tailers()
                last_log_scan_ts = now
            for path, tailer in list(tailers.items()):
                new_lines = tailer.read_new()
                for line in new_lines:
                    print(DIM(f"[log] {line}", color))
                counters["log_lines"] += len(new_lines)

            # ---- poll ai_calls ----
            new_calls = _poll_ai_calls(last_ai_id, limit=10)
            for call in new_calls:
                cid = call.get("id") or 0
                if cid > last_ai_id:
                    last_ai_id = int(cid)
                all_ai_calls.append(call)
                counters["ai_calls"] += 1

                anomalies = anomaly_detector.check(call)
                print(_format_call(call, anomalies, color))

            # ---- poll events ----
            new_evts = _poll_events(last_event_id, limit=5)
            for evt in new_evts:
                eid = evt.get("id") or 0
                if eid > last_event_id:
                    last_event_id = int(eid)
                all_events.append(evt)
                counters["events"] += 1
                ts_str_v = _ts_str(float(evt.get("ts") or 0))
                topic = evt.get("topic", "?")
                print(CYAN(f"{ts_str_v} [EVENT] {topic}", color))

            # ---- snapshot every snap_interval ----
            if now - last_snap_ts >= snap_interval:
                pool = _pool_counters(tag)
                snap_path = _write_snapshot(
                    snap_dir, run_id,
                    dict(counters), all_ai_calls, all_events,
                    pool, start_pool_stats,
                )
                print(f"\n[live_tail] Snapshot written: {snap_path}")
                last_snap_ts = now

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[live_tail] Ctrl-C received. Writing final snapshot...")

    # Final snapshot
    pool = _pool_counters(tag)
    snap_path = _write_snapshot(
        snap_dir, run_id,
        dict(counters), all_ai_calls, all_events,
        pool, start_pool_stats,
    )
    print(f"[live_tail] Final snapshot: {snap_path}")
    print("[live_tail] Done.")


if __name__ == "__main__":
    main()
