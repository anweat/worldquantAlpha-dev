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
TASK_PAUSE_REQUESTED     = register_topic("TASK_PAUSE_REQUESTED",  description="User/CLI pause (agents drop subsequent events for this trace)")
TASK_RESUME_REQUESTED    = register_topic("TASK_RESUME_REQUESTED", description="User/CLI resume a paused trace")
TASK_START_REQUESTED     = register_topic("TASK_START_REQUESTED",  description="External (web/CLI) requests daemon coordinator to launch a pipeline task")
TASK_CANCELLED           = register_topic("TASK_CANCELLED",        description="Trace status flipped to cancelled")
TASK_PAUSED              = register_topic("TASK_PAUSED",           description="Trace status flipped to paused")
TASK_RESUMED             = register_topic("TASK_RESUMED",          description="Trace status flipped back to running after pause")
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
ALPHA_DRAFT_SKIPPED      = register_topic(
    "ALPHA_DRAFT_SKIPPED",
    payload_schema={
        "reason": "str - why this draft was skipped (duplicate / invalid / filtered)",
        "expression": "str|None - the rejected expression",
        "trace_id": "str|None",
    },
    description="alpha_gen produced a candidate but discarded it (dedup/validation); informational",
)

# Round-5 b3: error events (sim/gen unrecoverable failures emit dedicated topic)
ALPHA_GEN_ERRORED = register_topic(
    "ALPHA_GEN_ERRORED",
    payload_schema={
        "reason": "str - error message",
        "attempts": "int - number of attempts before giving up",
        "trace_id": "str|None",
    },
    description="alpha_gen failed after retries (b1/b3); trace marked failed",
)
ALPHA_SIM_ERRORED = register_topic(
    "ALPHA_SIM_ERRORED",
    payload_schema={
        "expression": "str - simulated expression",
        "reason": "str - error message",
        "trace_id": "str|None",
    },
    description="sim_executor unrecoverable failure / no alpha_id (b3)",
)

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
# R6-C: trace lifecycle (per-iteration state machine inside a Task)
# ---------------------------------------------------------------------------
TRACE_COMPLETED = register_topic(
    "TRACE_COMPLETED",
    payload_schema={
        "trace_id": "str",
        "task_id": "str|None - parent task if this trace belongs to one",
        "outcome": "dict - per-pipeline result snapshot (counts, alpha_ids...)",
    },
    description="A pipeline trace finished cleanly; coordinator may spawn next iteration",
)
TRACE_FAILED = register_topic(
    "TRACE_FAILED",
    payload_schema={
        "trace_id": "str",
        "task_id": "str|None",
        "reason": "str",
        "kind": "str - soft|hard (see config/tasks.yaml failure_policy)",
    },
    description="Pipeline trace failed; coordinator decides retry vs hard-fail",
)

# ---------------------------------------------------------------------------
# R6-C: task lifecycle (outer goal-oriented loop owning multiple traces)
# ---------------------------------------------------------------------------
TASK_ITERATION_DONE = register_topic(
    "TASK_ITERATION_DONE",
    payload_schema={
        "task_id": "str",
        "iteration": "int - 1-based",
        "trace_id": "str - trace that just finished",
        "progress": "dict - cumulative goal counters",
    },
    description="Coordinator advanced one iteration; goal not yet satisfied",
)
TASK_GOAL_SATISFIED = register_topic(
    "TASK_GOAL_SATISFIED",
    payload_schema={
        "task_id": "str",
        "iterations": "int",
        "progress": "dict",
    },
    description="Task goal expression evaluated true; coordinator stops spawning",
)
TASK_EXHAUSTED = register_topic(
    "TASK_EXHAUSTED",
    payload_schema={
        "task_id": "str",
        "iterations": "int",
        "reason": "str - max_iterations|wall_time|consecutive_soft_failures|hard_failure",
        "progress": "dict",
    },
    description="Task ended without satisfying goal (cap or hard-fail)",
)
PIPELINE_ECHO = register_topic(
    "PIPELINE_ECHO",
    description="Test-only no-op topic for echo_pipeline (round6_e2e smoke).",
)

# ---------------------------------------------------------------------------
# R6-C: unified AI dispatch layer (request/response over the bus)
# ---------------------------------------------------------------------------
AI_CALL_REQUESTED = register_topic(
    "AI_CALL_REQUESTED",
    payload_schema={
        "call_id": "str - producer-assigned uuid for callback correlation",
        "prompt_kind": "str - template name in prompts/*.yaml",
        "vars": "dict - jinja-style variables for the template",
        "agent": "str - AGENT_TYPE of the requester",
        "adapter_hint": "str|None - 'openai' | 'glm' | None (auto)",
        "model_hint": "str|None - per-mode model override",
        "trace_id": "str",
    },
    description="An agent requests an AI completion via the unified service",
)
AI_CALL_DONE = register_topic(
    "AI_CALL_DONE",
    payload_schema={
        "call_id": "str",
        "ai_call_id": "int - row id in ai_calls table",
        "response": "dict|str - parsed response (json or text)",
        "trace_id": "str",
    },
    description="ai_service finished a call; consumer matches on call_id",
)
AI_CALL_FAILED = register_topic(
    "AI_CALL_FAILED",
    payload_schema={
        "call_id": "str",
        "reason": "str",
        "fatal": "bool - True triggers task hard-fail (not just trace-level)",
        "trace_id": "str",
    },
    description="ai_service gave up on a call; fatal=True propagates to task",
)

# ---------------------------------------------------------------------------
# R6-C: summarizer agent (cursor-pull, multi-mode)
# ---------------------------------------------------------------------------
SUMMARIZER_DONE = register_topic(
    "SUMMARIZER_DONE",
    payload_schema={
        "mode": "str - failure_summary|crawl_doc_summary|...",
        "scope": "str - dataset_tag or _global",
        "artifact_path": "str - relative path under memory/<scope>/",
        "items_consumed": "int",
        "ai_call_id": "int|None",
    },
    description="Summarizer wrote a new artifact and advanced its cursor",
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
    # R6-C additions: trace + task + AI lifecycle must survive crashes so the
    # coordinator can replay/resume goal-oriented loops cleanly.
    TRACE_COMPLETED,
    TRACE_FAILED,
    TASK_ITERATION_DONE,
    TASK_GOAL_SATISFIED,
    TASK_EXHAUSTED,
    AI_CALL_REQUESTED,
    AI_CALL_DONE,
    AI_CALL_FAILED,
    SUMMARIZER_DONE,
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


def make_event(topic: str | Topic, dataset_tag: str | None = None, **payload: Any) -> Event:
    """Build an Event. Inherits trace_id from current context, or starts a new one.

    ``dataset_tag`` is optional: if missing/empty, the event is tagged as
    ``"_global"`` and will be archived in the untagged shared workspace
    (see config/topics.yaml + bus/topic_meta.py). Topics whose registry entry
    sets ``scope: tag`` will still be routed to ``_global/orphans/...`` rather
    than rejected, keeping producers simple.
    """
    from wq_bus.utils.tag_context import get_trace_id, new_trace_id
    if isinstance(topic, Topic):
        topic = topic.value
    if not dataset_tag:
        dataset_tag = "_global"
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
