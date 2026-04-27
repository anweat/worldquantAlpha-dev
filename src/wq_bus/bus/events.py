"""Event catalog — single source of truth for all bus topics and payload schemas.

Every event payload **must** include `dataset_tag`. Helper `make_event()` enforces this.

Topics are short uppercase strings.  New topics are registered via ``register_topic``
(from ``wq_bus.bus.topic_registry``); existing 13 + 6 new phase-1 topics are registered
below as module-level constants for back-compat.

Add new topics: import ``register_topic`` and call it at module/import time.
Document producers/consumers in ``docs/architecture/EVENT_CATALOG.md``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from wq_bus.bus.topic_registry import register_topic


# ---------------------------------------------------------------------------
# Legacy Topic enum — kept for back-compat (isinstance checks, .value access)
# ---------------------------------------------------------------------------

class Topic(str, Enum):
    # Alpha generation flow
    GENERATE_REQUESTED = "GENERATE_REQUESTED"
    ALPHA_DRAFTED = "ALPHA_DRAFTED"
    IS_RESULT = "IS_RESULT"
    IS_PASSED = "IS_PASSED"
    SC_RESULT = "SC_RESULT"
    BATCH_DONE = "BATCH_DONE"

    # Learning / analysis
    LEARNING_DRAFTED = "LEARNING_DRAFTED"
    PORTFOLIO_ANALYZED = "PORTFOLIO_ANALYZED"

    # Crawler / knowledge ingestion
    CRAWL_REQUESTED = "CRAWL_REQUESTED"
    DOC_FETCHED = "DOC_FETCHED"
    KNOWLEDGE_UPDATED = "KNOWLEDGE_UPDATED"

    # Submission
    QUEUE_FLUSH_REQUESTED = "QUEUE_FLUSH_REQUESTED"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_FAILED = "SUBMISSION_FAILED"


# ---------------------------------------------------------------------------
# Register all existing topics in the dynamic registry (idempotent)
# ---------------------------------------------------------------------------

for _t in Topic:
    register_topic(_t.value)

# Phase 1 new topics (TRACE_AS_TASK.md + EVENT_CATALOG §3)
TASK_STARTED             = register_topic("TASK_STARTED",   description="bus.start_task() fired")
TASK_COMPLETED           = register_topic("TASK_COMPLETED", description="Task finished successfully")
TASK_FAILED              = register_topic("TASK_FAILED",    description="Task failed / exception")
TASK_TIMEOUT             = register_topic("TASK_TIMEOUT",   description="Supervisor detected timeout")
TASK_CANCEL_REQUESTED    = register_topic("TASK_CANCEL_REQUESTED", description="User/CLI cancel")
POOL_UPDATED             = register_topic("POOL_UPDATED",   description="pool_stats updated")
STRENGTH_OVERRIDE_SET    = register_topic("STRENGTH_OVERRIDE_SET", description="StrengthRouter override")
AI_CACHE_REISSUED        = register_topic("AI_CACHE_REISSUED", description="Recovered package resent")
RECIPE_PROPOSED          = register_topic("RECIPE_PROPOSED", description="LLM proposed a new recipe")
BUDGET_EXHAUSTED         = register_topic("BUDGET_EXHAUSTED", description="daily_ai_cap reached")
SESSION_INVALID          = register_topic("SESSION_INVALID", description="BRAIN session expired")

# Phase 2 T1 new topics
RECIPE_CANDIDATES_READY  = register_topic("RECIPE_CANDIDATES_READY", description="pattern_extractor wrote recipe_candidates JSON")
FAILURE_BATCH_READY      = register_topic("FAILURE_BATCH_READY",     description=">=10 pending failures accumulated")
POOL_STATS_UPDATED       = register_topic("POOL_STATS_UPDATED",      description="pool_stats refreshed (periodic)")

# Phase 2 T2-pre new topics
RATE_PRESSURE = register_topic(
    "RATE_PRESSURE",
    payload_schema={
        "rate_429": "float - fraction of requests returning 429/503 in last 5-min window",
        "window_secs": "int - observation window size in seconds (always 300)",
        "max_concurrent_new": "int - recommended new concurrency cap for sim_executor",
        "dataset_tag": "str - active dataset tag at time of event",
    },
    description="429 rate > 20% in 5-min window; sim_executor should reduce concurrency",
)

# Phase 2 T2 — API health-check loop
HEALTH_PROBE_DONE = register_topic(
    "HEALTH_PROBE_DONE",
    payload_schema={
        "ok": "bool - probe succeeded",
        "latency_ms": "int - end-to-end probe latency",
        "kind": "str - 'auth' | 'simulate' | 'untested_alpha'",
        "alpha_id": "str|None - probe target alpha id if kind != 'auth'",
        "error": "str|None - error string when ok=False",
        "rolling_failure_rate": "float - failure rate over the recent window",
    },
    description="api_healthcheck completed one probe; informational only",
)
API_DEGRADED = register_topic(
    "API_DEGRADED",
    payload_schema={
        "rolling_failure_rate": "float",
        "window_size": "int",
        "paused_agents": "list[str] - agent types asked to pause (alpha_gen / submitter)",
        "reason": "str",
    },
    description="rolling probe failure rate exceeded threshold; gate downstream agents",
)
API_RESTORED = register_topic(
    "API_RESTORED",
    payload_schema={
        "consecutive_ok": "int",
        "resumed_agents": "list[str]",
    },
    description="API recovered after N consecutive OK probes; resume gated agents",
)

# ---------------------------------------------------------------------------
# Topics whose payloads are mirrored to state.db.events for crash recovery
# ---------------------------------------------------------------------------

CRITICAL_TOPICS: set[str] = {
    Topic.SUBMITTED.value,
    Topic.SUBMISSION_FAILED.value,
    Topic.LEARNING_DRAFTED.value,
    Topic.KNOWLEDGE_UPDATED.value,
    Topic.GENERATE_REQUESTED.value,
    Topic.ALPHA_DRAFTED.value,
    Topic.BATCH_DONE.value,
    Topic.PORTFOLIO_ANALYZED.value,
    Topic.IS_PASSED.value,
    Topic.SC_RESULT.value,
    Topic.QUEUE_FLUSH_REQUESTED.value,
    TASK_STARTED,
    TASK_FAILED,
    TASK_COMPLETED,
    TASK_TIMEOUT,
    RECIPE_CANDIDATES_READY,
    RECIPE_PROPOSED,
    FAILURE_BATCH_READY,
    HEALTH_PROBE_DONE,
    API_DEGRADED,
    API_RESTORED,
    SESSION_INVALID,
    BUDGET_EXHAUSTED,
}


@dataclass
class Event:
    """Generic event envelope. Specific payloads can be subclasses or just dicts."""
    topic: str
    dataset_tag: str
    payload: dict = field(default_factory=dict)
    trace_id: str = ""

    def to_dict(self) -> dict:
        return {"topic": self.topic, "dataset_tag": self.dataset_tag,
                "trace_id": self.trace_id, **self.payload}


def make_event(topic: str | Topic, dataset_tag: str, **payload: Any) -> Event:
    """Build an Event. Inherits trace_id from current context, or starts a new one."""
    from wq_bus.utils.tag_context import get_trace_id, new_trace_id
    if isinstance(topic, Topic):
        topic = topic.value
    if not dataset_tag:
        raise ValueError(f"event {topic} requires a non-empty dataset_tag")
    trace_id = payload.pop("trace_id", None) or get_trace_id() or new_trace_id()
    return Event(topic=topic, dataset_tag=dataset_tag, trace_id=trace_id, payload=payload)


# ---------- typed payload helpers (dataclasses) ----------

@dataclass
class GenerateRequestedPayload:
    n: int = 10
    hint: str = ""
    source: str = "cli"  # cli | scheduler | knowledge_update


@dataclass
class AlphaDraftedPayload:
    expression: str
    settings: dict
    fingerprint: str
    rationale: str = ""


@dataclass
class ISResultPayload:
    alpha_id: str
    expression: str
    settings: dict
    is_metrics: dict  # sharpe/fitness/turnover/...
    passed: bool


@dataclass
class SCResultPayload:
    alpha_id: str
    sc_value: float
    passed: bool


@dataclass
class BatchDonePayload:
    batch_id: str
    n_total: int
    n_is_passed: int
    n_sc_passed: int


@dataclass
class CrawlRequestedPayload:
    target: str  # name from crawl_targets.yaml
    force: bool = False


@dataclass
class DocFetchedPayload:
    url_hash: str
    source: str
    title: str


@dataclass
class SubmittedPayload:
    alpha_id: str
    submission_id: Optional[str] = None
