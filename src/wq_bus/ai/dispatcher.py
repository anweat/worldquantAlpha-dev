"""Central AI dispatcher v2 — routes, batches, rate-limits, and logs all AI calls.

Dispatcher v2 design (AI_DISPATCHER.md §2):
- Single entry: call(task_pkg_or_agent, payload_or_source, source) -> dict
- StrengthRouter resolves model tier per (agent, mode)
- per_call adapters → BatchBuffer keyed (adapter, strength)
- per_token adapters → bypass buffer, call directly per task
- PackageCache for crash-safe stage tracking
- Global Semaphore(4) for concurrency
- daily_ai_cap counted for auto only; manual bypasses
- Retry once on network/timeout/JSON-parse-fail
- scan_and_reissue() on startup

Backward compat: call(agent_type_str, payload_dict, ...) still works.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

from wq_bus.ai import subagent_packer, transforms as ai_transforms
from wq_bus.ai.adapters.copilot_cli import CopilotAdapter
from wq_bus.ai.adapters.glm import GLMAdapter
from wq_bus.ai.adapters.openai import OpenAIAdapter
from wq_bus.ai.batch_buffer import BatchBuffer
from wq_bus.ai.cache import get_cache
from wq_bus.ai.model_router import ModelRouter
from wq_bus.ai.rate_limiter import RateLimiter
from wq_bus.ai.strength import get_router as get_strength_router
from wq_bus.data.state_db import record_ai_call, count_ai_calls_today
from wq_bus.utils.logging import get_logger
from wq_bus.utils.tag_context import get_tag, with_tag, get_trace_id, new_trace_id, with_trace
from wq_bus.utils.yaml_loader import load_yaml

_log = get_logger(__name__)

_INSTANCE: "Dispatcher | None" = None

# Global concurrency gate (AI_DISPATCHER.md §5)
_GLOBAL_SEMAPHORE: asyncio.Semaphore | None = None


def _global_sem() -> asyncio.Semaphore:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(4)
    return _GLOBAL_SEMAPHORE


class _NullAsyncContext:
    """A no-op async context manager used when no per-adapter semaphore exists."""
    async def __aenter__(self):  # noqa: D401
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False


_NULL_SEM = _NullAsyncContext()


def get_dispatcher(**kwargs: Any) -> "Dispatcher":
    """Return the module-level singleton :class:`Dispatcher`.

    On first call the instance is created with *kwargs*; subsequent calls
    return the cached instance (kwargs are ignored after first creation).
    """
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Dispatcher(**kwargs)
    return _INSTANCE


def _load_adapter_config() -> dict:
    try:
        profiles = load_yaml("agent_profiles") or {}
        return profiles.get("adapters") or {}
    except Exception:
        return {}


def _load_daily_cap() -> int:
    try:
        cfg = load_yaml("triggers") or {}
        return int(cfg.get("daily_ai_cap", 80))
    except Exception:
        return 80


def _load_concurrency_cfg() -> dict:
    """Load concurrency block from agent_profiles or triggers config."""
    try:
        profiles = load_yaml("agent_profiles") or {}
        cc = profiles.get("concurrency")
        if cc:
            return cc
    except Exception:
        pass
    try:
        cfg = load_yaml("triggers") or {}
        return cfg.get("concurrency") or {}
    except Exception:
        return {}


class Dispatcher:
    """Composes StrengthRouter + BatchBuffer + PackageCache + adapters.

    Backward-compat API:
        await dispatcher.call("alpha_gen", payload_dict)          # legacy
        await dispatcher.call(task_pkg_dict, source="auto")       # v2
        await dispatcher.call("alpha_gen", payload, source="auto")# hybrid
    """

    def __init__(
        self,
        override_model: str | None = None,
        override_depth: str | None = None,
        override_batch_size: int | None = None,
        override_flush_secs: float | None = None,
        dry_run: bool = False,
    ) -> None:
        # Allow env override so any caller (CLI/tests) can flip dry-run without
        # plumbing a flag through every site that constructs a Dispatcher.
        import os as _os
        if not dry_run and _os.environ.get("WQBUS_DRY", "").strip().lower() in ("1","true","yes","on"):
            dry_run = True
        self._dry_run = dry_run
        self._router = ModelRouter(
            override_model=override_model,
            override_depth=override_depth,
            override_batch_size=override_batch_size,
            override_flush_secs=override_flush_secs,
        )
        self._limiter = RateLimiter()
        self._strength_router = get_strength_router()
        self._cache = get_cache()

        # BatchBuffer keyed by (adapter_name, strength) — filled lazily per bucket
        self._buffers: dict[tuple[str, str], BatchBuffer] = {}

        # Adapter instances
        self._adapters: dict[str, Any] = {
            "copilot": CopilotAdapter(),
            "copilot_cli": CopilotAdapter(),
            "openai": OpenAIAdapter(),
            "openai_gpt5": OpenAIAdapter(),
            "glm": GLMAdapter(),
            "glm_4_5": GLMAdapter(),
        }

        # Per-adapter concurrency limits (from config) — lazy created
        self._per_adapter_max: dict[str, asyncio.Semaphore] = {}
        self._per_adapter_limits: dict[str, int] = {}
        try:
            cc = _load_concurrency_cfg()
            global_max = int(cc.get("global_max", 4))
            global _GLOBAL_SEMAPHORE
            if _GLOBAL_SEMAPHORE is None:
                _GLOBAL_SEMAPHORE = asyncio.Semaphore(max(1, global_max))
            for name, limit in (cc.get("per_adapter_max") or {}).items():
                try:
                    self._per_adapter_limits[str(name)] = max(1, int(limit))
                except Exception:
                    pass
        except Exception:
            _log.debug("dispatcher: concurrency cfg load failed (non-fatal)")

        # Discover transform registry for chain_hook
        try:
            ai_transforms.discover()
        except Exception:
            _log.debug("dispatcher: transforms discover failed (non-fatal)")

    def _per_adapter_sem(self, adapter_name: str) -> asyncio.Semaphore | None:
        """Return per-adapter semaphore (creating on first call), or None if unconfigured."""
        if adapter_name not in self._per_adapter_limits:
            return None
        sem = self._per_adapter_max.get(adapter_name)
        if sem is None:
            sem = asyncio.Semaphore(self._per_adapter_limits[adapter_name])
            self._per_adapter_max[adapter_name] = sem
        return sem

    # ------------------------------------------------------------------
    # Public: on startup scan and reissue incomplete packages
    # ------------------------------------------------------------------

    def startup_reissue(self) -> None:
        """Scan cache for incomplete packages and log them for re-dispatch.

        Actual re-dispatch happens lazily on next call; this just logs.
        """
        try:
            incomplete = self._cache.scan_and_reissue()
            if incomplete:
                _log.info("startup_reissue: %d incomplete packages found", len(incomplete))
        except Exception:
            _log.debug("startup_reissue: cache scan failed (non-fatal)")

    # ------------------------------------------------------------------
    # Main entry point (v2 + legacy compat)
    # ------------------------------------------------------------------

    async def call(
        self,
        agent_type_or_pkg: "str | dict",
        payload_or_source: "dict | str | None" = None,
        *,
        source: Literal["auto", "manual"] = "auto",
        force_immediate: bool = False,
    ) -> dict:
        """Dispatch one AI call. Accepts legacy (agent_type, payload) or new (task_pkg, source).

        Legacy call (backward compat):
            result = await dispatcher.call("alpha_gen", {"hint": "..."})

        New v2 call (single task pkg):
            result = await dispatcher.call(
                {"tasks": [{"agent": "alpha_gen", "mode": "explore", "payload": {...}}]},
                source="auto"
            )
        """
        # --- Normalize to (agent_type, payload, mode, source) ---
        if isinstance(agent_type_or_pkg, str):
            agent_type = agent_type_or_pkg
            payload = payload_or_source if isinstance(payload_or_source, dict) else {}
            mode = payload.get("mode") or payload.get("_mode")
            if isinstance(payload_or_source, str):
                source = payload_or_source  # type: ignore[assignment]
        else:
            # New task_pkg dict form
            pkg = agent_type_or_pkg
            if isinstance(payload_or_source, str):
                source = payload_or_source  # type: ignore[assignment]
            tasks = pkg.get("tasks") or []
            if not tasks:
                return {}
            # For now handle single-task pkg; multi-task bundling is done by BatchBuffer
            first = tasks[0]
            agent_type = first.get("agent", "")
            payload = first.get("payload") or {}
            mode = first.get("mode") or payload.get("mode")
            # Guard: ensure agent wrote no strength/model
            for field in ("strength", "model"):
                if field in first:
                    _log.warning(
                        "dispatcher: task pkg has forbidden field %r from agent %s — ignoring",
                        field, agent_type,
                    )
                    first.pop(field, None)

        if self._dry_run:
            return self._dry_run_response(agent_type, payload)

        # --- Daily AI cap check (auto only) ---
        if source == "auto":
            cap = _load_daily_cap()
            today_count = 0
            try:
                # Filter by source='auto' so manual calls don't burn the
                # auto budget (the cap only blocks auto, but the count
                # must match the cap's denominator — see is_capped()).
                today_count = count_ai_calls_today(source="auto")
            except Exception:
                pass
            if today_count >= cap:
                _log.warning("daily_ai_cap=%d reached (%d today) — blocking auto call to %s",
                             cap, today_count, agent_type)
                self._emit_budget_exhausted()
                raise RuntimeError(
                    f"daily_ai_cap={cap} reached — use source='manual' to bypass"
                )

        # --- Resolve strength and adapter ---
        strength = self._strength_router.resolve(agent_type, mode)
        adapter_name, billing_mode = self._resolve_adapter(agent_type)

        # --- Dispatch ---
        cfg = self._router.resolve(agent_type)

        if billing_mode == "per_token" or force_immediate or cfg["batch_size"] == 1:
            return await self._direct_call(agent_type, payload, cfg,
                                           adapter_name=adapter_name, strength=strength,
                                           source=source)

        # per_call → BatchBuffer keyed by (adapter_name, strength)
        bucket_key = (adapter_name, strength)
        buf = self._get_or_create_buffer(bucket_key)
        payload["_strength"] = strength
        payload["_adapter"] = adapter_name
        payload["_source"] = source
        return await buf.submit(agent_type, payload)

    def _resolve_adapter(self, agent_type: str) -> tuple[str, str]:
        """Return (adapter_name, billing_mode) for agent_type from config."""
        try:
            profiles = load_yaml("agent_profiles") or {}
            agent_cfg = profiles.get("agents", {}).get(agent_type, {})
            provider = agent_cfg.get("provider") or profiles.get("defaults", {}).get("provider", "copilot")
            adapters = profiles.get("adapters") or {}
            # Map provider -> adapter key
            adapter_name = provider
            if provider == "copilot":
                adapter_name = "copilot_cli"
            billing_mode = (adapters.get(adapter_name) or {}).get("billing_mode", "per_call")
            return adapter_name, billing_mode
        except Exception:
            return "copilot_cli", "per_call"

    def _get_or_create_buffer(self, bucket_key: tuple[str, str]) -> BatchBuffer:
        """Return (or create) the BatchBuffer for (adapter, strength) bucket."""
        if bucket_key not in self._buffers:
            adapter_name, strength = bucket_key

            async def _flusher(agent_type: str, payloads: list[dict]) -> list[dict]:
                return await self._bucket_flush(agent_type, payloads,
                                                adapter_name=adapter_name, strength=strength)

            self._buffers[bucket_key] = BatchBuffer(
                flusher=_flusher,
                config_resolver=self._router.resolve,
            )
        return self._buffers[bucket_key]

    # ------------------------------------------------------------------
    # Flush: per_call bucket
    # ------------------------------------------------------------------

    async def _bucket_flush(
        self,
        agent_type: str,
        payloads: list[dict],
        *,
        adapter_name: str,
        strength: str,
    ) -> list[dict]:
        """Flush a bucket: NEVER mix strength in one package."""
        # Strip internal routing fields from payloads
        clean_payloads = []
        for p in payloads:
            cp = {k: v for k, v in p.items() if not k.startswith("_")}
            clean_payloads.append(cp)

        return await self._flusher(
            agent_type, clean_payloads,
            adapter_name=adapter_name, strength=strength, source="auto",
        )

    async def _direct_call(
        self,
        agent_type: str,
        payload: dict,
        cfg: dict,
        *,
        adapter_name: str,
        strength: str,
        source: str,
    ) -> dict:
        """Call adapter directly (no batching) — per_token or force_immediate."""
        clean = {k: v for k, v in payload.items() if not k.startswith("_")}
        results = await self._flusher(
            agent_type, [clean], cfg=cfg,
            adapter_name=adapter_name, strength=strength, source=source,
        )
        return results[0]

    async def _flusher(
        self,
        agent_type: str,
        payloads: list[dict],
        *,
        cfg: dict | None = None,
        adapter_name: str = "copilot_cli",
        strength: str = "medium",
        source: str = "auto",
    ) -> list[dict]:
        """Core flush: build package, call adapter (with retry), record to DB."""
        if cfg is None:
            cfg = self._router.resolve(agent_type)

        # Select model from strength tier
        model, depth = self._model_for_strength(adapter_name, strength, cfg)
        n = len(payloads)

        # Rate limit (legacy — still honoured)
        if source == "auto" and not self._limiter.check_and_reserve(agent_type):
            raise RuntimeError(
                f"Rate limit exceeded for agent_type={agent_type!r}"
            )

        prompt = subagent_packer.pack(payloads, agent_type)
        messages = [{"role": "user", "content": prompt}]

        adapter = self._adapters.get(adapter_name) or self._adapters.get("copilot_cli") or self._adapters["copilot"]
        tag = get_tag() or "_global"

        # Create cache package
        pkg_id = self._cache.create_package(
            trace_id=self._current_trace_id(),
            agents=[agent_type],
            source=source,
            strength=strength,
            adapter=adapter_name,
            model=model,
            task_pkg={"tasks": payloads},
            dataset_tag=tag,
        )

        t0 = time.monotonic()
        success = True
        error_msg: str | None = None
        response_text: str = ""
        results: list[dict] = []

        async with _global_sem():
            adapter_sem = self._per_adapter_sem(adapter_name)
            # Use async-with so a CancelledError during acquire never leaks the slot
            sem_ctx = adapter_sem if adapter_sem is not None else _NULL_SEM
            async with sem_ctx:
                try:
                    self._cache.set_stage(pkg_id, "sent")
                    response_text = await self._call_with_retry(adapter, messages, model, depth)
                    self._cache.write_raw_response(pkg_id, response_text)
                    self._cache.set_stage(pkg_id, "received")
                    results = subagent_packer.unpack(response_text, n)
                    self._cache.write_result(pkg_id, {"results": results})
                    self._cache.set_stage(pkg_id, "unpacked")
                except Exception as exc:
                    success = False
                    error_msg = str(exc)
                    self._cache.write_error(pkg_id, error_msg)
                    self._cache.set_stage(pkg_id, "failed")
                    _log.error("Adapter call failed agent=%s pkg=%s: %s", agent_type, pkg_id, exc)
                    raise
                finally:
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    if source == "auto":
                        self._limiter.register_call(agent_type)

                    ai_call_id = self._safe_record(
                        agent_type=agent_type,
                        model=model,
                        provider=adapter_name,
                        depth=depth,
                        n_packed=n,
                        duration_ms=duration_ms,
                        success=success,
                        error=error_msg,
                        prompt_text=prompt,
                        response_text=response_text,
                        strength=strength,
                        source=source,
                        package_id=pkg_id,
                    )
                    if success:
                        for r in results:
                            if isinstance(r, dict):
                                r.setdefault("_ai_call_id", ai_call_id)
                                r.setdefault("_package_id", pkg_id)

        if success:
            self._cache.set_stage(pkg_id, "done")

        return results

    # ------------------------------------------------------------------
    # chain_hook: serialised multi-task call (AI_DISPATCHER.md §5.1)
    # ------------------------------------------------------------------

    async def call_chain(
        self,
        agent_type: str,
        tasks: list[dict],
        *,
        source: Literal["auto", "manual"] = "auto",
        ctx: dict | None = None,
    ) -> list[dict]:
        """Execute a list of tasks honouring chain_hook dependencies.

        Each task is a dict ``{"id": str, "payload": dict, "mode": str | None,
        "chain_hook": {"from": tid, "transform": name} | None}``.

        Tasks without a chain_hook execute first (in one batch via standard
        dispatch); tasks with a chain_hook receive their dependency's output
        through ``transforms.apply(name, prev_output, ctx)`` injected into
        ``payload['chain_context']`` before dispatch. Max 2 levels of chaining
        per call (deeper chains must be split across calls).

        Returns results in the same order as input tasks.
        """
        if not tasks:
            return []

        ctx = ctx or {}
        outer_trace_id = get_trace_id() or ""
        outer_tag = get_tag() or ""

        def _write_sub_trace(sub_id: str, task: dict) -> None:
            """Write a sub_trace row with origin='dispatcher_pack' linked to outer."""
            try:
                from wq_bus.bus.tasks import _write_trace
                _write_trace(
                    sub_id,
                    kind=f"dispatcher_pack:{agent_type}",
                    origin="dispatcher_pack",
                    parent_trace_id=outer_trace_id or None,
                    task_payload_json=json.dumps({
                        "task_id": task.get("id"),
                        "agent": agent_type,
                        "mode": task.get("mode"),
                        "has_chain_hook": bool(task.get("chain_hook")),
                    }),
                    dataset_tag=outer_tag,
                )
            except Exception:
                _log.debug("sub_trace write failed", exc_info=True)

        def _close_sub_trace(sub_id: str, status: str, err: str | None = None) -> None:
            try:
                from wq_bus.bus.tasks import _update_trace_status
                _update_trace_status(sub_id, status, error=err)
            except Exception:
                pass

        # Index by id
        by_id: dict[str, dict] = {}
        for i, t in enumerate(tasks):
            tid = str(t.get("id") or f"t{i}")
            t["id"] = tid
            by_id[tid] = t

        # Validate chain depth ≤ 2
        def depth_of(t: dict, seen: set[str] | None = None) -> int:
            seen = seen or set()
            tid = t["id"]
            if tid in seen:
                return 0
            seen.add(tid)
            hook = t.get("chain_hook") or {}
            parent = hook.get("from")
            if not parent or parent not in by_id:
                return 0
            return 1 + depth_of(by_id[parent], seen)

        results_by_id: dict[str, dict] = {}

        # Layer 0: tasks without chain_hook
        layer0 = [t for t in tasks if not (t.get("chain_hook") or {}).get("from")]
        # Validate remaining depth
        chained = [t for t in tasks if t not in layer0]
        for t in chained:
            if depth_of(t) > 2:
                raise ValueError(
                    f"chain_hook depth > 2 for task {t['id']!r}; split across multiple call_chain invocations"
                )

        # Run layer0 — one call per task (keeps strength routing per-task)
        for t in layer0:
            payload = dict(t.get("payload") or {})
            mode = t.get("mode")
            if mode and "mode" not in payload:
                payload["mode"] = mode
            sub_id = new_trace_id()
            _write_sub_trace(sub_id, t)
            try:
                with with_trace(sub_id):
                    res = await self.call(agent_type, payload, source=source)
                results_by_id[t["id"]] = res if isinstance(res, dict) else {"data": res}
                _close_sub_trace(sub_id, "ok")
            except Exception as e:
                _close_sub_trace(sub_id, "error", err=str(e)[:500])
                results_by_id[t["id"]] = {"error": str(e)[:500]}

        # Run chained layers iteratively
        remaining = list(chained)
        for _layer in range(1, 3):  # up to 2 levels
            if not remaining:
                break
            ready = [t for t in remaining if (t.get("chain_hook") or {}).get("from") in results_by_id]
            for t in ready:
                hook = t.get("chain_hook") or {}
                parent_id = hook["from"]
                tname = hook.get("transform") or "summarize_prev"
                snippet = ai_transforms.apply(tname, results_by_id.get(parent_id, {}), ctx)
                payload = dict(t.get("payload") or {})
                payload["chain_context"] = snippet
                payload["_chain_from"] = parent_id
                mode = t.get("mode")
                if mode and "mode" not in payload:
                    payload["mode"] = mode
                sub_id = new_trace_id()
                _write_sub_trace(sub_id, t)
                try:
                    with with_trace(sub_id):
                        res = await self.call(agent_type, payload, source=source)
                    results_by_id[t["id"]] = res if isinstance(res, dict) else {"data": res}
                    _close_sub_trace(sub_id, "ok")
                except Exception as e:
                    _close_sub_trace(sub_id, "error", err=str(e)[:500])
                    results_by_id[t["id"]] = {"error": str(e)[:500]}
            remaining = [t for t in remaining if t["id"] not in results_by_id]

        if remaining:
            _log.warning("call_chain: %d tasks unresolved (broken chain_hook)", len(remaining))
            for t in remaining:
                results_by_id[t["id"]] = {"error": "chain_hook unresolved"}

        return [results_by_id[t["id"]] for t in tasks]

    async def _call_with_retry(self, adapter, messages, model, depth, *, max_retries=1):
        """Call adapter, retry once on network/timeout/JSON-parse errors."""
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return await adapter.call(messages, model, depth)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    _log.warning("adapter call failed (attempt %d), retrying: %s", attempt + 1, exc)
                    await asyncio.sleep(2.0)
        raise last_exc  # type: ignore[misc]

    def _model_for_strength(self, adapter_name: str, strength: str, cfg: dict) -> tuple[str, str]:
        """Map (adapter, strength) to (model, depth) from config."""
        try:
            profiles = load_yaml("agent_profiles") or {}
            adapters = profiles.get("adapters") or {}
            tiers = (adapters.get(adapter_name) or {}).get("strength_tiers") or {}
            tier = tiers.get(strength)
            if tier:
                return str(tier.get("model", cfg["model"])), str(tier.get("depth", cfg["depth"]))
        except Exception:
            pass
        # Fallback: use ModelRouter cfg
        return cfg["model"], cfg["depth"]

    def _current_trace_id(self) -> str:
        try:
            from wq_bus.utils.tag_context import get_trace_id
            return get_trace_id() or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # dry_run stub
    # ------------------------------------------------------------------

    def _dry_run_response(self, agent_type: str, payload: dict) -> dict:
        """Stub response realistic enough to drive the bus end-to-end."""
        if agent_type == "alpha_gen":
            n = int(payload.get("n_requested") or payload.get("n") or 3)
            import random as _r
            seed = int(time.time() * 1000) % 100000
            base = [
                f"rank(liabilities/assets) * {seed % 7 + 1}",
                f"rank(operating_income/(assets+{seed % 13}))",
                f"rank(ts_delta(close, {(seed % 5) + 3}))",
                f"group_rank(retained_earnings/assets, sector) - {seed % 3}",
                f"rank(cash/(assets+{(seed * 3) % 11}))",
                f"rank(operating_cash_flow/(assets+{seed % 17}))",
            ]
            _r.shuffle(base)
            response = {"expressions": [
                {"expression": expr, "rationale": "dry-run stub", "settings_overrides": {}}
                for expr in base[:max(1, n)]
            ]}
        elif agent_type == "failure_analyzer":
            response = {"summary": "[dry-run] no real failures analyzed",
                        "mutation_tasks": []}
        elif agent_type == "doc_summarizer":
            n_docs = len((payload or {}).get("docs", [])) or 1
            response = {"summary_md": f"[dry-run] stub summary covering {n_docs} docs.",
                        "key_points": []}
        else:
            response = {"_dry_run": True, "agent_type": agent_type}

        ai_call_id = self._safe_record(
            agent_type=agent_type, model="dry-run", provider="stub",
            n_packed=1, success=True, duration_ms=0,
            prompt_text=f"[dry-run]\n{payload}",
            response_text=str(response),
        )
        response["_ai_call_id"] = ai_call_id
        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_budget_exhausted(self) -> None:
        try:
            from wq_bus.bus.event_bus import get_bus
            from wq_bus.bus.events import BUDGET_EXHAUSTED, make_event
            tag = get_tag() or "_global"
            get_bus().emit(make_event(BUDGET_EXHAUSTED, tag))
        except Exception:
            pass

    def _count_ai_calls_today(self, source: str | None = None) -> int:
        """Count AI calls in the last 24h, optionally filtered by *source*."""
        try:
            from wq_bus.data._sqlite import open_state
            cutoff = time.time() - 86400
            if source is not None:
                with open_state() as conn:
                    return int(conn.execute(
                        "SELECT COUNT(*) FROM ai_calls WHERE ts >= ? AND source = ?",
                        (cutoff, source),
                    ).fetchone()[0])
            else:
                return count_ai_calls_today()
        except Exception:
            return 0

    def _is_capped(self, source: str) -> bool:
        """Return True if the daily AI cap is reached for *source*.

        ``manual`` source always bypasses the cap, matching the behaviour of
        :meth:`call` which only enforces the cap when ``source == 'auto'``.
        """
        if source == "manual":
            return False
        # Allow tests to patch _daily_ai_cap on the instance.
        cap = getattr(self, "_daily_ai_cap", None) or _load_daily_cap()
        return self._count_ai_calls_today(source=source) >= cap

    def _safe_record(self, **kwargs: Any) -> int | None:
        """Call :func:`record_ai_call`; inject a fallback tag if none is active.

        record_ai_call now accepts strength/mode/adapter/package_id/source
        (migration 005 columns) — pass them through verbatim so the audit
        trail is complete and ``count_ai_calls_today(source='auto')`` works.
        """
        try:
            if get_tag() is None:
                with with_tag("_global"):
                    return record_ai_call(**kwargs)
            return record_ai_call(**kwargs)
        except Exception as exc:
            _log.warning("Failed to record ai_call to state.db: %s", exc)
            return None
