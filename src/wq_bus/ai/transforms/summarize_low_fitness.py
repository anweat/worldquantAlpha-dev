"""chain_hook transform — extract low-fitness/failed alphas from a prior batch result.

Used by call_chain to feed alpha_gen(explore) → failure_analyzer(review) chains.
The previous output is expected to look like the JSON returned by alpha_gen or
sim_executor batch summaries: ``{"alphas": [{"expression":..., "sharpe":..., "fitness":...}, ...]}``
or a generic dict with a ``failures`` array.
"""
from __future__ import annotations

import json

NAME = "summarize_low_fitness"


def _iter_alphas(prev: dict):
    for key in ("failures", "alphas", "near_miss", "results", "data"):
        v = prev.get(key)
        if isinstance(v, list):
            yield from v


def transform(prev_output: dict, ctx: dict) -> str:
    if not isinstance(prev_output, dict):
        return ""
    threshold = float((ctx or {}).get("fitness_threshold", 1.0))
    low: list[dict] = []
    for a in _iter_alphas(prev_output):
        if not isinstance(a, dict):
            continue
        fit = a.get("fitness") if a.get("fitness") is not None else a.get("is_fitness")
        try:
            if fit is None or float(fit) < threshold:
                low.append({
                    "expression": (a.get("expression") or a.get("expr") or "")[:160],
                    "sharpe": a.get("sharpe"),
                    "fitness": fit,
                    "turnover": a.get("turnover"),
                    "reason": a.get("rejection_reason") or a.get("error"),
                })
        except (TypeError, ValueError):
            continue
    if not low:
        return "## Previous task: no low-fitness alphas found\n"
    body = json.dumps(low[:20], ensure_ascii=False, indent=2)
    return (
        "## Previous batch — low-fitness candidates (fitness < "
        f"{threshold})\n```json\n{body}\n```\n"
        "Focus your next analysis on common failure patterns across these expressions.\n"
    )
