"""Crawler-side threshold checks → DOC_FETCHED batch event emission.

Called by crawler_agent after each fetch run. Counts pending docs per source
and emits a DOC_FETCHED event when any source reaches its trigger_threshold.

When threshold is hit, this also starts a child ``doc_summary`` task whose
parent_trace_id is the current crawler trace (read from the trace contextvar).
The DOC_FETCHED event is then emitted under the child trace, so the
doc_summarizer's processing flows naturally into the doc_summary trace.
"""
from __future__ import annotations

from wq_bus.bus.events import Topic, make_event
from wq_bus.bus.tasks import start_task
from wq_bus.crawler.targets_loader import load_targets
from wq_bus.data._sqlite import open_knowledge
from wq_bus.utils.logging import get_logger
from wq_bus.utils.tag_context import get_tag, get_trace_id, with_trace

log = get_logger(__name__)


def _count_pending_per_source(dataset_tag: str) -> dict[str, int]:
    """Return {source: pending_doc_count} for the given dataset_tag."""
    with open_knowledge() as conn:
        rows = conn.execute(
            """SELECT source, COUNT(*) AS cnt
               FROM crawl_docs
               WHERE dataset_tag=? AND summarized='pending'
               GROUP BY source""",
            (dataset_tag,),
        ).fetchall()
    return {row["source"]: row["cnt"] for row in rows}


def check_threshold_and_emit(bus, dataset_tag: str) -> None:
    """Emit DOC_FETCHED batch events for any source that has hit its threshold.

    For each crawl target whose *source* has >= trigger_threshold pending docs,
    a child ``doc_summary`` task is started (parent = current crawler trace),
    and one DOC_FETCHED event is emitted under the child trace_id.
    """
    targets = load_targets()
    pending = _count_pending_per_source(dataset_tag)
    parent_trace = get_trace_id()  # current crawler trace, may be None

    for target_name, target in targets.items():
        count = pending.get(target.source, 0)
        if count >= target.trigger_threshold:
            log.info(
                "threshold reached for source=%s (%d >= %d); spawning doc_summary child",
                target.source, count, target.trigger_threshold,
            )
            child = start_task(
                kind="doc_summary",
                payload={"source": target.source, "target": target_name,
                         "pending_count": count},
                origin="crawl_chain",
                parent=parent_trace,
                dataset_tag=dataset_tag,
            )
            with with_trace(child.trace_id):
                event = make_event(
                    Topic.DOC_FETCHED,
                    dataset_tag,
                    trace_id=child.trace_id,
                    source=target.source,
                    target=target_name,
                    pending_count=count,
                )
                bus.emit(event)
