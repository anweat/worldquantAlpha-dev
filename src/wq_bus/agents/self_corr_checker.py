"""self_corr_checker agent — checks SELF_CORRELATION on IS-passed alphas.

Listens: IS_PASSED
Emits:   SC_RESULT (passed/failed), enqueues to submission_queue if passed.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from wq_bus.agents.base import AgentBase
from wq_bus.analysis.self_correlation import check, extract_sc_value, extract_sc_result
from wq_bus.bus.events import Event, Topic, make_event
from wq_bus.data import knowledge_db, state_db
from wq_bus.utils.yaml_loader import load_yaml

if TYPE_CHECKING:
    from wq_bus.brain.client import BrainClient


class SelfCorrChecker(AgentBase):
    AGENT_TYPE = "self_corr_checker"
    SUBSCRIPTIONS = [Topic.IS_PASSED]

    def __init__(self, bus, brain_client: "BrainClient") -> None:
        super().__init__(bus)
        self.client = brain_client
        ana = load_yaml("analysis")
        self.threshold = float(ana.get("self_correlation_threshold", 0.7))

    async def on_is_passed(self, event: Event) -> None:
        alpha_id = event.payload["alpha_id"]
        record = event.payload.get("alpha_record")
        tag = event.dataset_tag

        # If SC is still PENDING, poll up to N times waiting for BRAIN to compute it.
        # TUTORIAL accounts can take 5-10 min for SELF_CORRELATION to resolve.
        loop = asyncio.get_running_loop()
        for attempt in range(20):  # ~20 * 30s = 10 min budget
            if record and not self._sc_pending(record):
                break
            await asyncio.sleep(30)
            try:
                record = await loop.run_in_executor(None, self.client.get_alpha, alpha_id)
            except Exception as e:  # noqa: BLE001
                # Transient HTTP / auth failure — log + retry next attempt
                # rather than abandoning the whole SC check for this alpha.
                self.log.warning("get_alpha attempt %d/20 failed for %s: %s — retrying",
                                 attempt + 1, alpha_id, e)
                continue
        else:
            # Loop exhausted without break — SC still pending. Mark and exit
            # so this alpha doesn't sit forever in 'simulating' state.
            self.log.error("SC poll budget exhausted for %s; leaving as PENDING", alpha_id)
            self.bus.emit(make_event(Topic.SC_RESULT, tag,
                                     alpha_id=alpha_id, sc_value=None, passed=False,
                                     error="poll_budget_exhausted"))
            return

        passed, value = check(record, threshold=self.threshold)
        sc_result = extract_sc_result(record)
        self.log.info("SC check alpha=%s result=%s value=%s -> passed=%s",
                      alpha_id, sc_result, value, passed)

        knowledge_db.upsert_alpha(
            alpha_id, record.get("regular", {}).get("code", ""),
            record.get("settings", {}), settings_hash="",
            sc_metrics={"value": value, "passed": passed},
            status="sc_passed" if passed else "sc_failed",
        )

        if passed:
            state_db.enqueue_submission(
                alpha_id,
                is_metrics=record.get("is"),
                sc_value=value,
                priority=int((value or 0) * -100),  # lower SC -> higher priority
                note="auto-enqueued by self_corr_checker",
            )
            # Self-driving: ask the submitter to drain right away.
            self.bus.emit(make_event(Topic.QUEUE_FLUSH_REQUESTED, tag,
                                     source="self_corr_checker", alpha_id=alpha_id))

        self.bus.emit(make_event(Topic.SC_RESULT, tag,
                                 alpha_id=alpha_id, sc_value=value, passed=passed))

    @staticmethod
    def _sc_pending(record: dict) -> bool:
        for c in (record.get("is") or {}).get("checks") or []:
            if c.get("name") == "SELF_CORRELATION":
                return c.get("result") in ("PENDING", None)
        return True
