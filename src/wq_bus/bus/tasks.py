"""TaskHandle and bus.start_task() implementation.

Design per TRACE_AS_TASK.md:
- bus.start_task(kind, payload, origin, parent) creates a trace row, sets contextvar,
  emits TASK_STARTED, and returns a TaskHandle.
- TaskHandle supports .on_complete / .on_fail / .wait / .cancel / .status.
- Passive event handlers do NOT call start_task; they inherit trace_id from the event.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)

TaskStatus = Literal["running", "completed", "failed", "cancelled", "timeout"]

_TAG_RE = re.compile(r"^[A-Z]+_[A-Z0-9]+$")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_trace_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rand = secrets.token_hex(3)  # 6 chars
    return f"tr_{ts}_{rand}"


class TraceFailed(RuntimeError):
    """Raised when a TaskHandle.wait() resolves to a non-success status.

    Same type used in both .wait() and on_fail callbacks so callers can
    catch one exception consistently.
    """

    def __init__(self, trace_id: str, status: str, original: Exception | None = None) -> None:
        super().__init__(f"Task {trace_id} ended with status={status}: {original}")
        self.trace_id = trace_id
        self.status = status
        self.original = original


class TaskResult:
    """Opaque result holder passed to on_complete callbacks."""

    def __init__(self, trace_id: str, data: dict | None = None) -> None:
        self.trace_id = trace_id
        self.data: dict = data or {}


class TaskHandle:
    """Caller-facing handle for a started task.

    Usage::

        handle = bus.start_task("generate", payload={...}, origin="watchdog")
        handle.on_complete(lambda r: print("done", r.trace_id))
        result = await handle.wait(timeout=600)
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._status: TaskStatus = "running"
        self._event: asyncio.Event = asyncio.Event()
        self._result: TaskResult | None = None
        self._error: Exception | None = None
        self._on_complete: list[Callable[[TaskResult], None]] = []
        self._on_fail: list[Callable[[Exception], None]] = []

    @property
    def status(self) -> TaskStatus:
        return self._status

    def on_complete(self, cb: Callable[[TaskResult], None]) -> None:
        """Register a completion callback (thread-safe)."""
        if self._status == "completed" and self._result is not None:
            try:
                cb(self._result)
            except Exception:
                _log.exception("on_complete callback raised")
        else:
            self._on_complete.append(cb)

    def on_fail(self, cb: Callable[[Exception], None]) -> None:
        """Register a failure callback."""
        if self._status in ("failed", "cancelled", "timeout") and self._error is not None:
            try:
                cb(self._error)
            except Exception:
                _log.exception("on_fail callback raised")
        else:
            self._on_fail.append(cb)

    async def wait(self, timeout: float | None = None) -> TaskResult:
        """Suspend until the task completes (or timeout seconds elapse).

        Raises TimeoutError on timeout, TraceFailed on task failure
        (TraceFailed wraps the original exception in .original).
        """
        try:
            await asyncio.wait_for(asyncio.shield(self._event.wait()), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Task {self.trace_id} did not complete in {timeout}s")
        if self._status == "completed" and self._result is not None:
            return self._result
        raise TraceFailed(self.trace_id, self._status, self._error)

    def cancel(self) -> None:
        """Request cancellation (emits TASK_CANCEL_REQUESTED via bus)."""
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import TASK_CANCEL_REQUESTED, make_event
        from wq_bus.utils.tag_context import get_tag
        tag = get_tag() or "_global"
        get_bus().emit(make_event(TASK_CANCEL_REQUESTED, tag, trace_id=self.trace_id))

    # ------------------------------------------------------------------
    # Internal: called by bus or agent to resolve the handle
    # ------------------------------------------------------------------

    def _resolve_complete(self, data: dict | None = None) -> None:
        if self._status != "running":
            return
        self._status = "completed"
        self._result = TaskResult(self.trace_id, data)
        self._event.set()
        for cb in self._on_complete:
            try:
                cb(self._result)
            except Exception:
                _log.exception("on_complete callback raised for %s", self.trace_id)

    def _resolve_fail(self, error: Exception | str) -> None:
        if self._status != "running":
            return
        self._status = "failed"
        self._error = error if isinstance(error, Exception) else RuntimeError(str(error))
        self._event.set()
        for cb in self._on_fail:
            try:
                cb(self._error)
            except Exception:
                _log.exception("on_fail callback raised for %s", self.trace_id)

    def _resolve_timeout(self) -> None:
        if self._status != "running":
            return
        self._status = "timeout"
        self._error = TimeoutError(f"Task {self.trace_id} timed out")
        self._event.set()
        for cb in self._on_fail:
            try:
                cb(self._error)
            except Exception:
                _log.exception("on_fail callback raised (timeout) for %s", self.trace_id)


# ---------------------------------------------------------------------------
# Module-level handle registry (allows supervisor + completions to find handles)
# ---------------------------------------------------------------------------

_HANDLES: dict[str, TaskHandle] = {}


def get_handle(trace_id: str) -> TaskHandle | None:
    return _HANDLES.get(trace_id)


def complete_task(trace_id: str, data: dict | None = None) -> None:
    """Mark a task completed from outside the handle (e.g. from an agent handler).

    Order: DB update FIRST so that on a crash between in-memory and DB updates,
    the trace ends up marked completed in DB rather than orphaned as 'running'.
    """
    _update_trace_status(trace_id, "completed")
    h = _HANDLES.pop(trace_id, None)
    if h:
        h._resolve_complete(data)


def fail_task(trace_id: str, error: str | Exception) -> None:
    _update_trace_status(trace_id, "failed", error=str(error))
    h = _HANDLES.pop(trace_id, None)
    if h:
        h._resolve_fail(error)


def timeout_task(trace_id: str) -> None:
    _update_trace_status(trace_id, "timeout", error="supervisor timeout")
    h = _HANDLES.pop(trace_id, None)
    if h:
        h._resolve_timeout()


# ---------------------------------------------------------------------------
# DAO helpers (write to state.db trace table)
# ---------------------------------------------------------------------------

def _write_trace(
    trace_id: str,
    *,
    kind: str,
    origin: str,
    parent_trace_id: str | None,
    task_payload_json: str,
    dataset_tag: str,
) -> None:
    """Persist trace row. Raises on DB failure — caller (start_task) MUST
    propagate so we don't return a TaskHandle backed by no DB row.

    Uses plain INSERT (NOT ``INSERT OR IGNORE``): trace_id collisions are
    astronomically unlikely (12 hex chars + UTC timestamp) and silently
    dropping a duplicate would leave the in-memory _HANDLES map and DB out
    of sync. UNIQUE constraint violation surfaces as IntegrityError.
    """
    import json
    from wq_bus.data._sqlite import open_state
    with open_state() as conn:
        conn.execute(
            """INSERT INTO trace
               (trace_id, created_at, origin, parent_trace_id, task_kind,
                task_payload_json, status, started_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (trace_id, time.time(), origin, parent_trace_id, kind,
             task_payload_json, "running", _utcnow_iso()),
        )


def _update_trace_status(
    trace_id: str,
    status: str,
    *,
    error: str | None = None,
) -> None:
    try:
        from wq_bus.data._sqlite import open_state
        with open_state() as conn:
            conn.execute(
                "UPDATE trace SET status=?, ended_at=?, error=? WHERE trace_id=?",
                (status, _utcnow_iso(), error, trace_id),
            )
    except Exception:
        _log.exception("Failed to update trace status for %s", trace_id)


# ---------------------------------------------------------------------------
# Public API: start_task (called by bus or CLI)
# ---------------------------------------------------------------------------

def start_task(
    kind: str,
    payload: dict,
    origin: str,
    parent: str | None = None,
    *,
    dataset_tag: str | None = None,
) -> TaskHandle:
    """Create a trace, emit TASK_STARTED, return TaskHandle.

    This is exposed as ``bus.start_task(...)``; the EventBus delegates here.

    Args:
        kind: Task kind string (generate|simulate|submit|crawl|summarize|analyze).
        payload: Arbitrary task payload dict.
        origin: Who started this task (watchdog|manual_cli|dispatcher_pack|crawler|orphan).
        parent: Parent trace_id (for sub-tasks started by dispatcher_pack).
        dataset_tag: Override; falls back to contextvar get_tag().

    Returns:
        TaskHandle for the new task.
    """
    import json
    from wq_bus.utils.tag_context import get_tag
    from wq_bus.utils.tag_context import with_trace

    tag = dataset_tag or get_tag()
    if not tag:
        tag = "_global"

    trace_id = _new_trace_id()
    handle = TaskHandle(trace_id)

    # Write DB row FIRST. If DB is down, fail loudly — better than returning
    # a handle backed by no row (supervisor + trace CLI would never see it).
    try:
        _write_trace(
            trace_id,
            kind=kind,
            origin=origin,
            parent_trace_id=parent,
            task_payload_json=json.dumps(payload, default=str),
            dataset_tag=tag,
        )
    except Exception:
        _log.exception("start_task: DB write failed for trace_id=%s — aborting", trace_id)
        raise

    _HANDLES[trace_id] = handle

    # Emit TASK_STARTED — import lazily to avoid circular
    try:
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import TASK_STARTED, make_event
        event = make_event(
            TASK_STARTED,
            tag,
            task_kind=kind,
            origin=origin,
            parent_trace_id=parent,
            payload=payload,
            trace_id=trace_id,
        )
        get_bus().emit(event)
    except Exception:
        _log.exception("Failed to emit TASK_STARTED for %s", trace_id)

    _log.info("task started trace_id=%s kind=%s origin=%s tag=%s", trace_id, kind, origin, tag)
    return handle


def list_active_traces() -> list[dict]:
    """Return running trace rows from state.db.

    Re-raises on DB error (do NOT silently return [] — that would let the
    supervisor skip every timeout check).
    """
    from wq_bus.data._sqlite import open_state
    with open_state() as conn:
        rows = conn.execute(
            "SELECT * FROM trace WHERE status='running' ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
