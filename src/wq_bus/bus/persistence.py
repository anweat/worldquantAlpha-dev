"""Critical-event persistence to state.db.

Topics in `events.CRITICAL_TOPICS` are mirrored synchronously *before* handler
dispatch so they survive process crashes. `replay_unconsumed()` lets a fresh
process re-emit anything the previous run missed.
"""
from __future__ import annotations

from wq_bus.bus.events import Event
from wq_bus.data import state_db
from wq_bus.utils.logging import get_logger

log = get_logger(__name__)


def mirror_event(event: Event) -> None:
    """Synchronously persist a critical event (with trace_id)."""
    state_db.record_event(event.topic, event.payload,
                          dataset_tag=event.dataset_tag,
                          trace_id=getattr(event, "trace_id", None))


def replay_unconsumed(bus, *, dataset_tag: str | None = None) -> int:
    """Re-emit any unconsumed critical events for the given tag (or all).

    Returns count of events replayed.

    NOTE: Mirroring is suppressed during replay (bus._mirror_enabled is
    flipped off) to prevent the events table from doubling on every restart.
    """
    from wq_bus.bus.events import make_event
    rows = state_db.list_unconsumed_events(dataset_tag=dataset_tag) if dataset_tag else _list_all_unconsumed()
    n = 0
    prev_mirror = getattr(bus, "_mirror_enabled", True)
    bus._mirror_enabled = False
    try:
        for row in rows:
            evt = make_event(row["topic"], row["dataset_tag"], **_decode_payload(row["payload_json"]))
            bus.emit(evt)
            state_db.mark_event_consumed(row["id"])
            n += 1
    finally:
        bus._mirror_enabled = prev_mirror
    log.info("replayed %d unconsumed events (mirror suppressed)", n)
    return n


def _decode_payload(raw: str) -> dict:
    import json
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _list_all_unconsumed() -> list[dict]:
    """Variant that doesn't require a tag context (admin/replay use)."""
    from wq_bus.data._sqlite import open_state
    with open_state() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE consumed=0 ORDER BY id"
        ).fetchall()]
