"""DefaultStockpile — adaptive 4:2:1 weighted watchdog policy.

Per plan §8.2 + SIMULATION_POOL.md §4:
- Reads base weights from config/triggers.yaml.
- Applies adaptive bumps based on pool stats.
- Hard floors: queue, in_flight, cooldown, daily_cap.
- Picks mode via weighted random → emits GENERATE_REQUESTED.
- May call StrengthRouter.set_override to elevate explore when stuck.
"""
from __future__ import annotations

import random
import time
from typing import Any

from wq_bus.bus.events import Topic, make_event
from wq_bus.bus.policies import WatchdogPolicy
from wq_bus.utils.logging import get_logger
from wq_bus.utils.yaml_loader import load_yaml

_log = get_logger(__name__)


def _load_cfg() -> dict:
    try:
        return load_yaml("triggers") or {}
    except Exception:
        return {}


class DefaultStockpile(WatchdogPolicy):
    """Adaptive weighted mode picker.

    Weights start at explore:specialize:review_failure:track_news = 4:2:1:1
    and are adjusted per tick based on pool statistics.
    """

    # in-process cooldown tracker: {(dataset_tag, mode) -> last_triggered_ts}
    _cooldown: dict[tuple[str, str], float] = {}

    def __init__(self) -> None:
        cfg = _load_cfg()
        bw = cfg.get("base_weights") or {}
        self._base: dict[str, float] = {
            "explore":        float(bw.get("explore", 4)),
            "specialize":     float(bw.get("specialize", 2)),
            "review_failure": float(bw.get("review_failure", 1)),
            "track_news":     float(bw.get("track_news", 1)),
        }
        self._cooldown_min: float = float(cfg.get("cooldown_min", 30))
        self._queue_cap: int = int(cfg.get("queue_cap", 2000))
        self._daily_ai_cap: int = int(cfg.get("daily_ai_cap", 80))
        # When False, allow new triggers while sims are in flight (higher
        # throughput at the cost of pool pressure). Default True preserves
        # the conservative throttle described in SIMULATION_POOL.md §4.
        self._block_when_in_flight: bool = bool(cfg.get("block_when_in_flight", True))
        self._in_flight_soft_cap: int = int(cfg.get("in_flight_soft_cap", 0))
        self._saturation = cfg.get("saturation") or {}

    def should_trigger(self, state: dict) -> list:
        """Return GENERATE_REQUESTED event(s) or []."""
        tag = state.get("dataset_tag", "_global")

        # --- Hard floors ---
        if state.get("queue_pending", 0) >= self._queue_cap:
            _log.debug("watchdog: queue_pending >= %d, skip", self._queue_cap)
            return []
        in_flight = int(state.get("in_flight_sims", 0))
        if self._block_when_in_flight and in_flight > 0:
            _log.debug("watchdog: in_flight_sims=%d > 0 (block_when_in_flight=True), skip",
                       in_flight)
            return []
        if (not self._block_when_in_flight
                and self._in_flight_soft_cap > 0
                and in_flight >= self._in_flight_soft_cap):
            _log.debug("watchdog: in_flight_sims=%d >= soft_cap %d, skip",
                       in_flight, self._in_flight_soft_cap)
            return []
        if state.get("daily_ai_count", 0) >= self._daily_ai_cap:
            _log.debug("watchdog: daily_ai_cap reached, skip")
            return []

        # --- Adaptive weights ---
        weights = dict(self._base)
        pool = state.get("pool_stats") or []
        alphas_tried = sum(p.get("alphas_tried", 0) for p in pool)
        avg_sc = self._avg_self_corr(pool)
        any_high_pass = self._any_high_pass(pool)

        high_sc_threshold = float(self._saturation.get("high_self_corr_threshold", 0.6))
        low_pool_threshold = int(self._saturation.get("low_pool_size_threshold", 50))

        if avg_sc > high_sc_threshold:
            weights["explore"] *= 2.0
            _log.debug("watchdog: high avg_sc=%.2f → doubling explore weight", avg_sc)
            # Optionally elevate explore strength when stuck
            self._maybe_elevate_explore_strength(tag)

        if alphas_tried < low_pool_threshold:
            weights["explore"] *= 2.0
            _log.debug("watchdog: alphas_tried=%d < %d → doubling explore weight",
                       alphas_tried, low_pool_threshold)

        if any_high_pass:
            weights["specialize"] *= 2.0
            _log.debug("watchdog: direction with high pass rate → doubling specialize weight")

        # --- Cooldown check (pick mode until one isn't cooled down) ---
        mode = self._pick_mode(weights, tag)
        if mode is None:
            _log.debug("watchdog: all modes on cooldown for %s", tag)
            return []

        # Record trigger time
        self._cooldown[(tag, mode)] = time.time()

        dataset_tag = state.get("dataset_tag", "_global")
        _log.info("watchdog trigger: mode=%s tag=%s", mode, dataset_tag)
        return [make_event(Topic.GENERATE_REQUESTED, dataset_tag,
                           mode=mode, source="watchdog", n=4)]

    def _avg_self_corr(self, pool: list[dict]) -> float:
        vals = [p["avg_self_corr"] for p in pool
                if p.get("avg_self_corr") is not None]
        return sum(vals) / len(vals) if vals else 0.0

    def _any_high_pass(self, pool: list[dict]) -> bool:
        """True if any direction has is_passed >= 5 and submitted < target (5)."""
        for p in pool:
            if (p.get("alphas_is_passed", 0) >= 5
                    and p.get("alphas_submitted", 0) < 5):
                return True
        return False

    def _pick_mode(self, weights: dict[str, float], tag: str) -> str | None:
        """Weighted random pick, skipping cooled-down modes."""
        now = time.time()
        cooldown_secs = self._cooldown_min * 60

        available = {
            mode: w for mode, w in weights.items()
            if now - self._cooldown.get((tag, mode), 0) >= cooldown_secs
        }
        if not available:
            return None

        modes = list(available.keys())
        wts = [available[m] for m in modes]
        return random.choices(modes, weights=wts, k=1)[0]

    def _maybe_elevate_explore_strength(self, tag: str) -> None:
        """Elevate explore strength to 'high' for 30 min when avg_sc is high."""
        try:
            from wq_bus.ai.strength import get_router
            router = get_router()
            existing = next(
                (o for o in router.list_overrides()
                 if o["agent"] == "alpha_gen" and o["mode"] == "explore"),
                None,
            )
            if existing:
                return  # already overridden
            router.set_override(
                "alpha_gen", "explore", "high",
                ttl_min=30.0,
                note="watchdog: high avg_self_corr, exploring harder",
            )
        except Exception:
            _log.debug("watchdog: could not set strength override (non-fatal)")

    def build_state(self, tag: str) -> dict:
        """Helper: build the state dict for a given dataset_tag.

        Reads from state_db and knowledge_db. Used by triggers.py.
        """
        state: dict[str, Any] = {
            "dataset_tag": tag,
            "queue_pending": 0,
            "in_flight_sims": 0,
            "daily_ai_count": 0,
            "daily_ai_cap": self._daily_ai_cap,
            "pool_stats": [],
            "recent_modes": [],
        }
        try:
            from wq_bus.utils.tag_context import with_tag
            from wq_bus.data import state_db
            with with_tag(tag):
                state["queue_pending"] = state_db.queue_size("pending")
                state["daily_ai_count"] = state_db.count_ai_calls_today()
        except Exception as exc:
            _log.warning("build_state(%s): state_db read failed (%s) — using zero defaults", tag, exc)
            state["_state_db_error"] = str(exc)

        try:
            from wq_bus.data._sqlite import open_knowledge
            with open_knowledge() as conn:
                rows = conn.execute(
                    f"SELECT * FROM pool_stats_{tag}"
                ).fetchall()
                state["pool_stats"] = [dict(r) for r in rows]
        except Exception as exc:
            _log.warning("build_state(%s): pool_stats read failed (%s)", tag, exc)
            state["_pool_stats_error"] = str(exc)

        return state
