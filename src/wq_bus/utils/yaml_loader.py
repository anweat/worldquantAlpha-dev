"""YAML loading helpers."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "config"


@lru_cache(maxsize=64)
def load_yaml(name: str) -> dict[str, Any]:
    """Load a YAML file from config/.

    Args:
        name: Filename with or without .yaml extension, or absolute path.
    """
    path = Path(name)
    if not path.is_absolute():
        if not name.endswith((".yaml", ".yml")):
            name = name + ".yaml"
        path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def reload_yaml(name: str) -> dict[str, Any]:
    """Bypass cache and reload a YAML file."""
    load_yaml.cache_clear()
    return load_yaml(name)
