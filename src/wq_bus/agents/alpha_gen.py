"""alpha_gen agent — produces ALPHA_DRAFTED events from GENERATE_REQUESTED.

Modes: explore | specialize | review_failure | track_news (plan §13)

For each request:
1. Loads workspace context (pool stats, recent failures, crawl summaries).
2. Asks dispatcher for N expressions (single batched AI call).
3. For each returned expression:
   - fingerprint → dedup
   - dimensions.classify() → feature_vector → direction_id
   - recipes.match() → themes → themes_csv
   - upsert_direction + bump_stats
   - emit ALPHA_DRAFTED with direction_id / themes_csv
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar

from wq_bus.agents.base import AgentBase
from wq_bus.analysis.expression_fingerprint import fingerprint, is_duplicate, record
from wq_bus.bus.events import Event, Topic, make_event
from wq_bus.data import knowledge_db
from wq_bus.utils.tag_context import require_tag

from wq_bus.utils.paths import PROJECT_ROOT  # noqa: E402
MEMORY_DIR = PROJECT_ROOT / "memory"
DATA_DIR = PROJECT_ROOT / "data"


def _load_valid_fields(tag: str, *, limit: int = 40) -> list[dict]:
    """Load cached datafields for the given dataset tag. Returns up to ``limit``
    entries with id+description so the AI knows what to use."""
    import json
    candidates = [
        DATA_DIR / f"datafields_{tag}.json",
        DATA_DIR / f"datafields_{tag.lower()}.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        fields = data.get("fields") if isinstance(data, dict) else data
        if not isinstance(fields, list):
            continue
        out = []
        for f in fields[:limit]:
            if isinstance(f, dict):
                out.append({
                    "id": f.get("id"),
                    "desc": (f.get("description") or "")[:50],
                })
        return out
    return []


_MODE_HINTS: dict[str, str] = {
    "explore": (
        "EXPLORE MODE: Generate diverse novel alpha expressions across "
        "different data field classes and operator families. Prioritise unexplored directions."
    ),
    "specialize": (
        "SPECIALIZE MODE: Generate variations of known high-performing directions. "
        "Focus on improving Sharpe or reducing turnover for directions with good IS pass rates."
    ),
    "review_failure": (
        "REVIEW_FAILURE MODE: Analyse the recent failure patterns below and generate "
        "mutated alpha expressions that address specific failure reasons (HIGH_TURNOVER, "
        "LOW_SHARPE, HIGH_SELF_CORR). Use different operators or neutralization settings."
    ),
    "track_news": (
        "TRACK_NEWS MODE: Generate alphas inspired by recent crawl summaries and news themes. "
        "Focus on event-driven or macro-linked expressions."
    ),
}


class AlphaGen(AgentBase):
    AGENT_TYPE = "alpha_gen"
    SUBSCRIPTIONS = [Topic.GENERATE_REQUESTED, Topic.KNOWLEDGE_UPDATED]

    name:            ClassVar[str]  = "alpha_gen"
    modes:           ClassVar[list] = ["explore", "specialize", "review_failure", "track_news"]
    workspace_rules: ClassVar[dict] = {
        "reads":  ["context_index.json", "failure_patterns.json"],
        "writes": ["pool_stats_<TAG>"],
        "memory_files": ["insights.md"],
    }
    billing_hint:    ClassVar[str] = "per_call"

    def __init__(self, bus, dispatcher) -> None:
        super().__init__(bus, dispatcher)
        self._cached_summaries: list[str] = []
        # Programmatic-expansion factor: each AI seed is mutated into K
        # parameter-swept variants (windows + neutralization + decay +
        # truncation). Loaded from config/alpha_gen.yaml; default 4 → 15
        # AI seeds become ~60 simulator candidates per round.
        try:
            from wq_bus.utils.yaml_loader import load_yaml
            self._cfg = load_yaml("alpha_gen") or {}
        except Exception:
            self._cfg = {}

    async def on_knowledge_updated(self, event: Event) -> None:
        self._cached_summaries.clear()
        self.log.info("knowledge updated for %s, summary cache cleared", event.dataset_tag)

    async def on_generate_requested(self, event: Event) -> None:
        n = int(event.payload.get("n", 5))
        hint = event.payload.get("hint", "")
        tag = event.dataset_tag
        mode = str(event.payload.get("mode", "explore"))

        if mode not in self.modes:
            self.log.warning("unknown mode=%r for alpha_gen, defaulting to explore", mode)
            mode = "explore"

        context = self._build_context(tag, hint, mode)

        # ── Mode budget for the fragment + combiner pipeline ───────────────
        # Falls back to legacy "ask AI for n complete alphas" if no
        # mode_budgets entry exists for this mode.
        mode_budgets = (self._cfg.get("mode_budgets") or {})
        mode_cfg = mode_budgets.get(mode) or {}
        use_fragments = bool(mode_cfg)

        # ── Pick prompt + build vars ───────────────────────────────────────
        if use_fragments:
            prompt_kind = "alpha_gen.fragments"
            prompt_vars = {
                "dataset_tag":      tag,
                "mode":             mode,
                "n_signals":        int(mode_cfg.get("n_signals", 8)),
                "n_filters":        int(mode_cfg.get("n_filters", 3)),
                "n_weights":        int(mode_cfg.get("n_weights", 2)),
                "top_directions":   context.get("top_submitted", []),
                "recent_failures":  context.get("recent_failures",
                                                context.get("recent_learnings", [])),
                "recent_summaries": context.get("crawl_summaries", []),
                "available_docs":   context.get("available_docs", ""),
            }
        else:
            prompt_kind = "alpha_gen.repair" if mode == "review_failure" else "alpha_gen.explore"
            if prompt_kind == "alpha_gen.repair":
                mut_tasks = (context.get("mutation_tasks")
                             or context.get("failure_mutations")
                             or [])
                prompt_vars = {
                    "dataset_tag":     tag,
                    "n":               n,
                    "mutation_tasks":  mut_tasks,
                    "top_directions":  context.get("top_submitted", []),
                    "available_docs":  context.get("available_docs", ""),
                }
            else:
                prompt_vars = {
                    "dataset_tag":      tag,
                    "n":                n,
                    "top_directions":   context.get("top_submitted", []),
                    "recent_failures":  context.get("recent_failures",
                                                    context.get("recent_learnings", [])),
                    "recent_summaries": context.get("crawl_summaries", []),
                    "available_docs":   context.get("available_docs", ""),
                }

        # b1: one retry with backoff for transient AI failures
        r = None
        last_exc: Exception | None = None
        for attempt in range(1, 3):
            try:
                r = await self.ai_request(prompt_kind, prompt_vars, timeout=300)
                if r is not None:
                    break
                # ai_request returned None on timeout/AI_CALL_FAILED — treat as
                # transient and retry once.
                last_exc = RuntimeError("ai_request returned None")
            except Exception as e:
                last_exc = e
                self.log.warning("alpha gen attempt %d/2 failed mode=%s: %s", attempt, mode, e)
            if attempt < 2:
                await asyncio.sleep(2.0 if attempt == 1 else 8.0)

        # ── Fallback: if fragments prompt failed/empty, retry legacy explore ──
        # Reasoning: the combiner depends on at least 1 signal; if AI returns
        # empty fragments we don't want a wasted round. Legacy alpha_gen.explore
        # has years of prompt tuning and is a safe net.
        used_fallback = False
        if use_fragments:
            from wq_bus.agents.alpha_combiner import parse_ai_response as _parse_frags
            ai_call_id_top0 = r.get("_ai_call_id") if isinstance(r, dict) else None
            preview_frags = _parse_frags(r, ai_call_id=ai_call_id_top0) if r else None
            need_fallback = (r is None) or (preview_frags is None) or (not preview_frags.signals)
            if need_fallback:
                self.log.warning(
                    "alpha_gen.fragments produced no signals — falling back to alpha_gen.explore"
                )
                fb_kind = "alpha_gen.explore"
                fb_vars = {
                    "dataset_tag":      tag,
                    "n":                int(mode_cfg.get("n_signals", n) or n),
                    "top_directions":   context.get("top_submitted", []),
                    "recent_failures":  context.get("recent_failures",
                                                    context.get("recent_learnings", [])),
                    "recent_summaries": context.get("crawl_summaries", []),
                }
                try:
                    r = await self.ai_request(fb_kind, fb_vars, timeout=300)
                    used_fallback = True
                except Exception as e:
                    last_exc = e
                    r = None

        if r is None:
            # b3: emit dedicated error event so trace can close cleanly
            try:
                from wq_bus.bus.events import make_event as _mk
                self.bus.emit(_mk("ALPHA_GEN_ERRORED", tag,
                                  reason=f"{type(last_exc).__name__}: {last_exc}",
                                  attempts=2))
            except Exception:
                self.log.exception("failed to emit ALPHA_GEN_ERRORED")
            return

        # ── Build seeds: either via combiner (fragments) or legacy direct ──
        ai_call_id_top = r.get("_ai_call_id") if isinstance(r, dict) else None
        seeds: list[tuple[str, dict, str | None, str]] = []

        if use_fragments and not used_fallback:
            from wq_bus.agents.alpha_combiner import (
                combine as _combine, parse_ai_response as _parse_frags,
            )
            frags = _parse_frags(r, ai_call_id=ai_call_id_top)
            combined = _combine(frags, mode_cfg)
            self.log.info(
                "alpha_combiner: signals=%d filters=%d weights=%d → combined=%d "
                "(strategies=%s)",
                len(frags.signals), len(frags.filters), len(frags.weights),
                len(combined),
                mode_cfg.get("enabled_strategies") or "<all>",
            )
            for ca in combined:
                seeds.append((
                    ca.expr,
                    ca.settings or {},
                    ca.provenance.get("ai_call_id") or ai_call_id_top,
                    f"[{ca.provenance.get('strategy','combo')}] "
                    f"{ca.provenance.get('rationale','')}".strip(),
                ))
        else:
            # Legacy / fallback path
            items: list[dict]
            if isinstance(r, dict) and isinstance(r.get("alphas"), list):
                items = r["alphas"]
            elif isinstance(r, dict) and isinstance(r.get("expressions"), list):
                items = r["expressions"]
            elif isinstance(r, dict) and r.get("expression"):
                items = [r]
            else:
                items = []
            for item in items[:max(n, int(mode_cfg.get("n_signals", n) or n))]:
                expr = (item or {}).get("expression", "").strip()
                if not expr:
                    continue
                seeds.append((
                    expr,
                    (item or {}).get("settings_overrides") or {},
                    item.get("_ai_call_id") or ai_call_id_top,
                    (item or {}).get("rationale", ""),
                ))

        n_emitted = 0
        import uuid as _uuid
        batch_id = _uuid.uuid4().hex[:8]
        # Programmatic expansion (post-combiner): each seed → K variants by
        # perturbing ts_* windows + simulator settings.
        from wq_bus.agents.alpha_mutator import expand_batch
        expansion_factor = max(1, int(
            mode_cfg.get("expansion_factor",
                         self._cfg.get("expansion_factor", 4))
        ))
        # Expand: list of (expr, settings, parent_idx)
        expanded = expand_batch(
            [(s[0], s[1]) for s in seeds],
            factor=expansion_factor,
        )
        # First pass: filter out duplicates / blanks so batch_total reflects what
        # sim_executor will actually see. Without this the BATCH_DONE counter would
        # never converge when N items collapse via dedup.
        prepared: list[tuple[str, str, dict, str | None, str]] = []
        for v_expr, v_settings, parent_idx in expanded:
            if not v_expr:
                continue
            if is_duplicate(v_expr):
                self.log.debug("dedup skip: %s", v_expr[:80])
                continue
            fp_hash, _ = fingerprint(v_expr)
            record(v_expr)
            _, _, p_aicid, p_rationale = seeds[parent_idx]
            # Mark variants (parent_idx>0 within seed → variant) in rationale
            rationale = p_rationale if v_expr == seeds[parent_idx][0] and v_settings == seeds[parent_idx][1] \
                                    else f"[variant] {p_rationale}"
            prepared.append((v_expr, fp_hash, v_settings, p_aicid, rationale))
        self.log.info(
            "alpha_gen: mode=%s prompt=%s seeds=%d → expanded=%d → after_dedup=%d "
            "(factor=%d, fallback=%s)",
            mode, prompt_kind, len(seeds), len(expanded), len(prepared),
            expansion_factor, used_fallback,
        )

        batch_total = len(prepared)
        if batch_total == 0:
            # Nothing to draft this round — emit BATCH_DONE immediately so the
            # coordinator's wait_for(BATCH_DONE) doesn't wedge until timeout.
            try:
                self.bus.emit(make_event(Topic.BATCH_DONE, tag,
                                         batch_id=batch_id, n_total=0,
                                         n_is_passed=0, n_sc_passed=0))
            except Exception:
                self.log.exception("empty BATCH_DONE emit failed")
            self.log.info("alpha_gen emitted 0/%d drafts for %s mode=%s (1 AI call) — empty batch", n, tag, mode)
            return

        for expr, fp_hash, settings_overrides, ai_call_id, rationale in prepared:
            direction_id, themes_csv = self._classify_and_register(
                expr, settings_overrides, tag, mode, hint
            )

            try:
                from wq_bus.data import workspace
                workspace.bump_stats(tag, direction_id, alphas_tried=1)
            except Exception as e:
                self.log.debug("bump_stats(alphas_tried) failed for %s: %s", direction_id, e)

            try:
                self.bus.emit(make_event(Topic.ALPHA_DRAFTED, tag,
                                         expression=expr,
                                         settings=settings_overrides,
                                         fingerprint=fp_hash,
                                         ai_call_id=ai_call_id,
                                         rationale=rationale,
                                         direction_id=direction_id,
                                         themes_csv=themes_csv,
                                         mode=mode,
                                         batch_id=batch_id,
                                         batch_total=batch_total))
            except Exception as e:
                self.log.exception("ALPHA_DRAFTED emit failed; rolling back fingerprint: %s", e)
                try:
                    knowledge_db.delete_fingerprint(fp_hash)
                except Exception:
                    self.log.exception("fingerprint rollback failed for %s", fp_hash[:12])
                # Decrement batch_total via a "skip" notification so sim_executor
                # doesn't wait forever for an alpha that never made it to the bus.
                try:
                    self.bus.emit(make_event("ALPHA_DRAFT_SKIPPED", tag,
                                             batch_id=batch_id, reason="emit_failed"))
                except Exception:
                    pass
                continue
            n_emitted += 1

        self.log.info("alpha_gen emitted %d/%d drafts for %s mode=%s batch=%s (1 AI call)",
                      n_emitted, n, tag, mode, batch_id)

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    def _classify_and_register(
        self, expr: str, settings: dict, tag: str, mode: str, hint: str
    ) -> tuple[str, str | None]:
        """Classify expression → (direction_id, themes_csv). Register in workspace."""
        direction_id = "unknown|other|MARKET|1-4"  # safe default
        themes_csv: str | None = None
        fv: dict = {}

        try:
            from wq_bus.domain import dimensions, recipes
            fv = dimensions.classify(expr, settings)
            direction_id = dimensions.project_id(fv)
        except Exception as e:
            self.log.debug("dimensions classify failed: %s", e)

        try:
            from wq_bus.domain import recipes
            themes = recipes.match(expr)
            if themes:
                themes_csv = ",".join(themes)
        except Exception as e:
            self.log.debug("recipes match failed: %s", e)

        try:
            from wq_bus.data import workspace
            workspace.upsert_direction(
                tag, direction_id, fv,
                raw_description=f"mode={mode} hint={hint[:100]}",
                origin="auto_extract",
                themes_csv=themes_csv,
            )
        except Exception as e:
            self.log.debug("upsert_direction failed: %s", e)

        return direction_id, themes_csv

    def _load_failure_patterns(self, tag: str) -> dict:
        """Load memory/<TAG>/failure_patterns.json (mutation_tasks + patterns)."""
        import json
        fp = MEMORY_DIR / tag / "failure_patterns.json"
        if not fp.exists():
            return {}
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            self.log.debug("failed to read failure_patterns.json: %s", e)
            return {}

    def _top_alphas_by_direction(self, tag: str, k: int = 3) -> list[dict]:
        """Return top directions by is_pass_rate, each with up to k passing alphas."""
        try:
            from wq_bus.data._sqlite import open_knowledge
            with open_knowledge() as conn:
                # Top 3 directions by is_pass_rate having >=1 pass
                dirs = conn.execute(
                    f"""SELECT d.direction_id, d.semantic_name, d.themes_csv,
                               ps.alphas_tried, ps.alphas_is_passed,
                               ps.avg_sharpe, ps.avg_fitness
                        FROM directions_{tag} d
                        JOIN pool_stats_{tag} ps USING(direction_id)
                        WHERE ps.alphas_is_passed >= 1
                        ORDER BY (CAST(ps.alphas_is_passed AS REAL)/MAX(ps.alphas_tried,1)) DESC,
                                 ps.alphas_is_passed DESC
                        LIMIT 3"""
                ).fetchall()
                out: list[dict] = []
                for d in dirs:
                    rows = conn.execute(
                        """SELECT expression, sharpe, fitness, turnover
                           FROM alphas
                           WHERE dataset_tag=? AND direction_id=?
                             AND status IN ('is_passed','sc_passed','submitted')
                           ORDER BY COALESCE(sharpe,0) DESC LIMIT ?""",
                        (tag, d["direction_id"], k),
                    ).fetchall()
                    out.append({
                        "direction_id": d["direction_id"],
                        "semantic_name": d["semantic_name"] or "",
                        "themes_csv": d["themes_csv"],
                        "alphas_tried": d["alphas_tried"],
                        "alphas_is_passed": d["alphas_is_passed"],
                        "avg_sharpe": d["avg_sharpe"],
                        "top_alphas": [
                            {"expr": r["expression"][:160],
                             "sharpe": r["sharpe"],
                             "fitness": r["fitness"],
                             "turnover": r["turnover"]}
                            for r in rows
                        ],
                    })
                return out
        except Exception as e:
            self.log.debug("_top_alphas_by_direction failed: %s", e)
            return []

    def _recent_fingerprints(self, tag: str, limit: int = 30) -> list[str]:
        """Return recent fingerprints (skeletons) to discourage duplicates."""
        try:
            from wq_bus.data._sqlite import open_knowledge
            with open_knowledge() as conn:
                rows = conn.execute(
                    """SELECT skeleton FROM expr_fingerprints
                       WHERE dataset_tag=? AND skeleton IS NOT NULL
                       ORDER BY rowid DESC LIMIT ?""",
                    (tag, limit),
                ).fetchall()
                return [r["skeleton"] for r in rows if r["skeleton"]]
        except Exception:
            return []

    def _load_portfolio_analysis(self, tag: str) -> dict:
        """Load memory/<TAG>/portfolio_analysis.json (gap_directions / overcrowded / suggestions)."""
        import json
        fp = MEMORY_DIR / tag / "portfolio_analysis.json"
        if not fp.exists():
            return {}
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            self.log.debug("failed to read portfolio_analysis.json: %s", e)
            return {}

    def _approved_recipe_hints(self, tag: str, k: int = 6) -> list[dict]:
        """Return top-k approved recipes (semantic_name + theme_tags + hypothesis)
        as compact hints for the AI to seed brand-new alphas around."""
        try:
            from wq_bus.domain import recipes as _recipes
            rows = _recipes.list_recipes(status="approved") or []
            out: list[dict] = []
            for r in rows[:k]:
                out.append({
                    "recipe_id": r.get("recipe_id"),
                    "semantic_name": r.get("semantic_name"),
                    "theme_tags": r.get("theme_tags"),
                    "example": (r.get("example_expressions") or "").split(";")[0][:160],
                    "hypothesis": (r.get("notes") or "")[:240],
                })
            return out
        except Exception as e:
            self.log.debug("approved_recipe_hints failed: %s", e)
            return []

    def _build_context(self, tag: str, hint: str, mode: str) -> dict:
        """Build prompt context with mode-specific prefix.

        rev-h7: heavy lifting (top alphas / failures / recipes / portfolio /
        crawl summaries / insights) is delegated to CuratedContext, which
        scores by recency+quality, deduplicates by theme, and applies a
        char-budget when the adapter bills per token. This module only adds
        agent-local fields (mode_hint, hint, valid_fields, avoid_expressions,
        and the specialize-mode top-directions block).
        """
        from wq_bus.ai.context_curator import CuratedContext

        mode_hint = _MODE_HINTS.get(mode, "")
        curated = CuratedContext(agent_type="alpha_gen", mode=mode, tag=tag).build()
        valid_fields = _load_valid_fields(tag)

        ctx: dict = {
            "dataset_tag": tag,
            "mode": mode,
            "mode_hint": mode_hint,
            "hint": hint,
            # Curator outputs (legacy keys preserved so prompt template is unchanged)
            "recent_learnings":     curated.get("recent_learnings", []),
            "top_submitted":        curated.get("top_submitted", []),
            "crawl_summaries":      curated.get("crawl_summaries", []),
            "insights_md":          (curated.get("insights") or [""])[0] if curated.get("insights") else "",
            "pool_summary":         curated.get("pool_summary", []),
            "gap_directions":       curated.get("gap_directions", []),
            "overcrowded_directions": curated.get("overcrowded_directions", []),
            "portfolio_suggestions": curated.get("portfolio_suggestions", []),
            "recipe_hints":         curated.get("recipe_hints", []),
            "valid_fields":         valid_fields,
            "field_rule": (
                "STRICT: Only use field ids from valid_fields. Common WQ price/volume "
                "fields (close, open, high, low, volume, vwap, returns, adv20) and "
                "ts_*/group_*/rank operators are always available. NEVER invent field "
                "names like net_income/equity/cashflow_op — use only listed ids or the "
                "common price/volume set."
            ),
            "_curator_meta":        curated.get("_curator_meta", {}),
        }

        # Universal: avoid recently-tried expression skeletons (agent-local;
        # not in curator because skeleton scoring is dedupe-only, no quality).
        ctx["avoid_expressions"] = self._recent_fingerprints(tag, limit=30)

        # Mode-specific add-ons that the curator does not own.
        if mode == "review_failure":
            ctx["failure_patterns"] = curated.get("failure_patterns", [])
            ctx["mutation_tasks"]   = curated.get("mutation_tasks", [])
            # Keep summary text from the raw file (curator returns just the lists)
            fp_data = self._load_failure_patterns(tag)
            ctx["failure_summary"]  = (fp_data.get("summary") or "")[:1000]

        if mode == "specialize":
            ctx["top_directions"] = self._top_alphas_by_direction(tag, k=3)
            ctx["specialize_rule"] = (
                "Pick ONE of top_directions and produce N variations that PRESERVE its "
                "core data field + neutralization, but vary decay/operator wrapping/"
                "truncation to improve Sharpe or reduce turnover. DO NOT reuse any "
                "expression listed in avoid_expressions verbatim."
            )

        if mode == "track_news":
            ctx["news_rule"] = (
                "Use crawl_summaries above to extract one current theme (earnings season / "
                "macro shock / sector rotation) and craft N alphas that operationalize it."
            )

        # ── Optional doc index (Copilot CLI sub-agent can `view` on demand) ──
        # Best-effort: failures here must not break prompt rendering.
        try:
            from wq_bus.ai.doc_manifest import load_for_mode, render_for_prompt
            doc_entries = load_for_mode(mode, dataset_tag=tag)
            ctx["available_docs"] = render_for_prompt(doc_entries)
        except Exception as e:
            self.log.debug("doc_manifest load failed: %s", e)
            ctx["available_docs"] = ""

        return ctx
