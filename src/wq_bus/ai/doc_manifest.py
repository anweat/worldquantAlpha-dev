"""Doc manifest loader for AI sub-agents.

Reads ``docs/manifest.generated.yaml`` (built by ``scripts/manifest_builder.py``)
and exposes filtered entries for a given agent mode + dataset_tag. Agents inject
the filtered list into prompts so the AI sub-agent can ``view <path>`` on demand
instead of receiving every doc inline.

Usage::

    from wq_bus.ai.doc_manifest import load_for_mode
    entries = load_for_mode("explore", dataset_tag="usa_top3000")
    # → list[{"path": str, "title": str, "summary": str, "tags": list[str],
    #         "priority": int, "size": int, "mtime": str}]

If the generated file is missing, falls back to the handwritten
``docs/manifest.yaml``; a warning is logged but the call never raises so
prompt rendering stays robust.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATED = PROJECT_ROOT / "docs" / "manifest.generated.yaml"
HANDWRITTEN = PROJECT_ROOT / "docs" / "manifest.yaml"


@lru_cache(maxsize=1)
def _raw_manifest() -> dict:
    # Prefer generated (has size/mtime/summary); fall back to handwritten.
    for p in (GENERATED, HANDWRITTEN):
        if p.exists():
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if isinstance(raw, dict) and raw:
                return raw
    return {}


def reload() -> None:
    """Drop cache; force re-read on next access (used by CLI/tests)."""
    _raw_manifest.cache_clear()


def _resolve_per_tag(path_template: str, tag: str | None) -> str | None:
    """Replace ``{tag}`` and verify the file exists; return None if not."""
    if "{tag}" in path_template:
        if not tag:
            return None
        path = path_template.replace("{tag}", tag)
    else:
        path = path_template
    if not (PROJECT_ROOT / path).exists():
        return None
    return path


def load_for_mode(
    mode: str,
    dataset_tag: str | None = None,
    *,
    max_entries: int = 12,
    max_priority: int = 4,
) -> list[dict[str, Any]]:
    """Return ranked list of doc entries relevant to *mode*.

    Filters by ``applies_to_modes`` and ``priority <= max_priority``. Per-tag
    scope entries with missing files are silently dropped. Result is sorted by
    ``priority`` ascending then ``path`` for stability.
    """
    raw = _raw_manifest()
    entries: Iterable[dict] = raw.get("entries") or []
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        modes = e.get("applies_to_modes") or ["*"]
        if "*" not in modes and mode not in modes:
            continue
        prio = int(e.get("priority", 4))
        if prio > max_priority:
            continue
        path = _resolve_per_tag(str(e.get("path", "")), dataset_tag)
        if not path:
            continue
        out.append({
            "path": path,
            "title": str(e.get("title", "")),
            "summary": str(e.get("summary", "")),
            "tags": list(e.get("tags") or []),
            "priority": prio,
            "size": int(e.get("size", 0)),
            "mtime": str(e.get("mtime", "")),
        })
    out.sort(key=lambda x: (x["priority"], x["path"]))
    return out[:max_entries]


def render_for_prompt(entries: list[dict[str, Any]]) -> str:
    """Format entries as a compact bullet list for prompt injection.

    One line per entry; empty string if list is empty (caller may skip the
    section entirely)."""
    if not entries:
        return ""
    lines: list[str] = []
    for e in entries:
        size_kb = max(1, (e.get("size") or 0) // 1024)
        tags = ",".join(e.get("tags") or [])
        title = e.get("title") or ""
        summary = e.get("summary") or ""
        suffix = f" — {summary}" if summary and summary != title else ""
        lines.append(
            f"- {e['path']} ({size_kb}KB, [{tags}]) — {title}{suffix}"
        )
    return "\n".join(lines)
