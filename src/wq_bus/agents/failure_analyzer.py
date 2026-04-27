"""failure_analyzer agent — summarizes a batch's failures into learnings.

Listens: BATCH_DONE
Emits:   LEARNING_DRAFTED
Writes:  memory/{tag}/failure_patterns.json
"""
from __future__ import annotations

import json
from pathlib import Path

from wq_bus.agents.base import AgentBase
from wq_bus.bus.events import Event, Topic, make_event
from wq_bus.data import knowledge_db

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEMORY_DIR = PROJECT_ROOT / "memory"


class FailureAnalyzer(AgentBase):
    AGENT_TYPE = "failure_analyzer"
    SUBSCRIPTIONS = [Topic.BATCH_DONE]

    async def on_batch_done(self, event: Event) -> None:
        tag = event.dataset_tag
        # Dataset filtering is automatic: list_alphas uses require_tag() and
        # event_bus wraps the handler in with_tag(event.dataset_tag).
        all_alphas = knowledge_db.list_alphas(limit=300)
        failed = [a for a in all_alphas
                  if a["status"] not in ("submitted", "is_passed", "sc_passed")]
        if not failed:
            self.log.info("batch_done: no failures to analyze for %s", tag)
            return

        # Split: near-miss (sharpe>=0.8 but didn't pass) vs hard failures.
        def _sharpe(a: dict) -> float:
            try:
                return float(a.get("sharpe") or 0.0)
            except Exception:
                return 0.0

        near_miss = sorted(
            [a for a in failed if _sharpe(a) >= 0.8],
            key=_sharpe, reverse=True,
        )[:20]
        near_ids = {a["alpha_id"] for a in near_miss}
        hard_failures = [a for a in failed if a["alpha_id"] not in near_ids][:30]

        def _row(a: dict) -> dict:
            return {
                "expr": a["expression"][:200],
                "sharpe": a.get("sharpe"),
                "fitness": a.get("fitness"),
                "turnover": a.get("turnover"),
                "status": a["status"],
            }

        # Pull supporting context: prior summarised patterns (continuity),
        # passing alphas in same dataset (positive comparison set per T3-A
        # dim 1), and pool direction summary so AI can spot direction-level
        # blind spots.
        prior_patterns = self._load_prior_patterns(tag)
        passing_top = self._top_passing(all_alphas)
        pool_summary = self._pool_summary(tag)

        payload = {
            "dataset_tag": tag,
            "n_total": event.payload.get("n_total"),
            "n_is_passed": event.payload.get("n_is_passed"),
            "failures": [_row(a) for a in hard_failures],
            "near_miss": [_row(a) for a in near_miss],
            "prior_patterns": prior_patterns,
            "passing_top": passing_top,
            "pool_summary": pool_summary,
        }
        try:
            result = await self.call_ai(payload, force_immediate=True)
        except Exception as e:  # noqa: BLE001
            self.log.exception("failure_analyzer AI call failed: %s", e)
            return

        summary = (result or {}).get("summary", "")
        if not isinstance(summary, str):
            summary = json.dumps(summary, ensure_ascii=False) if summary else ""
        patterns = (result or {}).get("patterns", [])
        mutation_tasks = (result or {}).get("mutation_tasks", [])

        # Persist
        knowledge_db.add_learning("failure_pattern", summary,
                                  payload={"patterns": patterns, "mutation_tasks": mutation_tasks})
        out_dir = MEMORY_DIR / tag
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "failure_patterns.json").write_text(
            json.dumps({"summary": summary, "patterns": patterns,
                        "mutation_tasks": mutation_tasks}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.bus.emit(make_event(Topic.LEARNING_DRAFTED, tag,
                                 kind="failure_pattern",
                                 summary=summary[:300],
                                 mutation_count=len(mutation_tasks)))

    # ------------------------------------------------------------------
    # context helpers
    # ------------------------------------------------------------------
    def _load_prior_patterns(self, tag: str) -> dict:
        """Load previously synthesised failure_patterns.json, if any."""
        f = MEMORY_DIR / tag / "failure_patterns.json"
        if not f.exists():
            return {}
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {
            "summary": (data.get("summary") or "")[:500],
            "patterns": (data.get("patterns") or [])[:5],
            "mutation_tasks": (data.get("mutation_tasks") or [])[:5],
        }

    def _top_passing(self, all_alphas: list[dict]) -> list[dict]:
        """Top 5 IS-passed alphas to give AI a positive comparison set."""
        passed = [a for a in all_alphas
                  if a.get("status") in ("submitted", "is_passed", "sc_passed")]

        def _sh(a: dict) -> float:
            try:
                return float(a.get("sharpe") or 0.0)
            except Exception:
                return 0.0

        passed.sort(key=_sh, reverse=True)
        return [
            {
                "expr": a["expression"][:200],
                "sharpe": a.get("sharpe"),
                "fitness": a.get("fitness"),
                "turnover": a.get("turnover"),
                "direction_id": a.get("direction_id"),
            }
            for a in passed[:5]
        ]

    def _pool_summary(self, tag: str) -> dict:
        """Compact pool stats for AI: total_directions + pass-rate hint."""
        try:
            from wq_bus.data._sqlite import open_knowledge
            with open_knowledge() as con:
                row_dirs = con.execute(
                    "SELECT COUNT(DISTINCT direction_id) FROM alphas "
                    "WHERE dataset_tag = ? AND direction_id IS NOT NULL",
                    (tag,),
                ).fetchone()
                row_total = con.execute(
                    "SELECT COUNT(*), "
                    "SUM(CASE WHEN status IN ('submitted','is_passed','sc_passed') "
                    "THEN 1 ELSE 0 END) FROM alphas WHERE dataset_tag = ?",
                    (tag,),
                ).fetchone()
            total_dirs = row_dirs[0] if row_dirs else 0
            total = row_total[0] if row_total else 0
            passed = row_total[1] if row_total else 0
            return {
                "total_directions": int(total_dirs or 0),
                "total_alphas": int(total or 0),
                "passed_alphas": int(passed or 0),
                "pass_rate": round((passed / total), 3) if total else 0.0,
            }
        except Exception as e:
            self.log.debug("pool_summary failed for %s: %s", tag, e)
            return {}
