"""submitter agent — drains submission_queue when triggered."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from wq_bus.agents.base import AgentBase
from wq_bus.bus.events import Event, Topic, make_event
from wq_bus.data import knowledge_db, state_db
from wq_bus.utils.yaml_loader import load_yaml

if TYPE_CHECKING:
    from wq_bus.brain.client import BrainClient


class Submitter(AgentBase):
    AGENT_TYPE = "submitter"
    SUBSCRIPTIONS = [Topic.QUEUE_FLUSH_REQUESTED]

    def __init__(self, bus, brain_client: "BrainClient") -> None:
        super().__init__(bus)
        self.client = brain_client
        sub = load_yaml("submission")
        self.daily_max = int(sub.get("daily_max", 6))
        self.max_per_flush = int(sub.get("max_per_flush", 4))
        # Dead-letter after this many transient failures (default 3).
        self.max_retries = int(sub.get("max_retries", 3))

    async def on_queue_flush_requested(self, event: Event) -> None:
        tag = event.dataset_tag
        # Enforce daily_max BEFORE picking items so we don't even try when
        # the day's budget is exhausted (was loaded from yaml but never
        # checked previously — see submission.yaml: daily_max).
        try:
            already_today = state_db.count_submitted_today()
        except Exception:
            already_today = 0
        remaining_today = max(0, self.daily_max - already_today)
        if remaining_today <= 0:
            self.log.info("submitter: daily_max=%d reached (today=%d), skip flush for %s",
                          self.daily_max, already_today, tag)
            return
        # Pick up both fresh and retry-eligible items.
        queue = state_db.list_queue(status="pending")
        queue += state_db.list_queue(status="retry_pending")
        if not queue:
            self.log.info("submission queue empty for %s", tag)
            return

        loop = asyncio.get_running_loop()
        n_submitted = 0
        budget = min(self.max_per_flush, remaining_today)
        for item in queue:
            if n_submitted >= budget:
                break
            alpha_id = item["alpha_id"]
            # Atomic claim — if we lose the race (another flush already took
            # this item), skip and keep going.
            if not state_db.claim_queue_item(alpha_id):
                self.log.debug("submitter: lost claim race for %s, skipping", alpha_id)
                continue
            try:
                if alpha_id.startswith("DRY"):
                    # Synthetic dry-run alpha — skip the real API call.
                    resp = {"id": f"sub_{alpha_id}", "status": "ACTIVE", "_dry_run": True}
                else:
                    resp = await loop.run_in_executor(None, self.client.submit_alpha, alpha_id)
                state_db.update_queue_status(alpha_id, "submitted",
                                             note=str(resp)[:200])
                knowledge_db.upsert_alpha(
                    alpha_id, "", {}, "",
                    status="submitted",
                )
                self.bus.emit(make_event(Topic.SUBMITTED, tag,
                                         alpha_id=alpha_id,
                                         submission_id=(resp or {}).get("id")))
                n_submitted += 1
            except Exception as e:  # noqa: BLE001
                self.log.exception("submit failed %s: %s", alpha_id, e)
                # Re-read row to get current retry_count (may have been
                # bumped by previous flush attempts).
                row = state_db.get_queue_item(alpha_id) or {}
                attempts = int(row.get("retry_count") or 0) + 1
                if attempts >= self.max_retries:
                    state_db.update_queue_status(
                        alpha_id, "dead_letter",
                        note=f"max_retries={self.max_retries} exceeded",
                        last_error=str(e)[:200], bump_retry=True,
                    )
                    self.log.error("dead-letter %s after %d attempts: %s",
                                   alpha_id, attempts, str(e)[:200])
                else:
                    state_db.update_queue_status(
                        alpha_id, "retry_pending",
                        note=f"attempt={attempts}/{self.max_retries}",
                        last_error=str(e)[:200], bump_retry=True,
                    )
                self.bus.emit(make_event(Topic.SUBMISSION_FAILED, tag,
                                         alpha_id=alpha_id,
                                         error=str(e)[:200],
                                         attempt=attempts,
                                         dead_letter=attempts >= self.max_retries))

        self.log.info("submitter flushed %d/%d for %s", n_submitted, len(queue), tag)
