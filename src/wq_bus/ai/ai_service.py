"""ai_service — bus-driven unified AI dispatch layer.

Consumes ``AI_CALL_REQUESTED`` events, renders the requested prompt from
``config/prompts/<kind>.yaml`` via :mod:`wq_bus.ai.prompt_registry`, calls
the existing :class:`wq_bus.ai.dispatcher.Dispatcher` (which still owns
batching, budget, retries, dry-run synthesis), persists the call into
``ai_calls`` with ``call_id``/``trace_id``/``prompt_kind``, and emits
``AI_CALL_DONE`` (success) or ``AI_CALL_FAILED`` (terminal failure).

Per-trace serialization is enforced via an in-process ``asyncio.Lock`` keyed
by ``trace_id`` so a single trace's AI calls never race each other (matters
when an agent emits multiple AI requests within one pipeline step).

Locks for completed/failed traces are released on TRACE_COMPLETED /
TRACE_FAILED to keep memory bounded.

This service is **additive** — legacy callers using ``dispatcher.call()``
directly continue to work. New agents should ``self.bus.emit`` an
``AI_CALL_REQUESTED`` event and await the matching ``AI_CALL_DONE``.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from wq_bus.ai.prompt_registry import PromptError, render
from wq_bus.bus.events import (
    AI_CALL_DONE,
    AI_CALL_FAILED,
    AI_CALL_REQUESTED,
    TASK_STARTED,
    TRACE_COMPLETED,
    TRACE_FAILED,
    Event,
    make_event,
)
from wq_bus.utils.logging import get_logger
from wq_bus.utils.tag_context import with_tag, with_trace

_log = get_logger(__name__)


class AIService:
    """Bus-driven AI request handler.

    Construction:
        svc = AIService(bus, dispatcher)
        svc.start()   # subscribes; idempotent

    The dispatcher is the same instance used by legacy direct callers.
    """

    AGENT_TYPE = "ai_service"

    def __init__(self, bus, dispatcher) -> None:
        self.bus = bus
        self.dispatcher = dispatcher
        self._trace_locks: dict[str, asyncio.Lock] = {}
        self._lock_meta: dict[str, float] = {}   # trace_id -> last touch ts
        self._started = False
        self.log = _log

    # --------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self.bus.subscribe(AI_CALL_REQUESTED, self._on_request)
        self.bus.subscribe(TRACE_COMPLETED, self._on_trace_end)
        self.bus.subscribe(TRACE_FAILED, self._on_trace_end)
        # Per-round AI cap is process-local; the daemon must reset it on every
        # new task pipeline iteration, otherwise once the cap is hit the daemon
        # is permanently stuck. (CLI subcommands reset explicitly; daemon does
        # not.) A "task" maps cleanly to a "round" in the rate-limiter sense.
        self.bus.subscribe(TASK_STARTED, self._on_task_started)
        self._started = True
        self.log.info("ai_service subscribed to AI_CALL_REQUESTED + trace lifecycle + TASK_STARTED")

    async def _on_task_started(self, event: Event) -> None:
        try:
            self.dispatcher._limiter.reset_round()
        except Exception:
            self.log.debug("reset_round failed on TASK_STARTED", exc_info=True)

    # --------------------------------------------------------------
    def _get_lock(self, trace_id: str) -> asyncio.Lock:
        lock = self._trace_locks.get(trace_id)
        if lock is None:
            lock = asyncio.Lock()
            self._trace_locks[trace_id] = lock
        self._lock_meta[trace_id] = time.time()
        # Soft-cap: prune locks older than 1h that no one's awaiting (defensive).
        self._maybe_prune_locks()
        return lock

    def _maybe_prune_locks(self) -> None:
        if len(self._trace_locks) < 256:
            return
        cutoff = time.time() - 3600.0
        stale = [
            tid for tid, ts in self._lock_meta.items()
            if ts < cutoff and not self._trace_locks[tid].locked()
        ]
        for tid in stale:
            self._trace_locks.pop(tid, None)
            self._lock_meta.pop(tid, None)
        if stale:
            self.log.debug("ai_service pruned %d stale trace locks", len(stale))

    async def _on_trace_end(self, event: Event) -> None:
        tid = event.trace_id or event.payload.get("trace_id")
        if not tid:
            return
        # Drop the lock entry; if a handler is mid-flight it still owns its own ref.
        if tid in self._trace_locks and not self._trace_locks[tid].locked():
            self._trace_locks.pop(tid, None)
            self._lock_meta.pop(tid, None)

    # --------------------------------------------------------------
    async def _on_request(self, event: Event) -> None:
        p = event.payload or {}
        call_id: str = str(p.get("call_id") or "")
        prompt_kind: str = str(p.get("prompt_kind") or "")
        vars_: dict = p.get("vars") or {}
        agent: str = str(p.get("agent") or "ai_service")
        adapter_hint: Optional[str] = p.get("adapter_hint")
        model_hint: Optional[str] = p.get("model_hint")
        trace_id: str = event.trace_id or str(p.get("trace_id") or "")
        dataset_tag: str = event.dataset_tag or "_global"

        if not call_id or not prompt_kind:
            self.log.warning(
                "AI_CALL_REQUESTED missing call_id/prompt_kind (got call_id=%r prompt_kind=%r) — ignoring",
                call_id, prompt_kind,
            )
            return

        async def _emit_failed(reason: str, *, fatal: bool) -> None:
            try:
                self.bus.emit(make_event(
                    AI_CALL_FAILED,
                    dataset_tag=dataset_tag,
                    call_id=call_id,
                    reason=reason,
                    fatal=fatal,
                    trace_id=trace_id,
                ))
            except Exception:
                self.log.exception("ai_service: failed to emit AI_CALL_FAILED")

        # Render the prompt up-front; rendering errors are *fatal* (caller bug).
        # Backward-compat: declared template variables missing from `vars_`
        # get a safe empty default. This lets us add new optional context
        # variables (e.g. `available_docs`) without breaking AI_CALL_REQUESTED
        # events buffered before the schema change.
        try:
            from wq_bus.ai.prompt_registry import _load_template  # type: ignore
            declared = list((_load_template(prompt_kind).get("variables") or []))
            for v in declared:
                vars_.setdefault(str(v), "")
        except Exception:
            pass
        try:
            rendered = render(prompt_kind, vars_, strict=True)
        except PromptError as exc:
            self.log.error("ai_service: prompt render failed: %s", exc)
            await _emit_failed(f"prompt_render_failed: {exc}", fatal=True)
            return

        lock = self._get_lock(trace_id) if trace_id else asyncio.Lock()
        async with lock:
            with with_tag(dataset_tag), with_trace(trace_id or None):
                t0 = time.monotonic()
                payload = {
                    "_prompt_kind": prompt_kind,
                    "_call_id": call_id,
                    "_rendered_system": rendered.system,
                    "_rendered_user": rendered.user,
                    "_response_format": rendered.meta.response_format,
                    "_model_hint": model_hint or rendered.meta.default_model,
                    "_adapter_hint": adapter_hint or rendered.meta.adapter_hint,
                    # Pass the original vars so legacy adapters that still use
                    # subagent_packer have something useful to work with.
                    "vars": vars_,
                    "mode": prompt_kind.split(".")[-1],
                }
                try:
                    # Use force_immediate to avoid batch-buffer cross-call mixing
                    # (per-trace serialization defeats batching anyway).
                    response = await self.dispatcher.call(
                        agent, payload, source="auto", force_immediate=True,
                    )
                    duration_ms = int((time.monotonic() - t0) * 1000)
                except Exception as exc:
                    self.log.exception("ai_service: dispatcher.call failed (kind=%s)", prompt_kind)
                    # Heuristic: budget/cap exhaustion is fatal at the task level;
                    # transient network errors are not.
                    msg = str(exc)
                    fatal = ("daily_ai_cap" in msg) or ("budget" in msg.lower())
                    await _emit_failed(f"dispatcher_error: {msg}", fatal=fatal)
                    return

                # Persist + emit success.
                try:
                    from wq_bus.data.state_db import record_ai_call
                    ai_call_id = record_ai_call(
                        agent_type=agent,
                        model=str(payload["_model_hint"]),
                        provider=str(payload.get("_adapter_hint") or "auto"),
                        duration_ms=duration_ms,
                        success=True,
                        trace_id=trace_id or None,
                        prompt_text=(rendered.system + "\n\n" + rendered.user)[:16000],
                        response_text=_serialize_response(response)[:16000],
                        mode=payload["mode"],
                        source="auto",
                        call_id=call_id,
                        prompt_kind=prompt_kind,
                    )
                except Exception:
                    self.log.exception("ai_service: record_ai_call failed (non-fatal)")
                    ai_call_id = None

                try:
                    self.bus.emit(make_event(
                        AI_CALL_DONE,
                        dataset_tag=dataset_tag,
                        call_id=call_id,
                        ai_call_id=ai_call_id,
                        response=response,
                        trace_id=trace_id,
                    ))
                except Exception:
                    self.log.exception("ai_service: emit AI_CALL_DONE failed")


def _serialize_response(resp: Any) -> str:
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    try:
        return json.dumps(resp, ensure_ascii=False, default=str)
    except Exception:
        return str(resp)


__all__ = ["AIService"]
