"""alpha_combiner — assemble alpha expressions from AI-produced fragments.

Pure-Python, no I/O. Takes ``{signals, filters, weights}`` produced by the
``alpha_gen.fragments`` prompt and emits a list of ``(expr, settings)`` tuples
ready for ``alpha_mutator.expand_batch`` and ALPHA_DRAFTED emission.

Architecture (forward-compat with future plugin system, see plan.md
"Future (post-MVP)"):

    Strategy = Callable[[Fragments, ModeCfg], Iterable[CombinedAlpha]]

Each strategy is a pure function registered in ``STRATEGIES`` keyed by its
name. ``combine()`` looks up which strategies the active mode enables (via
``mode_cfg.enabled_strategies``) and runs them in order, deduplicating
across the union by ``(expr, settings_key)``.

To add a new strategy in the future:
    1. Define a function ``def my_strategy(frags, mode_cfg) -> list[CombinedAlpha]``
    2. Register: ``STRATEGIES["my_strategy"] = my_strategy``
    3. List it in ``config/alpha_gen.yaml > mode_budgets.<mode>.enabled_strategies``

Filter validation:
    The AI may produce filter expressions that are *not* legal booleans. We
    apply a top-level whitelist (``_FILTER_TOP_OPS``) — a filter is accepted
    only if its outermost operator is one of greater/less/and/or/etc. Invalid
    filters are dropped with a warning (logged via ``logging.warning``).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

_log = logging.getLogger(__name__)


# ─── Data shapes ───────────────────────────────────────────────────────────

@dataclass
class Fragment:
    """A single AI-produced fragment (signal/filter/weight)."""
    expr: str
    rationale: str = ""
    family_hint: str = ""
    ai_call_id: str | None = None


@dataclass
class Fragments:
    """Container for all three fragment categories from one AI call."""
    signals: list[Fragment] = field(default_factory=list)
    filters: list[Fragment] = field(default_factory=list)
    weights: list[Fragment] = field(default_factory=list)


@dataclass
class CombinedAlpha:
    """One combiner-produced alpha ready for ALPHA_DRAFTED emission.

    ``provenance`` is a dict the caller can inspect for trace/debug purposes;
    it carries the strategy name, parent fragment indices, and an inheritable
    ``ai_call_id`` (pulled from the dominant fragment).
    """
    expr: str
    settings: dict
    provenance: dict


# ─── Filter operator whitelist ────────────────────────────────────────────

_FILTER_TOP_OPS: frozenset[str] = frozenset({
    "greater", "less", "greater_equal", "less_equal", "equal", "not_equal",
    "and", "or", "not", "trade_when", "is_nan",
})

_TOP_OP_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _filter_is_legal(expr: str) -> bool:
    """True iff *expr*'s outermost operator is in the boolean whitelist."""
    m = _TOP_OP_RE.match(expr or "")
    if not m:
        return False
    return m.group(1) in _FILTER_TOP_OPS


# ─── Settings-key for dedup ───────────────────────────────────────────────

def _settings_key(s: dict) -> str:
    """Stable key used to dedup ``(expr, settings)`` pairs across strategies."""
    if not s:
        return ""
    return "|".join(f"{k}={s[k]}" for k in sorted(s))


# ─── Strategies ────────────────────────────────────────────────────────────

def _strategy_passthrough(frags: Fragments, mode_cfg: dict) -> list[CombinedAlpha]:
    """1-leg: each signal becomes a standalone alpha (already rank-wrapped)."""
    out: list[CombinedAlpha] = []
    for i, sig in enumerate(frags.signals):
        if not sig.expr:
            continue
        out.append(CombinedAlpha(
            expr=sig.expr,
            settings={},
            provenance={"strategy": "passthrough",
                        "signal_idx": i,
                        "ai_call_id": sig.ai_call_id,
                        "family_hint": sig.family_hint,
                        "rationale": sig.rationale},
        ))
    return out


def _strategy_linear_2leg(frags: Fragments, mode_cfg: dict) -> list[CombinedAlpha]:
    """2-leg linear: ``rank(A) + rank(B)`` (A,B already rank-wrapped, so just A+B).

    Caps emissions per signal at ``combos_per_signal`` to honor mode budget.
    Pairs each signal with subsequent signals only (avoid duplicate symmetric
    pairs A+B / B+A).
    """
    out: list[CombinedAlpha] = []
    cap = max(0, int(mode_cfg.get("combos_per_signal", 2)))
    if cap == 0 or len(frags.signals) < 2:
        return out
    sigs = frags.signals
    for i, a in enumerate(sigs):
        if not a.expr:
            continue
        emitted_for_i = 0
        for j in range(i + 1, len(sigs)):
            if emitted_for_i >= cap:
                break
            b = sigs[j]
            if not b.expr or a.expr == b.expr:
                continue
            out.append(CombinedAlpha(
                expr=f"({a.expr}) + ({b.expr})",
                settings={},
                provenance={"strategy": "linear_2leg",
                            "signal_idx": i,
                            "partner_idx": j,
                            "ai_call_id": a.ai_call_id or b.ai_call_id,
                            "rationale": f"2-leg combo: {a.family_hint} + {b.family_hint}"},
            ))
            emitted_for_i += 1
    return out


