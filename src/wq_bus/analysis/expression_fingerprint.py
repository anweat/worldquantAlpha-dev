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

from wq_bus.utils.paths import PROJECT_ROOT as _PROJECT_ROOT  # noqa: E402
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


# Commutative operators whose first 2 args are interchangeable.
# Sorting these args before hashing ensures ts_corr(a,b,n) and ts_corr(b,a,n)
# yield the same fingerprint (they are mathematically identical).
_COMMUTATIVE_OPS: frozenset[str] = frozenset({
    "ts_corr", "correlation", "covariance", "ts_covariance",
    "add", "multiply", "max", "min",
})


def _canonicalize_commutative(expr: str) -> str:
    """Sort the first 2 args of commutative operator calls (best-effort).

    Handles single-level nesting (good enough for fingerprint dedupe; perfect
    canonicalization would require a full parser, which is overkill here).
    """
    def _rewrite(m: re.Match) -> str:
        op = m.group(1)
        args_str = m.group(2)
        # Split on commas at depth-0 only
        depth = 0
        parts: list[str] = []
        last = 0
        for i, ch in enumerate(args_str):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(args_str[last:i].strip())
                last = i + 1
        parts.append(args_str[last:].strip())
        if len(parts) >= 2:
            a, b = sorted(parts[:2])
            parts = [a, b] + parts[2:]
        return f"{op}({', '.join(parts)})"

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(o) for o in _COMMUTATIVE_OPS) + r")\s*\(([^()]*)\)"
    )
    # Iterate until no further rewrites (handles a single level of nesting per pass)
    prev = None
    cur = expr
    for _ in range(5):
        if cur == prev:
            break
        prev = cur
        cur = pattern.sub(_rewrite, cur)
    return cur


def fingerprint(expr: str) -> tuple[str, dict[str, object]]:
    """Compute (sha256_hex, parse_dict) for an expression.

    Normalisation steps before hashing:
      1. Lowercase + collapse whitespace.
      2. Canonicalise commutative operator args (ts_corr/correlation/...).

    Result: ``rank( a / b )`` == ``rank(a/b)`` and ``ts_corr(close,volume,20)``
    == ``ts_corr(volume,close,20)`` produce the same fingerprint.
    """
    parsed = parse_expression(expr)
    canonical = _canonicalize_commutative(expr.strip().lower())
    normalised = re.sub(r"\s+", "", canonical)
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
