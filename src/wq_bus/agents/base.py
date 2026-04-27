"""AgentBase — common scaffold for all bus agents.

Every wq-bus agent:
- subscribes to one or more topics during __init__
- emits new events via self.bus.emit(...)
- uses self.dispatcher.call(agent_type, payload) for ALL AI work (never invoke adapters directly)
- inherits dataset_tag awareness via the bus (event.dataset_tag is propagated to handlers via tag_context)

Subclasses define:
    AGENT_TYPE: str               # used by dispatcher for model routing
    SUBSCRIPTIONS: list[Topic]    # topics handled
    name: ClassVar[str]           # canonical agent name (same as AGENT_TYPE)
    subscribes: ClassVar[list]    # list of topic strings (AGENT_INTERFACE §1)
    modes: ClassVar[list]         # supported mode strings
    workspace_rules: ClassVar[dict] # reads/writes/memory_files
    billing_hint: ClassVar[str]   # per_call|per_token|either
    enforcement: str              # strict|lenient (instance-level, default lenient)

Per AGENT_INTERFACE §9: lenient mode fills missing fields from defaults.yaml and
logs WARN; strict mode re-raises. handle() exceptions emit TASK_FAILED + log jsonl.
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, ClassVar, Literal

from wq_bus.bus.events import Event, Topic
from wq_bus.utils.logging import get_logger


class AgentProtocolError(Exception):
    """Raised by strict-mode agents when required protocol fields are missing."""

if TYPE_CHECKING:
    from wq_bus.bus.event_bus import EventBus


def _load_defaults() -> dict:
    try:
        from wq_bus.utils.yaml_loader import load_yaml
        return load_yaml("defaults") or {}
    except Exception:
        return {}


class AgentBase:
    # ---- ClassVar protocol (AGENT_INTERFACE §1) ----
    AGENT_TYPE: ClassVar[str] = "base"
    SUBSCRIPTIONS: ClassVar[list] = []

    # New protocol fields (subclasses should override)
    name:             ClassVar[str] = "base"
    subscribes:       ClassVar[list] = []
    modes:            ClassVar[list] = []
    workspace_rules:  ClassVar[dict] = {"reads": [], "writes": [], "memory_files": []}
    billing_hint:     ClassVar[str] = "either"  # per_call|per_token|either

    def __init__(
        self,
        bus: "EventBus",
        dispatcher=None,
        *,
        enforcement: Literal["strict", "lenient"] = "lenient",
    ) -> None:
        self.bus = bus
        self.dispatcher = dispatcher
        self.enforcement: Literal["strict", "lenient"] = enforcement
        self.log = get_logger(f"agent.{self.AGENT_TYPE}")
        self._defaults = _load_defaults()

        # Subscribe using SUBSCRIPTIONS (Topic enum or plain str list) or subscribes (string list)
        sub_values = [t.value if hasattr(t, "value") else str(t) for t in self.SUBSCRIPTIONS]
        all_subs = list(self.SUBSCRIPTIONS) + [
            s for s in self.subscribes if s not in sub_values
        ]
        # Validate against topic_registry — warn (don't raise) on unknown topics
        # so a typo in a string-list subscription is caught early at startup
        # rather than silently never firing.
        try:
            from wq_bus.bus.topic_registry import is_registered
            for t in all_subs:
                tname = t.value if isinstance(t, Topic) else str(t)
                if not is_registered(tname):
                    self.log.warning(
                        "agent %s subscribed to unregistered topic %r — "
                        "handler will never fire unless someone emits this exact name",
                        self.AGENT_TYPE, tname,
                    )
        except Exception:  # noqa: BLE001
            pass
        for topic in all_subs:
            self.bus.subscribe(topic, self._safe_dispatch)
        self.log.info(
            "agent %s subscribed enforcement=%s topics=%s",
            self.AGENT_TYPE, enforcement,
            [t.value if isinstance(t, Topic) else t for t in all_subs],
        )

    # ------------------------------------------------------------------
    # Safe dispatch wrapper (AGENT_INTERFACE §9.1)
    # ------------------------------------------------------------------

    async def _safe_dispatch(self, event: Event) -> None:
        """Wrap _dispatch with exception handling; emit TASK_FAILED on error."""
        t0 = time.monotonic()
        try:
            await self._dispatch(event)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self.log.debug(
                "event handled agent=%s topic=%s trace=%s duration_ms=%d",
                self.AGENT_TYPE, event.topic, event.trace_id, elapsed_ms,
            )
            # Trace closure is topic-driven via EventBus._maybe_close_trace
            # (uses _TERMINAL_TOPICS_BY_KIND keyed by business task_kind).
            # Agents do NOT need to emit TASK_COMPLETED themselves.
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self.log.error(
                "handler error agent=%s topic=%s trace=%s duration_ms=%d error=%r",
                self.AGENT_TYPE, event.topic, event.trace_id, elapsed_ms, exc,
                exc_info=True,
            )
            self._emit_task_failed(event, exc)

    def _emit_task_failed(self, event: Event, exc: Exception) -> None:
        try:
            from wq_bus.bus.events import TASK_FAILED, make_event
            err_event = make_event(
                TASK_FAILED,
                event.dataset_tag,
                trace_id=event.trace_id,
                agent=self.AGENT_TYPE,
                error=repr(exc),
            )
            self.bus.emit(err_event)
        except Exception:
            self.log.exception("Failed to emit TASK_FAILED for %s", event.trace_id)

    async def _dispatch(self, event: Event) -> None:
        """Default router by topic; subclasses can override per-topic handlers
        named `on_<TOPIC_LOWER>` or implement `handle(event)`."""
        # Try new protocol handle() first
        if hasattr(self, "handle") and callable(getattr(self, "handle")):
            handler = getattr(self, "handle")
            if handler.__qualname__ != "AgentBase.handle":
                results = await handler(event)
                # If handler yields events, emit them
                if results:
                    try:
                        for evt in results:
                            if evt is not None:
                                self.bus.emit(evt)
                    except TypeError:
                        pass  # not iterable
                return

        handler_name = f"on_{event.topic.lower()}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            self.log.warning("no handler %s on %s", handler_name, type(self).__name__)
            return
        await handler(event)

    # ------------------------------------------------------------------
    # Defaults helper (lenient mode only)
    # ------------------------------------------------------------------

    def get_default(self, *path: str, fallback=None):
        """Drill into defaults.yaml with dot-path keys; return fallback if absent."""
        node = self._defaults
        for key in path:
            if not isinstance(node, dict):
                return fallback
            node = node.get(key, fallback)
            if node is fallback:
                return fallback
        return node

    def fill_payload_defaults(self, topic: str, payload: dict) -> dict:
        """Fill missing keys in *payload* from payload_defaults[topic]."""
        defaults = (self._defaults.get("payload_defaults") or {}).get(topic, {})
        filled = dict(defaults)
        filled.update(payload)
        if filled != payload:
            missing = {k for k in defaults if k not in payload}
            self.log.warning(
                "lenient: filled missing payload fields=%s for topic=%s agent=%s",
                sorted(missing), topic, self.AGENT_TYPE,
            )
        return filled

    # ------------------------------------------------------------------
    # Subclass helpers
    # ------------------------------------------------------------------

    async def call_ai(self, payload: dict, *, force_immediate: bool = False) -> dict:
        if not self.dispatcher:
            raise RuntimeError(f"{self.AGENT_TYPE} has no dispatcher attached")
        return await self.dispatcher.call(
            self.AGENT_TYPE, payload, force_immediate=force_immediate
        )

    async def health(self) -> dict:
        return {"ok": True, "agent": self.AGENT_TYPE}
