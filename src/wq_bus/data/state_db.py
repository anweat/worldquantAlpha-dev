"""state.db DAO — events mirror, submission queue, AI call ledger, locks."""
from __future__ import annotations

import json
import time
from typing import Any, Iterable, Optional

from wq_bus.data._sqlite import open_state
from wq_bus.utils.tag_context import require_tag


# ---------- events ----------

def record_event(topic: str, payload: dict, *, dataset_tag: Optional[str] = None,
                 trace_id: Optional[str] = None) -> int:
    tag = dataset_tag or require_tag()
    if trace_id is None:
        from wq_bus.utils.tag_context import get_trace_id
        trace_id = get_trace_id()
    with open_state() as conn:
        cur = conn.execute(
            "INSERT INTO events (ts, topic, dataset_tag, payload_json, trace_id) VALUES (?, ?, ?, ?, ?)",
            (time.time(), topic, tag, json.dumps(payload, ensure_ascii=False, default=str), trace_id),
        )
        return cur.lastrowid


def list_unconsumed_events(topic: Optional[str] = None, *, dataset_tag: Optional[str] = None) -> list[dict]:
    tag = dataset_tag or require_tag()
    sql = "SELECT * FROM events WHERE consumed=0 AND dataset_tag=?"
    params: list = [tag]
    if topic:
        sql += " AND topic=?"
        params.append(topic)
    sql += " ORDER BY id"
    with open_state() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def mark_event_consumed(event_id: int) -> None:
    with open_state() as conn:
        conn.execute("UPDATE events SET consumed=1 WHERE id=?", (event_id,))


# ---------- submission queue ----------

def enqueue_submission(
    alpha_id: str,
    *,
    is_metrics: dict | None = None,
    sc_value: float | None = None,
    priority: int = 0,
    note: str = "",
    trace_id: str | None = None,
) -> None:
    """Enqueue an alpha for submission.

    Uses ON CONFLICT … DO UPDATE so re-enqueuing an existing item
    preserves ``retry_count`` (previously INSERT OR REPLACE reset it,
    making the dead-letter escalation logic unreliable).
    """
    tag = require_tag()
    if trace_id is None:
        from wq_bus.utils.tag_context import get_trace_id
        trace_id = get_trace_id()
    now = time.time()
    with open_state() as conn:
        conn.execute(
            """INSERT INTO submission_queue
               (alpha_id, dataset_tag, status, priority, is_metrics, sc_value,
                enqueued_at, updated_at, note, trace_id)
               VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(alpha_id, dataset_tag) DO UPDATE SET
                 status='pending',
                 priority=excluded.priority,
                 is_metrics=COALESCE(excluded.is_metrics, submission_queue.is_metrics),
                 sc_value=COALESCE(excluded.sc_value, submission_queue.sc_value),
                 updated_at=excluded.updated_at,
                 note=excluded.note,
                 trace_id=COALESCE(excluded.trace_id, submission_queue.trace_id)
               """,
            (alpha_id, tag, priority,
             json.dumps(is_metrics) if is_metrics else None,
             sc_value, now, now, note, trace_id),
        )


def list_queue(status: str = "pending") -> list[dict]:
    tag = require_tag()
    with open_state() as conn:
        rows = conn.execute(
            """SELECT * FROM submission_queue
               WHERE dataset_tag=? AND status=?
               ORDER BY priority DESC, enqueued_at ASC""",
            (tag, status),
        ).fetchall()
        return [dict(r) for r in rows]


def update_queue_status(alpha_id: str, status: str, *, note: str = "",
                        last_error: str | None = None,
                        bump_retry: bool = False) -> None:
    tag = require_tag()
    with open_state() as conn:
        if bump_retry:
            conn.execute(
                """UPDATE submission_queue
                   SET status=?, updated_at=?, note=?,
                       last_error=COALESCE(?, last_error),
                       retry_count=retry_count+1
                   WHERE alpha_id=? AND dataset_tag=?""",
                (status, time.time(), note, last_error, alpha_id, tag),
            )
        else:
            conn.execute(
                """UPDATE submission_queue
                   SET status=?, updated_at=?, note=?,
                       last_error=COALESCE(?, last_error)
                   WHERE alpha_id=? AND dataset_tag=?""",
                (status, time.time(), note, last_error, alpha_id, tag),
            )


def get_queue_item(alpha_id: str) -> dict | None:
    tag = require_tag()
    with open_state() as conn:
        row = conn.execute(
            """SELECT * FROM submission_queue
               WHERE alpha_id=? AND dataset_tag=?""",
            (alpha_id, tag),
        ).fetchone()
        return dict(row) if row else None


def queue_size(status: str = "pending") -> int:
    tag = require_tag()
    with open_state() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM submission_queue WHERE dataset_tag=? AND status=?",
            (tag, status),
        ).fetchone()
        return int(row["n"])


