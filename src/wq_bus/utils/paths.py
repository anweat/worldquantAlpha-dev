"""Single source of truth for filesystem layout (rev-h7).

Eliminates 13 separate ``Path(__file__).resolve().parents[3]`` recomputations
that all silently depend on the wq_bus package staying at depth 3 from the
project root. If the layout ever moves, fix this file (and only this file).
"""
from __future__ import annotations

from pathlib import Path

# src/wq_bus/utils/paths.py  →  parents[0]=utils, [1]=wq_bus, [2]=src, [3]=project root
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

CONFIG_DIR: Path = PROJECT_ROOT / "config"
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
MEMORY_DIR: Path = PROJECT_ROOT / "memory"
DOCS_DIR: Path = PROJECT_ROOT / "docs"
SCRIPTS_DIR: Path = PROJECT_ROOT / "scripts"
RESULTS_DIR: Path = PROJECT_ROOT / "test_results"
CACHE_DIR: Path = PROJECT_ROOT / ".cache"
STATE_DIR: Path = PROJECT_ROOT / ".state"

__all__ = [
    "PROJECT_ROOT",
    "CONFIG_DIR",
    "DATA_DIR",
    "LOGS_DIR",
    "MEMORY_DIR",
    "DOCS_DIR",
    "SCRIPTS_DIR",
    "RESULTS_DIR",
    "CACHE_DIR",
    "STATE_DIR",
]
