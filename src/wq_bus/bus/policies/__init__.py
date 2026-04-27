"""WatchdogPolicy ABC — pluggable trigger strategy for the bus daemon.

Per SIMULATION_POOL.md §4 and plan §8.2:
    class MyPolicy(WatchdogPolicy):
        def should_trigger(self, state: dict) -> list[BusEvent]: ...
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class WatchdogPolicy(ABC):
    """Abstract base class for watchdog trigger policies.

    ``should_trigger`` is called on each daemon tick with a *state* dict that
    contains at minimum:

        {
            "queue_pending":  int,
            "in_flight_sims": int,
            "daily_ai_count": int,
            "daily_ai_cap":   int,
            "pool_stats":     list[dict],   # from pool_stats_<TAG>
            "dataset_tag":    str,
            "recent_modes":   list[str],    # last N triggered modes
        }

    Returns a (possibly empty) list of :class:`~wq_bus.bus.events.Event` objects
    to emit onto the bus.  An empty list means "don't trigger anything now".
    """

    @abstractmethod
    def should_trigger(self, state: dict) -> list:
        """Return events to emit, or [] to skip this tick."""
        ...
