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
    tag = require_tag()
    if trace_id is None:
        from wq_bus.utils.tag_context import get_trace_id
        trace_id = get_trace_id()
    now = time.time()
    with open_state() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO submission_queue
               (alpha_id, dataset_tag, status, priority, is_metrics, sc_value,
                enqueued_at, updated_at, note, trace_id)
               VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)""",
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
) -> int:
    """Record one AI call. Returns the inserted row id (used to link alphas back)."""
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
                trace_id, prompt_text, response_text)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), tag, agent_type, model, depth, provider, n_packed,
             tokens_in, tokens_out, cost_usd, duration_ms, 1 if success else 0, error,
             trace_id, prompt_text, response_text),
        )
        return cur.lastrowid


def count_ai_calls_today(*, agent_type: str | None = None) -> int:
    """Count AI calls in the last 24h. Used by RateLimiter for daily cap."""
    cutoff = time.time() - 86400
    sql = "SELECT COUNT(*) AS n FROM ai_calls WHERE ts >= ?"
    params: list = [cutoff]
    if agent_type:
        sql += " AND agent_type=?"
        params.append(agent_type)
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
