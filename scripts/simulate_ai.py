"""simulate_ai.py — Fake/stub AI adapter for testing.

Returns deterministic stub responses keyed by (agent_type, mode).

Usage:
    # Set environment variable to use this adapter everywhere:
    set WQ_AI_ADAPTER=fake_simulate

    # Or pass adapter_name explicitly in code:
    from scripts.simulate_ai import FakeAdapter
    adapter = FakeAdapter()
    response = await adapter.call(messages, model, depth)

    # Or run standalone to see what a given mode returns:
    python scripts/simulate_ai.py alpha_gen.explore
    python scripts/simulate_ai.py failure_analyzer
    python scripts/simulate_ai.py doc_summarizer
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Deterministic stub responses per (agent_type, mode)
# ---------------------------------------------------------------------------

_ALPHA_TEMPLATES = [
    "rank(liabilities/assets)",
    "rank(operating_income/assets)",
    "ts_corr(rank(close), rank(volume), 10)",
    "group_rank(retained_earnings/assets, sector)",
    "rank(ts_delta(close, 5))",
    "rank(operating_cash_flow/(assets+1))",
    "rank(net_income/equity)",
    "group_rank(ebitda/total_debt, industry)",
]

_STUBS: dict[str, dict] = {
    # alpha_gen modes
    "alpha_gen.explore": {
        "expressions": [
            {"expression": _ALPHA_TEMPLATES[0], "rationale": "fundamental ratio rank", "settings_overrides": {}},
            {"expression": _ALPHA_TEMPLATES[1], "rationale": "profitability rank", "settings_overrides": {}},
            {"expression": _ALPHA_TEMPLATES[2], "rationale": "price-volume correlation", "settings_overrides": {}},
            {"expression": _ALPHA_TEMPLATES[3], "rationale": "sector-relative earnings", "settings_overrides": {}},
        ]
    },
    "alpha_gen.specialize": {
        "expressions": [
            {"expression": _ALPHA_TEMPLATES[4], "rationale": "momentum variant",
             "settings_overrides": {"decay": 2, "neutralization": "SUBINDUSTRY"}},
            {"expression": _ALPHA_TEMPLATES[5], "rationale": "cash flow variant",
             "settings_overrides": {"decay": 0, "neutralization": "SECTOR"}},
        ]
    },
    "alpha_gen.review_failure": {
        "expressions": [
            {"expression": _ALPHA_TEMPLATES[6], "rationale": "low-turnover mutation", "settings_overrides": {"decay": 0}},
            {"expression": _ALPHA_TEMPLATES[7], "rationale": "industry-neutral variant", "settings_overrides": {}},
        ]
    },
    "alpha_gen.track_news": {
        "expressions": [
            {"expression": "rank(ts_delta(volume, 3))", "rationale": "news-driven volume spike", "settings_overrides": {}},
            {"expression": "rank(close - ts_mean(close, 5))", "rationale": "short-term price reversion", "settings_overrides": {}},
        ]
    },
    # failure_analyzer
    "failure_analyzer": {
        "summary": "[stub] Recent failures: HIGH_TURNOVER (40%), LOW_SHARPE (35%), HIGH_SELF_CORR (25%).",
        "mutation_tasks": [
            {"type": "reduce_turnover", "hint": "use decay=0 for fundamental alphas"},
            {"type": "add_neutralization", "hint": "use SUBINDUSTRY neutralization"},
        ],
        "fail_breakdown": {"HIGH_TURNOVER": 4, "LOW_SHARPE": 3, "HIGH_SELF_CORR": 2},
    },
    # doc_summarizer
    "doc_summarizer": {
        "summary_md": "## Stub Summary\n\nThis is a stub summary of crawled documents.\n\n"
                      "Key themes: quantitative finance, factor investing, alpha generation.",
        "key_points": [
            "Fundamental ratios outperform in bear markets",
            "Sector neutralization reduces self-correlation",
        ],
        "tags": ["fundamental", "momentum", "neutralization"],
    },
}


def get_stub(agent_type: str, mode: Optional[str] = None, payload: dict | None = None) -> dict:
    """Return deterministic stub response for (agent_type, mode).

    Falls back gracefully: agent_type.mode → agent_type → generic.
    """
    payload = payload or {}
    # Try to extract mode from payload if not given
    if not mode:
        mode = payload.get("mode") or payload.get("_mode")

    key = f"{agent_type}.{mode}" if mode else agent_type
    if key in _STUBS:
        return dict(_STUBS[key])
    if agent_type in _STUBS:
        return dict(_STUBS[agent_type])

    # Generic fallback
    return {"_stub": True, "agent_type": agent_type, "mode": mode}


# ---------------------------------------------------------------------------
# FakeAdapter — drop-in replacement for real adapters
# ---------------------------------------------------------------------------

class FakeAdapter:
    """Drop-in AI adapter that returns JSON stubs without network calls.

    Detects agent_type / mode from the prompt text and returns the matching stub.
    """

    billing_mode: str = "per_call"

    async def call(
        self,
        messages: list[dict],
        model: str,
        depth: str | None = None,
    ) -> str:
        """Return stub JSON. Parses agent_type and mode from messages."""
        agent_type, mode = self._parse_prompt(messages)
        stub = get_stub(agent_type, mode)
        # Return a JSON array with one element (as expected by subagent_packer.unpack)
        return json.dumps([stub])

    def _parse_prompt(self, messages: list[dict]) -> tuple[str, str]:
        """Try to extract agent_type and mode from the packed prompt."""
        text = " ".join(m.get("content", "") for m in messages).lower()
        # Detect agent
        agent_type = "alpha_gen"  # default
        for ag in ("failure_analyzer", "doc_summarizer", "portfolio_analyzer",
                   "alpha_gen", "crawler"):
            if ag.replace("_", "") in text.replace("_", "") or ag in text:
                agent_type = ag
                break

        # Detect mode
        mode = "explore"  # default
        for m in ("specialize", "review_failure", "track_news", "explore"):
            if m.replace("_", " ") in text or m in text:
                mode = m
                break

        return agent_type, mode


# ---------------------------------------------------------------------------
# Module-level adapter installation (via env var WQ_AI_ADAPTER=fake_simulate)
# ---------------------------------------------------------------------------

def install_as_default() -> None:
    """Monkey-patch the dispatcher to use FakeAdapter."""
    try:
        from wq_bus.ai import dispatcher as _d
        _adapter = FakeAdapter()
        _d._INSTANCE = None  # reset singleton
        instance = _d.get_dispatcher(dry_run=False)
        for key in list(instance._adapters.keys()):
            instance._adapters[key] = _adapter
    except Exception as e:
        print(f"[simulate_ai] install_as_default failed: {e}", file=sys.stderr)


def maybe_install() -> None:
    """Check WQ_AI_ADAPTER env var and install if set to 'fake_simulate'."""
    import os
    if os.environ.get("WQ_AI_ADAPTER") == "fake_simulate":
        install_as_default()
        print("[simulate_ai] FakeAdapter installed as default AI adapter", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI: python scripts/simulate_ai.py <agent_type>[.<mode>]
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/simulate_ai.py <agent_type>[.<mode>]")
        print("  e.g. alpha_gen.explore | failure_analyzer | doc_summarizer")
        sys.exit(1)

    spec = sys.argv[1]
    if "." in spec:
        agent_type, mode = spec.split(".", 1)
    else:
        agent_type, mode = spec, None

    stub = get_stub(agent_type, mode)
    print(json.dumps(stub, indent=2))


if __name__ == "__main__":
    main()
