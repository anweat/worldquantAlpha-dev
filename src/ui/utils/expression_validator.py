"""
expression_validator.py — Local syntax & heuristic validation for FE expressions.
"""
import re
import json
from pathlib import Path
from functools import lru_cache

_OPERATORS_FILE = Path(__file__).parent.parent.parent.parent / "operators_full.json"

# Well-known data fields by category
_PRICE_FIELDS = ["open", "close", "high", "low", "vwap", "volume", "returns",
                  "adv5", "adv10", "adv20", "adv60", "cap"]
_FUNDAMENTAL_FIELDS = [
    "assets", "liabilities", "sales", "equity", "operating_income", "net_income",
    "ebitda", "capex", "cash", "debt", "book_value", "shares_outstanding",
    "dividends", "revenue", "gross_profit", "total_debt", "current_assets",
    "current_liabilities", "retained_earnings", "ppe", "goodwill",
]


@lru_cache(maxsize=1)
def load_operators() -> list:
    with open(_OPERATORS_FILE, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_operator_names() -> frozenset:
    return frozenset(op["name"] for op in load_operators())


def validate_expression(expr: str) -> dict:
    """
    Returns:
        valid (bool), issues (list[str]), warnings (list[str]),
        estimated_category (str), estimated_turnover (str), used_operators (list[str])
    """
    issues: list[str] = []
    warnings: list[str] = []

    if not expr.strip():
        return {"valid": False, "issues": ["表达式不能为空"], "warnings": [],
                "estimated_category": "", "estimated_turnover": "", "used_operators": []}

    # Parentheses balance
    depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            issues.append("括号不匹配：出现多余的 ')'")
            break
    if depth > 0:
        issues.append(f"括号不匹配：缺少 {depth} 个 ')'")

    # Identify function calls
    op_names = get_operator_names()
    used_funcs = re.findall(r'\b([a-z_][a-z0-9_]*)\s*\(', expr)
    used_operators = [f for f in used_funcs if f in op_names]
    unknown_funcs = [f for f in used_funcs if f not in op_names]
    if unknown_funcs:
        warnings.append(f"未知函数（可能是字段名）: {', '.join(unknown_funcs)}")

    # Recommend rank() wrap
    stripped = expr.strip()
    if not any(stripped.startswith(p) for p in ("rank(", "group_rank(", "ts_rank(")):
        warnings.append("建议用 rank() 包裹表达式，确保截面归一化到 [-1, 1]")

    # Category estimation
    has_fundamental = any(
        re.search(rf'\b{f}\b', expr) for f in _FUNDAMENTAL_FIELDS
    )
    has_price = any(
        re.search(rf'\b{f}\b', expr) for f in _PRICE_FIELDS
    )
    has_ts_op = bool(re.search(r'\bts_', expr))

    if has_fundamental and not (has_price or has_ts_op):
        est_category = "fundamental"
        est_turnover = "1-5%（基本面因子，换手极低）"
    elif (has_price or has_ts_op) and not has_fundamental:
        est_category = "technical"
        est_turnover = "20-80%（技术因子，换手较高）"
    elif has_fundamental and (has_price or has_ts_op):
        est_category = "mixed"
        est_turnover = "5-30%（混合型）"
    else:
        est_category = "unknown"
        est_turnover = "未知"

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "estimated_category": est_category,
        "estimated_turnover": est_turnover,
        "used_operators": used_operators,
    }