def _strategy_filtered(frags: Fragments, mode_cfg: dict) -> list[CombinedAlpha]:
    """Filter-gated: ``if_else(filter, signal, 0)`` for each (signal, filter).

    Caps per signal at ``combos_per_signal``. Drops filters that fail the
    top-level boolean whitelist.
    """
    out: list[CombinedAlpha] = []
    cap = max(0, int(mode_cfg.get("combos_per_signal", 2)))
    if cap == 0 or not frags.filters:
        return out
    legal_filters: list[tuple[int, Fragment]] = []
    for fi, f in enumerate(frags.filters):
        if not f.expr:
            continue
        if not _filter_is_legal(f.expr):
            _log.warning("alpha_combiner: dropping illegal filter (top-op not boolean): %s",
                         f.expr[:80])
            continue
        legal_filters.append((fi, f))
    if not legal_filters:
        return out
    for si, sig in enumerate(frags.signals):
        if not sig.expr:
            continue
        for k, (fi, flt) in enumerate(legal_filters[:cap]):
            out.append(CombinedAlpha(
                expr=f"if_else({flt.expr}, {sig.expr}, 0)",
                settings={},
                provenance={"strategy": "filtered",
                            "signal_idx": si,
                            "filter_idx": fi,
                            "ai_call_id": sig.ai_call_id or flt.ai_call_id,
                            "rationale": f"filter-gated {sig.family_hint}"},
            ))
    return out


def _strategy_weighted(frags: Fragments, mode_cfg: dict) -> list[CombinedAlpha]:
    """Weight-scaled: ``(weight) * (signal)`` for each (signal, weight)."""
    out: list[CombinedAlpha] = []
    cap = max(0, int(mode_cfg.get("combos_per_signal", 2)))
    if cap == 0 or not frags.weights:
        return out
    for si, sig in enumerate(frags.signals):
        if not sig.expr:
            continue
        for wi, w in enumerate(frags.weights[:cap]):
            if not w.expr:
                continue
            out.append(CombinedAlpha(
                expr=f"({w.expr}) * ({sig.expr})",
                settings={},
                provenance={"strategy": "weighted",
                            "signal_idx": si,
                            "weight_idx": wi,
                            "ai_call_id": sig.ai_call_id or w.ai_call_id,
                            "rationale": f"weighted {sig.family_hint}"},
            ))
    return out


# Strategy registry — key is the name used in mode_budgets.<mode>.enabled_strategies.
# Add new strategies here (or via plugin extension once that lands post-MVP).
StrategyFn = Callable[[Fragments, dict], list[CombinedAlpha]]

STRATEGIES: dict[str, StrategyFn] = {
    "passthrough": _strategy_passthrough,
    "linear_2leg": _strategy_linear_2leg,
    "filtered":    _strategy_filtered,
    "weighted":    _strategy_weighted,
}


def register_strategy(name: str, fn: StrategyFn, *, overwrite: bool = False) -> None:
    """Register an extra combiner strategy (forward-compat plugin hook).

    External callers (or future plugin loader) can register new strategies at
    import time. Refuses to overwrite an existing name unless explicit.
    """
    if name in STRATEGIES and not overwrite:
        raise ValueError(f"strategy {name!r} already registered (pass overwrite=True)")
    STRATEGIES[name] = fn


# ─── Public entry point ───────────────────────────────────────────────────

def combine(frags: Fragments, mode_cfg: dict) -> list[CombinedAlpha]:
    """Run all enabled strategies and return deduplicated CombinedAlpha list.

    Dedup key: ``(expr, settings_key(settings))`` — first occurrence wins so
    earlier strategies (e.g. passthrough) take precedence over later ones.
    """
    enabled = list(mode_cfg.get("enabled_strategies") or list(STRATEGIES.keys()))
    seen: set[tuple[str, str]] = set()
    out: list[CombinedAlpha] = []
    for name in enabled:
        fn = STRATEGIES.get(name)
        if fn is None:
            _log.warning("alpha_combiner: unknown strategy %r in mode_cfg, skipping", name)
            continue
        try:
            produced = fn(frags, mode_cfg) or []
        except Exception:
            _log.exception("alpha_combiner: strategy %r raised, skipping", name)
            continue
        for ca in produced:
            if not ca.expr:
                continue
            key = (ca.expr, _settings_key(ca.settings))
            if key in seen:
                continue
            seen.add(key)
            out.append(ca)
    return out


# ─── AI response → Fragments adapter ──────────────────────────────────────

def parse_ai_response(payload: Any, *, ai_call_id: str | None = None) -> Fragments:
    """Convert the AI response (already JSON-parsed) into a Fragments object.

    Tolerant: missing keys → empty list; non-dict items skipped silently.
    Backwards-compatible: if the AI returned ``{"alphas":[...]}`` or
    ``{"expressions":[...]}`` (legacy shape), treat them as signals so the
    combiner can still produce passthrough alphas during fallback.
    """
    frags = Fragments()
    if not isinstance(payload, dict):
        return frags

    def _take(key: str, into: list[Fragment]) -> None:
        items = payload.get(key) or []
        if not isinstance(items, list):
            return
        for it in items:
            if not isinstance(it, dict):
                continue
            expr = (it.get("expr") or it.get("expression") or "").strip()
            if not expr:
                continue
            into.append(Fragment(
                expr=expr,
                rationale=str(it.get("rationale") or ""),
                family_hint=str(it.get("family_hint") or it.get("direction_hint") or ""),
                ai_call_id=it.get("_ai_call_id") or ai_call_id,
            ))

    _take("signals", frags.signals)
    _take("filters", frags.filters)
    _take("weights", frags.weights)

    if not frags.signals:
        # Legacy fallback: treat top-level alpha lists as signals.
        for legacy_key in ("alphas", "expressions"):
            _take(legacy_key, frags.signals)
            if frags.signals:
                break

    return frags
