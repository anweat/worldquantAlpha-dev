"""CLI/cron → bus event triggers + WatchdogPolicy integration.

Thin helpers that cli.py and the daemon use to emit "request"-type events into the bus.
Keeps cli.py free of bus internals.

WatchdogPolicy back-compat:
    from wq_bus.bus.triggers import watchdog_tick
    events = watchdog_tick(dataset_tag)  # uses DefaultStockpile
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from wq_bus.bus.event_bus import get_bus
from wq_bus.bus.events import (
    Topic, make_event,
    RECIPE_CANDIDATES_READY, FAILURE_BATCH_READY, POOL_STATS_UPDATED,
)

if TYPE_CHECKING:
    from wq_bus.bus.policies import WatchdogPolicy

# Module-level policy singleton (overridable by tests)
_policy: "WatchdogPolicy | None" = None

# Cooldown tracker for topic-based triggers: topic → last_emitted_ts
_topic_cooldown: dict[str, float] = {}


def get_policy() -> "WatchdogPolicy":
    global _policy
    if _policy is None:
        from wq_bus.bus.policies.default_stockpile import DefaultStockpile
        _policy = DefaultStockpile()
    return _policy


def set_policy(policy: "WatchdogPolicy") -> None:
    """Override the module-level policy (useful in tests)."""
    global _policy
    _policy = policy


def trigger_generate(dataset_tag: str, n: int = 10, hint: str = "",
                     mode: str = "explore") -> None:
    get_bus().emit(make_event(Topic.GENERATE_REQUESTED, dataset_tag,
                              n=n, hint=hint, mode=mode, source="cli"))


def trigger_crawl(dataset_tag: str, target: str, force: bool = False) -> None:
    get_bus().emit(make_event(Topic.CRAWL_REQUESTED, dataset_tag,
                              target=target, force=force))


def trigger_flush(dataset_tag: str) -> None:
    get_bus().emit(make_event(Topic.QUEUE_FLUSH_REQUESTED, dataset_tag))


def _load_trigger_cfg() -> dict:
    try:
        from wq_bus.utils.yaml_loader import load_yaml
        return (load_yaml("triggers") or {}).get("triggers", {})
    except Exception:
        return {}


def _check_topic_triggers(dataset_tag: str) -> list:
    """Check topic-based thresholds and emit events when conditions are met.

    Returns list of emitted events.
    """
    emitted = []
    now = time.time()
    cfg = _load_trigger_cfg()
    bus = get_bus()

    # --- FAILURE_BATCH_READY ---
    fb_cfg = cfg.get("failure_batch_ready", {})
    fb_threshold = int(fb_cfg.get("threshold", 10))
    fb_cooldown  = float(fb_cfg.get("cooldown_secs", 900))
    last_fb = _topic_cooldown.get("FAILURE_BATCH_READY", 0.0)
    if now - last_fb >= fb_cooldown:
        try:
            from wq_bus.data._sqlite import open_knowledge
            with open_knowledge() as conn:
                # Count alphas that failed IS or have no sharpe (simulated but not is_passed)
                row = conn.execute(
                    """SELECT COUNT(*) AS n FROM alphas
                       WHERE dataset_tag=?
                         AND status='simulated'
                         AND (sharpe IS NULL OR sharpe < 1.25
                              OR fitness IS NULL OR fitness < 1.0)""",
                    (dataset_tag,),
                ).fetchone()
            pending_failures = int(row["n"] if row else 0)
            if pending_failures >= fb_threshold:
                ev = make_event(FAILURE_BATCH_READY, dataset_tag,
                                pending_failures=pending_failures)
                bus.emit(ev)
                _topic_cooldown["FAILURE_BATCH_READY"] = now
                emitted.append(ev)
        except Exception:
            pass

    # --- POOL_STATS_UPDATED ---
    # Plan §T1-G: fire when >=N new directions appeared since last fire (default 20).
    ps_cfg = cfg.get("pool_stats_updated", {})
    ps_cooldown = float(ps_cfg.get("cooldown_secs", 1800))
    ps_min_new_dirs = int(ps_cfg.get("min_new_directions", 20))
    last_ps = _topic_cooldown.get("POOL_STATS_UPDATED", 0.0)
    if now - last_ps >= ps_cooldown:
        try:
            from wq_bus.data._sqlite import open_knowledge
            with open_knowledge() as conn:
                row = conn.execute(
                    """SELECT COUNT(DISTINCT direction_id) AS n FROM alphas
                       WHERE dataset_tag=? AND status!='legacy'
                         AND direction_id IS NOT NULL""",
                    (dataset_tag,),
                ).fetchone()
            distinct_dirs = int(row["n"] if row else 0)
            baseline_key = f"POOL_STATS_UPDATED::baseline::{dataset_tag}"
            baseline = int(_topic_cooldown.get(baseline_key, 0))
            new_dirs = max(distinct_dirs - baseline, 0)
            if distinct_dirs > 0 and (baseline == 0 or new_dirs >= ps_min_new_dirs):
                ev = make_event(POOL_STATS_UPDATED, dataset_tag,
                                total_directions=distinct_dirs,
                                new_directions=new_dirs)
                bus.emit(ev)
                _topic_cooldown["POOL_STATS_UPDATED"] = now
                _topic_cooldown[baseline_key] = distinct_dirs
                emitted.append(ev)
        except Exception:
            pass

    return emitted


def watchdog_tick(dataset_tag: str) -> list:
    """Run the watchdog policy and emit any resulting events.

    Also checks threshold-based topic triggers (FAILURE_BATCH_READY, POOL_STATS_UPDATED).

    Returns the list of events emitted (empty if nothing triggered).
    """
    policy = get_policy()
    emitted = []
    try:
        from wq_bus.bus.policies.default_stockpile import DefaultStockpile
        if isinstance(policy, DefaultStockpile):
            state = policy.build_state(dataset_tag)
        else:
            state = {"dataset_tag": dataset_tag}
        events = policy.should_trigger(state)
        bus = get_bus()
        for evt in events:
            bus.emit(evt)
        emitted.extend(events)
    except Exception:
        from wq_bus.utils.logging import get_logger
        get_logger(__name__).exception("watchdog_tick failed for %s", dataset_tag)

    # Topic-based threshold triggers
    try:
        emitted.extend(_check_topic_triggers(dataset_tag))
    except Exception:
        from wq_bus.utils.logging import get_logger
        get_logger(__name__).exception("topic trigger check failed for %s", dataset_tag)

    return emitted
