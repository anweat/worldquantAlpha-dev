"""Centralised time helpers (rev-h7).

Replaces ~10 ad-hoc copies of `_utcnow_iso()` scattered across the codebase
and gives every consumer a single source of truth for UTC handling, day
boundaries, and NTP-jump defence.

Conventions:
    * All ISO timestamps use ``%Y-%m-%dT%H:%M:%SZ`` (UTC, second precision).
    * ``utcnow_ts()`` is a thin wrapper around ``time.time()`` so tests can
      monkey-patch one symbol if we ever need fake clocks.
    * ``today_start_ts_utc()`` returns the epoch seconds of 00:00:00 UTC for
      the *current* day. Use this for "since midnight UTC" semantics
      (e.g. daily caps) — much more meaningful than ``time.time() - 86400``
      which slides with whatever moment the query runs and drifts on NTP
      corrections.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

__all__ = [
    "utcnow",
    "utcnow_iso",
    "utcnow_ts",
    "today_utc_str",
    "today_start_ts_utc",
    "iso_to_ts",
    "safe_elapsed",
]


def utcnow() -> datetime:
    """Timezone-aware UTC ``datetime``."""
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp, second precision (e.g. ``2026-04-27T09:30:15Z``)."""
    return utcnow().strftime(_ISO_FMT)


def utcnow_ts() -> float:
    """Epoch seconds (UTC). Centralised so tests can monkey-patch."""
    return time.time()


def today_utc_str() -> str:
    """Current calendar day in UTC as ``YYYY-MM-DD``.

    Used for partition keys (e.g. daily_budget_reservations.day).
    """
    return utcnow().strftime("%Y-%m-%d")


def today_start_ts_utc() -> float:
    """Epoch seconds of 00:00:00 UTC for *today*.

    Use as a "since midnight UTC" cutoff for daily counts so that:
        * Result is stable within a calendar day (small NTP wobbles do not
          slide the window).
        * Day boundaries align with timezone-agnostic reporting.
    """
    now = utcnow()
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return midnight.timestamp()


def iso_to_ts(iso_str: str) -> float | None:
    """Parse an ISO-8601 timestamp back to epoch seconds; ``None`` on failure.

    Tolerant: accepts both trailing ``Z`` and offset forms, with or without
    fractional seconds.
    """
    if not iso_str:
        return None
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def safe_elapsed(started_ts: float, now_ts: float | None = None) -> float:
    """Defensive elapsed-seconds: clamps negatives (NTP step backwards) to 0.

    Supervisor / timeout logic should use this instead of raw subtraction so
    a clock correction does not instantly time-out a healthy trace.
    """
    cur = utcnow_ts() if now_ts is None else now_ts
    elapsed = cur - started_ts
    return elapsed if elapsed >= 0 else 0.0
