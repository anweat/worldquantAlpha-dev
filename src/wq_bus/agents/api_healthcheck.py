"""api_healthcheck — periodic BRAIN API probe + child-task spawner.

Runs an asyncio loop (or a one-shot probe) that pings the BRAIN API. Each probe
is wrapped in its own ``health_probe`` trace (parent-less). On a *successful*
probe it can optionally spawn a child ``alpha_round`` task whose
``parent_trace_id`` points at the probe trace, giving you a clean parent→child
trace chain that mirrors "API healthy ⇒ trigger one gen+sim round".

This agent **does not** gate other agents via topic subscriptions. Topic
subscriptions are reserved for workspace separation; cross-agent business
coordination happens via the trace tree (``bus.start_task(parent=...)``).

Probe modes (set at construction or via CLI):

* ``auth``           — cheapest, just GET /authentication
* ``simulate``       — re-simulates a tiny canned expression (BRAIN dedups, so
                       this hits the cache + sim queue path without burning quota)
* ``untested_alpha`` — picks an alpha currently in submission_queue (or any
                       recently drafted alpha) and runs ``get_alpha`` on it

When the rolling failure rate exceeds ``failure_threshold`` the agent emits
``RATE_PRESSURE`` so ``sim_executor`` halves its concurrency window.
``RATE_PRESSURE`` is a concurrency hint (not gating) — sim_executor uses it
to decide how many sims to run in parallel, not whether to run them.

Every probe emits ``HEALTH_PROBE_DONE`` (informational, closes the
``health_probe`` trace via ``_TERMINAL_TOPICS_BY_KIND``).

The agent is normally launched via ``wqbus health`` (loop) or
``wqbus task health_probe`` (one-shot). Plug into a daemon by instantiating
and ``await agent.start()``.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import TYPE_CHECKING, Deque, Literal

from wq_bus.agents.base import AgentBase
from wq_bus.bus.events import Event, Topic, make_event, HEALTH_PROBE_DONE, RATE_PRESSURE
from wq_bus.bus.tasks import start_task, complete_task, fail_task
from wq_bus.data import state_db, knowledge_db
from wq_bus.utils.tag_context import with_tag, with_trace

if TYPE_CHECKING:
    from wq_bus.brain.client import BrainClient

ProbeKind = Literal["auth", "simulate", "untested_alpha"]

_DEFAULT_PROBE_EXPR = "rank(close)"
_DEFAULT_PROBE_SETTINGS = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 0,
    "neutralization": "MARKET",
    "truncation": 0.05,
    "pasteurization": "ON",
    "nanHandling": "OFF",
    "unitHandling": "VERIFY",
    "language": "FASTEXPR",
}


class ApiHealthCheck(AgentBase):
    AGENT_TYPE = "api_healthcheck"
    SUBSCRIPTIONS: list = []  # purely producer; no inbound topics

    name = "api_healthcheck"
    modes: list = ["auth", "simulate", "untested_alpha"]
    workspace_rules = {"reads": [], "writes": [], "memory_files": []}
    billing_hint = "per_call"

    def __init__(
        self,
        bus,
        brain_client: "BrainClient",
        *,
        dataset_tag: str,
        probe_kind: ProbeKind = "auth",
        probe_expr: str | None = None,
        probe_settings: dict | None = None,
        interval_secs: float = 60.0,
        window_size: int = 5,
        failure_threshold: float = 0.5,
        spawn_round: bool = False,
        spawn_round_n: int = 5,
        spawn_round_mode: str = "explore",
    ) -> None:
        super().__init__(bus)
        self.client = brain_client
        self.dataset_tag = dataset_tag
        self.probe_kind: ProbeKind = probe_kind
        self.probe_expr = probe_expr or _DEFAULT_PROBE_EXPR
        self.probe_settings = probe_settings or _DEFAULT_PROBE_SETTINGS
        self.interval_secs = float(interval_secs)
        self.window_size = int(window_size)
        self.failure_threshold = float(failure_threshold)

        # spawn_round: if True, every successful probe spawns a child alpha_round
        # task whose parent_trace_id is the probe trace. One child per probe at most.
        self.spawn_round = bool(spawn_round)
        self.spawn_round_n = int(spawn_round_n)
        self.spawn_round_mode = str(spawn_round_mode)

        self._window: Deque[bool] = deque(maxlen=self.window_size)
        self._consecutive_ok = 0
        self._was_pressured = False
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the background probe loop. Idempotent."""
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="api_healthcheck.loop")
        self.log.info(
            "api_healthcheck started kind=%s interval=%.0fs window=%d threshold=%.2f spawn_round=%s",
            self.probe_kind, self.interval_secs, self.window_size,
            self.failure_threshold, self.spawn_round,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        self.log.info("api_healthcheck stopped")

    # ------------------------------------------------------------------
    # Probe loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with with_tag(self.dataset_tag):
                    # Each iteration is its own health_probe trace.
                    await self.run_probe_with_trace()
            except Exception as e:  # noqa: BLE001
                self.log.exception("probe iteration crashed: %s", e)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_secs)
            except asyncio.TimeoutError:
                pass

    async def run_probe_with_trace(self) -> dict:
        """Wrap a single probe in a fresh health_probe trace. Returns probe result.

        On success and if ``spawn_round`` is set, this also spawns a child
        ``alpha_round`` trace and emits ``GENERATE_REQUESTED`` under that
        child trace_id. Caller does not need to manage trace context.
        """
        handle = start_task(
            kind="health_probe",
            payload={"probe_kind": self.probe_kind, "spawn_round": self.spawn_round},
            origin="watchdog",
            dataset_tag=self.dataset_tag,
        )
        try:
            with with_trace(handle.trace_id):
                result = await self.probe_once()
                # On success, optionally spawn a child alpha_round.
                if self.spawn_round and result.get("ok"):
                    child = self._spawn_alpha_round_child(handle.trace_id)
                    result["child_alpha_round_trace_id"] = child
            # health_probe trace closes via HEALTH_PROBE_DONE topic mapping
            # in EventBus._maybe_close_trace; we still call complete_task to
            # set summary payload + status idempotently.
            complete_task(handle.trace_id, {"agent": self.AGENT_TYPE, "result": result})
            return result
        except Exception as e:  # noqa: BLE001
            fail_task(handle.trace_id, e)
            raise

    async def probe_once(self) -> dict:
        """Run a single probe + update window + emit events. Returns probe dict.

        Emits HEALTH_PROBE_DONE every time, and RATE_PRESSURE when the rolling
        failure rate crosses threshold. Does NOT manage traces — call
        ``run_probe_with_trace`` if you want trace bookkeeping.
        """
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        ok = False
        err: str | None = None
        kind = self.probe_kind
        alpha_id: str | None = None

        try:
            if kind == "auth":
                ok = await loop.run_in_executor(None, self.client.check_auth)
            elif kind == "simulate":
                rec = await loop.run_in_executor(
                    None, self.client.simulate, self.probe_expr, self.probe_settings,
                )
                alpha_id = (rec or {}).get("id") or (rec or {}).get("alpha_id")
                ok = bool(alpha_id) and "error" not in (rec or {})
                if not ok:
                    err = str((rec or {}).get("error") or "no alpha_id")
            elif kind == "untested_alpha":
                target = self._pick_untested_alpha()
                if not target:
                    ok = await loop.run_in_executor(None, self.client.check_auth)
                    kind = "auth"
                else:
                    alpha_id = target
                    rec = await loop.run_in_executor(None, self.client.get_alpha, alpha_id)
                    ok = bool(rec) and "error" not in (rec or {})
                    if not ok:
                        err = str((rec or {}).get("error") or "get_alpha failed")
            else:
                raise ValueError(f"unknown probe_kind {kind!r}")
        except Exception as e:  # noqa: BLE001
            ok = False
            err = repr(e)[:200]

        latency_ms = int((time.monotonic() - t0) * 1000)
        self._window.append(ok)
        if ok:
            self._consecutive_ok += 1
        else:
            self._consecutive_ok = 0

        failure_rate = self._failure_rate()
        result = {
            "ok": ok,
            "latency_ms": latency_ms,
            "kind": kind,
            "alpha_id": alpha_id,
            "error": err,
            "rolling_failure_rate": failure_rate,
        }
        self.bus.emit(make_event(HEALTH_PROBE_DONE, self.dataset_tag, **result))
        self.log.info(
            "probe kind=%s ok=%s latency_ms=%d window=%s failure_rate=%.2f",
            kind, ok, latency_ms,
            "".join("1" if s else "0" for s in self._window),
            failure_rate,
        )
        self._maybe_emit_pressure(failure_rate)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _failure_rate(self) -> float:
        if not self._window:
            return 0.0
        return sum(0 if s else 1 for s in self._window) / len(self._window)

    def _maybe_emit_pressure(self, failure_rate: float) -> None:
        """Emit RATE_PRESSURE on degradation; this is a concurrency hint, not gating."""
        pressured_now = (
            len(self._window) >= self.window_size
            and failure_rate >= self.failure_threshold
        )
        if pressured_now and not self._was_pressured:
            self._was_pressured = True
            self.bus.emit(make_event(
                RATE_PRESSURE, self.dataset_tag,
                rate_429=round(failure_rate, 3),
                window_secs=int(self.window_size * self.interval_secs),
                max_concurrent_new=1,
            ))
            self.log.warning(
                "RATE_PRESSURE emitted: failure_rate=%.0f%% (sim_executor will halve concurrency)",
                failure_rate * 100,
            )
        elif not pressured_now and self._was_pressured:
            self._was_pressured = False
            self.log.info("API pressure cleared (failure_rate=%.0f%%)", failure_rate * 100)

    def _spawn_alpha_round_child(self, parent_trace_id: str) -> str:
        """Spawn a child alpha_round task and emit GENERATE_REQUESTED under it."""
        child = start_task(
            kind="alpha_round",
            payload={
                "n": self.spawn_round_n,
                "mode": self.spawn_round_mode,
                "spawned_by": "api_healthcheck",
            },
            origin="health_probe",
            parent=parent_trace_id,
            dataset_tag=self.dataset_tag,
        )
        with with_trace(child.trace_id):
            self.bus.emit(make_event(
                Topic.GENERATE_REQUESTED, self.dataset_tag,
                trace_id=child.trace_id,
                n=self.spawn_round_n,
                mode=self.spawn_round_mode,
                hint="spawned by api_healthcheck after successful probe",
            ))
        self.log.info(
            "spawned child alpha_round trace=%s parent=%s",
            child.trace_id, parent_trace_id,
        )
        return child.trace_id

    def _pick_untested_alpha(self) -> str | None:
        """Choose a real alpha id from the submission queue (or recently drafted)."""
        try:
            queue = state_db.list_queue(status="pending")
            if queue:
                return queue[0]["alpha_id"]
            for a in knowledge_db.list_alphas(limit=20):
                aid = a.get("alpha_id")
                if aid and not aid.startswith("DRY"):
                    return aid
        except Exception as e:
            self.log.debug("_pick_untested_alpha failed: %s", e)
        return None
