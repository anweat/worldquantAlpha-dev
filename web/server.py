"""wqbus web — minimal stdlib HTTP server for command + log + config + KB UI.

Design notes (R6-B):
* stdlib only (BaseHTTPRequestHandler) — no FastAPI/Flask
* binds 127.0.0.1 by default, no auth
* reverse-proxy friendly: serves all assets via relative paths and reads
  X-Forwarded-Prefix to prepend to <base href> in index.html
* endpoints (all rooted at /api):
    GET  /api/state              -> high-level snapshot
    GET  /api/traces?limit=N     -> recent traces (status, kind, started_at, dataset_tag)
    GET  /api/trace/{trace_id}   -> single trace + events
    POST /api/task               -> {agent, mode, dataset_tag, n?, goal?} -> {trace_id}
    POST /api/task/{trace_id}/cancel|pause|resume
    GET  /api/log/tail?lines=N&tag=usa_top3000
    GET  /api/log/stream?tag=...   (SSE)
    GET  /api/config              -> [{name, size}]
    GET  /api/config/{name}       -> raw text
    PUT  /api/config/{name}       -> body=raw text (writes <name>.bak first)
    POST /api/kb/query            -> {sql} -> rows  (read-only allowlist)
    GET  /api/kb/quick/{name}     -> canned queries

Static frontend is served from web/static/ at the root /.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse as _up
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"

# Lazy imports of the wq_bus modules — only happen when an endpoint is hit
# so the web server can boot even if the bus has a transient import error.

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _open_knowledge():
    from wq_bus.data._sqlite import open_knowledge
    return open_knowledge()


def _open_state():
    from wq_bus.data._sqlite import open_state
    return open_state()


def _ensure_migrated() -> None:
    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, code: int, text: str,
                   ctype: str = "text/plain; charset=utf-8") -> None:
    body = text.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    n = int(handler.headers.get("Content-Length", "0") or "0")
    return handler.rfile.read(n) if n > 0 else b""


# ---------------------------------------------------------------------------
# read-only SQL allowlist for KB query
# ---------------------------------------------------------------------------
_SQL_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace)\b",
    re.IGNORECASE,
)


def _safe_kb_sql(sql: str) -> bool:
    return not _SQL_FORBIDDEN.search(sql)


_KB_QUICK = {
    "alphas_recent":
        "SELECT alpha_id, dataset_tag, status, sharpe, fitness, created_at "
        "FROM alphas ORDER BY created_at DESC LIMIT 50",
    "alphas_passed":
        "SELECT alpha_id, dataset_tag, sharpe, fitness, turnover, created_at "
        "FROM alphas WHERE status='is_passed' "
        "ORDER BY sharpe DESC LIMIT 50",
    "fingerprints_recent":
        "SELECT * FROM expr_fingerprints ORDER BY rowid DESC LIMIT 50",
    "learnings_recent":
        "SELECT * FROM learnings ORDER BY rowid DESC LIMIT 50",
    "submission_queue":
        "SELECT id, alpha_id, dataset_tag, status, retries, priority, last_error "
        "FROM submission_queue ORDER BY id DESC LIMIT 50",
    "sim_dlq":
        "SELECT * FROM sim_dead_letter ORDER BY id DESC LIMIT 50",
}


# ---------------------------------------------------------------------------
# log tailing
# ---------------------------------------------------------------------------

def _log_path(tag: str | None) -> Path:
    if tag and tag != "_global":
        return LOG_DIR / tag / "wqbus.log"
    return LOG_DIR / "wqbus.log"


def _tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    # Cheap reverse tail; OK for log files up to a few hundred MB.
    n = max(1, min(n, 5000))
    chunk = 8192
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        data = b""
        while size > 0 and data.count(b"\n") <= n:
            step = min(chunk, size)
            size -= step
            f.seek(size)
            data = f.read(step) + data
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-n:]


# ---------------------------------------------------------------------------
# main handler
# ---------------------------------------------------------------------------

class _H(BaseHTTPRequestHandler):
    server_version = "wqbus-web/0.1"

    # Quieter logging — route through stdout but prefix.
    def log_message(self, fmt, *args):  # noqa: A003
        sys.stdout.write("[wqbus-web] " + (fmt % args) + "\n")

    # -----------------------------------------------------------------
    # routing
    # -----------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        try:
            url = _up.urlparse(self.path)
            p = url.path
            qs = _up.parse_qs(url.query)
            if p == "/" or p == "/index.html":
                return self._serve_index()
            if p.startswith("/static/"):
                return self._serve_static(p[len("/static/"):])
            if p == "/api/state":
                return self._api_state()
            if p == "/api/traces":
                return self._api_traces(qs)
            m = re.match(r"^/api/trace/([\w\-]+)$", p)
            if m:
                return self._api_trace(m.group(1))
            # R6-C: pipeline tasks
            if p == "/api/pipeline/catalog":
                return self._api_pipeline_catalog()
            if p == "/api/pipeline/list":
                return self._api_pipeline_list(qs)
            m = re.match(r"^/api/pipeline/([\w\-]+)$", p)
            if m:
                return self._api_pipeline_show(m.group(1))
            # R6-C: summarizer modes
            if p == "/api/summarizer/modes":
                return self._api_summarizer_modes()
            if p == "/api/log/tail":
                return self._api_log_tail(qs)
            if p == "/api/log/stream":
                return self._api_log_stream(qs)
            if p == "/api/config":
                return self._api_config_list()
            m = re.match(r"^/api/config/([\w\-\.]+)$", p)
            if m:
                return self._api_config_get(m.group(1))
            m = re.match(r"^/api/kb/quick/(\w+)$", p)
            if m:
                return self._api_kb_quick(m.group(1))
            return _json_response(self, 404, {"error": "not_found", "path": p})
        except Exception as exc:  # noqa: BLE001
            return _json_response(self, 500, {"error": "internal", "detail": repr(exc)})

    def do_POST(self):  # noqa: N802
        try:
            url = _up.urlparse(self.path)
            p = url.path
            if p == "/api/task":
                return self._api_task_start()
            m = re.match(r"^/api/task/([\w\-]+)/(cancel|pause|resume)$", p)
            if m:
                return self._api_task_control(m.group(1), m.group(2))
            # R6-C pipeline tasks
            if p == "/api/pipeline/start":
                return self._api_pipeline_start()
            m = re.match(r"^/api/pipeline/([\w\-]+)/(cancel|pause|resume)$", p)
            if m:
                return self._api_pipeline_control(m.group(1), m.group(2))
            # R6-C summarizer manual run
            m = re.match(r"^/api/summarizer/run/([\w\-]+)$", p)
            if m:
                return self._api_summarizer_run(m.group(1))
            if p == "/api/kb/query":
                return self._api_kb_query()
            return _json_response(self, 404, {"error": "not_found", "path": p})
        except Exception as exc:  # noqa: BLE001
            return _json_response(self, 500, {"error": "internal", "detail": repr(exc)})

    def do_PUT(self):  # noqa: N802
        try:
            url = _up.urlparse(self.path)
            p = url.path
            m = re.match(r"^/api/config/([\w\-\.]+)$", p)
            if m:
                return self._api_config_put(m.group(1))
            return _json_response(self, 404, {"error": "not_found", "path": p})
        except Exception as exc:  # noqa: BLE001
            return _json_response(self, 500, {"error": "internal", "detail": repr(exc)})

    # -----------------------------------------------------------------
    # static
    # -----------------------------------------------------------------
    def _serve_index(self):
        idx = STATIC / "index.html"
        if not idx.exists():
            return _text_response(self, 500, "index.html missing", "text/plain")
        prefix = self.headers.get("X-Forwarded-Prefix", "").rstrip("/")
        base = (prefix + "/") if prefix else "./"
        html = idx.read_text(encoding="utf-8").replace("__BASE__", base)
        return _text_response(self, 200, html, "text/html; charset=utf-8")

    def _serve_static(self, name: str):
        # path traversal guard
        target = (STATIC / name).resolve()
        if not str(target).startswith(str(STATIC.resolve())):
            return _json_response(self, 403, {"error": "forbidden"})
        if not target.exists():
            return _json_response(self, 404, {"error": "not_found"})
        ctype = "application/octet-stream"
        if name.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif name.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif name.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        elif name.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        return _text_response(self, 200, target.read_text(encoding="utf-8"), ctype)

    # -----------------------------------------------------------------
    # /api/state
    # -----------------------------------------------------------------
    def _api_state(self):
        _ensure_migrated()
        with _open_state() as c:
            traces_total   = c.execute("SELECT COUNT(*) AS n FROM trace").fetchone()["n"]
            traces_running = c.execute("SELECT COUNT(*) AS n FROM trace WHERE status='running'").fetchone()["n"]
            traces_paused  = c.execute("SELECT COUNT(*) AS n FROM trace WHERE status='paused'").fetchone()["n"]
            events_total   = c.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            try:
                sim_dlq    = c.execute("SELECT COUNT(*) AS n FROM sim_dead_letter WHERE state='open'").fetchone()["n"]
            except Exception:
                sim_dlq = None
            try:
                tasks_running   = c.execute(
                    "SELECT COUNT(*) AS n FROM task WHERE status='running'").fetchone()["n"]
                tasks_total     = c.execute("SELECT COUNT(*) AS n FROM task").fetchone()["n"]
            except Exception:
                tasks_running = tasks_total = None
            tags = [r["dataset_tag"] for r in c.execute(
                "SELECT DISTINCT dataset_tag FROM events WHERE dataset_tag IS NOT NULL "
                "AND dataset_tag != '_global' ORDER BY dataset_tag").fetchall()]
        try:
            with _open_knowledge() as kc:
                alphas_total = kc.execute("SELECT COUNT(*) AS n FROM alphas").fetchone()["n"]
        except Exception:
            alphas_total = None
        return _json_response(self, 200, {
            "ok": True,
            "version": "wqbus-web/0.2",
            "root": str(ROOT),
            "tags": tags,
            "counts": {
                "traces_total":   traces_total,
                "traces_running": traces_running,
                "traces_paused":  traces_paused,
                "events_total":   events_total,
                "sim_dlq_open":   sim_dlq,
                "alphas_total":   alphas_total,
                "tasks_total":    tasks_total,
                "tasks_running":  tasks_running,
            },
        })

    # -----------------------------------------------------------------
    # /api/traces  &  /api/trace/{id}
    # -----------------------------------------------------------------
    def _api_traces(self, qs):
        _ensure_migrated()
        limit = int((qs.get("limit") or ["50"])[0])
        limit = max(1, min(limit, 500))
        with _open_state() as c:
            # trace table has no dataset_tag column — derive from earliest
            # event of the trace (LEFT JOIN keeps tagless rows visible too).
            rows = c.execute(
                "SELECT t.trace_id, t.task_kind, t.status, t.origin, "
                "       t.started_at, t.ended_at, t.error, "
                "       (SELECT e.dataset_tag FROM events e "
                "          WHERE e.trace_id=t.trace_id LIMIT 1) AS dataset_tag "
                "FROM trace t ORDER BY t.created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            data = [dict(r) for r in rows]
        return _json_response(self, 200, {"ok": True, "traces": data})

    def _api_trace(self, trace_id: str):
        _ensure_migrated()
        with _open_state() as c:
            tr = c.execute("SELECT * FROM trace WHERE trace_id=?", (trace_id,)).fetchone()
            if not tr:
                return _json_response(self, 404, {"error": "not_found"})
            evs = c.execute(
                "SELECT id, ts, topic, dataset_tag, payload_json AS payload "
                "FROM events WHERE trace_id=? ORDER BY id ASC LIMIT 1000",
                (trace_id,),
            ).fetchall()
        return _json_response(self, 200, {
            "ok": True,
            "trace": dict(tr),
            "events": [dict(e) for e in evs],
        })

    # -----------------------------------------------------------------
    # /api/task — start / control
    # -----------------------------------------------------------------
    def _api_task_start(self):
        body = _read_body(self)
        try:
            req = json.loads(body or b"{}")
        except Exception as e:
            return _json_response(self, 400, {"error": "bad_json", "detail": str(e)})
        agent = (req.get("agent") or "alpha_gen").lower()
        mode  = req.get("mode") or "explore"
        tag   = req.get("dataset_tag")
        if not tag:
            return _json_response(self, 400, {"error": "dataset_tag_required"})

        # Reuse CLI helpers so we don't duplicate the agent→kind/topic mapping.
        from wq_bus.cli import _kind_for_agent, _task_topic_for, _instantiate_agents_for
        from wq_bus.bus.tasks import start_task
        from wq_bus.bus.events import make_event
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.utils.tag_context import with_tag

        topic, base_payload = _task_topic_for(
            agent, mode, url=req.get("url"), goal=req.get("goal"),
            summarize=bool(req.get("summarize")), n=int(req.get("n") or 3),
        )
        bus = get_bus()
        with with_tag(tag):
            kind = _kind_for_agent(agent)
            handle = start_task(
                kind=kind,
                payload={"agent": agent, "mode": mode, **base_payload},
                origin="web", dataset_tag=tag,
            )
            # Instantiate the chain in this process so emits are handled.
            try:
                _instantiate_agents_for(agent, bus)
            except Exception:
                pass
            bus.emit(make_event(topic, tag, trace_id=handle.trace_id, **base_payload))
        return _json_response(self, 200, {
            "ok": True, "trace_id": handle.trace_id, "kind": kind, "topic": topic,
        })

    def _api_task_control(self, trace_id: str, action: str):
        from wq_bus.bus.tasks import cancel_task, pause_task, resume_task
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import (
            make_event, TASK_CANCEL_REQUESTED, TASK_PAUSE_REQUESTED,
            TASK_RESUME_REQUESTED,
        )
        # Look up tag to attach to the control event (trace has no
        # dataset_tag column — read from any event for this trace).
        with _open_state() as c:
            row = c.execute(
                "SELECT status FROM trace WHERE trace_id=?", (trace_id,)
            ).fetchone()
            if not row:
                return _json_response(self, 404, {"error": "not_found"})
            tag_row = c.execute(
                "SELECT dataset_tag FROM events WHERE trace_id=? LIMIT 1",
                (trace_id,),
            ).fetchone()
        tag = (tag_row["dataset_tag"] if tag_row else None) or "_global"
        bus = get_bus()
        # Direct mutation (so caller sees change immediately) + emit the topic
        # for any agent / external listener.
        if action == "cancel":
            ok = cancel_task(trace_id, reason="web_cancel")
            bus.emit(make_event(TASK_CANCEL_REQUESTED, tag, trace_id=trace_id))
        elif action == "pause":
            ok = pause_task(trace_id)
            bus.emit(make_event(TASK_PAUSE_REQUESTED,  tag, trace_id=trace_id))
        elif action == "resume":
            ok = resume_task(trace_id)
            bus.emit(make_event(TASK_RESUME_REQUESTED, tag, trace_id=trace_id))
        else:
            return _json_response(self, 400, {"error": "bad_action"})
        return _json_response(self, 200, {"ok": ok, "action": action, "trace_id": trace_id})

    # -----------------------------------------------------------------
    # /api/pipeline/* — R6-C task pipelines
    # -----------------------------------------------------------------
    def _api_pipeline_catalog(self):
        """Return tasks.yaml catalog: {tasks: [{name,pipeline,goal,...}], pipelines: [...]}"""
        from wq_bus.utils.yaml_loader import load_yaml
        from wq_bus.utils.paths import PROJECT_ROOT
        cfg = load_yaml(PROJECT_ROOT / "config" / "tasks.yaml") or {}
        tasks = cfg.get("tasks") or {}
        pipelines = cfg.get("pipelines") or {}
        return _json_response(self, 200, {
            "ok": True,
            "tasks": [
                {"name": k, **(v if isinstance(v, dict) else {})}
                for k, v in tasks.items()
            ],
            "pipelines": [
                {"name": k, **(v if isinstance(v, dict) else {})}
                for k, v in pipelines.items()
            ],
        })

    def _api_pipeline_list(self, qs):
        _ensure_migrated()
        from wq_bus.data import task_db
        status = (qs.get("status") or [None])[0]
        limit = int((qs.get("limit") or ["50"])[0])
        rows = task_db.list_tasks(status=status, limit=max(1, min(limit, 500)))
        return _json_response(self, 200, {"ok": True, "tasks": rows})

    def _api_pipeline_show(self, task_id: str):
        _ensure_migrated()
        from wq_bus.data import task_db
        row = task_db.get_task(task_id)
        if not row:
            return _json_response(self, 404, {"error": "not_found"})
        try:
            iters = task_db.list_pipeline_states_for_task(task_id)
        except Exception:
            iters = []
        try:
            progress = json.loads(row.get("progress_json") or "{}")
        except Exception:
            progress = {}
        return _json_response(self, 200, {
            "ok": True, "task": row, "iterations": iters, "progress": progress,
        })

    def _api_pipeline_start(self):
        body = _read_body(self)
        try:
            req = json.loads(body or b"{}")
        except Exception as e:
            return _json_response(self, 400, {"error": "bad_json", "detail": str(e)})
        name = req.get("task_name") or req.get("name")
        if not name:
            return _json_response(self, 400, {"error": "task_name_required"})
        # Validate task exists synchronously (cheap) so the user gets a 400 now,
        # not a silent drop into the bus.
        from wq_bus.coordinator.goal import get_task as _get_task
        if not _get_task(name):
            return _json_response(self, 400, {
                "error": "unknown_task",
                "detail": f"task {name!r} not in config/tasks.yaml",
            })
        tag = req.get("dataset_tag") or "_global"
        overrides = {}
        if req.get("max_iterations") is not None:
            overrides["max_iterations"] = int(req["max_iterations"])
        if req.get("wall_time_secs") is not None:
            overrides["wall_time_secs"] = int(req["wall_time_secs"])

        # Emit TASK_START_REQUESTED. The long-lived daemon's CoordinatorAgent
        # picks this up and owns the task lifecycle. The web process never
        # spawns its own coordinator (avoids the multi-coordinator race).
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import make_event
        bus = get_bus()
        bus.emit(make_event(
            "TASK_START_REQUESTED", tag,
            task_name=name,
            overrides=overrides or None, origin="web",
        ))
        return _json_response(self, 202, {
            "ok": True, "queued": True, "task_name": name, "dataset_tag": tag,
            "note": "Task accepted. Daemon coordinator will create the task row "
                    "and launch iterations within ~1s. Poll /api/pipeline/list.",
        })

    def _api_pipeline_control(self, task_id: str, action: str):
        from wq_bus.data import task_db
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import make_event
        row = task_db.get_task(task_id)
        if not row:
            return _json_response(self, 404, {"error": "not_found"})
        topic = {
            "cancel": "TASK_CANCEL_REQUESTED",
            "pause":  "TASK_PAUSE_REQUESTED",
            "resume": "TASK_RESUME_REQUESTED",
        }.get(action)
        if not topic:
            return _json_response(self, 400, {"error": "bad_action"})
        tag = row.get("dataset_tag") or "_global"
        bus = get_bus()
        bus.emit(make_event(topic, tag, task_id=task_id))
        return _json_response(self, 200, {"ok": True, "action": action, "task_id": task_id})

    # -----------------------------------------------------------------
    # /api/summarizer — manual mode trigger
    # -----------------------------------------------------------------
    def _api_summarizer_modes(self):
        from wq_bus.utils.yaml_loader import load_yaml
        from wq_bus.utils.paths import PROJECT_ROOT
        cfg = load_yaml(PROJECT_ROOT / "config" / "summarizer.yaml") or {}
        modes = cfg.get("modes") or {}
        return _json_response(self, 200, {
            "ok": True,
            "modes": [
                {"name": k, "enabled": (v or {}).get("enabled", True),
                 "source": (v or {}).get("source"),
                 "prompt_kind": (v or {}).get("prompt_kind"),
                 "wake_interval": (v or {}).get("wake_interval")}
                for k, v in modes.items()
            ],
        })

    def _api_summarizer_run(self, mode: str):
        import asyncio
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.ai.ai_service import AIService
        from wq_bus.ai.dispatcher import get_dispatcher
        from wq_bus.agents.summarizer import SummarizerAgent

        async def _go():
            bus = get_bus()
            dispatcher = get_dispatcher()
            AIService(bus, dispatcher).start()
            s = SummarizerAgent(bus); s.start(run_loop=False)
            return await s.run_once(mode, force=True)
        try:
            res = asyncio.run(_go())
        except ValueError as e:
            return _json_response(self, 400, {"error": "unknown_mode", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            return _json_response(self, 500, {"error": "run_failed", "detail": repr(e)})
        if res is None:
            return _json_response(self, 200, {"ok": False, "result": None,
                                              "note": "no items / AI returned None"})
        return _json_response(self, 200, {"ok": True, "result": res})

    # -----------------------------------------------------------------
    # /api/log/*
    # -----------------------------------------------------------------
    def _api_log_tail(self, qs):
        tag = (qs.get("tag") or [""])[0] or None
        n   = int((qs.get("lines") or ["200"])[0])
        path = _log_path(tag)
        return _json_response(self, 200, {
            "ok": True, "path": str(path), "lines": _tail_lines(path, n),
        })

    def _api_log_stream(self, qs):
        """SSE stream — sends new bytes as they're appended.

        Stops after ~30 minutes or when the client disconnects.
        """
        tag = (qs.get("tag") or [""])[0] or None
        path = _log_path(tag)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        offset = path.stat().st_size if path.exists() else 0
        deadline = time.time() + 30 * 60
        try:
            while time.time() < deadline:
                if path.exists():
                    sz = path.stat().st_size
                    if sz < offset:  # rotated
                        offset = 0
                    if sz > offset:
                        with path.open("rb") as f:
                            f.seek(offset)
                            chunk = f.read(sz - offset)
                            offset = sz
                        for line in chunk.decode("utf-8", errors="replace").splitlines():
                            self.wfile.write(b"data: " + line.encode("utf-8") + b"\n\n")
                        self.wfile.flush()
                else:
                    self.wfile.write(b": waiting for log file\n\n")
                    self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            return

    # -----------------------------------------------------------------
    # /api/config/*
    # -----------------------------------------------------------------
    def _api_config_list(self):
        files = []
        for p in sorted(CONFIG_DIR.glob("*.yaml")):
            files.append({"name": p.name, "size": p.stat().st_size})
        return _json_response(self, 200, {"ok": True, "files": files})

    def _api_config_get(self, name: str):
        path = (CONFIG_DIR / name).resolve()
        if not str(path).startswith(str(CONFIG_DIR.resolve())):
            return _json_response(self, 403, {"error": "forbidden"})
        if not path.exists():
            return _json_response(self, 404, {"error": "not_found"})
        return _text_response(self, 200, path.read_text(encoding="utf-8"))

    def _api_config_put(self, name: str):
        path = (CONFIG_DIR / name).resolve()
        if not str(path).startswith(str(CONFIG_DIR.resolve())):
            return _json_response(self, 403, {"error": "forbidden"})
        body = _read_body(self).decode("utf-8", errors="replace")
        # Basic YAML validation — refuse if it can't parse.
        try:
            import yaml
            yaml.safe_load(body)
        except Exception as e:
            return _json_response(self, 400, {"error": "yaml_invalid", "detail": str(e)})
        if path.exists():
            backup = path.with_suffix(path.suffix + f".bak-{int(time.time())}")
            shutil.copy2(path, backup)
        path.write_text(body, encoding="utf-8")
        return _json_response(self, 200, {"ok": True, "name": name, "size": len(body)})

    # -----------------------------------------------------------------
    # /api/kb/*
    # -----------------------------------------------------------------
    def _api_kb_quick(self, name: str):
        sql = _KB_QUICK.get(name)
        if not sql:
            return _json_response(self, 404, {"error": "unknown_quick", "available": list(_KB_QUICK)})
        return self._run_select(sql)

    def _api_kb_query(self):
        body = _read_body(self)
        try:
            req = json.loads(body or b"{}")
        except Exception as e:
            return _json_response(self, 400, {"error": "bad_json", "detail": str(e)})
        sql = (req.get("sql") or "").strip().rstrip(";")
        if not sql:
            return _json_response(self, 400, {"error": "sql_required"})
        if not _safe_kb_sql(sql):
            return _json_response(self, 400, {"error": "write_sql_forbidden"})
        return self._run_select(sql)

    def _run_select(self, sql: str):
        _ensure_migrated()
        sql_lc = sql.lower()
        if "limit" not in sql_lc:
            sql = sql + " LIMIT 500"
        # Try knowledge.db first (most KB queries live there); fall back to state.db.
        try:
            with _open_knowledge() as kc:
                rows = [dict(r) for r in kc.execute(sql).fetchall()]
        except Exception as exc:  # noqa: BLE001
            try:
                with _open_state() as c:
                    rows = [dict(r) for r in c.execute(sql).fetchall()]
            except Exception as exc2:
                return _json_response(self, 400, {
                    "error": "query_failed",
                    "detail": f"knowledge: {exc!r} | state: {exc2!r}",
                })
        return _json_response(self, 200, {"ok": True, "rows": rows, "count": len(rows)})


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, port), _H)
    print(f"[wqbus-web] serving http://{host}:{port}/  root={ROOT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[wqbus-web] shutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    serve(args.host, args.port)
