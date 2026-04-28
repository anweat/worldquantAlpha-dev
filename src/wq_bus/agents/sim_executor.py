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
    subscribes = ["RATE_PRESSURE", "ALPHA_DRAFT_SKIPPED"]   # dynamic topics (not in Topic enum)

    def __init__(self, bus, brain_client: "BrainClient", *, dispatcher=None) -> None:
        super().__init__(bus, dispatcher)
        self.client = brain_client
        sub = load_yaml("submission")
        thr = sub.get("thresholds", {})
        self.sharpe_min = float(thr.get("sharpe_min", 1.25))
        self.fitness_min = float(thr.get("fitness_min", 1.0))
        self.turnover_min = float(thr.get("turnover_min", 0.01))
        self.turnover_max = float(thr.get("turnover_max", 0.70))
        # b2/b4: configurable simulation poll timeouts
        sim_cfg = sub.get("simulation", {}) or {}
        self.poll_timeout_sec = int(sim_cfg.get("poll_timeout_sec", 600))
        self.poll_interval_sec = int(sim_cfg.get("poll_interval_sec", 8))
        # batch tracking — per-batch progress so BATCH_DONE auto-fires when
        # all alphas in a generation burst have either passed or failed.
        # Map: batch_id -> {"total": int, "done": int, "is_passed": int, "tag": str}
        self._batches: dict[str, dict] = {}
        self._batch_lock = asyncio.Lock()
        # Legacy globals kept for backward compat with cli.emit_batch_done().
        self._batch_id = uuid.uuid4().hex[:8]
        self._batch_total = 0
        self._batch_is_passed = 0
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
        """Wait until a simulation slot is available, then claim it.

        Uses ``wait_for(...)`` with a 60-s heartbeat so a stuck notify_all
        (e.g. release path threw before notifying) won't deadlock the agent
        forever.  We re-check the predicate after each wake-up.
        """
        async with self._sim_cond:
            while self._active_sims >= self._max_concurrent:
                try:
                    await asyncio.wait_for(self._sim_cond.wait(), timeout=60)
                except asyncio.TimeoutError:
                    # 60-s heartbeat — DEBUG since multiple waiting tasks all
                    # wake at the same time and would otherwise spam WARNING.
                    self.log.debug(
                        "sim_slot wait heartbeat (active=%d max=%d) — re-checking",
                        self._active_sims, self._max_concurrent,
                    )
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

        # Cancel any outstanding restore task from a previous pressure event,
        # awaiting cancellation so we never leak both the old and new task
        # (fire-and-forget cancel could race and never restore concurrency).
        old = self._pressure_restore_task
        if old and not old.done():
            old.cancel()
            try:
                await old
            except (asyncio.CancelledError, Exception):
                pass

        self._pressure_restore_task = asyncio.create_task(
            self._restore_concurrency(self._orig_max_concurrent, restore_delay)
        )

    async def _restore_concurrency(self, orig_max: int, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._sim_cond:
            self._max_concurrent = orig_max
            self._sim_cond.notify_all()
        self.log.info("RATE_PRESSURE lifted: concurrency restored to %d", orig_max)

    async def on_alpha_draft_skipped(self, event: Event) -> None:
        """alpha_gen rolled back a draft (emit failed) — decrement batch_total
        so BATCH_DONE doesn't wait for an alpha that never reached the bus."""
        batch_id = event.payload.get("batch_id")
        if not batch_id:
            return
        emit_payload = None
        async with self._batch_lock:
            b = self._batches.get(batch_id)
            if not b:
                return
            b["total"] = max(b["done"], b["total"] - 1)
            if b["done"] >= b["total"]:
                emit_payload = dict(b)
                self._batches.pop(batch_id, None)
        if emit_payload is not None:
            try:
                self.bus.emit(make_event(Topic.BATCH_DONE, event.dataset_tag,
                                         batch_id=batch_id,
                                         n_total=emit_payload["total"],
                                         n_is_passed=emit_payload["is_passed"],
                                         n_sc_passed=0))
            except Exception:
                self.log.exception("BATCH_DONE auto-emit (skip path) failed batch=%s", batch_id)

    # ------------------------------------------------------------------

    async def on_alpha_drafted(self, event: Event) -> None:
        expr = event.payload["expression"]
        settings = event.payload.get("settings", {}) or {}
        ai_call_id = event.payload.get("ai_call_id")
        tag = event.dataset_tag
        # Per-batch progress accounting (see alpha_gen — every draft carries
        # batch_id + batch_total; sim_executor fires BATCH_DONE once the last
        # alpha in the batch finishes simulating, regardless of pass/fail).
        batch_id = event.payload.get("batch_id")
        batch_total = int(event.payload.get("batch_total") or 0)
        if batch_id and batch_total > 0:
            async with self._batch_lock:
                self._batches.setdefault(batch_id, {
                    "total": batch_total, "done": 0, "is_passed": 0, "tag": tag,
                })

        passed_is = False
        try:
            await self._process_drafted(expr, settings, ai_call_id, tag, event)
            # _process_drafted captures pass via _batch_is_passed_flag attr trick? we use return
        finally:
            if batch_id:
                await self._mark_batch_alpha_done(batch_id, tag)

    async def _process_drafted(self, expr, settings, ai_call_id, tag, event):
        """Run the simulation + emit IS_RESULT/IS_PASSED. Sets self._last_pass for batch counting."""
        self._last_pass = False

        # Dry-run: fabricate a deterministic alpha_id so the bus chain can be tested
        # without hitting the BRAIN API.
        is_dry = bool(getattr(getattr(self, "dispatcher", None), "_dry_run", False))
        if is_dry:
            import hashlib as _h
            digest = _h.sha1(expr.encode()).hexdigest()
            alpha_id = "DRY" + digest[:9]
            # Hash-seeded synthetic IS so dry-run pass rate ~14% (matches
            # production usa_top3000.pass_rate_14d), letting the bus pipeline
            # exercise both passing and failing branches.
            seed = int(digest[:8], 16)
            bucket = seed % 100
            if bucket < 14:
                sharpe = 1.30 + (seed % 50) / 100.0       # 1.30 - 1.79
                fitness = 1.05 + (seed % 30) / 100.0      # 1.05 - 1.34
                turnover = 0.02 + (seed % 8) / 100.0      # 0.02 - 0.09
            elif bucket < 60:
                sharpe = 0.40 + (seed % 80) / 100.0       # 0.40 - 1.19
                fitness = 0.30 + (seed % 60) / 100.0      # below 1.0
                turnover = 0.10 + (seed % 35) / 100.0
            else:
                sharpe = 0.10 + (seed % 30) / 100.0
                fitness = 0.10 + (seed % 20) / 100.0
                turnover = 0.45 + (seed % 40) / 100.0
            sc_result = "PASS" if (seed >> 8) % 100 < 85 else "FAIL"
            alpha_record = {"id": alpha_id, "is": {
                "sharpe": round(sharpe, 3), "fitness": round(fitness, 3),
                "turnover": round(turnover, 3), "returns": round(0.05 + (seed % 30)/100.0, 3),
                "checks": [{"name": "SELF_CORRELATION", "result": sc_result}],
            }}
        else:
            # run sync simulate in executor — guarded by condition to respect BRAIN concurrent cap
            loop = asyncio.get_running_loop()
            # Expose main loop to BrainClient so it can call_soon_threadsafe for RATE_PRESSURE
            self.client._main_loop = loop
            await self._acquire_sim_slot()
            try:
                try:
                    alpha_record = await loop.run_in_executor(
                        None,
                        lambda: self.client.simulate(
                            expr, settings,
                            poll_interval=self.poll_interval_sec,
                            max_wait=self.poll_timeout_sec,
                        ),
                    )
                except Exception as e:  # noqa: BLE001
                    self.log.exception("simulate failed for expr=%s: %s", expr[:80], e)
                    # b3: emit error event so trace can be closed and metrics tracked
                    try:
                        from wq_bus.bus.events import make_event as _mk
                        self.bus.emit(_mk("ALPHA_SIM_ERRORED", tag,
                                          expression=expr, reason=f"{type(e).__name__}: {e}"))
                    except Exception:
                        self.log.exception("failed to emit ALPHA_SIM_ERRORED")
                    # c2: persist to sim_dead_letter for offline triage
                    try:
                        from wq_bus.data import state_db as _sdb
                        _sdb.add_sim_dead_letter(
                            expression=expr, settings=settings,
                            reason=f"{type(e).__name__}: {e}",
                        )
                    except Exception:
                        self.log.exception("sim DLQ insert failed for expr=%s", expr[:80])
                    return
            finally:
                await self._release_sim_slot()

        alpha_id = alpha_record.get("id") or alpha_record.get("alpha_id")
        if not alpha_id:
            err = alpha_record.get("error")
            body_preview = str(alpha_record.get("body") or alpha_record.get("data") or "")[:300]
            self.log.warning("simulate returned no alpha_id for expr=%s; error=%s body=%s",
                             expr[:80], err, body_preview)
            # b3: emit error event for non-dry runs only (dry-run always produces an id)
            if not is_dry:
                try:
                    from wq_bus.bus.events import make_event as _mk
                    self.bus.emit(_mk("ALPHA_SIM_ERRORED", tag,
                                      expression=expr,
                                      reason=f"no_alpha_id: {err or body_preview[:100]}"))
                except Exception:
                    self.log.exception("failed to emit ALPHA_SIM_ERRORED")
                # c2: persist to sim_dead_letter for offline triage
                try:
                    from wq_bus.data import state_db as _sdb
                    _sdb.add_sim_dead_letter(
                        expression=expr, settings=settings,
                        reason=f"no_alpha_id: {err or body_preview[:100]}",
                    )
                except Exception:
                    self.log.exception("sim DLQ insert failed for expr=%s", expr[:80])
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
            self._last_pass = passed_is

    async def _mark_batch_alpha_done(self, batch_id: str, tag: str) -> None:
        """Increment per-batch counter; emit BATCH_DONE when all alphas processed."""
        emit_payload = None
        async with self._batch_lock:
            b = self._batches.get(batch_id)
            if not b:
                return
            b["done"] += 1
            if getattr(self, "_last_pass", False):
                b["is_passed"] += 1
            if b["done"] >= b["total"]:
                emit_payload = dict(b)
                self._batches.pop(batch_id, None)
        if emit_payload is not None:
            try:
                self.bus.emit(make_event(Topic.BATCH_DONE, tag,
                                         batch_id=batch_id,
                                         n_total=emit_payload["total"],
                                         n_is_passed=emit_payload["is_passed"],
                                         n_sc_passed=0))
                self.log.info("BATCH_DONE auto-emitted batch=%s total=%d is_passed=%d",
                              batch_id, emit_payload["total"], emit_payload["is_passed"])
            except Exception:
                self.log.exception("BATCH_DONE auto-emit failed batch=%s", batch_id)

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
