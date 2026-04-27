"""Process-internal asyncio event bus.

Design:
- Pub/sub: each topic has an unbounded list of async handlers.
- `emit()` is fire-and-forget by default; handlers run as background tasks
  (gathered with return_exceptions so a single failure doesn't cascade).
- `emit_and_wait()` awaits all handlers (useful in tests).
- Critical topics (see events.CRITICAL_TOPICS) are mirrored to state.db.events
  *before* dispatching, so a crash mid-handler doesn't lose them.
- Dataset tag is propagated: when a handler runs, it executes inside
  `with_tag(event.dataset_tag)` so DAOs auto-scope.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Awaitable, Callable, Optional

from wq_bus.bus.events import CRITICAL_TOPICS, Event, Topic
from wq_bus.bus.topic_registry import is_registered, TOPIC_REGISTRY
from wq_bus.utils.logging import get_logger
from wq_bus.utils.tag_context import with_tag

log = get_logger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._tasks: set[asyncio.Task] = set()
        self._mirror_enabled: bool = True

    # ------------------------------------------------------------------
    # subscription
    # ------------------------------------------------------------------
    def subscribe(self, topic: str | Topic, handler: Handler) -> None:
        key = topic.value if isinstance(topic, Topic) else topic
        self._handlers[key].append(handler)
        log.debug("subscribed %s -> %s", key, getattr(handler, "__qualname__", handler))

    def unsubscribe(self, topic: str | Topic, handler: Handler) -> None:
        key = topic.value if isinstance(topic, Topic) else topic
        if handler in self._handlers.get(key, []):
            self._handlers[key].remove(handler)

    # ------------------------------------------------------------------
    # emit
    # ------------------------------------------------------------------
    def emit(self, event: Event) -> None:
        """Fire-and-forget. Handlers run in background tasks."""
        self._mirror(event)
        handlers = list(self._handlers.get(event.topic, []))
        if not handlers:
            log.debug("no handlers for %s", event.topic)
            # No handlers will run, so check terminal closure now.
            self._maybe_close_trace_safe(event)
            return
        # Schedule handlers; defer terminal-trace closure until they finish so
        # CLI-emitted terminal topics don't close the trace before the agent
        # handler has a chance to run.
        async def _run_then_close():
            await asyncio.gather(
                *(self._run_handler(h, event) for h in handlers),
                return_exceptions=True,
            )
            self._maybe_close_trace_safe(event)
        task = asyncio.create_task(_run_then_close())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def emit_and_wait(self, event: Event) -> None:
        """Await all handlers. Exceptions are logged, not re-raised."""
        self._mirror(event)
        handlers = list(self._handlers.get(event.topic, []))
        await asyncio.gather(
            *(self._run_handler(h, event) for h in handlers),
            return_exceptions=True,
        )
        self._maybe_close_trace_safe(event)

    async def drain(self, timeout: Optional[float] = None) -> None:
        """Wait for all in-flight background tasks to finish, including
        downstream tasks emitted by handlers themselves."""
        import time as _t
        deadline = (_t.monotonic() + timeout) if timeout else None
        # Loop until no new tasks appear
        while self._tasks:
            pending = list(self._tasks)
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - _t.monotonic())
                if remaining == 0.0:
                    return
            await asyncio.wait(pending, timeout=remaining)
            # Give the loop a tick so done_callbacks remove finished tasks
            # and any newly-spawned tasks register themselves.
            await asyncio.sleep(0)

    def start_task(
        self,
        kind: str,
        payload: dict,
        origin: str,
        parent: str | None = None,
        *,
        dataset_tag: str | None = None,
    ):
        """Create and track a new task trace. Returns a TaskHandle.

        Delegates to ``wq_bus.bus.tasks.start_task``; exposed here so callers
        can do ``bus.start_task(...)`` without knowing the implementation module.
        """
        from wq_bus.bus.tasks import start_task
        return start_task(kind, payload, origin, parent, dataset_tag=dataset_tag)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    async def _run_handler(self, handler: Handler, event: Event) -> None:
        try:
            from wq_bus.utils.tag_context import with_trace
            with with_tag(event.dataset_tag), with_trace(event.trace_id or None):
                await handler(event)
        except Exception as e:  # noqa: BLE001
            log.exception("handler %s failed on %s: %s",
                          getattr(handler, "__qualname__", handler), event.topic, e)

    def _mirror(self, event: Event) -> None:
        if not self._mirror_enabled:
            return
        if event.topic not in CRITICAL_TOPICS:
            return
        try:
            from wq_bus.bus.persistence import mirror_event
            mirror_event(event)
        except Exception:  # noqa: BLE001
            log.exception("failed to mirror critical event %s", event.topic)
        # Hard signals (TASK_FAILED/TASK_COMPLETED) close immediately; soft
        # terminal topics are deferred to after handlers run (see emit()).
        try:
            self._maybe_close_trace_hard(event)
        except Exception:  # noqa: BLE001
            log.exception("failed to hard-close trace for %s", event.topic)

    def _maybe_close_trace_safe(self, event: Event) -> None:
        try:
            self._maybe_close_trace(event)
        except Exception:  # noqa: BLE001
            log.exception("failed to auto-close trace for %s", event.topic)

    # Topics that mark a task as terminally COMPLETED for given task_kind.
    # task_kind is a *business round*, not an agent name. The agent that emits
    # the terminal topic doesn't need to know it's the last one — the bus
    # closes the trace based on this map.
    #
    # To add a new task_kind, edit the module-level TERMINAL_TOPICS_BY_KIND
    # dict below or call register_terminal_topics(kind, topics) at startup.
    @property
    def _TERMINAL_TOPICS_BY_KIND(self) -> dict[str, set[str]]:
        return TERMINAL_TOPICS_BY_KIND

    def _maybe_close_trace_hard(self, event: Event) -> None:
        """Immediate close on TASK_COMPLETED / TASK_FAILED only."""
        trace_id = getattr(event, "trace_id", None)
        if not trace_id:
            return
        topic = event.topic
        if topic == "TASK_FAILED":
            from wq_bus.bus.tasks import fail_task
            fail_task(trace_id, event.payload.get("error", "unknown"))
            return
        if topic == "TASK_COMPLETED":
            from wq_bus.bus.tasks import complete_task
            complete_task(trace_id, event.payload)
            return

    def _maybe_close_trace(self, event: Event) -> None:
        """Deferred (post-handler) close: terminal topic for trace's task_kind."""
        trace_id = getattr(event, "trace_id", None)
        if not trace_id:
            return
        topic = event.topic
        # Hard signals already handled in _maybe_close_trace_hard.
        if topic in ("TASK_FAILED", "TASK_COMPLETED"):
            return
        # Soft signals: terminal topic for the trace's task_kind
        try:
            from wq_bus.data._sqlite import open_state
            with open_state() as conn:
                row = conn.execute(
                    "SELECT task_kind, status FROM trace WHERE trace_id=?",
                    (trace_id,),
                ).fetchone()
        except Exception:
            return
        if not row or row["status"] != "running":
            return
        terminals = self._TERMINAL_TOPICS_BY_KIND.get(row["task_kind"], set())
        if topic in terminals:
            from wq_bus.bus.tasks import complete_task
            complete_task(trace_id, {"terminal_topic": topic})


