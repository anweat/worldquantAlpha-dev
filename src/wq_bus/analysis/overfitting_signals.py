"""overfitting_signals.py — Heuristic overfitting risk analysis for submitted alphas."""
from __future__ import annotations

import re

from wq_bus.analysis.stats_helpers import safe_div
from wq_bus.data import knowledge_db

# Matches ts_xxx(expr, N) — captures the window integer N (flat, no nesting)
_TS_WINDOW_RE = re.compile(r"\bts_\w+\s*\([^,)]+,\s*(\d+)")
_TS_FUNC_RE = re.compile(r"\bts_\w+\s*\(")

_TOP_N_FIELDS = 5


def _parse_ts_windows(expression: str) -> list[int]:
    """Extract ts_xxx window parameters, robust to nested function calls.

    Walks each ``ts_xxx(`` opening, finds the matching close paren tracking
    paren depth, splits arguments at depth 0, and treats the last numeric
    literal as the window. Avoids the previous regex's bug where
    ``ts_corr(ts_delta(close,5), volume, 10)`` captured 5 (inner) instead
    of 10 (outer).
    """
    windows: list[int] = []
    for m in _TS_FUNC_RE.finditer(expression):
        depth = 0
        start = m.end() - 1  # position of '('
        end = -1
        for i in range(start, len(expression)):
            ch = expression[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            continue
        body = expression[start + 1:end]
        parts: list[str] = []
        cur: list[str] = []
        d = 0
        for ch in body:
            if ch == "(":
                d += 1
            elif ch == ")":
                d -= 1
            if ch == "," and d == 0:
                parts.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        if cur:
            parts.append("".join(cur).strip())
        for tok in reversed(parts):
            try:
                windows.append(int(tok))
                break
            except ValueError:
                continue
    return windows


def _top_fields(expressions: list[str], n: int = _TOP_N_FIELDS) -> set[str]:
    """Return the n most common field names across all expressions."""
    from collections import Counter
    from wq_bus.analysis.expression_fingerprint import parse_expression

    counter: Counter[str] = Counter()
    for expr in expressions:
        parsed = parse_expression(expr)
        counter.update(parsed["fields"])
    return {name for name, _ in counter.most_common(n)}


def analyze() -> dict:
    """Compute overfitting risk signals across all submitted alphas.

    Returns a dict with:
    - parameter_concentration: {window_value: count, ...}
    - field_overlap_rate: fraction of alphas sharing at least one top-5 field
    - high_corr_pair_count: number of PnL pairs above 0.7 threshold
    - score: heuristic 0–1 (>0.6 = high overfit risk)
    - suggestions: list of actionable strings

    Also writes a 'overfit_signal' learning via knowledge_db.add_learning.
    """
    alphas = knowledge_db.list_alphas(status="submitted", limit=500)
    expressions = [a["expression"] for a in alphas if a.get("expression")]

    # 1. Parameter concentration — ts_xxx window histogram
    from collections import Counter
    window_counter: Counter[int] = Counter()
    for expr in expressions:
        window_counter.update(_parse_ts_windows(expr))
    parameter_concentration = {str(k): v for k, v in window_counter.most_common()}

    # 2. Field overlap rate — how many alphas share ≥1 top-5 fields
    top5 = _top_fields(expressions)
    overlap_count = 0
    if expressions and top5:
        from wq_bus.analysis.expression_fingerprint import parse_expression
        for expr in expressions:
            parsed = parse_expression(expr)
            if set(parsed["fields"]) & top5:
                overlap_count += 1
    field_overlap_rate = safe_div(overlap_count, len(expressions))

    # 3. High PnL correlation pair count
    high_corr_pairs = knowledge_db.list_pnl_corr(threshold=0.7)
    high_corr_pair_count = len(high_corr_pairs)

    # 4. Heuristic score (0–1)
    n_submitted = len(expressions)
    # Parameter concentration: top window used in >50% of alphas → signal
    top_window_frac = 0.0
    if window_counter and n_submitted:
        top_window_frac = safe_div(window_counter.most_common(1)[0][1], n_submitted)

    score = min(1.0, (
        top_window_frac * 0.35 +
        field_overlap_rate * 0.35 +
        min(1.0, safe_div(high_corr_pair_count, max(n_submitted, 1))) * 0.30
    ))

    # 5. Suggestions
    suggestions: list[str] = []
    if top_window_frac > 0.5:
        top_window = window_counter.most_common(1)[0][0]
        suggestions.append(
            f"Over {top_window_frac:.0%} of submitted alphas use ts window={top_window}. "
            "Diversify lookback periods to reduce parameter overfit."
        )
    if field_overlap_rate > 0.7:
        suggestions.append(
            f"Field overlap rate is {field_overlap_rate:.0%} (>{_TOP_N_FIELDS} shared fields). "
            "Try different data fields to improve independence."
        )
    if high_corr_pair_count > 3:
        suggestions.append(
            f"{high_corr_pair_count} alpha pairs have PnL correlation ≥ 0.7. "
            "Submitted portfolio is highly correlated — consider diversifying strategies."
        )
    if score > 0.6:
        suggestions.append(
            f"Overall overfit score {score:.2f} > 0.6 — HIGH RISK. "
            "Review portfolio diversity before submitting more alphas."
        )
    elif score < 0.3:
        suggestions.append("Overfit score looks healthy. Portfolio appears well-diversified.")

    result = {
        "parameter_concentration": parameter_concentration,
        "field_overlap_rate": field_overlap_rate,
        "high_corr_pair_count": high_corr_pair_count,
        "score": score,
        "suggestions": suggestions,
    }

    summary = (
        f"Overfit score={score:.2f} | "
        f"field_overlap={field_overlap_rate:.0%} | "
        f"high_corr_pairs={high_corr_pair_count} | "
        f"n_submitted={n_submitted}"
    )
    knowledge_db.add_learning(kind="overfit_signal", content=summary, payload=result)

    return result
