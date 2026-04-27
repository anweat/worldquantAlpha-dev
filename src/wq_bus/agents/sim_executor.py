"""sim_executor agent — runs BRAIN simulations for drafted alphas.

Listens: ALPHA_DRAFTED, RATE_PRESSURE
Emits:   IS_RESULT, IS_PASSED (if metrics meet thresholds), BATCH_DONE (after a burst)

Calls BrainClient (sync) inside an executor so it doesn't block the loop.

RATE_PRESSURE response: temporarily reduces concurrency to 1 for 600s then
auto-restores.  Uses asyncio.Condition instead of a plain Semaphore so that
already-waiting coroutines are not deadlocked when the limit changes.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

from wq_bus.agents.base import AgentBase
from wq_bus.bus.events import Event, Topic, make_event
from wq_bus.data import knowledge_db
from wq_bus.utils.tag_context import require_tag
from wq_bus.utils.yaml_loader import load_yaml

if TYPE_CHECKING:
    from wq_bus.brain.client import BrainClient


def _settings_hash(settings: dict) -> str:
    import hashlib, json
    return hashlib.sha256(
        json.dumps(settings, sort_keys=True).encode()
    ).hexdigest()[:16]


class SimExecutor(AgentBase):
    AGENT_TYPE = "sim_executor"
    SUBSCRIPTIONS = [Topic.ALPHA_DRAFTED]
    subscribes = ["RATE_PRESSURE"]   # dynamic topic (not in Topic enum)

    def __init__(self, bus, brain_client: "BrainClient", *, dispatcher=None) -> None:
        super().__init__(bus, dispatcher)
        self.client = brain_client
        sub = load_yaml("submission")
        thr = sub.get("thresholds", {})
        self.sharpe_min = float(thr.get("sharpe_min", 1.25))
        self.fitness_min = float(thr.get("fitness_min", 1.0))
        self.turnover_min = float(thr.get("turnover_min", 0.01))
        self.turnover_max = float(thr.get("turnover_max", 0.70))
        # batch tracking
        self._batch_id = uuid.uuid4().hex[:8]
        self._batch_total = 0
        self._batch_is_passed = 0
        self._batch_lock = asyncio.Lock()
        # Concurrency guard: use Condition so limit changes don't deadlock waiters.
        max_concurrent = int(sub.get("concurrent_simulations", 3))
        self._max_concurrent: int = max_concurrent
        self._orig_max_concurrent: int = max_concurrent
        self._active_sims: int = 0
        self._sim_cond: asyncio.Condition = asyncio.Condition()
        self._pressure_restore_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Concurrency helpers (replace old _sim_semaphore)
    # ------------------------------------------------------------------

    async def _acquire_sim_slot(self) -> None:
        """Wait until a simulation slot is available, then claim it."""
        async with self._sim_cond:
            while self._active_sims >= self._max_concurrent:
                await self._sim_cond.wait()
            self._active_sims += 1

    async def _release_sim_slot(self) -> None:
        """Release a simulation slot and notify waiters."""
        async with self._sim_cond:
            self._active_sims = max(0, self._active_sims - 1)
            self._sim_cond.notify_all()

    # ------------------------------------------------------------------
    # RATE_PRESSURE handler
    # ------------------------------------------------------------------

    async def on_rate_pressure(self, event: Event) -> None:
        """Reduce concurrency to 1 for 600s, then auto-restore."""
        new_max = int(event.payload.get("max_concurrent_new", 1))
        restore_delay = float(event.payload.get("window_secs", 600))

        async with self._sim_cond:
            self._max_concurrent = new_max
            self.log.warning(
                "RATE_PRESSURE: concurrency reduced %d→%d for %.0fs",
                self._orig_max_concurrent, new_max, restore_delay,
            )

        # Cancel any outstanding restore task from a previous pressure event
        if self._pressure_restore_task and not self._pressure_restore_task.done():
            self._pressure_restore_task.cancel()

        self._pressure_restore_task = asyncio.create_task(
            self._restore_concurrency(self._orig_max_concurrent, restore_delay)
        )

    async def _restore_concurrency(self, orig_max: int, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._sim_cond:
            self._max_concurrent = orig_max
            self._sim_cond.notify_all()
        self.log.info("RATE_PRESSURE lifted: concurrency restored to %d", orig_max)

    # ------------------------------------------------------------------
    # Main handler
    # ------------------------------------------------------------------

    async def on_alpha_drafted(self, event: Event) -> None:
        expr = event.payload["expression"]
        settings = event.payload.get("settings", {}) or {}
        ai_call_id = event.payload.get("ai_call_id")
        tag = event.dataset_tag

        # Dry-run: fabricate a deterministic alpha_id so the bus chain can be tested
        # without hitting the BRAIN API.
        is_dry = bool(getattr(getattr(self, "dispatcher", None), "_dry_run", False))
        if is_dry:
            import hashlib as _h
            alpha_id = "DRY" + _h.sha1(expr.encode()).hexdigest()[:9]
            alpha_record = {"id": alpha_id, "is": {"sharpe": 1.4, "fitness": 1.1,
                                                    "turnover": 0.05, "returns": 0.12,
                                                    "checks": [{"name": "SELF_CORRELATION",
                                                                "result": "PASS"}]}}
        else:
            # run sync simulate in executor — guarded by condition to respect BRAIN concurrent cap
            loop = asyncio.get_running_loop()
            # Expose main loop to BrainClient so it can call_soon_threadsafe for RATE_PRESSURE
            self.client._main_loop = loop
            await self._acquire_sim_slot()
            try:
                try:
                    alpha_record = await loop.run_in_executor(
                        None, self.client.simulate, expr, settings
                    )
                except Exception as e:  # noqa: BLE001
                    self.log.exception("simulate failed for expr=%s: %s", expr[:80], e)
                    return
            finally:
                await self._release_sim_slot()

        alpha_id = alpha_record.get("id") or alpha_record.get("alpha_id")
        if not alpha_id:
            err = alpha_record.get("error")
            body_preview = str(alpha_record.get("body") or alpha_record.get("data") or "")[:300]
            self.log.warning("simulate returned no alpha_id for expr=%s; error=%s body=%s",
                             expr[:80], err, body_preview)
            return
        is_metrics = (alpha_record.get("is") or {}).copy()
        # keep checks array intact (needed for SC parsing later); strip other complex sub-objects
        metrics_flat = {
            k: v for k, v in is_metrics.items()
            if k == "checks" or isinstance(v, (int, float, str, bool, type(None)))
        }

        sharpe = metrics_flat.get("sharpe") or 0
        fitness = metrics_flat.get("fitness") or 0
        turnover = metrics_flat.get("turnover") or 0

        passed_is = (
            sharpe >= self.sharpe_min
            and fitness >= self.fitness_min
            and self.turnover_min <= turnover <= self.turnover_max
        )

        # persist
        knowledge_db.upsert_alpha(
            alpha_id, expr, settings, _settings_hash(settings),
            is_metrics=metrics_flat,
            status="is_passed" if passed_is else "simulated",
            ai_call_id=ai_call_id,
        )

        self.bus.emit(make_event(Topic.IS_RESULT, tag,
                                 alpha_id=alpha_id, expression=expr, settings=settings,
                                 is_metrics=metrics_flat, passed=passed_is))
        if passed_is:
            self.bus.emit(make_event(Topic.IS_PASSED, tag,
                                     alpha_id=alpha_id, alpha_record=alpha_record))

        async with self._batch_lock:
            self._batch_total += 1
            if passed_is:
                self._batch_is_passed += 1

    async def emit_batch_done(self) -> None:
        """Caller (CLI / scheduler) triggers this when a generation burst completes."""
        async with self._batch_lock:
            tag = require_tag()
            self.bus.emit(make_event(Topic.BATCH_DONE, tag,
                                     batch_id=self._batch_id,
                                     n_total=self._batch_total,
                                     n_is_passed=self._batch_is_passed,
                                     n_sc_passed=0))
            self._batch_id = uuid.uuid4().hex[:8]
            self._batch_total = 0
            self._batch_is_passed = 0
