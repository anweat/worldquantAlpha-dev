"""AI package cache — file-based crash recovery for dispatcher calls.

Per AI_DISPATCHER.md §9:
  data/ai_cache/<package_id>/
    meta.json    — trace_id, agents, source, strength, started_at, adapter, model
    input.json   — full prompt + task pkg
    stage        — text file: queued|sent|received|unpacked|done|failed
    raw_response.txt — raw AI response text
    result.json  — unpacked result
    error.txt    — failure reason

Stage transitions are atomic: write .tmp then os.replace().
Startup: scan and reissue incomplete packages.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal, Optional

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)

from wq_bus.utils.paths import PROJECT_ROOT as _PROJECT_ROOT  # noqa: E402
_CACHE_ROOT = _PROJECT_ROOT / "data" / "ai_cache"
_ARCHIVE_ROOT = _CACHE_ROOT / "archive"

Stage = Literal["queued", "sent", "received", "unpacked", "done", "failed"]
VALID_STAGES: tuple[Stage, ...] = ("queued", "sent", "received", "unpacked", "done", "failed")


from wq_bus.utils.timeutil import utcnow_iso as _utcnow_iso  # noqa: E402


def _new_package_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"pk_{ts}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# PackageCache
# ---------------------------------------------------------------------------

class PackageCache:
    """Manages the file-based AI call cache."""

    def __init__(self, cache_root: Path | None = None) -> None:
        self._root = cache_root or _CACHE_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        _ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)

    def create_package(
        self,
        *,
        trace_id: str,
        agents: list[str],
        source: str,
        strength: str,
        adapter: str,
        model: str,
        task_pkg: dict,
        dataset_tag: str = "_global",
    ) -> str:
        """Create a new package directory and write meta + input. Returns package_id."""
        pkg_id = _new_package_id()
        pkg_dir = self._root / pkg_id
        pkg_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "package_id": pkg_id,
            "trace_id": trace_id,
            "agents": agents,
            "source": source,
            "strength": strength,
            "adapter": adapter,
            "model": model,
            "dataset_tag": dataset_tag,
            "started_at": _utcnow_iso(),
        }
        _atomic_write(pkg_dir / "meta.json", json.dumps(meta, indent=2))
        _atomic_write(pkg_dir / "input.json", json.dumps(task_pkg, indent=2, default=str))
        self._set_stage(pkg_id, "queued")
        _log.debug("cache package created: %s", pkg_id)
        return pkg_id

    def set_stage(self, package_id: str, stage: Stage) -> None:
        """Transition stage (atomic)."""
        self._set_stage(package_id, stage)

    def _set_stage(self, package_id: str, stage: str) -> None:
        pkg_dir = self._root / package_id
        if not pkg_dir.exists():
            return
        _atomic_write(pkg_dir / "stage", stage)

    def write_raw_response(self, package_id: str, text: str) -> None:
        """Write raw AI response text immediately (before JSON parse)."""
        pkg_dir = self._root / package_id
        _atomic_write(pkg_dir / "raw_response.txt", text)

    def write_result(self, package_id: str, result: dict) -> None:
        """Write unpacked result JSON."""
        pkg_dir = self._root / package_id
        _atomic_write(pkg_dir / "result.json", json.dumps(result, indent=2, default=str))

    def write_error(self, package_id: str, error: str) -> None:
        """Write error message."""
        pkg_dir = self._root / package_id
        _atomic_write(pkg_dir / "error.txt", error)

    def get_stage(self, package_id: str) -> Stage | None:
        stage_file = self._root / package_id / "stage"
        if stage_file.exists():
            return stage_file.read_text(encoding="utf-8").strip()  # type: ignore[return-value]
        return None

    def get_meta(self, package_id: str) -> dict | None:
        meta_file = self._root / package_id / "meta.json"
        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def get_input(self, package_id: str) -> dict | None:
        f = self._root / package_id / "input.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def get_result(self, package_id: str) -> dict | None:
        f = self._root / package_id / "result.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def list_packages(self, stage: str | None = None) -> list[dict]:
        """List all packages, optionally filtered by stage."""
        result = []
        for pkg_dir in sorted(self._root.iterdir()):
            if not pkg_dir.is_dir() or pkg_dir.name == "archive":
                continue
            pkg_id = pkg_dir.name
            s = self.get_stage(pkg_id)
            if stage and s != stage:
                continue
            meta = self.get_meta(pkg_id) or {}
            result.append({
                "package_id": pkg_id,
                "stage": s,
                "trace_id": meta.get("trace_id"),
                "agents": meta.get("agents", []),
                "strength": meta.get("strength"),
                "adapter": meta.get("adapter"),
                "model": meta.get("model"),
                "started_at": meta.get("started_at"),
                "dataset_tag": meta.get("dataset_tag"),
            })
        return result

    def scan_and_reissue(self) -> list[str]:
        """On startup: scan incomplete packages and return IDs to reissue.

        Per AI_DISPATCHER.md §9:
        - queued → requeue for sending
        - sent (no raw_response) → mark for resend
        - received (no result) → reparse / resend
        - done/failed → skip
        """
        to_reissue: list[str] = []
        for pkg_dir in sorted(self._root.iterdir()):
            if not pkg_dir.is_dir() or pkg_dir.name == "archive":
                continue
            pkg_id = pkg_dir.name
            stage = self.get_stage(pkg_id)
            if stage in (None, "done", "failed"):
                continue

            if stage == "queued":
                _log.info("cache recovery: pkg=%s stage=queued -> requeue", pkg_id)
                to_reissue.append(pkg_id)

            elif stage == "sent":
                raw = pkg_dir / "raw_response.txt"
                if not raw.exists() or raw.stat().st_size == 0:
                    _log.info("cache recovery: pkg=%s stage=sent, no response -> resend", pkg_id)
                    self._set_stage(pkg_id, "queued")
                    to_reissue.append(pkg_id)
                else:
                    # Response arrived but not parsed yet
                    _log.info("cache recovery: pkg=%s stage=sent, has response -> received", pkg_id)
                    self._set_stage(pkg_id, "received")
                    to_reissue.append(pkg_id)

            elif stage == "received":
                result_f = pkg_dir / "result.json"
                if not result_f.exists():
                    _log.info("cache recovery: pkg=%s stage=received, no result -> reparse", pkg_id)
                    to_reissue.append(pkg_id)

            elif stage == "unpacked":
                _log.info("cache recovery: pkg=%s stage=unpacked -> check tasks", pkg_id)
                to_reissue.append(pkg_id)

        if to_reissue:
            _log.info("cache recovery: %d packages need reissue", len(to_reissue))
            try:
                from wq_bus.bus.event_bus import get_bus
                from wq_bus.bus.events import AI_CACHE_REISSUED, make_event
                for pkg_id in to_reissue:
                    meta = self.get_meta(pkg_id) or {}
                    tag = meta.get("dataset_tag", "_global")
                    get_bus().emit(make_event(
                        AI_CACHE_REISSUED, tag, package_id=pkg_id,
                    ))
            except Exception:
                _log.debug("Failed to emit AI_CACHE_REISSUED events")

        return to_reissue

    def archive_done(self, before_hours: float = 24) -> int:
        """Archive 'done' packages older than *before_hours*. Returns count archived."""
        cutoff = time.time() - before_hours * 3600
        archived = 0
        for pkg_dir in list(self._root.iterdir()):
            if not pkg_dir.is_dir() or pkg_dir.name == "archive":
                continue
            pkg_id = pkg_dir.name
            if self.get_stage(pkg_id) != "done":
                continue
            meta = self.get_meta(pkg_id) or {}
            started = meta.get("started_at", "")
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(started.rstrip("Z") + "+00:00")
                if dt.timestamp() > cutoff:
                    continue
            except Exception:
                pass
            # Move to archive/<date>/
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            arch_dir = _ARCHIVE_ROOT / date_str / pkg_id
            try:
                shutil.move(str(pkg_dir), str(arch_dir))
                archived += 1
            except Exception:
                _log.warning("Failed to archive package %s", pkg_id)
        if archived:
            _log.info("Archived %d done packages", archived)
        return archived

    def prune(self, before_date: str) -> int:
        """Delete archived packages before *before_date* (YYYY-MM-DD). Returns count."""
        count = 0
        for date_dir in _ARCHIVE_ROOT.iterdir():
            if not date_dir.is_dir():
                continue
            if date_dir.name < before_date:
                try:
                    shutil.rmtree(date_dir)
                    count += 1
                except Exception:
                    pass
        return count


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* atomically using a .tmp intermediate."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_cache: Optional[PackageCache] = None


def get_cache() -> PackageCache:
    global _cache
    if _cache is None:
        _cache = PackageCache()
    return _cache
