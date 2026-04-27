"""Rate limiter for AI dispatch — enforces daily and per-round caps."""
from __future__ import annotations

from wq_bus.data.state_db import count_ai_calls_today
from wq_bus.utils.logging import get_logger
from wq_bus.utils.yaml_loader import load_yaml

_log = get_logger(__name__)


class RateLimiter:
    """Enforces daily and per-round caps on AI calls.

    Reads limits from config/ai_dispatch.yaml under ``rate_limits``.
    Per-round counters are in-process only; reset with :meth:`reset_round`.
    Daily caps are enforced by querying the ``ai_calls`` table in state.db.
    """

    def __init__(self) -> None:
        self._round_counts: dict[str, int] = {}
        self._load_config()

    def _load_config(self) -> None:
        cfg = load_yaml("ai_dispatch").get("rate_limits", {})
        self._daily_cap_total: int = int(cfg.get("daily_cap_total", 200))
        self._daily_cap_per_agent: dict[str, int] = {
            k: int(v) for k, v in cfg.get("daily_cap_per_agent", {}).items()
        }
        self._per_round_cap: dict[str, int] = {
            k: int(v) for k, v in cfg.get("per_round_cap_per_agent", {}).items()
        }

    def check_and_reserve(self, agent_type: str) -> bool:
        """Return True if a call for *agent_type* is allowed under all caps.

        Checks (in order):
        1. Global daily cap across all agents.
        2. Per-agent daily cap.
        3. Per-agent per-round cap (in-process counter).

        Does **not** increment any counter — call :meth:`register_call` after a
        successful adapter call.
        """
        try:
            total_today = count_ai_calls_today()
        except Exception as exc:
            _log.warning("Could not query daily call count: %s — allowing call", exc)
            total_today = 0

        if total_today >= self._daily_cap_total:
            _log.warning(
                "Global daily cap %d reached (%d calls today) — blocking %s",
                self._daily_cap_total, total_today, agent_type,
            )
            return False

        agent_cap = self._daily_cap_per_agent.get(agent_type)
        if agent_cap is not None:
            try:
                agent_today = count_ai_calls_today(agent_type=agent_type)
            except Exception:
                agent_today = 0
            if agent_today >= agent_cap:
                _log.warning(
                    "Daily cap for %s (%d) reached (%d calls today)",
                    agent_type, agent_cap, agent_today,
                )
                return False

        round_cap = self._per_round_cap.get(agent_type)
        if round_cap is not None:
            if self._round_counts.get(agent_type, 0) >= round_cap:
                _log.warning("Round cap for %s (%d) reached", agent_type, round_cap)
                return False

        return True

    def register_call(self, agent_type: str) -> None:
        """Increment the in-process per-round counter for *agent_type*."""
        self._round_counts[agent_type] = self._round_counts.get(agent_type, 0) + 1

    def reset_round(self) -> None:
        """Clear all per-round counters (call at the start of each new round)."""
        self._round_counts.clear()
