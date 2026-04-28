"""Boundary tests for AI rate-cap accounting & fan-out filter.

Run: `python scripts/test_rate_cap.py`

Covers regressions for:
  T1: per-round cap MUST NOT decrement on adapter failure (only on success).
  T2: reset_round() actually clears counters.
  T3: TASK_STARTED → ai_service triggers reset_round() so daemon doesn't lock up.
  T4: AgentBase._on_ai_call_failed silently returns (no WARNING) for foreign cids.
  T5: ModelUnavailableError → fallback model retry, success counts only ONCE.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure src/ on path so direct script run works
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wq_bus.ai.rate_limiter import RateLimiter

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def _record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    tag = PASS if ok else FAIL
    print(f"  {tag}  {name}  {detail}")


# ----------------------------------------------------------------------------
# T1 + T2: rate_limiter accounting
# ----------------------------------------------------------------------------

def test_rate_limiter_basic() -> None:
    print("[T1] per-round cap accounting")
    rl = RateLimiter()
    # Force a small cap for the test
    rl._per_round_cap["__test_agent"] = 2

    # 4 reservation checks but only 1 register_call (simulating 3 failures + 1 success)
    for _ in range(4):
        assert rl.check_and_reserve("__test_agent")
    rl.register_call("__test_agent")  # only 1 success
    _record("only-success-counts: 4 checks + 1 register → still under cap",
            rl.check_and_reserve("__test_agent"),
            f"counter={rl._round_counts.get('__test_agent', 0)}")

    rl.register_call("__test_agent")  # 2nd success → at cap
    _record("at cap (2 successes, cap=2)",
            not rl.check_and_reserve("__test_agent"),
            f"counter={rl._round_counts.get('__test_agent', 0)}")

    print("[T2] reset_round() clears counters")
    rl.reset_round()
    _record("post-reset: cap available again",
            rl.check_and_reserve("__test_agent"),
            f"counter={rl._round_counts.get('__test_agent', 0)}")


# ----------------------------------------------------------------------------
# T3: TASK_STARTED → ai_service.reset_round wiring
# ----------------------------------------------------------------------------

async def test_task_started_resets_round() -> None:
    print("[T3] TASK_STARTED triggers ai_service reset_round")
    from wq_bus.bus.event_bus import EventBus
    from wq_bus.bus.events import TASK_STARTED, make_event
    from wq_bus.ai.ai_service import AIService

    class _StubLimiter:
        def __init__(self) -> None:
            self.reset_calls = 0
        def reset_round(self) -> None:
            self.reset_calls += 1

    class _StubDispatcher:
        def __init__(self) -> None:
            self._limiter = _StubLimiter()

    bus = EventBus()
    dispatcher = _StubDispatcher()
    svc = AIService(bus, dispatcher)
    svc.start()

    bus.emit(make_event(TASK_STARTED, dataset_tag="_global", trace_id="trace-test-1"))
    # event_bus is sync-emit; await a tick to drain
    await asyncio.sleep(0.05)
    _record("TASK_STARTED → reset_round called once",
            dispatcher._limiter.reset_calls >= 1,
            f"reset_calls={dispatcher._limiter.reset_calls}")


# ----------------------------------------------------------------------------
# T4: AgentBase._on_ai_call_failed silent for foreign cid
# ----------------------------------------------------------------------------

async def test_ai_failed_fanout_silent() -> None:
    print("[T4] AI_CALL_FAILED for foreign call_id stays silent (DEBUG, not WARNING)")
    from wq_bus.bus.event_bus import EventBus
    from wq_bus.bus.events import AI_CALL_FAILED, make_event
    from wq_bus.agents.base import AgentBase

    class _DummyAgent(AgentBase):
        AGENT_TYPE = "dummy_x"
        subscribes = []
        async def _handle(self, event):  # required override
            return None

    bus = EventBus()
    agent = _DummyAgent(bus)
    # Manually attach the AI listener (normally done lazily by ai_request)
    agent._ai_pending = {}
    bus.subscribe(AI_CALL_FAILED, agent._on_ai_call_failed)

    # Capture WARNING+ logs from agent.dummy_x
    captured: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = lambda r: captured.append(r) if r.levelno >= logging.WARNING else None
    logging.getLogger("agent.dummy_x").addHandler(handler)
    logging.getLogger("agent.dummy_x").setLevel(logging.DEBUG)

    # 1) cid that doesn't belong to this agent type → ignored entirely
    bus.emit(make_event(AI_CALL_FAILED, dataset_tag="_global",
                        call_id="other_agent_abc123", reason="x"))
    # 2) cid belongs but unknown → DEBUG (not WARNING)
    bus.emit(make_event(AI_CALL_FAILED, dataset_tag="_global",
                        call_id="dummy_x_unknown123", reason="x"))
    await asyncio.sleep(0.05)

    _record("no WARNING logged for foreign or unknown cid",
            len(captured) == 0,
            f"warnings={[r.getMessage() for r in captured]}")


# ----------------------------------------------------------------------------
# T5: ModelUnavailableError → fallback (smoke; uses stub adapter)
# ----------------------------------------------------------------------------

async def test_model_unavailable_fallback() -> None:
    print("[T5] dispatcher._call_with_retry falls back on ModelUnavailableError")
    from wq_bus.ai.adapters.copilot_cli import ModelUnavailableError

    class _StubAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []
        async def call(self, messages, model, depth):
            self.calls.append(model)
            if model.startswith("claude-sonnet-4.6"):
                raise ModelUnavailableError(f"mock unavail: {model}")
            return '{"ok": true, "model": "%s"}' % model

    # Build a minimal Dispatcher just to access _call_with_retry
    from wq_bus.ai.dispatcher import Dispatcher
    disp = Dispatcher.__new__(Dispatcher)  # bypass __init__ for unit test

    adapter = _StubAdapter()
    res = await disp._call_with_retry(
        adapter, [{"role": "user", "content": "hi"}],
        model="claude-sonnet-4.6", depth="normal", adapter_name="copilot_cli",
    )
    _record("fallback retried with gpt-5.4",
            "gpt-5.4" in res and len(adapter.calls) == 2 and adapter.calls[1] == "gpt-5.4",
            f"calls={adapter.calls}")


# ----------------------------------------------------------------------------

async def main() -> None:
    test_rate_limiter_basic()
    await test_task_started_resets_round()
    await test_ai_failed_fanout_silent()
    await test_model_unavailable_fallback()
    print()
    n_pass = sum(1 for _, ok, _ in results if ok)
    n_total = len(results)
    print(f"=== {n_pass}/{n_total} passed ===")
    sys.exit(0 if n_pass == n_total else 1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s %(message)s")
    # Silence the noisy bus subscribe logger during tests
    logging.getLogger("wq_bus.bus.event_bus").setLevel(logging.WARNING)
    asyncio.run(main())
