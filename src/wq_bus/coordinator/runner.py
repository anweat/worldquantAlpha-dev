"""CoordinatorAgent — outer Task loop + inner pipeline state machine.

Responsibilities (R6-C):
- Create a ``task`` row from a tasks.yaml entry; spawn its first trace.
- Drive the inner pipeline state machine for each trace: emit step's
  ``emit`` topic, await ``wait_for`` / ``wait_for_any`` / ``collect_until``,
  advance ``current_step``, persist via ``task_db.upsert_pipeline_state``.
- On trace finish (steps exhausted) emit TRACE_COMPLETED, update task progress,
  evaluate goal — if satisfied → TASK_GOAL_SATISFIED + finish_task; otherwise
  emit TASK_ITERATION_DONE and spawn the next trace until max_iterations /
  wall_time / consecutive-soft-failures triggers TASK_EXHAUSTED.
- Honors TASK_PAUSE_REQUESTED / TASK_RESUME_REQUESTED / TASK_CANCEL_REQUESTED
  at the trace level (the existing trace control gate already pauses agent
  handlers; coordinator additionally stops spawning new iterations on a paused
  task and finalizes on cancel).

The Coordinator is a pure orchestrator: it owns *no* business logic specific
to alpha generation/simulation/submission. It only wires events in the order
declared in config/tasks.yaml.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from wq_bus.bus.events import (
    TASK_CANCELLED,
    TASK_CANCEL_REQUESTED,
    TASK_EXHAUSTED,
    TASK_GOAL_SATISFIED,
    TASK_ITERATION_DONE,
    TASK_PAUSE_REQUESTED,
    TASK_RESUME_REQUESTED,
    TASK_START_REQUESTED,
    TRACE_COMPLETED,
    TRACE_FAILED,
    Event,
    Topic,
    make_event,
)
from wq_bus.coordinator.goal import (
    PipelineDef,
    PipelineStep,
    TaskDef,
    classify_failure,
    evaluate,
    get_pipeline,
    get_task,
)
from wq_bus.data import task_db
from wq_bus.utils.logging import get_logger
from wq_bus.utils.tag_context import new_trace_id, with_tag, with_trace

_log = get_logger(__name__)


# Counters fed by these topics (once per event, on the *child* trace):
_PROGRESS_TOPICS = {
    "ALPHA_DRAFTED": "alphas_drafted",
    "IS_PASSED": "is_passed_count",
    "ALPHA_SUBMITTED": "submitted_count",
    "SUBMITTED": "submitted_count",
}


class CoordinatorAgent:
    """Single-process Coordinator. Construct once per ``wqbus daemon``."""

    AGENT_TYPE = "coordinator"

    def __init__(self, bus) -> None:
        self.bus = bus
        # task_id -> {"task": TaskDef, "pipeline": PipelineDef, "dataset_tag": str,
        #             "consecutive_soft": int, "started_at": float,
        #             "current_trace": str|None, "cancelled": bool, "paused": bool}
        self._tasks: dict[str, dict[str, Any]] = {}
        # trace_id -> {"task_id": str, "step_idx": int, "wait_event": asyncio.Event,
        #              "collected": list, "matched": str|None}
        self._traces: dict[str, dict[str, Any]] = {}
        # task_id -> set[asyncio.Task] — keeps strong refs so background iteration
        # tasks aren't GC'd, and lets us catch crashes via done_callback.
        self._iteration_tasks: dict[str, set[Any]] = {}
        self._started = False
        self.log = _log

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        # Listen for *all* topics by registering on a wildcard set we care about.
        # The bus has no wildcard subscribe; we listen to a curated set.
        listened = {
            "BATCH_DONE", "ALPHA_DRAFTED", "IS_PASSED", "SUBMITTED",
            "ALPHA_SUBMITTED", "SUBMISSION_FAILED", "ALPHA_GEN_ERRORED",
            "ALPHA_SIM_ERRORED", "KNOWLEDGE_UPDATED", "SUMMARIZER_DONE",
            "TASK_FAILED", "TASK_TIMEOUT",
        }
        for t in listened:
            try:
                self.bus.subscribe(t, self._on_event)
            except Exception:
                # Some envs may not have these topics registered; ignore.
                pass
        self.bus.subscribe(TASK_CANCEL_REQUESTED, self._on_cancel_requested)
        self.bus.subscribe(TASK_PAUSE_REQUESTED, self._on_pause_requested)
        self.bus.subscribe(TASK_RESUME_REQUESTED, self._on_resume_requested)
        self.bus.subscribe(TASK_START_REQUESTED, self._on_start_requested)
        self._started = True
        self.log.info("coordinator subscribed (task pipelines + control)")

    # ------------------------------------------------------------------
    # Public: launch a task
    # ------------------------------------------------------------------
    async def start_task(
        self,
        task_name: str,
        *,
        dataset_tag: Optional[str] = None,
        origin: str = "cli",
        overrides: Optional[dict] = None,
    ) -> str:
        """Create a task row and spawn its first iteration.

        Returns the new task_id. Raises ValueError on unknown task / pipeline.
        """
        tdef = get_task(task_name)
        if not tdef:
            raise ValueError(f"unknown task {task_name!r} (config/tasks.yaml)")
        pdef = get_pipeline(tdef.pipeline)
        if not pdef:
            raise ValueError(
                f"task {task_name!r} references unknown pipeline {tdef.pipeline!r}"
            )
        ov = overrides or {}
        task_id = task_db.create_task(
            name=task_name,
            pipeline=tdef.pipeline,
            goal=tdef.goal,
            dataset_tag=dataset_tag,
            failure_policy={
                "soft": list(tdef.failure_policy.soft),
                "hard": list(tdef.failure_policy.hard),
                "abort_after_consecutive_soft": tdef.failure_policy.abort_after_consecutive_soft,
            },
            max_iterations=int(ov.get("max_iterations", tdef.max_iterations)),
            wall_time_secs=int(ov.get("wall_time_secs", tdef.wall_time_secs)),
            origin=origin,
        )
        self._tasks[task_id] = {
            "task": tdef,
            "pipeline": pdef,
            "dataset_tag": dataset_tag or "_global",
            "consecutive_soft": 0,
            "started_at": time.time(),
            "current_trace": None,
            "cancelled": False,
            "paused": False,
            "max_iterations": int(ov.get("max_iterations", tdef.max_iterations)),
            "wall_time_secs": int(ov.get("wall_time_secs", tdef.wall_time_secs)),
        }
        # Kick off iteration 1 in the background.
        self._spawn_iteration(task_id, 1)
        return task_id

    # ------------------------------------------------------------------
    def _spawn_iteration(self, task_id: str, iteration: int) -> None:
        """Spawn `_run_iteration` as a tracked background task.

        Keeps a strong reference (so it isn't GC'd), guards against cancel
        races (cancelled-after-goal-eval), and routes any unhandled exception
        into `_exhaust` so the task row can never get stuck in 'running'.
        """
        ctx = self._tasks.get(task_id)
        if not ctx or ctx.get("cancelled"):
            return  # cancel landed between the goal-eval and here
        t = asyncio.create_task(self._run_iteration(task_id, iteration=iteration))
        self._iteration_tasks.setdefault(task_id, set()).add(t)

        def _done(fut, _tid=task_id):  # noqa: ANN001
            self._iteration_tasks.get(_tid, set()).discard(fut)
            try:
                fut.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.log.exception(
                    "coordinator: iteration crashed task=%s: %s", _tid, e,
                )
                # Best-effort schedule of _exhaust on a fresh task.
                if _tid in self._tasks:
                    asyncio.create_task(
                        self._exhaust(_tid, f"unhandled_exception:{type(e).__name__}")
                    )

        t.add_done_callback(_done)

    # ------------------------------------------------------------------
    async def _run_iteration(self, task_id: str, iteration: int) -> None:
        ctx = self._tasks.get(task_id)
        if not ctx:
            return
        if ctx["cancelled"]:
            return
        # Pause: hold here until resumed (poll lightly).
        while ctx["paused"] and not ctx["cancelled"]:
            await asyncio.sleep(0.5)
        tdef: TaskDef = ctx["task"]
        pdef: PipelineDef = ctx["pipeline"]
        dataset_tag: str = ctx["dataset_tag"]

        # Wall-time / iteration-cap checks before spawning.
        elapsed = time.time() - ctx["started_at"]
        if elapsed >= ctx["wall_time_secs"]:
            await self._exhaust(task_id, "wall_time")
            return
        if iteration > ctx["max_iterations"]:
            await self._exhaust(task_id, "max_iterations")
            return

        trace_id = new_trace_id()
        ctx["current_trace"] = trace_id
        # Persist parent_task_id on the trace row (best-effort: trace row may
        # not exist yet — bus.tasks creates it on TASK_STARTED). We instead
        # persist via pipeline_state, which is enough for queries.
        task_db.upsert_pipeline_state(
            trace_id=trace_id, pipeline=pdef.name, task_id=task_id,
            iteration=iteration, current_step=0, status="running",
        )
        outcome: dict[str, int] = {}
        with with_tag(dataset_tag), with_trace(trace_id):
            for step_idx, step in enumerate(pdef.steps):
                if ctx["cancelled"]:
                    return
                while ctx["paused"] and not ctx["cancelled"]:
                    await asyncio.sleep(0.5)
                ok, reason, step_outcome = await self._run_step(
                    task_id=task_id, trace_id=trace_id,
                    iteration=iteration, step_idx=step_idx, step=step,
                    dataset_tag=dataset_tag,
                )
                # Merge counts.
                for k, v in step_outcome.items():
                    outcome[k] = outcome.get(k, 0) + v
                if not ok:
                    await self._on_trace_failed(
                        task_id=task_id, trace_id=trace_id,
                        reason=reason or "step_failed",
                        outcome=outcome,
                    )
                    return
                task_db.upsert_pipeline_state(
                    trace_id=trace_id, pipeline=pdef.name, task_id=task_id,
                    iteration=iteration, current_step=step_idx + 1,
                    status="running",
                )
        # Pipeline finished cleanly.
        await self._on_trace_completed(
            task_id=task_id, trace_id=trace_id,
            iteration=iteration, outcome=outcome,
        )

    # ------------------------------------------------------------------
    async def _run_step(
        self, *, task_id: str, trace_id: str, iteration: int,
        step_idx: int, step: PipelineStep, dataset_tag: str,
    ) -> tuple[bool, Optional[str], dict[str, int]]:
        """Execute a single pipeline step. Returns (ok, reason_if_fail, counts)."""
        # Set up wait state for this trace before emitting (avoid race).
        wait_event = asyncio.Event()
        self._traces[trace_id] = {
            "task_id": task_id,
            "step_idx": step_idx,
            "wait_event": wait_event,
            "collected": [],
            "matched": None,
            "wait_topics": self._wait_topics_for(step),
            "collect_target": (step.collect_until or {}).get("count", 1) if step.collect_until else 1,
            "counts": {},
        }
        # Emit kickoff event (if any).
        if step.emit:
            # Validate against topic registry — typo'd topics in tasks.yaml
            # would otherwise emit silently and dead-lock the wait_for step.
            from wq_bus.bus.topic_registry import is_registered
            if not is_registered(step.emit):
                self.log.error(
                    "coordinator: pipeline %s step %s emit topic %r is NOT registered — refusing",
                    pdef.name, step.id, step.emit,
                )
                return False, f"unknown_emit_topic: {step.emit}", {}
            payload = dict(step.payload or {})
            try:
                self.bus.emit(make_event(
                    step.emit,
                    dataset_tag=dataset_tag,
                    trace_id=trace_id,
                    **payload,
                ))
            except Exception as exc:
                self.log.exception("coordinator: emit %s failed (step=%s)", step.emit, step.id)
                return False, f"emit_failed: {exc}", {}

        # If no wait specified, finish step immediately.
        if not (step.wait_for or step.wait_for_any or step.collect_until):
            self._traces.pop(trace_id, None)
            return True, None, {}

        timeout = step.timeout if step.collect_until is None else int(step.collect_until.get("timeout", step.timeout))
        try:
            await asyncio.wait_for(wait_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            counts = self._traces.get(trace_id, {}).get("counts", {})
            self._traces.pop(trace_id, None)
            # collect_until partial success: if we collected at least one event,
            # accept it (avoids spurious soft-fails on slow producers).
            if step.collect_until and counts:
                return True, None, counts
            return False, f"step_timeout:{step.id}", counts

        info = self._traces.pop(trace_id, None) or {}
        return True, None, info.get("counts", {})

    @staticmethod
    def _wait_topics_for(step: PipelineStep) -> set[str]:
        topics: set[str] = set()
        if step.wait_for:
            topics.add(step.wait_for)
        if step.wait_for_any:
            topics.update(step.wait_for_any)
        if step.collect_until:
            t = step.collect_until.get("topic")
            if t:
                topics.add(t)
        return topics

    # ------------------------------------------------------------------
    async def _on_event(self, event: Event) -> None:
        """Generic dispatcher: feeds wait state machines + progress counters."""
        tid = event.trace_id
        if not tid:
            return
        info = self._traces.get(tid)
        if not info:
            return
        topic = event.topic
        # Always count progress topics regardless of step's wait spec.
        prog_key = _PROGRESS_TOPICS.get(topic)
        if prog_key:
            info["counts"][prog_key] = info["counts"].get(prog_key, 0) + 1

        wait_topics: set[str] = info.get("wait_topics", set())
        if topic not in wait_topics:
            return
        # Failure topics short-circuit: hand back control as a step-failure.
        if topic in ("TASK_FAILED", "TASK_TIMEOUT"):
            info["matched"] = topic
            info["wait_event"].set()
            return
        # Single-event waits.
        if not info.get("collect_target") or info["collect_target"] <= 1:
            info["matched"] = topic
            info["wait_event"].set()
            return
        # collect_until: count specific topic occurrences.
        info.setdefault("collected", []).append(topic)
        if len(info["collected"]) >= info["collect_target"]:
            info["matched"] = topic
            info["wait_event"].set()

    # ------------------------------------------------------------------
    async def _on_trace_completed(
        self, *, task_id: str, trace_id: str, iteration: int, outcome: dict[str, int],
    ) -> None:
        ctx = self._tasks.get(task_id)
        if not ctx:
            return
        ctx["consecutive_soft"] = 0
        # Persist + emit lifecycle.
        task_db.upsert_pipeline_state(
            trace_id=trace_id, pipeline=ctx["pipeline"].name, task_id=task_id,
            iteration=iteration, current_step=len(ctx["pipeline"].steps),
            status="completed",
        )
        self._merge_progress(task_id, iteration, outcome)
        try:
            self.bus.emit(make_event(
                TRACE_COMPLETED, dataset_tag=ctx["dataset_tag"],
                trace_id=trace_id, task_id=task_id, outcome=outcome,
            ))
        except Exception:
            self.log.exception("emit TRACE_COMPLETED failed")
        await self._maybe_advance_or_finish(task_id, iteration)

    async def _on_trace_failed(
        self, *, task_id: str, trace_id: str, reason: str, outcome: dict[str, int],
    ) -> None:
        ctx = self._tasks.get(task_id)
        if not ctx:
            return
        kind = classify_failure(reason, ctx["task"].failure_policy)
        # Unknown reasons treated as soft to avoid spurious aborts.
        if kind == "unknown":
            kind = "soft"
        if kind == "soft":
            ctx["consecutive_soft"] += 1
        task_db.upsert_pipeline_state(
            trace_id=trace_id, pipeline=ctx["pipeline"].name, task_id=task_id,
            iteration=ctx["task"].max_iterations, current_step=-1,  # marker
            status="failed",
        )
        self._merge_progress(
            task_id, iteration=ctx["consecutive_soft"],
            outcome={**outcome, "soft_failures": int(kind == "soft"),
                     "hard_failures": int(kind == "hard")},
        )
        try:
            self.bus.emit(make_event(
                TRACE_FAILED, dataset_tag=ctx["dataset_tag"],
                trace_id=trace_id, task_id=task_id, reason=reason, kind=kind,
            ))
        except Exception:
            self.log.exception("emit TRACE_FAILED failed")
        if kind == "hard":
            await self._exhaust(task_id, "hard_failure")
            return
        if ctx["consecutive_soft"] >= ctx["task"].failure_policy.abort_after_consecutive_soft:
            await self._exhaust(task_id, "consecutive_soft_failures")
            return
        # Soft failure: try next iteration.
        await self._maybe_advance_or_finish(task_id, iteration_just_finished=ctx["consecutive_soft"])

    # ------------------------------------------------------------------
    def _merge_progress(self, task_id: str, iteration: int, outcome: dict[str, int]) -> None:
        ctx = self._tasks.get(task_id)
        if not ctx:
            return
        # Read current persisted progress, sum, write back.
        row = task_db.get_task(task_id) or {}
        try:
            import json as _json
            current = _json.loads(row.get("progress_json") or "{}")
        except Exception:
            current = {}
        for k, v in outcome.items():
            current[k] = int(current.get(k, 0) or 0) + int(v or 0)
        current["iterations"] = int(row.get("iterations") or 0) + 1
        current["wall_time_elapsed"] = int(time.time() - ctx["started_at"])
        task_db.update_task_progress(
            task_id, iterations=current["iterations"], progress=current,
        )

    async def _maybe_advance_or_finish(self, task_id: str, iteration_just_finished: int) -> None:
        ctx = self._tasks.get(task_id)
        if not ctx or ctx["cancelled"]:
            return
        row = task_db.get_task(task_id) or {}
        try:
            import json as _json
            progress = _json.loads(row.get("progress_json") or "{}")
        except Exception:
            progress = {}
        goal = ctx["task"].goal
        if evaluate(goal, progress):
            # HIGH-2: write terminal DB state BEFORE emitting, so any concurrent
            # reader sees the final state and won't re-spawn or re-evaluate.
            task_db.finish_task(task_id, "satisfied")
            self._tasks.pop(task_id, None)
            self._iteration_tasks.pop(task_id, None)
            try:
                self.bus.emit(make_event(
                    TASK_GOAL_SATISFIED, dataset_tag=ctx["dataset_tag"],
                    task_id=task_id, iterations=int(progress.get("iterations", 0)),
                    progress=progress,
                ))
            except Exception:
                self.log.exception("emit TASK_GOAL_SATISFIED failed")
            return
        # Not satisfied: emit iteration-done + spawn next.
        try:
            self.bus.emit(make_event(
                TASK_ITERATION_DONE, dataset_tag=ctx["dataset_tag"],
                task_id=task_id, iteration=int(progress.get("iterations", 0)),
                trace_id=ctx.get("current_trace") or "",
                progress=progress,
            ))
        except Exception:
            self.log.exception("emit TASK_ITERATION_DONE failed")
        next_iter = int(progress.get("iterations", 0)) + 1
        if next_iter > ctx["max_iterations"]:
            await self._exhaust(task_id, "max_iterations")
            return
        # Re-check cancel here too — it may have landed between goal eval and here.
        # _on_cancel_requested already finishes the task in DB; just stop spawning.
        if ctx.get("cancelled"):
            self._tasks.pop(task_id, None)
            self._iteration_tasks.pop(task_id, None)
            return
        self._spawn_iteration(task_id, next_iter)

    async def _exhaust(self, task_id: str, reason: str) -> None:
        ctx = self._tasks.pop(task_id, None)
        self._iteration_tasks.pop(task_id, None)  # HIGH-3: prevent leak
        if not ctx:
            return
        row = task_db.get_task(task_id) or {}
        try:
            import json as _json
            progress = _json.loads(row.get("progress_json") or "{}")
        except Exception:
            progress = {}
        status = "exhausted" if reason != "hard_failure" else "failed"
        # HIGH-2: persist terminal state first, then announce.
        task_db.finish_task(task_id, status, error=reason)
        try:
            self.bus.emit(make_event(
                TASK_EXHAUSTED, dataset_tag=ctx["dataset_tag"],
                task_id=task_id,
                iterations=int(progress.get("iterations", 0)),
                reason=reason, progress=progress,
            ))
        except Exception:
            self.log.exception("emit TASK_EXHAUSTED failed")

    # ------------------------------------------------------------------
    # Control plane
    # ------------------------------------------------------------------
    async def _on_start_requested(self, event: Event) -> None:
        """External start request (typically from the web UI).

        Payload: {task_name, dataset_tag?, overrides?, origin?}.
        Allows a long-lived daemon coordinator to own the task lifecycle
        even though the requester is short-lived (HTTP handler).
        """
        p = event.payload or {}
        name = p.get("task_name") or p.get("name")
        if not name:
            return
        try:
            await self.start_task(
                name,
                dataset_tag=p.get("dataset_tag") or event.dataset_tag,
                origin=p.get("origin") or "external",
                overrides=p.get("overrides") or None,
            )
        except ValueError as e:
            self.log.warning("TASK_START_REQUESTED: %s", e)
        except Exception:
            self.log.exception("TASK_START_REQUESTED handler crashed")

    async def _on_cancel_requested(self, event: Event) -> None:
        # Trace-level cancel may come in too; for tasks we look up by task_id.
        task_id = (event.payload or {}).get("task_id")
        if task_id and task_id in self._tasks:
            self._tasks[task_id]["cancelled"] = True
            self._iteration_tasks.pop(task_id, None)  # HIGH-3
            task_db.finish_task(task_id, "cancelled")
            self.log.info("coordinator: cancelled task %s", task_id)

    async def _on_pause_requested(self, event: Event) -> None:
        task_id = (event.payload or {}).get("task_id")
        if task_id and task_id in self._tasks:
            self._tasks[task_id]["paused"] = True
            task_db.set_task_status(task_id, "paused")

    async def _on_resume_requested(self, event: Event) -> None:
        task_id = (event.payload or {}).get("task_id")
        if task_id and task_id in self._tasks:
            self._tasks[task_id]["paused"] = False
            task_db.set_task_status(task_id, "running")


__all__ = ["CoordinatorAgent"]
