"""Crawl target configuration — loads config/crawl_targets.yaml.

Each target defines what to fetch, how to clean it, and when to emit a
DOC_FETCHED batch event (trigger_threshold).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from wq_bus.utils.yaml_loader import load_yaml

_CONFIG_KEY = "crawl_targets"


@dataclass
class CrawlTarget:
    name: str
    url_template: str
    source: str
    login_required: bool
    content_expectation: str
    cleaning_rules: list[str]
    trigger_threshold: int
    dataset_tag: str
    type: str  # 'html' | 'pdf' | 'spa'
    max_per_run: int = 20
    extra: dict = field(default_factory=dict)


def load_targets() -> dict[str, CrawlTarget]:
    """Return all targets keyed by name from config/crawl_targets.yaml."""
    raw: dict[str, Any] = load_yaml(_CONFIG_KEY)
    targets_raw: dict[str, Any] = raw.get("targets", {})
    result: dict[str, CrawlTarget] = {}
    for name, cfg in targets_raw.items():
        if not isinstance(cfg, dict):
            continue
        known_keys = {
            "url_template", "source", "login_required", "content_expectation",
            "cleaning_rules", "trigger_threshold", "dataset_tag", "type",
            "max_per_run",
        }
        extra = {k: v for k, v in cfg.items() if k not in known_keys}
        result[name] = CrawlTarget(
            name=name,
            url_template=cfg.get("url_template", ""),
            source=cfg.get("source", name),
            login_required=bool(cfg.get("login_required", False)),
            content_expectation=cfg.get("content_expectation", ""),
            cleaning_rules=list(cfg.get("cleaning_rules", [])),
            trigger_threshold=int(cfg.get("trigger_threshold", 10)),
            dataset_tag=cfg.get("dataset_tag", "shared"),
            type=cfg.get("type", "html"),
            max_per_run=int(cfg.get("max_per_run", 20)),
            extra=extra,
        )
    return result


def get_target(name: str) -> CrawlTarget:
    """Return the named target; raise KeyError if not found."""
    targets = load_targets()
    if name not in targets:
        raise KeyError(f"Crawl target '{name}' not found in config/crawl_targets.yaml")
    return targets[name]
