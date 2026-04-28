"""portfolio_analyzer agent — runs PnL correlation + overfitting heuristics.

Listens: SUBMITTED  (also callable manually via CLI)
Emits:   PORTFOLIO_ANALYZED, optionally LEARNING_DRAFTED
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from wq_bus.agents.base import AgentBase
from wq_bus.analysis.overfitting_signals import analyze as analyze_overfit
from wq_bus.analysis.pnl_correlation import compute_pairwise_corr
from wq_bus.bus.events import Event, Topic, make_event

if TYPE_CHECKING:
    from wq_bus.brain.client import BrainClient

from wq_bus.utils.paths import PROJECT_ROOT  # noqa: E402
MEMORY_DIR = PROJECT_ROOT / "memory"


class PortfolioAnalyzer(AgentBase):
    AGENT_TYPE = "portfolio_analyzer"
    SUBSCRIPTIONS = [Topic.SUBMITTED]

    def __init__(self, bus, brain_client: "BrainClient") -> None:
        super().__init__(bus)
        self.client = brain_client
        self._submitted_since_last_analysis = 0

    async def on_submitted(self, event: Event) -> None:
        self._submitted_since_last_analysis += 1
        if self._submitted_since_last_analysis < 3:
            return
        await self.analyze_now(event.dataset_tag)
        self._submitted_since_last_analysis = 0

    async def analyze_now(self, tag: str, *, recent_n: int | None = None) -> dict:
        """Run pairwise PnL correlation + overfitting heuristics.

        Args:
            tag: dataset tag.
            recent_n: cap analysis to the most recently submitted N alphas.
                Defaults to ``analysis.portfolio_recent_n`` (yaml) or 100.
                Pass 0 to disable the cap (dangerous on large portfolios —
                runtime is O(n²) and each uncached PnL is one HTTP call).
        """
        import asyncio
        # Resolve cap from yaml if not explicitly set
        if recent_n is None:
            try:
                from wq_bus.utils.yaml_loader import load_yaml
                ana = load_yaml("analysis") or {}
                recent_n = int(ana.get("portfolio_recent_n", 100))
            except Exception:
                recent_n = 100
        loop = asyncio.get_running_loop()
        # PnL correlation in executor (network-heavy). Tag context is contextvar-
        # based and does not propagate into thread executors — propagate explicitly.
        from wq_bus.utils.tag_context import with_tag

        def _run_corr():
            with with_tag(tag):
                return compute_pairwise_corr(self.client, 0.7, 100, recent_n)

        try:
            corr_pairs = await loop.run_in_executor(None, _run_corr)
        except TypeError:
            # function may have keyword-only args; fall back to sync direct call
            with with_tag(tag):
                corr_pairs = compute_pairwise_corr(self.client, recent_n=recent_n)
        with with_tag(tag):
            overfit = analyze_overfit()

        out = {"corr_pairs": corr_pairs, "overfit": overfit}
        out_dir = MEMORY_DIR / tag
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "portfolio.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self.bus.emit(make_event(Topic.PORTFOLIO_ANALYZED, tag, **{
            "n_high_corr_pairs": len(corr_pairs),
            "overfit_score": overfit.get("score"),
        }))
        return out
