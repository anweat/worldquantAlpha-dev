"""Trace Supervisor — monitors running tasks for timeout / stuck.

Per TRACE_AS_TASK.md §4: background coroutine scanning the trace table.
On timeout, emits TASK_TIMEOUT and marks trace status=timeout.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)


class TraceSupervisor:
    """Background asyncio task that watches active traces for timeouts.

    Reads timeout config from ``config/triggers.yaml`` (task_timeouts section).
    Falls back to ``default_timeout_secs`` if kind-specific timeout is absent.
    """

    def __init__(
        self,
        *,
        tick_secs: float = 15.0,
        default_timeout_secs: float = 900.0,
    ) -> None:
        self._tick_secs = tick_secs
        self._default_timeout_secs = default_timeout_secs
        self._kind_timeouts: dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._load_config()

    def _load_config(self) -> None:
        try:
            from wq_bus.utils.yaml_loader import load_yaml
            cfg = load_yaml("triggers")
            task_timeouts = cfg.get("task_timeouts") or {}
            for kind, secs in task_timeouts.items():
                self._kind_timeouts[str(kind)] = float(secs)
            self._tick_secs = float(cfg.get("supervisor", {}).get("tick_secs", self._tick_secs))
            self._default_timeout_secs = float(
                cfg.get("supervisor", {}).get("default_timeout_secs", self._default_timeout_secs)
            )
        except Exception:
            _log.debug("triggers.yaml not found or invalid; using defaults")

    def _timeout_for(self, kind: str | None) -> float:
        if kind and kind in self._kind_timeouts:
            return self._kind_timeouts[kind]
        return self._default_timeout_secs

    async def run(self) -> None:
        """Main supervisor loop. Call as asyncio.create_task(supervisor.run())."""
        self._running = True
        _log.info("TraceSupervisor started (tick=%.0fs default_timeout=%.0fs)",
                  self._tick_secs, self._default_timeout_secs)
        while self._running:
            try:
                await self._tick()
            except Exception:
                _log.exception("Supervisor tick error (swallowed, continuing)")
            await asyncio.sleep(self._tick_secs)

    async def _tick(self) -> None:
        from wq_bus.bus.tasks import list_active_traces, timeout_task
        now_iso = _utcnow_iso()
        now_ts = time.time()

        try:
            traces = list_active_traces()
        except Exception:
            # DB hiccup — log loudly so monitoring can pick it up; skip THIS
            # tick rather than swallowing every future tick silently.
            _log.exception("Supervisor: list_active_traces failed; skipping tick")
            return

        for trace in traces:
            started_raw = trace.get("started_at") or trace.get("created_at")
            if not started_raw:
                continue
            try:
                started_ts = _parse_ts(started_raw)
            except Exception:
                continue

            elapsed = now_ts - started_ts
            # Defend against NTP corrections / clock skew that produce a
            # negative elapsed: just skip rather than instantly timing-out.
            if elapsed < 0:
                _log.warning("Supervisor: negative elapsed for %s (%.0fs) — clock skew? skipping",
                             trace.get("trace_id"), elapsed)
                continue
            kind = trace.get("task_kind")
            limit = self._timeout_for(kind)

            if elapsed > limit:
                trace_id = trace["trace_id"]
                _log.warning(
                    "Supervisor timeout: trace_id=%s kind=%s elapsed=%.0fs limit=%.0fs",
                    trace_id, kind, elapsed, limit,
                )
                timeout_task(trace_id)
                await self._emit_timeout(trace)

    async def _emit_timeout(self, trace: dict) -> None:
        try:
            from wq_bus.bus.event_bus import get_bus
            from wq_bus.bus.events import TASK_TIMEOUT, make_event
            tag = trace.get("dataset_tag") or "_global"
            evt = make_event(
                TASK_TIMEOUT,
                tag,
                trace_id=trace["trace_id"],
                task_kind=trace.get("task_kind"),
            )
            get_bus().emit(evt)
        except Exception:
            _log.exception("Failed to emit TASK_TIMEOUT for %s", trace.get("trace_id"))

    def start(self) -> "TraceSupervisor":
        """Schedule the supervisor coroutine as a background task."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. invoked from sync context) — fall back
            # to the policy's loop. get_event_loop() is deprecated for the
            # common case but still the documented escape hatch when there
            # is no running loop and we don't want to create a new one.
            loop = asyncio.get_event_loop_policy().get_event_loop()
        self._task = loop.create_task(self.run())
        return self

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    @property
    def running(self) -> bool:
        return self._running


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: str | float) -> float:
    """Parse ISO string or epoch float to epoch float."""
    if isinstance(value, (int, float)):
        return float(value)
    # ISO 8601 UTC
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(str(value).rstrip("Z").replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        # epoch string fallback
        return float(value)


# Module-level singleton
_supervisor: Optional[TraceSupervisor] = None


def get_supervisor(**kwargs) -> TraceSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = TraceSupervisor(**kwargs)
    return _supervisor
