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

from pathlib import Path
from typing import ClassVar

from wq_bus.agents.base import AgentBase
from wq_bus.analysis.expression_fingerprint import fingerprint, is_duplicate, record
from wq_bus.bus.events import Event, Topic, make_event
from wq_bus.data import knowledge_db
from wq_bus.utils.tag_context import require_tag

PROJECT_ROOT = Path(__file__).resolve().parents[3]
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

        # Build task package — MUST NOT include strength or model
        task_payload = {
            "context": context,
            "hint": hint,
            "n_requested": n,
            "mode": mode,
        }
        # Guard: assert no forbidden fields
        for bad_field in ("strength", "model"):
            assert bad_field not in task_payload, (
                f"alpha_gen MUST NOT write {bad_field!r} in task payload"
            )

        try:
            r = await self.call_ai(task_payload)
        except Exception as e:
            self.log.warning("alpha gen failed mode=%s: %s", mode, e)
            return

        # Accept either {"expressions": [{...}, ...]} or single {"expression": "..."}
        items: list[dict]
        if isinstance(r, dict) and isinstance(r.get("expressions"), list):
            items = r["expressions"]
        elif isinstance(r, dict) and r.get("expression"):
            items = [r]
        else:
            items = []

        n_emitted = 0
        for item in items[:n]:
            expr = (item or {}).get("expression", "").strip()
            if not expr:
                continue
            if is_duplicate(expr):
                self.log.debug("dedup skip: %s", expr[:80])
                continue
            fp_hash, _ = fingerprint(expr)
            record(expr)

            settings_overrides = (item or {}).get("settings_overrides") or {}
            ai_call_id = item.get("_ai_call_id") or r.get("_ai_call_id")

            # --- Dimensions + recipes integration ---
            direction_id, themes_csv = self._classify_and_register(
                expr, settings_overrides, tag, mode, hint
            )

            # Bump pool stats per-alpha against its own direction_id (plan §5.4)
            try:
                from wq_bus.data import workspace
                workspace.bump_stats(tag, direction_id, alphas_tried=1)
            except Exception as e:
                self.log.debug("bump_stats(alphas_tried) failed for %s: %s", direction_id, e)

            self.bus.emit(make_event(Topic.ALPHA_DRAFTED, tag,
                                     expression=expr,
                                     settings=settings_overrides,
                                     fingerprint=fp_hash,
                                     ai_call_id=ai_call_id,
                                     rationale=(item or {}).get("rationale", ""),
                                     direction_id=direction_id,
                                     themes_csv=themes_csv,
                                     mode=mode))
            n_emitted += 1

        self.log.info("alpha_gen emitted %d/%d drafts for %s mode=%s (1 AI call)",
                      n_emitted, n, tag, mode)

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
        """Build prompt context with mode-specific prefix."""
        mode_hint = _MODE_HINTS.get(mode, "")
        learnings = knowledge_db.recent_learnings(limit=10)
        top_alphas = knowledge_db.list_alphas(status="submitted", limit=5)
        summaries = knowledge_db.recent_summaries(limit=3)
        insights_path = MEMORY_DIR / tag / "insights.md"
        insights = insights_path.read_text(encoding="utf-8") if insights_path.exists() else ""

        # Pool context
        pool_summary = []
        try:
            from wq_bus.data import workspace
            pool_summary = workspace.list_directions(tag, limit=10)
        except Exception:
            pass

        # Inject valid datafield ids so AI doesn't hallucinate field names
        valid_fields = _load_valid_fields(tag)

        ctx: dict = {
            "dataset_tag": tag,
            "mode": mode,
            "mode_hint": mode_hint,
            "hint": hint,
            "recent_learnings": [{"kind": l["kind"], "content": l["content"][:300]} for l in learnings],
            "top_submitted": [{"expr": a["expression"][:120],
                               "sharpe": a.get("sharpe"), "fitness": a.get("fitness")}
                              for a in top_alphas],
            "crawl_summaries": [s["summary_md"][:500] for s in summaries],
            "insights_md": insights[:2000],
            "pool_summary": pool_summary[:5],
            "valid_fields": valid_fields,
            "field_rule": (
                "STRICT: Only use field ids from valid_fields. Common WQ price/volume "
                "fields (close, open, high, low, volume, vwap, returns, adv20) and "
                "ts_*/group_*/rank operators are always available. NEVER invent field "
                "names like net_income/equity/cashflow_op — use only listed ids or the "
                "common price/volume set."
            ),
        }

        # ---- Mode-specific context injection ----
        # Universal: avoid recently-tried expression skeletons
        ctx["avoid_expressions"] = self._recent_fingerprints(tag, limit=30)
        # Universal: portfolio insights (gap directions = explore, overcrowded = avoid)
        pa = self._load_portfolio_analysis(tag)
        if pa:
            ctx["gap_directions"] = (pa.get("gap_directions") or [])[:8]
            ctx["overcrowded_directions"] = (pa.get("overcrowded_directions") or [])[:8]
            sugg = pa.get("suggestions") or []
            ctx["portfolio_suggestions"] = [str(s)[:240] for s in sugg[:6]]
        # Universal: approved recipe hints (status='approved' only — proposed never leaks)
        ctx["recipe_hints"] = self._approved_recipe_hints(tag, k=6)

        if mode == "review_failure":
            fp_data = self._load_failure_patterns(tag)
            ctx["failure_patterns"] = (fp_data.get("patterns") or [])[:10]
            ctx["mutation_tasks"] = (fp_data.get("mutation_tasks") or [])[:10]
            ctx["failure_summary"] = (fp_data.get("summary") or "")[:1000]

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

        return ctx
