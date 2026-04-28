"""Programmatic expansion of AI-generated alpha seeds → parameter-swept variants.

Background
----------
The legacy project (archive/2026-04-25_old_core/alpha_factory.py) achieved
200-300 candidates per round with high quality via a static MASTER_POOL of
templates plus programmatic mutate/combo helpers — *zero* extra AI calls per
candidate. The new bus system is purely AI-driven, so a single round only
yields ~15 alphas (the safe single-prompt cap before LLMs start truncating
JSON or collapsing diversity).

This module restores that throughput economics: each AI seed is expanded
into K variants by perturbing time windows + simulator settings. K=4 turns
15 AI seeds into ~60 simulator candidates without any additional LLM cost.

Pure functions, no I/O, no bus. Caller dedups via the existing fingerprint
registry before emitting.
"""
from __future__ import annotations

import random
import re
from typing import Iterable

# Matches `ts_<name>(<arg-without-comma>, <int-window>)` — captures the int
# window so we can perturb it without disturbing the field expression.
_TS_PARAM_RE = re.compile(r'(ts_\w+\([^,()]+,\s*)(\d+)(\s*\))')

_NEUT_VARIANTS  = ("MARKET", "INDUSTRY", "SUBINDUSTRY")
_DECAY_VARIANTS = (0, 2, 4, 8)
_TRUNC_VARIANTS = (0.05, 0.08)
_WINDOW_FACTORS = (0.5, 0.75, 1.5, 2.0)


def _settings_key(s: dict) -> str:
    """Stable identity tuple for dedup inside one expansion call."""
    return (
        f"{s.get('decay','-')}/"
        f"{s.get('neutralization','-')}/"
        f"{s.get('truncation','-')}/"
        f"{s.get('universe','-')}"
    )


def _perturb_window(expr: str, rng: random.Random) -> str:
    """Pick one ts_*(..., N) occurrence and shift N by a random factor."""
    matches = list(_TS_PARAM_RE.finditer(expr))
    if not matches:
        return expr
    m = rng.choice(matches)
    n = int(m.group(2))
    factor = rng.choice(_WINDOW_FACTORS)
    new_n = max(2, min(504, int(round(n * factor))))
    if new_n == n:
        return expr
    return expr[:m.start()] + m.group(1) + str(new_n) + m.group(3) + expr[m.end():]


def expand(
    expr: str,
    settings: dict,
    *,
    factor: int = 4,
    seed: int | None = None,
) -> list[tuple[str, dict]]:
    """Return up to ``factor`` (expr, settings) variants of (expr, settings).

    The original (expr, settings) is *always* index 0. Subsequent variants
    perturb either the expression's first ts_* window or one of the simulator
    settings (neutralization / decay / truncation). Internal dedup ensures no
    two emitted variants share the same (expr, settings_key).

    Parameters
    ----------
    factor : int
        Total variants requested *including* the seed. ``factor=1`` is a
        passthrough. Default 4 → typical 15 AI seeds → ~60 candidates.
    seed : int | None
        RNG seed for reproducibility (mainly for tests).
    """
    if factor < 1:
        return [(expr, dict(settings))]

    rng = random.Random(seed)
    out: list[tuple[str, dict]] = [(expr, dict(settings))]
    seen: set[tuple[str, str]] = {(expr, _settings_key(settings))}

    attempts = 0
    max_attempts = factor * 6
    while len(out) < factor and attempts < max_attempts:
        attempts += 1
        new_expr = expr
        new_settings = dict(settings)

        # 60% chance: perturb a ts_* window. (No effect if expr has no ts_*.)
        if rng.random() < 0.6:
            new_expr = _perturb_window(expr, rng)

        # Independent settings rotations.
        if rng.random() < 0.5:
            new_settings["neutralization"] = rng.choice(_NEUT_VARIANTS)
        if rng.random() < 0.4:
            new_settings["decay"] = rng.choice(_DECAY_VARIANTS)
        if rng.random() < 0.3:
            new_settings["truncation"] = rng.choice(_TRUNC_VARIANTS)

        key = (new_expr, _settings_key(new_settings))
        if key in seen:
            continue
        seen.add(key)
        out.append((new_expr, new_settings))

    return out


def expand_batch(
    seeds: Iterable[tuple[str, dict]],
    *,
    factor: int = 4,
    seed: int | None = None,
) -> list[tuple[str, dict, int]]:
    """Expand a list of (expr, settings) seeds → flat (expr, settings, parent_idx) list.

    ``parent_idx`` is the index in the original ``seeds`` list, useful for
    tracing variants back to their AI-generated parent in events / logs.
    """
    seed_list = list(seeds)
    out: list[tuple[str, dict, int]] = []
    base_seed = seed if seed is not None else 0
    for i, (expr, settings) in enumerate(seed_list):
        # Per-seed RNG seed so identical seeds across runs produce identical
        # variants (helps with reproducible debugging).
        for v_expr, v_settings in expand(expr, settings, factor=factor, seed=base_seed + i):
            out.append((v_expr, v_settings, i))
    return out
