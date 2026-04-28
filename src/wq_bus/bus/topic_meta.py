"""Topic metadata loader.

Resolves bus event topics to (workspace_scope, topic_subspace) for artifact
archival and indexed querying. Source of truth: ``config/topics.yaml``.

Decoupling principle: producers don't need to know where their events get
indexed. They emit; the bus layer fills topic_subspace + workspace_scope from
the registry; consumers (summarizer / curator) query by (scope, subspace).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class TopicMeta:
    """Artifact placement metadata for a single bus topic."""
    scope: str            # "tag" | "global" | "either"
    subspace: str         # slash-separated subindex path
    searchable: bool      # summarizer should index this
    retention_days: int   # prune budget


_DEFAULT = TopicMeta(scope="either", subspace="events/misc",
                     searchable=False, retention_days=30)


@lru_cache(maxsize=1)
def _load_registry() -> tuple[TopicMeta, dict[str, TopicMeta]]:
    """Load topics.yaml; return (defaults, {topic: TopicMeta})."""
    try:
        from wq_bus.utils.yaml_loader import load_yaml
        raw = load_yaml("topics") or {}
    except Exception:
        raw = {}
    defaults_raw = raw.get("defaults") or {}
    defaults = TopicMeta(
        scope=str(defaults_raw.get("scope", _DEFAULT.scope)),
        subspace=str(defaults_raw.get("subspace", _DEFAULT.subspace)),
        searchable=bool(defaults_raw.get("searchable", _DEFAULT.searchable)),
        retention_days=int(defaults_raw.get("retention_days", _DEFAULT.retention_days)),
    )
    topics_raw = raw.get("topics") or {}
    out: dict[str, TopicMeta] = {}
    for name, entry in topics_raw.items():
        if not isinstance(entry, dict):
            continue
        out[str(name).upper()] = TopicMeta(
            scope=str(entry.get("scope", defaults.scope)),
            subspace=str(entry.get("subspace", defaults.subspace)),
            searchable=bool(entry.get("searchable", defaults.searchable)),
            retention_days=int(entry.get("retention_days", defaults.retention_days)),
        )
    return defaults, out


def reload() -> None:
    """Drop the cache; re-read on next lookup. Use after editing topics.yaml."""
    _load_registry.cache_clear()


def get(topic: str) -> TopicMeta:
    """Return TopicMeta for *topic*, falling back to defaults if unregistered."""
    defaults, registry = _load_registry()
    return registry.get((topic or "").upper(), defaults)


def resolve_scope(topic: str, dataset_tag: Optional[str]) -> tuple[str, str]:
    """Compute (workspace_scope, topic_subspace) for an event.

    Returns:
        workspace_scope: "_global" or the dataset_tag value used for archival.
        topic_subspace: slash path (always non-empty).
    """
    meta = get(topic)
    sub = meta.subspace or _DEFAULT.subspace
    if meta.scope == "global":
        return "_global", sub
    if meta.scope == "tag":
        # tag-scoped topics REQUIRE a tag; if missing fall back to _global
        # rather than raising — keeps producers simple, but we leave a
        # marker subspace prefix so the caller can audit.
        if not dataset_tag or dataset_tag == "_global":
            return "_global", f"orphans/{sub}"
        return dataset_tag, sub
    # either
    if dataset_tag and dataset_tag != "_global":
        return dataset_tag, sub
    return "_global", sub


def list_searchable() -> list[str]:
    """Return all topic names where searchable=True (sorted)."""
    _, registry = _load_registry()
    return sorted(name for name, m in registry.items() if m.searchable)
