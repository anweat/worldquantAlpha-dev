"""doc_summarizer agent — multi-mode AI summarisation dispatcher.

Modes
-----
crawl_summary   (was 'batch') — triggered by DOC_FETCHED
recipe_synthesis              — triggered by RECIPE_CANDIDATES_READY
failure_synthesis             — triggered by FAILURE_BATCH_READY
portfolio_review              — triggered by POOL_STATS_UPDATED

Self-loop OFF (B10 must still pass):
  on_doc_fetched MUST NOT re-emit DOC_FETCHED.
  Use `wqbus drain-docs --max-batches N` for manual batch draining.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import ClassVar

from wq_bus.agents.base import AgentBase
from wq_bus.bus.events import (
    Event, Topic, make_event,
    RECIPE_CANDIDATES_READY, FAILURE_BATCH_READY, POOL_STATS_UPDATED,
)
from wq_bus.data import knowledge_db
from wq_bus.utils.yaml_loader import load_yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEMORY_DIR = PROJECT_ROOT / "memory"


def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class DocSummarizer(AgentBase):
    AGENT_TYPE = "doc_summarizer"
    SUBSCRIPTIONS = [
        Topic.DOC_FETCHED,
        RECIPE_CANDIDATES_READY,
        FAILURE_BATCH_READY,
        POOL_STATS_UPDATED,
    ]

    name:            ClassVar[str] = "doc_summarizer"
    subscribes:      ClassVar[list] = [
        "DOC_FETCHED",
        "RECIPE_CANDIDATES_READY",
        "FAILURE_BATCH_READY",
        "POOL_STATS_UPDATED",
    ]
    modes:           ClassVar[list] = [
        "crawl_summary",
        "recipe_synthesis",
        "failure_synthesis",
        "portfolio_review",
    ]
    workspace_rules: ClassVar[dict] = {
        "reads":  [],
        "writes": ["memory/<TAG>/failure_patterns.json", "memory/<TAG>/portfolio_analysis.json"],
        "memory_files": [],
    }
    billing_hint:    ClassVar[str] = "per_call"

    def __init__(self, bus, dispatcher) -> None:
        super().__init__(bus, dispatcher)
        crawl = load_yaml("crawl_targets")
        self.batch_threshold = int(crawl.get("summarize_threshold", 5))

    # ------------------------------------------------------------------
    # Mode: crawl_summary (existing behaviour preserved)
    # ------------------------------------------------------------------

    async def on_doc_fetched(self, event: Event) -> None:
        """Batch pending crawl_docs and ask AI to summarise them.

        Self-loop removed: MUST NOT re-emit DOC_FETCHED from here (B10).

        Idle-flush: if pending docs sit below the batch_threshold but the
        oldest one is older than ``crawl_targets.idle_flush_secs`` (default
        900s), flush the partial batch so tail items don't stall forever.
        """
        tag = event.dataset_tag
        pending = knowledge_db.list_pending_docs(limit=self.batch_threshold * 2)
        if not pending:
            return
        if len(pending) < self.batch_threshold:
            # Idle-flush escape: only proceed if oldest pending is stale.
            try:
                from wq_bus.utils.yaml_loader import load_yaml
                idle_secs = float(load_yaml("crawl_targets").get("idle_flush_secs", 900))
            except Exception:
                idle_secs = 900.0
            oldest = min((d.get("fetched_at") or 0.0) for d in pending) if pending else 0.0
            import time as _t
            if oldest <= 0 or (_t.time() - float(oldest)) < idle_secs:
                return  # not stale yet
            self.log.info("doc_summarizer: idle-flushing %d sub-threshold docs (oldest age >= %.0fs)",
                          len(pending), idle_secs)

        batch = pending[: self.batch_threshold]
        payload = {
            "docs": [
                {
                    "url_hash": d["url_hash"],
                    "source":   d["source"],
                    "title":    d["title"],
                    "body":     (d["body_md"] or "")[:6000],
                }
                for d in batch
            ],
            "mode": "crawl_summary",
        }
        try:
            result = await self.call_ai(payload, force_immediate=True)
        except Exception as e:
            self.log.exception("doc_summarizer[crawl_summary] AI failed: %s", e)
            return

        summary = (result or {}).get("summary_md", "")
        if not summary:
            return
        url_hashes = [d["url_hash"] for d in batch]
        knowledge_db.add_summary(
            scope=f"batch_{len(batch)}",
            summary_md=summary,
            doc_ids=url_hashes,
        )
        knowledge_db.mark_docs_summarized(url_hashes, status="summarized")
        self.bus.emit(make_event(
            Topic.KNOWLEDGE_UPDATED, tag,
            n_docs=len(batch),
            summary_preview=summary[:300],
        ))
        # NOTE: self-loop removed — no re-emit of DOC_FETCHED here.

    # ------------------------------------------------------------------
    # Mode: recipe_synthesis
    # ------------------------------------------------------------------

    async def on_recipe_candidates_ready(self, event: Event) -> None:
        tag = event.dataset_tag
        out_path_str = event.payload.get("out_path", "")
        n_groups     = event.payload.get("n_groups", 0)

        if not out_path_str or not n_groups:
            return

        try:
            candidates = json.loads(Path(out_path_str).read_text(encoding="utf-8"))
        except Exception as e:
            self.log.warning("recipe_synthesis: could not read candidates file: %s", e)
            return

        payload = {
            "mode":            "recipe_synthesis",
            "dataset_tag":     tag,
            "candidate_groups": candidates[:30],  # cap context size
        }
        try:
            result = await self.call_ai(payload, force_immediate=True)
        except Exception as e:
            self.log.exception("doc_summarizer[recipe_synthesis] AI failed: %s", e)
            return

        recipes = (result or {}).get("recipes", [])
        if not recipes:
            self.log.info("recipe_synthesis: AI returned no new recipes")
            return

        self._insert_proposed_recipes(recipes, tag)
        self.log.info("recipe_synthesis: proposed %d new recipes for %s", len(recipes), tag)

    def _insert_proposed_recipes(self, recipes: list[dict], tag: str) -> None:
        import time
        from wq_bus.data._sqlite import open_knowledge
        ts = _utcnow_iso()
        with open_knowledge() as conn:
            for r in recipes:
                rid = r.get("recipe_id") or _make_recipe_id(r.get("semantic_name", ""))
                if not rid:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO composition_recipes
                       (recipe_id, semantic_name, pattern_regex, theme_tags,
                        example_expressions, origin, enabled,
                        status, proposed_by, proposed_at,
                        created_at, updated_at,
                        sample_alpha_ids_json, notes)
                       VALUES (?,?,?,?,?,?,1, 'proposed','ai:doc_summarizer',?,?,?,?,?)""",
                    (
                        rid,
                        r.get("semantic_name", rid),
                        r.get("pattern_regex"),
                        ",".join(r.get("theme_tags", [])) if isinstance(r.get("theme_tags"), list)
                            else (r.get("theme_tags") or ""),
                        json.dumps(r.get("sample_alpha_ids", [])),
                        "llm_proposed",
                        ts, ts, ts,
                        json.dumps(r.get("sample_alpha_ids", [])),
                        r.get("economic_hypothesis", ""),
                    ),
                )
        self.bus.emit(make_event(
            "RECIPE_PROPOSED", tag,
            n_proposed=len(recipes),
        ))

    # ------------------------------------------------------------------
    # Mode: failure_synthesis
    # ------------------------------------------------------------------

    async def on_failure_batch_ready(self, event: Event) -> None:
        tag = event.dataset_tag
        from wq_bus.data._sqlite import open_knowledge
        from wq_bus.utils.tag_context import with_tag

        with with_tag(tag):
            with open_knowledge() as conn:
                rows = conn.execute(
                    """SELECT alpha_id, expression, status, sharpe, fitness, turnover,
                              is_metrics_json, themes_csv
                       FROM alphas
                       WHERE dataset_tag=?
                         AND status IN ('simulated','is_passed')
                         AND (sharpe IS NULL OR sharpe < 1.25
                              OR fitness IS NULL OR fitness < 1.0
                              OR turnover > 0.7 OR turnover < 0.01)
                       ORDER BY updated_at DESC LIMIT 50""",
                    (tag,),
                ).fetchall()

        failures = [dict(r) for r in rows]
        if not failures:
            return

        # Split near-miss (sharpe>=0.8) vs hard failures so AI can prioritise.
        def _sh(f: dict) -> float:
            try:
                return float(f.get("sharpe") or 0.0)
            except Exception:
                return 0.0

        near = sorted([f for f in failures if _sh(f) >= 0.8], key=_sh, reverse=True)[:15]
        near_ids = {f.get("alpha_id") for f in near}
        hard = [f for f in failures if f.get("alpha_id") not in near_ids][:30]

        def _row(f: dict) -> dict:
            return {
                "alpha_id":   f.get("alpha_id"),
                "expression": (f.get("expression") or "")[:200],
                "sharpe":     f.get("sharpe"),
                "fitness":    f.get("fitness"),
                "turnover":   f.get("turnover"),
            }

        prior = self._load_prior_failure_patterns(tag)

        payload = {
            "mode":          "failure_synthesis",
            "dataset_tag":   tag,
            "failures":      [_row(f) for f in hard],
            "near_miss":     [_row(f) for f in near],
            "prior_patterns": prior,
        }
        try:
            result = await self.call_ai(payload, force_immediate=True)
        except Exception as e:
            self.log.exception("doc_summarizer[failure_synthesis] AI failed: %s", e)
            return

        patterns       = (result or {}).get("patterns", [])
        mutation_tasks = (result or {}).get("mutation_tasks", [])
        output = {"patterns": patterns, "mutation_tasks": mutation_tasks}

        out_path = MEMORY_DIR / tag / "failure_patterns.json"
        _atomic_write(out_path, output)
        self.log.info("failure_synthesis: wrote %d patterns + %d mutation_tasks → %s",
                      len(patterns), len(mutation_tasks), out_path)
        # Emit LEARNING_DRAFTED for parity with failure_analyzer (downstream
        # consumers can listen to one topic regardless of which agent ran).
        self.bus.emit(make_event(
            Topic.LEARNING_DRAFTED, tag,
            kind="failure_pattern",
            source="doc_summarizer.failure_synthesis",
            n_patterns=len(patterns),
            mutation_count=len(mutation_tasks),
        ))

    def _load_prior_failure_patterns(self, tag: str) -> dict:
        """Load prior memory/<TAG>/failure_patterns.json for AI continuity."""
        fp = MEMORY_DIR / tag / "failure_patterns.json"
        if not fp.exists():
            return {}
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {
            "patterns":       (data.get("patterns") or [])[:5],
            "mutation_tasks": (data.get("mutation_tasks") or [])[:5],
        }

    # ------------------------------------------------------------------
    # Mode: portfolio_review
    # ------------------------------------------------------------------

    async def on_pool_stats_updated(self, event: Event) -> None:
        tag = event.dataset_tag
        from wq_bus.data._sqlite import open_knowledge
        from wq_bus.utils.tag_context import with_tag

        with with_tag(tag):
            with open_knowledge() as conn:
                passing = conn.execute(
                    """SELECT alpha_id, expression, sharpe, fitness, turnover,
                              direction_id, themes_csv
                       FROM alphas
                       WHERE dataset_tag=? AND status IN ('is_passed','submitted')
                       ORDER BY sharpe DESC LIMIT 100""",
                    (tag,),
                ).fetchall()
                all_dirs = conn.execute(
                    """SELECT direction_id, COUNT(*) AS cnt
                       FROM alphas WHERE dataset_tag=? AND status!='legacy'
                       GROUP BY direction_id ORDER BY cnt DESC""",
                    (tag,),
                ).fetchall()

        pool_summary = {
            "passing_count": len(passing),
            "direction_histogram": [dict(r) for r in all_dirs[:40]],
        }

        # T3-A dim 5: cross-alpha correlation context (top high-corr pairs)
        corr_summary = self._build_corr_summary(tag)

        payload = {
            "mode":            "portfolio_review",
            "dataset_tag":     tag,
            "pool_summary":    pool_summary,
            "passing_alphas":  [dict(r) for r in passing[:20]],
            "corr_summary":    corr_summary,
        }
        try:
            result = await self.call_ai(payload, force_immediate=True)
        except Exception as e:
            self.log.exception("doc_summarizer[portfolio_review] AI failed: %s", e)
            return

        overcrowded = (result or {}).get("overcrowded_directions", [])
        gap_dirs    = (result or {}).get("gap_directions", [])
        suggestions = (result or {}).get("suggestions", [])
        output = {
            "overcrowded_directions": overcrowded,
            "gap_directions":         gap_dirs,
            "suggestions":            suggestions,
        }

        out_path = MEMORY_DIR / tag / "portfolio_analysis.json"
        _atomic_write(out_path, output)
        self.log.info("portfolio_review: wrote overcrowded=%d gap=%d → %s",
                      len(overcrowded), len(gap_dirs), out_path)
        # Emit PORTFOLIO_ANALYZED so the portfolio_review trace_kind closes.
        # (TERMINAL_TOPICS_BY_KIND['portfolio_review'] = {'PORTFOLIO_ANALYZED'})
        self.bus.emit(make_event(
            Topic.PORTFOLIO_ANALYZED, tag,
            source="doc_summarizer.portfolio_review",
            n_overcrowded=len(overcrowded),
            n_gap=len(gap_dirs),
            n_suggestions=len(suggestions),
        ))


    def _build_corr_summary(self, tag: str) -> dict:
        """Compact PnL-correlation summary (T3-A dim 5).

        Sources `pnl_corr` rows produced by portfolio_analyzer.compute_pairwise_corr.
        Returns the top-N highest |pearson| pairs above 0.7 plus quick count
        buckets so the AI can spot crowded clusters without a full matrix dump.
        """
        try:
            from wq_bus.utils.tag_context import with_tag
            from wq_bus.data import knowledge_db
            with with_tag(tag):
                pairs_high = knowledge_db.list_pnl_corr(threshold=0.7)
                pairs_med  = knowledge_db.list_pnl_corr(threshold=0.5)
            top = []
            for r in pairs_high[:10]:
                top.append({
                    "a":       r.get("alpha_a"),
                    "b":       r.get("alpha_b"),
                    "pearson": round(float(r.get("pearson") or 0.0), 3),
                    "n":       r.get("n_overlap"),
                })
            return {
                "n_high_corr_07": len(pairs_high),
                "n_med_corr_05":  len(pairs_med),
                "top_pairs":      top,
            }
        except Exception as e:
            self.log.debug("corr_summary failed for %s: %s", tag, e)
            return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_recipe_id(semantic_name: str) -> str:
    import hashlib
    slug = re.sub(r"[^a-z0-9]+", "_", semantic_name.lower()).strip("_")[:32]
    suffix = hashlib.sha1(semantic_name.encode()).hexdigest()[:6]
    return f"ai_{slug}_{suffix}"


import re  # noqa: E402 — placed after class to avoid import at module top
