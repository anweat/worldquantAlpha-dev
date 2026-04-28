"""SummarizerAgent — single agent with 7 modes, cursor-pull self-check loop.

Loose-coupling principle (R6-C): the summarizer is *not* triggered by other
modules. It wakes every ``wake_interval_secs`` (default 5 min, see
config/summarizer.yaml), consults its cursor file, and pulls new artifacts
from the relevant DB / file source. When ``min_new`` is reached it builds the
prompt vars, emits ``AI_CALL_REQUESTED`` (await ``AI_CALL_DONE``), writes the
output under ``memory/<scope>/<topic_subspace>/<mode>_<ts>.json``, and emits
``SUMMARIZER_DONE``.

Public API:
    svc = SummarizerAgent(bus)
    svc.start()                   # registers + spawns wake loop
    await svc.run_once(mode)      # manual one-shot (CLI: wqbus summarize <mode>)

The wake loop is opt-in: pass ``run_loop=False`` to ``start()`` to register the
AI_CALL_DONE/FAILED listener only (e.g. for tests).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from wq_bus.bus.events import (
    AI_CALL_DONE,
    AI_CALL_FAILED,
    AI_CALL_REQUESTED,
    SUMMARIZER_DONE,
    Event,
    make_event,
)
from wq_bus.utils.logging import get_logger
from wq_bus.utils.paths import PROJECT_ROOT
from wq_bus.utils.tag_context import with_tag, with_trace, new_trace_id
from wq_bus.utils.yaml_loader import load_yaml

_log = get_logger(__name__)


@dataclass
class _PendingCall:
    mode: str
    scope: str
    cursor_advance: dict[str, Any]   # what to write to cursor on success
    fut: asyncio.Future


class SummarizerAgent:
    AGENT_TYPE = "summarizer"

    def __init__(self, bus) -> None:
        self.bus = bus
        self.log = _log
        self._cfg = self._load_cfg()
        self._cursor_path = PROJECT_ROOT / self._cfg.get(
            "cursor_path", "memory/_global/_index/summarizer_cursors.json"
        )
        self._cursors: dict[str, Any] = self._load_cursors()
        self._pending: dict[str, _PendingCall] = {}   # call_id -> _PendingCall
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    def start(self, *, run_loop: bool = True) -> None:
        if self._running:
            # Allow upgrading from "listeners only" (run_loop=False) to "with loop"
            if run_loop and self._cfg.get("enabled", True) and self._loop_task is None:
                self._loop_task = asyncio.create_task(self._wake_loop())
                self.log.info("summarizer wake loop started post-init")
            return
        self.bus.subscribe(AI_CALL_DONE, self._on_ai_done)
        self.bus.subscribe(AI_CALL_FAILED, self._on_ai_failed)
        self._running = True
        if run_loop and self._cfg.get("enabled", True):
            self._loop_task = asyncio.create_task(self._wake_loop())
        self.log.info("summarizer started (run_loop=%s, modes=%s)",
                      run_loop, sorted((self._cfg.get("modes") or {}).keys()))

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------
    def _load_cfg(self) -> dict:
        return load_yaml("summarizer") or {"enabled": False, "modes": {}}

    def _load_cursors(self) -> dict:
        if not self._cursor_path.exists():
            return {}
        try:
            return json.loads(self._cursor_path.read_text(encoding="utf-8"))
        except Exception:
            self.log.exception("summarizer: cursor file unreadable; resetting")
            return {}

    def _save_cursors(self) -> None:
        self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cursor_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._cursors, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._cursor_path)

    # ------------------------------------------------------------------
    async def _wake_loop(self) -> None:
        interval = int(self._cfg.get("wake_interval_secs", 300))
        while self._running:
            try:
                await self._tick()
            except Exception:
                self.log.exception("summarizer wake tick failed")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return

    async def _tick(self) -> None:
        modes = self._cfg.get("modes") or {}
        for mode, mcfg in modes.items():
            if not mcfg.get("enabled", True):
                continue
            try:
                await self._maybe_run_mode(mode, mcfg)
            except Exception:
                self.log.exception("summarizer mode %s failed", mode)

    # ------------------------------------------------------------------
    async def _maybe_run_mode(self, mode: str, mcfg: dict) -> None:
        cursor = self._cursors.get(mode) or {}
        last_run_ts = float(cursor.get("last_run_ts") or 0.0)
        min_hours = float(mcfg.get("min_hours_since_last") or 0)
        if min_hours and (time.time() - last_run_ts) < min_hours * 3600:
            return
        items, advance = self._pull_items(mode, mcfg, cursor)
        min_new = int(mcfg.get("min_new") or 1)
        if len(items) < min_new:
            return
        await self._run(mode, mcfg, items, advance)

    async def run_once(self, mode: str, *, force: bool = True) -> Optional[dict]:
        """Manual entry: ignore thresholds and run *mode* now. Returns the
        summarizer result dict or ``None`` if the AI call failed."""
        modes = self._cfg.get("modes") or {}
        mcfg = modes.get(mode)
        if not mcfg:
            raise ValueError(f"unknown summarizer mode {mode!r}")
        cursor = self._cursors.get(mode) or {}
        items, advance = self._pull_items(mode, mcfg, cursor)
        if not items and not force:
            return None
        return await self._run(mode, mcfg, items, advance)

    # ------------------------------------------------------------------
    # Item pull adapters — keep simple; thresholds enforced by caller.
    # Each returns (items, advance_dict). advance_dict is merged into cursor on
    # successful AI completion (after artifact written).
    # ------------------------------------------------------------------
    def _pull_items(self, mode: str, mcfg: dict, cursor: dict) -> tuple[list[dict], dict]:
        source = mcfg.get("source")
        if source == "events":
            return self._pull_events(cursor)
        if source == "crawl_docs":
            return self._pull_crawl_docs(cursor)
        if source == "alphas_passed":
            return self._pull_alphas_passed(cursor)
        if source == "submitted_today":
            return self._pull_submitted_today(cursor)
        if source == "summaries_weekly":
            return self._pull_summaries_weekly(cursor)
        if source == "composite":
            # workspace_overview: snapshot multiple sources; not threshold-driven
            return self._pull_composite(cursor)
        return [], {}

    def _pull_events(self, cursor: dict) -> tuple[list[dict], dict]:
        from wq_bus.data._sqlite import open_state
        last_ts = float(cursor.get("last_event_ts") or 0.0)
        topics = ("ALPHA_SIM_ERRORED", "ALPHA_GEN_ERRORED")
        with open_state() as conn:
            rows = conn.execute(
                f"""SELECT id, ts, topic, dataset_tag, payload_json, trace_id
                       FROM events
                       WHERE ts > ? AND topic IN ({','.join(['?'] * len(topics))})
                       ORDER BY ts ASC LIMIT 200""",
                (last_ts, *topics),
            ).fetchall()
        items = [dict(r) for r in rows]
        advance = {"last_event_ts": rows[-1]["ts"]} if rows else {}
        return items, advance

    def _pull_crawl_docs(self, cursor: dict) -> tuple[list[dict], dict]:
        try:
            from wq_bus.data._sqlite import open_knowledge
        except Exception:
            return [], {}
        last_id = int(cursor.get("last_doc_id") or 0)
        try:
            with open_knowledge() as conn:
                rows = conn.execute(
                    """SELECT id, source, title, body_md, fetched_at
                          FROM crawl_docs WHERE id > ? AND COALESCE(state,'pending')='pending'
                          ORDER BY id ASC LIMIT 50""",
                    (last_id,),
                ).fetchall()
        except Exception:
            return [], {}
        items = [dict(r) for r in rows]
        advance = {"last_doc_id": rows[-1]["id"]} if rows else {}
        return items, advance

    def _pull_alphas_passed(self, cursor: dict) -> tuple[list[dict], dict]:
        try:
            from wq_bus.data._sqlite import open_knowledge
        except Exception:
            return [], {}
        last_id = int(cursor.get("last_alpha_rowid") or 0)
        try:
            with open_knowledge() as conn:
                rows = conn.execute(
                    """SELECT rowid, alpha_id, dataset_tag, expression,
                              sharpe, fitness, turnover, status
                         FROM alphas
                         WHERE rowid > ? AND status IN ('is_passed','submitted')
                         ORDER BY rowid ASC LIMIT 100""",
                    (last_id,),
                ).fetchall()
        except Exception:
            return [], {}
        items = [dict(r) for r in rows]
        advance = {"last_alpha_rowid": rows[-1]["rowid"]} if rows else {}
        return items, advance

    def _pull_submitted_today(self, cursor: dict) -> tuple[list[dict], dict]:
        from wq_bus.data._sqlite import open_state
        last_ts = float(cursor.get("last_event_ts") or 0.0)
        cutoff = max(last_ts, time.time() - 86400.0)
        with open_state() as conn:
            rows = conn.execute(
                """SELECT ts, dataset_tag, topic, payload_json, trace_id FROM events
                       WHERE topic='SUBMITTED' AND ts > ?
                       ORDER BY ts ASC LIMIT 500""",
                (cutoff,),
            ).fetchall()
        items = [dict(r) for r in rows]
        advance = {"last_event_ts": rows[-1]["ts"], "last_run_ts": time.time()} if rows else {"last_run_ts": time.time()}
        return items, advance

    def _pull_summaries_weekly(self, cursor: dict) -> tuple[list[dict], dict]:
        # Read prior daily_summary artifacts in last 7d under memory/_global/summaries/.
        base = PROJECT_ROOT / "memory" / "_global" / "summaries"
        if not base.exists():
            return [], {"last_run_ts": time.time()}
        cutoff = time.time() - 7 * 86400
        items: list[dict] = []
        for p in sorted(base.glob("daily_summary_*.json")):
            try:
                if p.stat().st_mtime < cutoff:
                    continue
                items.append({"path": str(p.relative_to(PROJECT_ROOT)),
                              "content": json.loads(p.read_text(encoding="utf-8"))})
            except Exception:
                continue
        return items, {"last_run_ts": time.time()}

    def _pull_composite(self, cursor: dict) -> tuple[list[dict], dict]:
        """workspace_overview: threshold-driven on new crawl_summaries.

        Each "item" represents one new partial summary written by either
        DocSummarizer (legacy crawl_summary) or this agent's crawl_doc_summary
        mode. Once ``min_new`` of them accumulate, the workspace_overview is
        regenerated using the latest summaries + global stats snapshot.
        """
        try:
            from wq_bus.data._sqlite import open_state, open_knowledge
        except Exception:
            return [], {}
        last_id = int(cursor.get("last_summary_id") or 0)
        try:
            with open_knowledge() as k:
                rows = k.execute(
                    """SELECT id, dataset_tag, scope, summary_md, created_at
                         FROM crawl_summaries WHERE id > ?
                         ORDER BY id ASC LIMIT 200""",
                    (last_id,),
                ).fetchall()
        except Exception:
            self.log.exception("workspace_overview: crawl_summaries query failed")
            return [], {}
        items = [dict(r) for r in rows]
        if not items:
            return [], {}
        # Attach a global snapshot to the LAST item so the prompt sees both
        # the new-summary stream and current platform-wide counts.
        try:
            with open_state() as s, open_knowledge() as k:
                snapshot = {
                    "events_total":   s.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"],
                    "traces_running": s.execute(
                        "SELECT COUNT(*) AS n FROM trace WHERE status='running'"
                    ).fetchone()["n"],
                    "alphas_total":   k.execute("SELECT COUNT(*) AS n FROM alphas").fetchone()["n"],
                    "summaries_total": k.execute(
                        "SELECT COUNT(*) AS n FROM crawl_summaries"
                    ).fetchone()["n"],
                }
            items.append({"snapshot": snapshot})
        except Exception:
            self.log.debug("workspace_overview: snapshot stats unavailable", exc_info=True)
        advance = {
            "last_summary_id": rows[-1]["id"],
            "last_run_ts":     time.time(),
        }
        return items, advance

    # ------------------------------------------------------------------
    async def _run(self, mode: str, mcfg: dict, items: list[dict],
                   advance: dict) -> Optional[dict]:
        prompt_kind = str(mcfg.get("prompt_kind") or mode)
        # Synthesize trace_id so AI_CALL_REQUESTED has a correlation id.
        trace_id = new_trace_id()
        scope = self._scope_for(items)
        vars_ = self._vars_for(mode, mcfg, items)

        call_id = "sumr_" + uuid.uuid4().hex[:10]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[call_id] = _PendingCall(
            mode=mode, scope=scope, cursor_advance=advance, fut=fut,
        )

        with with_tag(scope), with_trace(trace_id):
            try:
                self.bus.emit(make_event(
                    AI_CALL_REQUESTED,
                    dataset_tag=scope,
                    call_id=call_id,
                    prompt_kind=prompt_kind,
                    vars=vars_,
                    agent="summarizer",
                    trace_id=trace_id,
                ))
            except Exception:
                self.log.exception("summarizer: emit AI_CALL_REQUESTED failed")
                self._pending.pop(call_id, None)
                return None

        try:
            response = await asyncio.wait_for(fut, timeout=int(mcfg.get("timeout_secs", 300)))
        except asyncio.TimeoutError:
            self.log.warning("summarizer mode %s: AI call timed out", mode)
            self._pending.pop(call_id, None)
            return None
        if response is None:
            return None

        # Persist artifact + advance cursor.
        artifact_path = self._write_artifact(mode, scope, response)
        cursor = self._cursors.setdefault(mode, {})
        cursor.update(advance)
        cursor["last_run_ts"] = time.time()
        cursor["last_artifact"] = str(artifact_path.relative_to(PROJECT_ROOT))
        self._save_cursors()
        try:
            self.bus.emit(make_event(
                SUMMARIZER_DONE,
                dataset_tag=scope,
                mode=mode,
                scope=scope,
                artifact_path=str(artifact_path.relative_to(PROJECT_ROOT)),
                items_consumed=len(items),
                ai_call_id=None,
            ))
        except Exception:
            self.log.exception("summarizer: emit SUMMARIZER_DONE failed")
        return {
            "mode": mode,
            "scope": scope,
            "artifact": str(artifact_path),
            "items_consumed": len(items),
            "response": response if isinstance(response, dict) else {"raw": response},
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _scope_for(items: list[dict]) -> str:
        # If all items share a dataset_tag, scope to it; else _global.
        tags = {it.get("dataset_tag") for it in items if it.get("dataset_tag")}
        if len(tags) == 1:
            return next(iter(tags))
        return "_global"

    @staticmethod
    def _vars_for(mode: str, mcfg: dict, items: list[dict]) -> dict:
        # Mode-specific variable shaping; keep aligned with prompt templates.
        if mode == "failure_summary":
            failures = [
                {"trace_id": it.get("trace_id"),
                 "topic": it.get("topic"),
                 "payload": _safe_json_load(it.get("payload_json"))}
                for it in items
            ]
            return {
                "dataset_tag": SummarizerAgent._scope_for(items),
                "failures": failures,
                "existing_patterns": [],
            }
        if mode == "crawl_doc_summary":
            # Summarize one doc per call ideally; here we batch but keep minimal.
            it = items[0] if items else {}
            return {
                "source": it.get("source", ""),
                "title": it.get("title", ""),
                "body_md": (it.get("body_md") or "")[:8000],
            }
        if mode == "alpha_insight_extract":
            return {
                "dataset_tag": SummarizerAgent._scope_for(items),
                "passed_alphas": items,
            }
        if mode == "daily_summary":
            return {
                "date": time.strftime("%Y-%m-%d", time.gmtime()),
                "workspaces": sorted({it.get("dataset_tag") for it in items if it.get("dataset_tag")}),
                "global_metrics": {"submitted_count": len(items)},
            }
        if mode == "longterm_summary_7d":
            return {
                "week_range": time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
                              + " .. " + time.strftime("%Y-%m-%d", time.gmtime()),
                "workspaces": [],
                "global_metrics": {"daily_summaries": len(items)},
                "direction_evolution": [],
            }
        if mode == "diversity_analysis":
            dirs = sorted({(a.get("expression") or "")[:80] for a in items})
            return {
                "dataset_tag": SummarizerAgent._scope_for(items),
                "submitted_directions": [a for a in items if a.get("status") == "submitted"],
                "explored_directions": dirs,
                "all_directions": dirs,
            }
        if mode == "workspace_overview":
            snap = items[0].get("snapshot", {}) if items else {}
            return {
                "dataset_tag": "_global",
                "pool_summary": snap,
                "recent_learnings": [],
                "recent_submissions": [],
                "failure_pattern_counts": {},
            }
        return {}

    def _write_artifact(self, mode: str, scope: str, response: Any) -> Path:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        out_dir = PROJECT_ROOT / "memory" / scope / "summaries"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{mode}_{ts}.json"
        payload = {"mode": mode, "scope": scope, "ts": ts, "response": response}
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path

    # ------------------------------------------------------------------
    async def _on_ai_done(self, event: Event) -> None:
        call_id = (event.payload or {}).get("call_id")
        if not call_id or call_id not in self._pending:
            return
        pending = self._pending.pop(call_id)
        if not pending.fut.done():
            pending.fut.set_result((event.payload or {}).get("response"))

    async def _on_ai_failed(self, event: Event) -> None:
        call_id = (event.payload or {}).get("call_id")
        if not call_id or call_id not in self._pending:
            return
        pending = self._pending.pop(call_id)
        if not pending.fut.done():
            pending.fut.set_result(None)


def _safe_json_load(s: Any) -> Any:
    if not s:
        return {}
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return {"raw": str(s)[:200]}


__all__ = ["SummarizerAgent"]
