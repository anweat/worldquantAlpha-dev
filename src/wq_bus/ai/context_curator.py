"""ContextCurator (rev-h7) — score → diversify → cap. No AI calls.

Why this exists
---------------
Before this module, every agent that needed prompt context would read its
memory files, slice arbitrary head/tails (``[:5]``, ``[:300]``), and shove the
result into the AI payload. That meant:

* Stale items kept being fed back forever (no recency weighting).
* Same-direction alphas dominated the ``top_submitted`` slot (no diversity).
* No global token discipline — long ``crawl_summaries`` could blow the context.

ContextCurator centralises the "pick the most useful items that fit" step:

1. **Collect candidates** from ``knowledge_db`` (alphas / learnings / summaries
   / recipes) and ``memory/<TAG>/*`` (failure_patterns, portfolio_analysis,
   insights.md).
2. **Score** each candidate on (recency, sharpe-like quality, mode-relevance).
3. **Diversify** within each section (max-N per ``theme`` then round-robin).
4. **Cap** the *total* prompt size by char-budget. The budget is per-adapter:

   * ``billing_mode=per_token`` adapters → cap at ``token_cap`` (default 20000
     tokens ≈ 80000 chars).
   * ``billing_mode=per_call`` adapters → no hard cap (their cost is per call,
     so larger context is essentially free).

The output dict preserves the legacy keys each agent already reads, so wiring
is a one-line swap.

Usage
-----
    ctx = CuratedContext(agent_type="alpha_gen", mode="explore", tag=tag).build()
    payload["context"] = ctx
    await self.call_ai(payload)
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from wq_bus.utils.paths import MEMORY_DIR
from wq_bus.utils.yaml_loader import load_yaml
from wq_bus.utils.timeutil import utcnow_ts

# How many chars per token we assume (conservative; GPT/Claude both ~3.5-4).
_CHARS_PER_TOKEN = 4
# Default token cap if config is missing AND adapter is per_token.
_DEFAULT_TOKEN_CAP = 20_000
# Per-section soft caps before global trim. Tuned for typical alpha_gen prompt.
_SECTION_CAPS = {
    "top_submitted":          8,
    "recent_learnings":       6,
    "crawl_summaries":        3,
    "failure_patterns":       8,
    "mutation_tasks":         8,
    "near_miss":             10,
    "hard_failures":         15,
    "passing_top":            8,
    "recipe_hints":           6,
    "gap_directions":         6,
    "overcrowded_directions": 6,
    "pool_summary":           5,
    "prior_patterns":         5,
}


@dataclass
class _Candidate:
    """One item competing for a context slot."""
    section: str        # which key it ends up under
    payload: Any        # the actual value (dict/str)
    score: float        # 0..1, higher = keep
    theme: str = ""     # for dedup; "" = no dedup
    chars: int = 0      # used for budget accounting

    def __post_init__(self) -> None:
        if not self.chars:
            try:
                self.chars = len(json.dumps(self.payload, ensure_ascii=False, default=str))
            except Exception:
                self.chars = len(str(self.payload))


# ---------------------------------------------------------------------------
# Budget resolution (depends on dispatcher's adapter routing)
# ---------------------------------------------------------------------------

def _resolve_char_cap(agent_type: str) -> int | None:
    """Return char cap for ``agent_type``'s adapter, or ``None`` for unlimited.

    Reads ``config/agent_profiles.yaml``:
      * adapters.<name>.billing_mode  (per_call | per_token)
      * agents.<agent_type>.provider  (which adapter the agent uses)

    Override knob: ``context.token_cap`` in ``agent_profiles.yaml`` if present
    (otherwise default 20000).
    """
    try:
        profiles = load_yaml("agent_profiles") or {}
    except Exception:
        return _DEFAULT_TOKEN_CAP * _CHARS_PER_TOKEN

    agent_cfg = (profiles.get("agents") or {}).get(agent_type, {})
    provider = agent_cfg.get("provider") or (profiles.get("defaults") or {}).get("provider", "copilot")
    adapter_name = "copilot_cli" if provider == "copilot" else provider
    adapter = (profiles.get("adapters") or {}).get(adapter_name) or {}
    billing = adapter.get("billing_mode", "per_call")

    if billing == "per_call":
        return None  # cost is per call, no benefit to trimming

    token_cap = (
        (profiles.get("context") or {}).get("token_cap")
        or _DEFAULT_TOKEN_CAP
    )
    return int(token_cap) * _CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# Curator
# ---------------------------------------------------------------------------

class CuratedContext:
    """Build a scored + capped prompt context for one agent invocation."""

    def __init__(self, *, agent_type: str, mode: str, tag: str) -> None:
        self.agent_type = agent_type
        self.mode = mode
        self.tag = tag
        self._char_cap = _resolve_char_cap(agent_type)
        self._now_ts = utcnow_ts()
        self._meta: dict[str, Any] = {
            "agent": agent_type,
            "mode": mode,
            "char_cap": self._char_cap,
            "trimmed_sections": [],
        }

    # ---- public entrypoints -------------------------------------------

    def build(self) -> dict[str, Any]:
        """Return the curated context dict. Section keys match legacy agents."""
        sections: dict[str, list[_Candidate]] = {}

        if self.agent_type == "alpha_gen":
            sections.update(self._sections_for_alpha_gen())
        elif self.agent_type == "failure_analyzer":
            sections.update(self._sections_for_failure_analyzer())
        elif self.agent_type in ("doc_summarizer", "doc_summarizer.failure_synthesis"):
            sections.update(self._sections_for_failure_synthesis())
        else:
            # Unknown agent: return only the universal sections (top alphas +
            # learnings) so callers aren't broken by missing key.
            sections.update(self._sections_universal())

        # Apply per-section soft caps (already partly done by selectors via
        # _SECTION_CAPS, but enforce here too as a safety net).
        for name, items in list(sections.items()):
            cap = _SECTION_CAPS.get(name)
            if cap and len(items) > cap:
                items.sort(key=lambda c: c.score, reverse=True)
                sections[name] = items[:cap]
                self._meta["trimmed_sections"].append(f"{name}:soft({cap})")

        # Apply global char-budget trim if adapter bills per token.
        if self._char_cap is not None:
            self._enforce_budget(sections, self._char_cap)

        out: dict[str, Any] = {"_curator_meta": self._meta}
        for name, items in sections.items():
            out[name] = [c.payload for c in items]
        return out

    # ---- alpha_gen ----------------------------------------------------

    def _sections_for_alpha_gen(self) -> dict[str, list[_Candidate]]:
        s: dict[str, list[_Candidate]] = {}
        s.update(self._sections_universal())
        s["recipe_hints"]    = self._select_recipe_hints()
        s["gap_directions"], s["overcrowded_directions"], s["portfolio_suggestions"] = (
            self._select_portfolio()
        )
        s["pool_summary"]    = self._select_pool_summary()

        if self.mode == "review_failure":
            patterns, mutations = self._select_failure_patterns()
            s["failure_patterns"] = patterns
            s["mutation_tasks"]   = mutations
        return s

    # ---- failure_analyzer / doc_summarizer.failure_synthesis ---------

    def _sections_for_failure_analyzer(self) -> dict[str, list[_Candidate]]:
        s: dict[str, list[_Candidate]] = {}
        s["near_miss"], s["hard_failures"] = self._select_split_failures()
        s["passing_top"]      = self._select_passing_top()
        prior_patterns, prior_mutations = self._select_failure_patterns()
        s["prior_patterns"]   = prior_patterns
        s["pool_summary"]     = self._select_pool_summary()
        return s

    def _sections_for_failure_synthesis(self) -> dict[str, list[_Candidate]]:
        s: dict[str, list[_Candidate]] = {}
        s["near_miss"], s["hard_failures"] = self._select_split_failures()
        prior_patterns, prior_mutations = self._select_failure_patterns()
        s["prior_patterns"]   = prior_patterns
        return s

    # ---- shared selectors --------------------------------------------

    def _sections_universal(self) -> dict[str, list[_Candidate]]:
        return {
            "top_submitted":     self._select_top_submitted(),
            "recent_learnings":  self._select_recent_learnings(),
            "crawl_summaries":   self._select_crawl_summaries(),
            "insights":          self._select_insights(),
        }

    def _select_top_submitted(self) -> list[_Candidate]:
        from wq_bus.data import knowledge_db
        try:
            rows = knowledge_db.list_alphas(status="submitted", limit=30) or []
        except Exception:
            return []
        cands: list[_Candidate] = []
        for a in rows:
            sharpe = _safe_float(a.get("sharpe"))
            fitness = _safe_float(a.get("fitness"))
            quality = max(0.0, min(1.0, (sharpe or 0) / 4.0))     # sharpe~4 -> 1.0
            quality = 0.7 * quality + 0.3 * max(0.0, min(1.0, (fitness or 0) / 2.0))
            recency = self._recency_score(a.get("updated_at"))
            score = 0.6 * quality + 0.4 * recency
            theme = _theme_from_alpha(a)
            cands.append(_Candidate(
                section="top_submitted",
                payload={"expr": (a.get("expression") or "")[:120],
                         "sharpe": sharpe, "fitness": fitness},
                score=score, theme=theme,
            ))
        return self._dedupe_by_theme(cands, max_per_theme=2, cap=_SECTION_CAPS["top_submitted"])

    def _select_recent_learnings(self) -> list[_Candidate]:
        from wq_bus.data import knowledge_db
        try:
            rows = knowledge_db.recent_learnings(limit=30) or []
        except Exception:
            return []
        cands: list[_Candidate] = []
        for l in rows:
            recency = self._recency_score(l.get("ts") or l.get("updated_at"))
            kind_boost = 1.0 if (self.mode == "review_failure" and l.get("kind") == "failure_pattern") else 0.5
            score = 0.5 * recency + 0.5 * kind_boost
            cands.append(_Candidate(
                section="recent_learnings",
                payload={"kind": l.get("kind"), "content": (l.get("content") or "")[:300]},
                score=score, theme=l.get("kind", ""),
            ))
        return self._dedupe_by_theme(cands, max_per_theme=3, cap=_SECTION_CAPS["recent_learnings"])

    def _select_crawl_summaries(self) -> list[_Candidate]:
        from wq_bus.data import knowledge_db
        try:
            rows = knowledge_db.recent_summaries(limit=10) or []
        except Exception:
            return []
        cands: list[_Candidate] = []
        for s in rows:
            txt = (s.get("summary_md") or "")[:500]
            recency = self._recency_score(s.get("ts") or s.get("updated_at"))
            cands.append(_Candidate(
                section="crawl_summaries", payload=txt, score=recency,
                theme=(s.get("source") or "")[:40],
            ))
        return self._dedupe_by_theme(cands, max_per_theme=1, cap=_SECTION_CAPS["crawl_summaries"])

    def _select_insights(self) -> list[_Candidate]:
        path = MEMORY_DIR / self.tag / "insights.md"
        if not path.exists():
            return []
        try:
            txt = path.read_text(encoding="utf-8")[:2000]
        except Exception:
            return []
        return [_Candidate(section="insights", payload=txt, score=1.0)]

    def _select_recipe_hints(self) -> list[_Candidate]:
        try:
            from wq_bus.domain import recipes as _recipes
            rows = _recipes.list_recipes(status="approved") or []
        except Exception:
            return []
        cands: list[_Candidate] = []
        for r in rows:
            theme = ",".join(r.get("theme_tags", [])) if isinstance(r.get("theme_tags"), list) else (r.get("theme_tags") or "")
            cands.append(_Candidate(
                section="recipe_hints",
                payload={"name": r.get("semantic_name") or r.get("name"),
                         "theme": theme[:80],
                         "hypothesis": (r.get("economic_hypothesis") or "")[:240]},
                score=0.5 + 0.5 * self._recency_score(r.get("updated_at")),
                theme=theme.split(",")[0] if theme else "",
            ))
        return self._dedupe_by_theme(cands, max_per_theme=2, cap=_SECTION_CAPS["recipe_hints"])

    def _select_portfolio(self) -> tuple[list[_Candidate], list[_Candidate], list[_Candidate]]:
        path = MEMORY_DIR / self.tag / "portfolio_analysis.json"
        if not path.exists():
            return [], [], []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return [], [], []
        gap = [_Candidate("gap_directions", g, 1.0) for g in (data.get("gap_directions") or [])[:_SECTION_CAPS["gap_directions"]]]
        over = [_Candidate("overcrowded_directions", o, 1.0) for o in (data.get("overcrowded_directions") or [])[:_SECTION_CAPS["overcrowded_directions"]]]
        sugg = [_Candidate("portfolio_suggestions", str(s)[:240], 1.0) for s in (data.get("suggestions") or [])[:6]]
        return gap, over, sugg

    def _select_pool_summary(self) -> list[_Candidate]:
        try:
            from wq_bus.data import workspace
            rows = workspace.list_directions(self.tag, limit=20) or []
        except Exception:
            return []
        cands = [_Candidate("pool_summary", r, 1.0,
                            theme=str(r.get("direction") if isinstance(r, dict) else r)[:40])
                 for r in rows]
        return self._dedupe_by_theme(cands, max_per_theme=1, cap=_SECTION_CAPS["pool_summary"])

    def _select_failure_patterns(self) -> tuple[list[_Candidate], list[_Candidate]]:
        path = MEMORY_DIR / self.tag / "failure_patterns.json"
        if not path.exists():
            return [], []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return [], []
        patterns = (data.get("patterns") or [])[:_SECTION_CAPS["failure_patterns"]]
        mutations = (data.get("mutation_tasks") or [])[:_SECTION_CAPS["mutation_tasks"]]
        p_cands = [_Candidate("failure_patterns", p, 1.0,
                              theme=str(p.get("kind") if isinstance(p, dict) else p)[:40])
                   for p in patterns]
        m_cands = [_Candidate("mutation_tasks", m, 1.0) for m in mutations]
        return p_cands, m_cands

    def _select_split_failures(self) -> tuple[list[_Candidate], list[_Candidate]]:
        from wq_bus.data import knowledge_db
        try:
            all_alphas = knowledge_db.list_alphas(limit=300) or []
        except Exception:
            return [], []
        failed = [a for a in all_alphas
                  if a.get("status") not in ("submitted", "is_passed", "sc_passed")]
        near_raw = sorted([a for a in failed if (_safe_float(a.get("sharpe")) or 0) >= 0.8],
                          key=lambda a: _safe_float(a.get("sharpe")) or 0, reverse=True)[:_SECTION_CAPS["near_miss"]]
        near_ids = {a.get("alpha_id") for a in near_raw}
        hard_raw = [a for a in failed if a.get("alpha_id") not in near_ids][:_SECTION_CAPS["hard_failures"]]
        near = [_Candidate("near_miss", _failure_row(a),
                           score=_safe_float(a.get("sharpe")) or 0,
                           theme=_theme_from_alpha(a))
                for a in near_raw]
        hard = [_Candidate("hard_failures", _failure_row(a),
                           score=self._recency_score(a.get("updated_at")),
                           theme=_theme_from_alpha(a))
                for a in hard_raw]
        # Diversify hard failures so one ugly direction doesn't crowd out
        # learnings about other directions.
        hard = self._dedupe_by_theme(hard, max_per_theme=4, cap=_SECTION_CAPS["hard_failures"])
        return near, hard

    def _select_passing_top(self) -> list[_Candidate]:
        from wq_bus.data import knowledge_db
        try:
            rows = knowledge_db.list_alphas(status="submitted", limit=20) or []
        except Exception:
            return []
        cands = [_Candidate("passing_top",
                            {"expr": (a.get("expression") or "")[:160],
                             "sharpe": _safe_float(a.get("sharpe"))},
                            score=_safe_float(a.get("sharpe")) or 0,
                            theme=_theme_from_alpha(a))
                 for a in rows]
        return self._dedupe_by_theme(cands, max_per_theme=1, cap=_SECTION_CAPS["passing_top"])

    # ---- helpers ------------------------------------------------------

    def _recency_score(self, ts: Any) -> float:
        """Map an epoch (or None) to a 0..1 recency score with 7-day half life."""
        if ts is None:
            return 0.3
        try:
            t = float(ts)
        except Exception:
            return 0.3
        if t > 1e12:  # ms
            t /= 1000.0
        age_days = max(0.0, (self._now_ts - t) / 86400.0)
        # Exponential decay: ~7 day half-life → after 7d score ~0.5, 14d ~0.25.
        return math.exp(-age_days / 10.0)

    def _dedupe_by_theme(self, cands: list[_Candidate], *, max_per_theme: int, cap: int) -> list[_Candidate]:
        cands.sort(key=lambda c: c.score, reverse=True)
        keep: list[_Candidate] = []
        seen: dict[str, int] = {}
        for c in cands:
            k = c.theme or "_no_theme"
            if seen.get(k, 0) >= max_per_theme:
                continue
            keep.append(c)
            seen[k] = seen.get(k, 0) + 1
            if len(keep) >= cap:
                break
        return keep

    def _enforce_budget(self, sections: dict[str, list[_Candidate]], char_cap: int) -> None:
        """Drop lowest-scored items across all sections until total fits cap.

        Sections are protected proportionally — we never drain a section to
        zero while another still has many items above the cut.
        """
        total = sum(c.chars for items in sections.values() for c in items)
        if total <= char_cap:
            return
        # Build a flat list of (section, candidate), sort ascending by score.
        flat: list[tuple[str, _Candidate]] = []
        for name, items in sections.items():
            for c in items:
                flat.append((name, c))
        flat.sort(key=lambda pair: pair[1].score)
        idx = 0
        while total > char_cap and idx < len(flat):
            name, victim = flat[idx]
            section = sections[name]
            # Don't drain a section to zero unless we have to.
            if len(section) > 1 and victim in section:
                section.remove(victim)
                total -= victim.chars
                self._meta["trimmed_sections"].append(f"{name}:budget")
            idx += 1


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


def _theme_from_alpha(a: dict) -> str:
    """Cheap theme key from themes_csv or first 30 chars of expression."""
    t = a.get("themes_csv") or ""
    if t:
        return str(t).split(",")[0][:40]
    return (a.get("expression") or "")[:30]


def _failure_row(a: dict) -> dict:
    return {
        "expr":     (a.get("expression") or "")[:200],
        "sharpe":   _safe_float(a.get("sharpe")),
        "fitness":  _safe_float(a.get("fitness")),
        "turnover": _safe_float(a.get("turnover")),
        "status":   a.get("status"),
    }


__all__ = ["CuratedContext"]
