"""Dynamic topic registry for the wq-bus event system.

Topics are registered at import time; agents can call ``register_topic``
without touching ``events.py``.  The registry is in-process only
(no DB persistence needed — topics are re-registered each startup).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Global registry: topic_name -> metadata dict
TOPIC_REGISTRY: dict[str, dict] = {}


def register_topic(
    name: str,
    *,
    payload_schema: Optional[dict] = None,
    description: str = "",
) -> str:
    """Register a topic and return its canonical (uppercase) name.

    Idempotent: registering an already-known topic is a no-op and returns
    the existing name unchanged.  payload_schema is stored for documentation
    but not strictly validated at emit time (lenient default).

    Args:
        name: Topic name (will be uppercased).
        payload_schema: Optional dict describing required/optional payload fields.
        description: Human-readable description for tooling / docs.

    Returns:
        The canonical uppercase topic name.
    """
    name = name.upper()
    if name not in TOPIC_REGISTRY:
        TOPIC_REGISTRY[name] = {
            "payload_schema": payload_schema or {},
            "description": description,
            "registered_at": _utcnow_iso(),
        }
    return name


def is_registered(name: str) -> bool:
    """Return True if *name* is already registered (case-insensitive)."""
    return name.upper() in TOPIC_REGISTRY


def list_topics() -> list[dict]:
    """Return a snapshot of all registered topics (for CLI / --json)."""
    return [
        {
            "topic": k,
            "registered_at": v["registered_at"],
            "description": v.get("description", ""),
            "has_schema": bool(v.get("payload_schema")),
        }
        for k, v in sorted(TOPIC_REGISTRY.items())
    ]
