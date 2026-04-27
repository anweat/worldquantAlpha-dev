"""Dimension definitions and feature-vector extraction for alpha expressions.

Per SIMULATION_POOL.md §2:
- Hard-coded dimension classes (DATA_FIELD_CLASSES, OPERATOR_CLASSES, etc.)
- PROJECTION_DIMS: first 4 dimensions used to form direction_id
- classify(expression, settings) -> feature_vector dict
- project_id(feature_vector) -> direction_id string

Field→class mapping loaded from config/datasets.yaml (field_class_map section).
Unknown fields are logged and classified as "other".
"""
from __future__ import annotations

import re
from typing import Any

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Hard-coded dimension sets (SIMULATION_POOL.md §2)
# ---------------------------------------------------------------------------

DATA_FIELD_CLASSES = [
    "fundamental.ratio",
    "fundamental.absolute",
    "price",
    "volume",
    "technical",
    "macro",
    "other",
]

OPERATOR_CLASSES = [
    "rank",
    "group_rank",
    "ts_basic",    # ts_delta / ts_mean / ts_std_dev / ts_sum / ts_zscore
    "ts_corr",
    "arith",       # +,-,*,/,log,exp,abs,sign
    "logical",     # ?:, if_else, clamp
    "winsorize",
    "other",
]

NEUTRALIZATION = [
    "NONE", "MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY", "COUNTRY", "STATISTICAL",
]

DECAY_BAND = ["0", "1-4", "5-15", "16-30", ">30"]

TURNOVER_BAND = ["<5%", "5-30%", "30-70%", ">70%"]

# First 4 dimensions form the direction_id (SIMULATION_POOL.md §2 PROJECTION_DIMS)
PROJECTION_DIMS = ["data_field_class", "operator_class", "neutralization", "decay_band"]

# ---------------------------------------------------------------------------
# Known operator patterns → operator_class
# ---------------------------------------------------------------------------

_OP_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bgroup_rank\b"), "group_rank"),
    (re.compile(r"\brank\b"),       "rank"),
    (re.compile(r"\bts_corr\b"),    "ts_corr"),
    (re.compile(r"\bts_(delta|mean|std_dev|sum|zscore|skewness|min|max)\b"), "ts_basic"),
    (re.compile(r"\bwinsorize\b"),  "winsorize"),
    (re.compile(r"\b(log|exp|abs|sign|sqrt|pow)\b"), "arith"),
    (re.compile(r"\?|if_else\b|clamp\b"), "logical"),
    (re.compile(r"[+\-\*/]"),       "arith"),
]

# Fundamental fields (ratio / absolute split)
_FUND_RATIO_FIELDS = {
    "liabilities_to_assets", "debt_to_equity", "roe", "roa", "roc",
    "gross_margin", "net_margin", "operating_margin", "current_ratio", "quick_ratio",
    "asset_turnover", "inventory_turnover", "receivables_turnover",
    "price_to_book", "price_to_earnings", "price_to_sales", "ev_ebitda",
    "pe_ratio", "pb_ratio", "ps_ratio",
}

_FUND_ABS_FIELDS = {
    "assets", "liabilities", "equity", "revenue", "sales",
    "operating_income", "net_income", "ebitda", "ebit", "cash",
    "operating_cash_flow", "free_cash_flow", "capex",
    "retained_earnings", "total_debt", "short_term_debt", "long_term_debt",
    "goodwill", "intangibles", "inventory", "receivables",
    "dividends", "shares_outstanding", "book_value",
}

_PRICE_FIELDS = {"open", "high", "low", "close", "vwap", "returns", "adj_close"}

_VOLUME_FIELDS = {"volume", "adv20", "adv5", "adv60", "adv120", "turnover", "shares_traded"}

_TECH_FIELDS = {"rsi", "macd", "atr", "beta", "alpha_val", "momentum", "volatility"}

_MACRO_FIELDS = {"gdp", "cpi", "inflation", "interest_rate", "fx_rate", "vix"}


def _classify_field(field_name: str) -> str:
    """Map a field name to its DATA_FIELD_CLASS."""
    f = field_name.lower().replace(" ", "_")
    if f in _FUND_RATIO_FIELDS or f.endswith("_ratio") or f.endswith("_margin"):
        return "fundamental.ratio"
    if f in _FUND_ABS_FIELDS:
        return "fundamental.absolute"
    if f in _PRICE_FIELDS:
        return "price"
    if f in _VOLUME_FIELDS:
        return "volume"
    if f in _TECH_FIELDS:
        return "technical"
    if f in _MACRO_FIELDS:
        return "macro"
    # Try heuristics
    if any(k in f for k in ("liab", "asset", "equit", "revenue", "income",
                             "sales", "cash", "earn", "profit", "debt")):
        return "fundamental.absolute"
    if any(k in f for k in ("ratio", "margin", "yield", "rate", "roe", "roa",
                             "return_on", "per_share")):
        return "fundamental.ratio"
    if any(k in f for k in ("volume", "adv", "turnover", "shares_")):
        return "volume"
    if any(k in f for k in ("price", "close", "open", "high", "low", "return", "vwap")):
        return "price"
    return "other"


