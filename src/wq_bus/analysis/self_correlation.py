"""self_correlation.py — Extract and evaluate SELF_CORRELATION from alpha records.

SELF_CORRELATION is embedded in the /alphas/{id} response under is.checks —
do NOT call /alphas/{id}/check-submission (404 for TUTORIAL accounts).
"""
from __future__ import annotations


def extract_sc_value(alpha_record: dict) -> float | None:
    """Extract the SELF_CORRELATION value from an alpha record.

    Looks in alpha_record["is"]["checks"] for the entry with
    name == "SELF_CORRELATION" and returns its numeric 'value'.

    Returns None if:
    - The check is PENDING (value not yet available)
    - The key path doesn't exist
    - The value is not a valid float
    """
    try:
        checks: list[dict] = alpha_record["is"]["checks"]
    except (KeyError, TypeError):
        return None

    for check in checks:
        if check.get("name") == "SELF_CORRELATION":
            val = check.get("value")
            if val is None:
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

    return None


def extract_sc_result(alpha_record: dict) -> str | None:
    """Extract the SELF_CORRELATION 'result' enum (PASS/PENDING/FAIL).

    For TUTORIAL accounts BRAIN omits numeric `value` and only returns the
    enum result. Used as authoritative pass/fail signal when value is absent.
    """
    try:
        checks: list[dict] = alpha_record["is"]["checks"]
    except (KeyError, TypeError):
        return None
    for check in checks:
        if check.get("name") == "SELF_CORRELATION":
            r = check.get("result")
            return str(r).upper() if r is not None else None
    return None


def check(
    alpha_record: dict, threshold: float = 0.7
) -> tuple[bool, float | None]:
    """Evaluate the SELF_CORRELATION check for an alpha record.

    Resolution order:
    1. If a numeric `value` is present → passed = (value < threshold).
    2. Otherwise fall back to the enum `result`:
         PASS    → passed=True
         FAIL    → passed=False
         PENDING → passed=False (do NOT optimistically pass — submission would race)
         missing → passed=False (be conservative)
    """
    value = extract_sc_value(alpha_record)
    if value is not None:
        return (value < threshold), value
    result = extract_sc_result(alpha_record)
    if result == "PASS":
        return True, None
    # FAIL / PENDING / missing -> not yet eligible for submission
    return False, None
