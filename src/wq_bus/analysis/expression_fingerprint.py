"""expression_fingerprint.py — Parse and fingerprint FE alpha expressions.

Provides:
- parse_expression(): tokenize into ops, fields, skeleton
- fingerprint(): sha256 hash + parse dict
- is_duplicate(): check against knowledge_db
- record(): persist fingerprint to knowledge_db
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import NamedTuple

from wq_bus.data import knowledge_db

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OPERATORS_FILE = _PROJECT_ROOT / "operators_full.json"

# Fallback operator set if operators_full.json is not available
_FALLBACK_OPERATORS: frozenset[str] = frozenset({
    "rank", "ts_rank", "ts_mean", "ts_std_dev", "ts_zscore", "ts_corr",
    "ts_delta", "ts_delay", "ts_sum", "ts_min", "ts_max", "ts_argmin",
    "ts_argmax", "ts_decay_linear", "ts_regression",
    "group_rank", "group_mean", "group_zscore", "group_sum",
    "add", "subtract", "multiply", "divide", "abs", "log", "sqrt",
    "signed_power", "power", "max", "min", "sign", "if_else",
    "scale", "truncate", "normalize", "demean",
    "correlation", "covariance", "pasteurize",
    "vector_sum", "vector_neut",
    "trade_when", "settle_date_returns",
})


def _load_operators_set() -> frozenset[str]:
    try:
        with open(_OPERATORS_FILE, encoding="utf-8") as f:
            ops = json.load(f)
        return frozenset(o["name"] for o in ops if "name" in o)
    except Exception:
        return _FALLBACK_OPERATORS


OPERATORS_SET: frozenset[str] = _load_operators_set()

# Regex patterns
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_IDENTIFIER_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_FUNC_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class ParseResult(NamedTuple):
    ops: list[str]
    fields: list[str]
    skeleton: str


def parse_expression(expr: str) -> dict[str, object]:
    """Tokenize a Fast Expression into ops, fields, and a skeleton string.

    - ops: operator names found (identifiers immediately followed by '(')
    - fields: non-operator identifiers (data field names)
    - skeleton: expression with all numeric literals replaced by '#' and
                all field names replaced by 'F', whitespace normalized
    """
    # Extract operator names (identifiers followed by '(')
    ops: list[str] = []
    for m in _FUNC_CALL_RE.finditer(expr):
        name = m.group(1)
        if name in OPERATORS_SET:
            ops.append(name)

    # Extract field names: identifiers NOT in OPERATORS_SET and not pure numbers
    fields: list[str] = []
    seen_fields: set[str] = set()
    for m in _IDENTIFIER_RE.finditer(expr):
        name = m.group(1)
        if name not in OPERATORS_SET and name not in seen_fields:
            # Skip if it's immediately followed by '(' (already handled as op above)
            end = m.end()
            rest = expr[end:].lstrip()
            if rest.startswith("("):
                # It's a function call but not in our operators set — treat as op
                ops.append(name)
            else:
                fields.append(name)
                seen_fields.add(name)

    # Build skeleton: replace numbers with '#', field names with 'F'
    skeleton = expr
    # Replace numeric literals first
    skeleton = _NUMBER_RE.sub("#", skeleton)
    # Replace field names with 'F' (non-operator identifiers)
    field_set = set(fields)

    def _replace_identifier(m: re.Match) -> str:
        name = m.group(1)
        if name in field_set:
            return "F"
        return name

    skeleton = _IDENTIFIER_RE.sub(_replace_identifier, skeleton)
    # Normalize whitespace
    skeleton = re.sub(r"\s+", " ", skeleton).strip()

    return {"ops": sorted(set(ops)), "fields": fields, "skeleton": skeleton}


def fingerprint(expr: str) -> tuple[str, dict[str, object]]:
    """Compute (sha256_hex, parse_dict) for an expression.

    The hash is computed over the skeleton (normalized form), making
    structurally identical expressions with different field names produce
    different hashes, while numeric constant variations produce the same hash.

    Actually: we hash the full normalized expression (lowercased, whitespace
    collapsed) so that two expressions identical up to whitespace/case yield
    the same hash.
    """
    parsed = parse_expression(expr)
    # Normalise: lowercase + remove ALL whitespace for the hash input so that
    # "rank(a / b)" and "rank( a  /  b )" produce the same fingerprint.
    normalised = re.sub(r"\s+", "", expr.strip().lower())
    sha = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return sha, parsed


def is_duplicate(expr: str) -> bool:
    """Return True if this expression's fingerprint already exists in knowledge_db."""
    sha, _ = fingerprint(expr)
    return knowledge_db.fingerprint_exists(sha)


def record(expr: str, alpha_id: str | None = None) -> str:
    """Compute fingerprint and persist it to knowledge_db. Returns the hash."""
    sha, parsed = fingerprint(expr)
    knowledge_db.save_fingerprint(
        fp_hash=sha,
        expression=expr,
        op_set=parsed["ops"],
        field_set=parsed["fields"],
        skeleton=parsed["skeleton"],
        alpha_id=alpha_id,
    )
    return sha