def _load_field_class_map() -> dict[str, str]:
    """Load optional field_class_map from config/datasets.yaml."""
    try:
        from wq_bus.utils.yaml_loader import load_yaml
        ds = load_yaml("datasets") or {}
        fcm = ds.get("field_class_map") or {}
        return {k.lower(): v for k, v in fcm.items()}
    except Exception:
        return {}


_field_class_map: dict[str, str] | None = None


def _get_fcm() -> dict[str, str]:
    global _field_class_map
    if _field_class_map is None:
        _field_class_map = _load_field_class_map()
    return _field_class_map


def _classify_fields_in_expr(expression: str) -> str:
    """Extract the dominant data field class from an expression."""
    fcm = _get_fcm()
    # Find all identifier-like tokens (excluding operator names)
    # Allow short fields (e.g. "ni", "pe"); previously dropped <3-char tokens.
    tokens = re.findall(r"\b([a-z][a-z0-9_]*)\b", expression.lower())
    # Filter out known operators
    op_names = {"rank", "group_rank", "ts_corr", "ts_delta", "ts_mean",
                 "ts_std_dev", "ts_sum", "ts_zscore", "ts_skewness",
                 "ts_min", "ts_max", "winsorize", "log", "exp",
                 "abs", "sign", "sqrt", "pow", "if_else", "clamp",
                 "sector", "industry", "subindustry", "market"}
    field_tokens = [t for t in tokens if t not in op_names and len(t) >= 2]

    class_votes: dict[str, int] = {}
    unknown: list[str] = []
    for ft in field_tokens:
        cls = fcm.get(ft) or _classify_field(ft)
        if cls == "other":
            unknown.append(ft)
        class_votes[cls] = class_votes.get(cls, 0) + 1

    if unknown:
        _log.debug("unknown fields (classified as other): %s", unknown)

    if not class_votes:
        return "other"
    # Return dominant class
    return max(class_votes, key=class_votes.__getitem__)


def _classify_operator(expression: str) -> str:
    """Return the dominant operator class for an expression."""
    for pat, cls in _OP_PATTERNS:
        if pat.search(expression):
            return cls
    return "other"


def _classify_neutralization(settings: dict) -> str:
    raw = str(settings.get("neutralization", "MARKET")).upper()
    return raw if raw in NEUTRALIZATION else "MARKET"


def _classify_decay(settings: dict) -> str:
    decay = int(settings.get("decay", 4))
    if decay == 0:
        return "0"
    if decay <= 4:
        return "1-4"
    if decay <= 15:
        return "5-15"
    if decay <= 30:
        return "16-30"
    return ">30"


def _classify_turnover(is_metrics: dict | None) -> str:
    if not is_metrics:
        return "5-30%"
    to = float(is_metrics.get("turnover", 0.0))
    if to < 0.05:
        return "<5%"
    if to < 0.30:
        return "5-30%"
    if to < 0.70:
        return "30-70%"
    return ">70%"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(expression: str, settings: dict, is_metrics: dict | None = None) -> dict:
    """Extract a feature vector from an alpha expression + settings.

    Args:
        expression: The FE expression string.
        settings: Simulation settings dict (delay, decay, neutralization, ...).
        is_metrics: Optional IS metrics dict (for turnover_band; defaults to "5-30%").

    Returns:
        Feature vector dict with all 5 dimension keys.
    """
    return {
        "data_field_class": _classify_fields_in_expr(expression),
        "operator_class":   _classify_operator(expression),
        "neutralization":   _classify_neutralization(settings),
        "decay_band":       _classify_decay(settings),
        "turnover_band":    _classify_turnover(is_metrics),
    }


def project_id(feature_vector: dict) -> str:
    """Compute the direction_id (4-dim projection) from a feature vector.

    direction_id = "data_field_class|operator_class|neutralization|decay_band"

    Args:
        feature_vector: Dict returned by classify().

    Returns:
        Stable direction_id string.
    """
    parts = [str(feature_vector.get(dim, "other")) for dim in PROJECTION_DIMS]
    return "|".join(parts)


def semantic_name(direction_id: str) -> str:
    """Generate a human-readable name from a direction_id string."""
    parts = direction_id.split("|")
    if len(parts) < 4:
        return direction_id
    dfc, opc, neut, decay = parts[:4]
    neut_short = neut.lower().replace("subindustry", "subind").replace("industry", "ind")
    decay_short = decay.replace(">", "gt").replace("-", "_").replace("<", "lt")
    return f"{dfc.replace('.', '_')}_{opc}_{neut_short}_{decay_short}"
