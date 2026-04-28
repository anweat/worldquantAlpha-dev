"""pattern_extractor.py — Core pattern extraction for Alpha recipe synthesis.

Peels cosmetic wrapper operators to expose the structural core of an expression,
then groups alphas that share the same core for recipe proposal.

Public API
----------
strip_wrappers(expr)          → str  (inner core after peeling wrappers)
extract_core_tokens(expr)     → dict {core_form, fields, operators}
group_repeated_cores(alphas, min_support=3) → list[CoreGroup]
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Wrapper operator set
# ---------------------------------------------------------------------------

WRAPPER_OPS: frozenset[str] = frozenset({
    "rank",
    "group_rank",
    "zscore",
    "scale",
    "winsorize",
    "decay_linear",
    "quantile",
    "normalize",
    "signed_power",
    "sigmoid",
})

# Regex: matches outermost call of a wrapper op, allowing optional trailing
# comma-separated argument(s) after the first positional argument.
# Group 1 = the first (main) argument.
_WRAPPER_RE = re.compile(
    r"^(?:"
    + "|".join(re.escape(op) for op in WRAPPER_OPS)
    + r")\(\s*(.*?)(?:\s*,\s*[^,()]+)?\s*\)$",
    re.IGNORECASE | re.DOTALL,
)

# Used for tokenizing fields / operators from an expression
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ---------------------------------------------------------------------------
# strip_wrappers
# ---------------------------------------------------------------------------

def strip_wrappers(expr: str) -> str:
    """Recursively peel outermost wrapper operator while expression changes.

    Example:
        rank(group_rank(ts_corr(close, volume, 20), industry))
        → group_rank(ts_corr(close, volume, 20), industry)
        → ts_corr(close, volume, 20)
    """
    expr = expr.strip()
    while True:
        m = _WRAPPER_RE.match(expr)
        if not m:
            break
        inner = m.group(1).strip()
        if not inner or inner == expr:
            break
        expr = inner
    return expr


# ---------------------------------------------------------------------------
# extract_core_tokens
# ---------------------------------------------------------------------------

# Known data-field keywords (rough list; not exhaustive but sufficient for
# distinguishing fields from operators)
_KNOWN_OPERATORS: frozenset[str] = frozenset({
    "ts_corr", "ts_std_dev", "ts_delta", "ts_mean", "ts_sum", "ts_max", "ts_min",
    "ts_rank", "ts_ir", "ts_arg_max", "ts_arg_min", "ts_product",
    "rank", "group_rank", "zscore", "scale", "winsorize", "quantile",
    "normalize", "signed_power", "sigmoid", "decay_linear",
    "log", "abs", "sqrt", "sign", "tanh",
    "if_else", "coalesce", "nan_mask",
    "indneutralize",
}) | WRAPPER_OPS


def extract_core_tokens(expr: str) -> dict:
    """Return {core_form (str), fields (sorted list), operators (sorted list)}.

    ``core_form`` is the expression after stripping wrappers.
    ``fields`` = tokens that are NOT known operators (likely data field names).
    ``operators`` = tokens that ARE known operators (lowercased).
    """
    core_form = strip_wrappers(expr)
    tokens = _TOKEN_RE.findall(core_form)

    seen_fields: set[str] = set()
    seen_ops: set[str] = set()
    for tok in tokens:
        lc = tok.lower()
        if lc in _KNOWN_OPERATORS:
            seen_ops.add(lc)
        else:
            seen_fields.add(lc)

    return {
        "core_form": core_form,
        "fields": sorted(seen_fields),
        "operators": sorted(seen_ops),
    }


# ---------------------------------------------------------------------------
# group_repeated_cores
# ---------------------------------------------------------------------------

@dataclass
class CoreGroup:
    core_form: str
    support: int
    sample_alpha_ids: list[str]  # up to 5
    top_metrics: dict            # sharpe, fitness, turnover (median of top 5)
    direction_ids: set[str]
    themes_seen: list[str]

    def to_dict(self) -> dict:
        return {
            "core_form": self.core_form,
            "support": self.support,
            "sample_alpha_ids": self.sample_alpha_ids,
            "top_metrics": self.top_metrics,
            "direction_ids": sorted(self.direction_ids),
            "themes_seen": sorted(set(self.themes_seen)),
        }


def group_repeated_cores(
    alphas: list[dict],
    min_support: int = 3,
) -> list[CoreGroup]:
    """Group alphas by their stripped-wrapper core form.

    Parameters
    ----------
    alphas:
        List of alpha dicts, each expected to have at least:
        ``expression``, ``alpha_id``, and optionally
        ``sharpe``, ``fitness``, ``turnover``, ``direction_id``, ``themes_csv``.
    min_support:
        Minimum number of alphas sharing a core to include the group.

    Returns
    -------
    List of CoreGroup objects (sorted by support descending).
    """
    # core_form → list of alpha dicts
    buckets: dict[str, list[dict]] = {}
    for alpha in alphas:
        expr = (alpha.get("expression") or "").strip()
        if not expr:
            continue
        core = strip_wrappers(expr)
        buckets.setdefault(core, []).append(alpha)

    groups: list[CoreGroup] = []
    for core_form, members in buckets.items():
        if len(members) < min_support:
            continue

        ids = [a.get("alpha_id", "") for a in members if a.get("alpha_id")]
        sample_ids = ids[:5]

        # Collect metrics from members that have them
        sharpes  = [float(a["sharpe"])   for a in members if a.get("sharpe")   is not None]
        fitnesses = [float(a["fitness"]) for a in members if a.get("fitness")  is not None]
        turnovers = [float(a["turnover"])for a in members if a.get("turnover") is not None]

        def _median(vals: list[float]) -> float | None:
            return round(statistics.median(vals), 4) if vals else None

        top_metrics = {
            "sharpe":   _median(sharpes),
            "fitness":  _median(fitnesses),
            "turnover": _median(turnovers),
        }

        direction_ids: set[str] = set()
        themes_seen: list[str] = []
        for a in members:
            if a.get("direction_id"):
                direction_ids.add(a["direction_id"])
            if a.get("themes_csv"):
                themes_seen.extend(
                    t.strip() for t in a["themes_csv"].split(",") if t.strip()
                )

        groups.append(CoreGroup(
            core_form=core_form,
            support=len(members),
            sample_alpha_ids=sample_ids,
            top_metrics=top_metrics,
            direction_ids=direction_ids,
            themes_seen=themes_seen,
        ))

    groups.sort(key=lambda g: g.support, reverse=True)
    return groups


# ---------------------------------------------------------------------------
# CLI entry point (called from wq_bus.cli recipe extract)
# ---------------------------------------------------------------------------

def run_extract_cli(
    tag: str,
    min_support: int = 3,
    statuses: list[str] | None = None,
    out_path: Path | None = None,
    emit_event: bool = True,
) -> list[dict]:
    """Load alphas from knowledge.db, extract core groups, write JSON, emit event.

    Parameters
    ----------
    tag:
        Dataset tag (e.g. ``USA_TOP3000``).
    min_support:
        Minimum core repetitions to include a group.
    statuses:
        List of alpha statuses to include.  Defaults to
        ['simulated', 'is_passed', 'submitted'].  Always excludes 'legacy'.
    out_path:
        Output JSON path.  Defaults to ``data/recipe_candidates_<TAG>.json``.
    emit_event:
        Whether to emit ``RECIPE_CANDIDATES_READY`` on the bus.

    Returns
    -------
    List of CoreGroup dicts written to *out_path*.
    """
    import os
    import time

    from wq_bus.data._sqlite import open_knowledge, ensure_migrated

    ensure_migrated()

    if statuses is None:
        statuses = ["simulated", "is_passed", "submitted"]
    # Safety: always exclude legacy
    statuses = [s for s in statuses if s != "legacy"]

    placeholders = ",".join("?" * len(statuses))
    with open_knowledge() as conn:
        rows = conn.execute(
            f"""SELECT alpha_id, expression, sharpe, fitness, turnover,
                       direction_id, themes_csv, status
                FROM alphas
                WHERE dataset_tag=?
                  AND status IN ({placeholders})
                ORDER BY updated_at DESC""",
            [tag] + statuses,
        ).fetchall()
    alphas = [dict(r) for r in rows]

    groups = group_repeated_cores(alphas, min_support=min_support)
    result = [g.to_dict() for g in groups]

    if out_path is None:
        from wq_bus.utils.paths import PROJECT_ROOT as project_root
        out_path = project_root / "data" / f"recipe_candidates_{tag}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out_path)

    print(f"[pattern_extractor] wrote {len(result)} candidate groups → {out_path}")

    if emit_event and result:
        try:
            from wq_bus.bus.event_bus import get_bus
            from wq_bus.bus.events import make_event
            from wq_bus.bus.events import RECIPE_CANDIDATES_READY
            bus = get_bus()
            bus.emit(make_event(
                RECIPE_CANDIDATES_READY, tag,
                n_groups=len(result),
                out_path=str(out_path),
                min_support=min_support,
            ))
        except Exception as e:
            print(f"[pattern_extractor] WARN: could not emit RECIPE_CANDIDATES_READY: {e}")

    return result