def count_submitted_today() -> int:
    """How many alphas have status='submitted' with updated_at in the last 24h.

    Used by the submitter to enforce ``daily_max`` from submission.yaml across
    process restarts (the in-memory n_submitted counter resets per flush).
    """
    tag = require_tag()
    cutoff = time.time() - 86400
    with open_state() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM submission_queue
               WHERE dataset_tag=? AND status='submitted' AND updated_at >= ?""",
            (tag, cutoff),
        ).fetchone()
        return int(row["n"])


def claim_queue_item(alpha_id: str, *, from_status: tuple[str, ...] = ("pending", "retry_pending")) -> bool:
    """Atomically transition ``alpha_id`` to status='submitting' iff its current
    status is one of ``from_status``. Returns True if this caller wins the race.

    Prevents two concurrent flushes from double-submitting the same alpha.
    """
    tag = require_tag()
    placeholders = ",".join("?" for _ in from_status)
    with open_state() as conn:
        cur = conn.execute(
            f"""UPDATE submission_queue
                SET status='submitting', updated_at=?
                WHERE alpha_id=? AND dataset_tag=? AND status IN ({placeholders})""",
            (time.time(), alpha_id, tag, *from_status),
        )
        return cur.rowcount > 0


def requeue_alpha(alpha_id: str, *, reset_retry: bool = False, note: str = "manual requeue") -> bool:
    """Move an alpha (typically from 'dead_letter' / 'failed') back to 'pending'.

    Returns True if a row was updated. When ``reset_retry`` is True the
    retry_count is also reset to 0 (use sparingly — defeats dead-letter).
    """
    tag = require_tag()
    with open_state() as conn:
        if reset_retry:
            cur = conn.execute(
                """UPDATE submission_queue
                   SET status='pending', updated_at=?, note=?, retry_count=0,
                       last_error=NULL
                   WHERE alpha_id=? AND dataset_tag=?""",
                (time.time(), note, alpha_id, tag),
            )
        else:
            cur = conn.execute(
                """UPDATE submission_queue
                   SET status='pending', updated_at=?, note=?
                   WHERE alpha_id=? AND dataset_tag=?""",
                (time.time(), note, alpha_id, tag),
            )
        return cur.rowcount > 0


def list_queue_by_status(status: str) -> list[dict]:
    """List all queue items in a given status (for CLI / admin use)."""
    tag = require_tag()
    with open_state() as conn:
        rows = conn.execute(
            """SELECT * FROM submission_queue
               WHERE dataset_tag=? AND status=?
               ORDER BY updated_at DESC""",
            (tag, status),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- ai_calls ----------

def record_ai_call(
    *,
    agent_type: str,
    model: str,
    provider: str,
    depth: str | None = None,
    n_packed: int = 1,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: float | None = None,
    duration_ms: int | None = None,
    success: bool = True,
    error: str | None = None,
    trace_id: str | None = None,
    prompt_text: str | None = None,
    response_text: str | None = None,
    strength: str | None = None,
    mode: str | None = None,
    adapter: str | None = None,
    package_id: str | None = None,
    source: str = "auto",
) -> int:
    """Record one AI call. Returns the inserted row id (used to link alphas back).

    Migration 005 added strength/mode/adapter/package_id/source columns —
    callers should pass them so audit + count_ai_calls_today(source=...)
    stay correct.
    """
    tag = require_tag()
    if trace_id is None:
        from wq_bus.utils.tag_context import get_trace_id
        trace_id = get_trace_id()
    # Cap stored text to keep DB small but useful for debugging.
    MAX_LEN = 16_000
    if prompt_text and len(prompt_text) > MAX_LEN:
        prompt_text = prompt_text[:MAX_LEN] + f"\n...[truncated {len(prompt_text)-MAX_LEN}c]"
    if response_text and len(response_text) > MAX_LEN:
        response_text = response_text[:MAX_LEN] + f"\n...[truncated {len(response_text)-MAX_LEN}c]"
    with open_state() as conn:
        cur = conn.execute(
            """INSERT INTO ai_calls
               (ts, dataset_tag, agent_type, model, depth, provider, n_packed,
                tokens_in, tokens_out, cost_usd, duration_ms, success, error,
                trace_id, prompt_text, response_text,
                strength, mode, adapter, package_id, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), tag, agent_type, model, depth, provider, n_packed,
             tokens_in, tokens_out, cost_usd, duration_ms, 1 if success else 0, error,
             trace_id, prompt_text, response_text,
             strength, mode, adapter, package_id, source),
        )
        return cur.lastrowid


def count_ai_calls_today(*, agent_type: str | None = None,
                         source: str | None = None) -> int:
    """Count AI calls in the last 24h. Used by RateLimiter for daily cap.

    Pass ``source='auto'`` to exclude manual calls from the count (so manual
    invocations don't eat the daily auto budget).
    """
    cutoff = time.time() - 86400
    sql = "SELECT COUNT(*) AS n FROM ai_calls WHERE ts >= ?"
    params: list = [cutoff]
    if agent_type:
        sql += " AND agent_type=?"
        params.append(agent_type)
    if source:
        sql += " AND source=?"
        params.append(source)
    with open_state() as conn:
        return int(conn.execute(sql, params).fetchone()["n"])


# ---------- locks (advisory, single-process) ----------

def acquire_lock(name: str, holder: str, ttl_seconds: float = 300) -> bool:
    now = time.time()
    with open_state() as conn:
        row = conn.execute("SELECT * FROM locks WHERE name=?", (name,)).fetchone()
        if row and row["expires_at"] > now and row["holder"] != holder:
            return False
        conn.execute(
            "INSERT OR REPLACE INTO locks (name, holder, acquired_at, expires_at) VALUES (?,?,?,?)",
            (name, holder, now, now + ttl_seconds),
        )
        return True


def release_lock(name: str, holder: str) -> None:
    with open_state() as conn:
        conn.execute("DELETE FROM locks WHERE name=? AND holder=?", (name, holder))