# ---------------------------------------------------------------------------
# Task-kind → terminal topics registry.
#
# Editable at runtime via register_terminal_topics(kind, topics). Plugins or
# experimental flows can append a new kind without modifying EventBus.
# ---------------------------------------------------------------------------

TERMINAL_TOPICS_BY_KIND: dict[str, set[str]] = {
    # alpha_round = failure_synth → alpha_gen → sim_executor → (submitter)
    # sim_executor's BATCH_DONE is the canonical terminal; SUBMITTED also
    # closes for rounds that culminate in submission.
    "alpha_round":      {"BATCH_DONE", "SUBMITTED", "SUBMISSION_FAILED"},
    # crawl_summary = a single crawler run; closed manually by the
    # crawler driver (no natural terminal topic in the bus).
    "crawl_summary":    set(),
    # doc_summary = doc_summarizer consuming a batch (parent=crawl_summary)
    "doc_summary":      {"KNOWLEDGE_UPDATED", "RECIPE_CANDIDATES_READY",
                          "RECIPE_PROPOSED"},
    # health_probe = one probe; HEALTH_PROBE_DONE closes it.
    "health_probe":     {"HEALTH_PROBE_DONE"},
    # portfolio_review = an analyst pass over the portfolio
    "portfolio_review": {"PORTFOLIO_ANALYZED"},
}


def register_terminal_topics(kind: str, topics: "set[str] | list[str]") -> None:
    """Register or extend terminal topics for a task_kind. Idempotent."""
    existing = TERMINAL_TOPICS_BY_KIND.setdefault(kind, set())
    existing.update(topics)


# ----- module-level singleton -----

_bus: Optional[EventBus] = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_bus() -> None:
    """Test helper."""
    global _bus
    _bus = None
