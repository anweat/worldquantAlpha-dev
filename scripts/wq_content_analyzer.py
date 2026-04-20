"""
wq_content_analyzer.py - Extract alpha ideas from crawled WQ content.
Scans text files in data/crawl/, identifies:
  - Alpha expression patterns
  - Data fields mentioned
  - Operators used
  - Strategy descriptions
  - Quantitative hints (Sharpe, Fitness, turnover targets)
Saves ideas to SQLite alpha_ideas table.
"""
import sys, json, re, sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
CRAWL_DIR = ROOT / "data" / "crawl"
DB_PATH = ROOT / "data" / "crawl_state.db"
IDEAS_OUT = ROOT / "data" / "alpha_ideas_extracted.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─── Known FE operators ───────────────────────────────────────────────────────
FE_OPERATORS = {
    "ts_": ["ts_rank", "ts_zscore", "ts_delta", "ts_corr", "ts_std_dev",
            "ts_mean", "ts_sum", "ts_min", "ts_max", "ts_skewness",
            "ts_kurtosis", "ts_regression_slope", "ts_ir",
            "ts_percentage_change", "ts_covariance"],
    "cross_": ["rank", "group_rank", "group_zscore", "scale", "vector_neut"],
    "math_": ["log", "abs", "sign", "sqrt", "power", "min", "max",
              "if_else", "clamp", "sigmoid"],
}
ALL_OPERATORS = [op for group in FE_OPERATORS.values() for op in group]
ALL_OPERATORS += ["rank", "group_rank", "group_zscore", "scale",
                  "ts_rank", "ts_zscore", "ts_delta", "ts_corr",
                  "ts_std_dev", "ts_mean"]

# ─── Known data fields ────────────────────────────────────────────────────────
DATA_FIELDS = [
    "close", "open", "high", "low", "volume", "vwap", "returns",
    "liabilities", "assets", "equity", "debt", "cash_and_equivalents",
    "operating_income", "net_income", "revenue", "sales", "ebitda",
    "book_value", "market_cap", "shares_outstanding",
    "cash_flow_from_operations", "capital_expenditures", "free_cash_flow",
    "gross_profit", "net_profit_margin", "return_on_equity", "return_on_assets",
    "earnings_per_share", "dividends", "retained_earnings",
    "short_interest", "news_short_interest", "total_debt",
    "inventory", "accounts_receivable", "accounts_payable",
    "beta", "adv20", "adv60",
]

# ─── Regex patterns for expression detection ──────────────────────────────────
EXPR_PATTERNS = [
    # Explicit FE code blocks
    r"```(?:fastexpr|fe|alpha|python)?\s*(rank\([^`]+?)\s*```",
    r"`(rank\([^`]+?)`",
    r"`(group_rank\([^`]+?)`",
    r"`(ts_\w+\([^`]+?)`",
    # Common alpha formula patterns
    r"(rank\s*\(\s*[\w_]+\s*/\s*[\w_]+\s*\))",
    r"(rank\s*\(\s*-?\s*[\w_]+\s*\))",
    r"(group_rank\s*\([^)]+\))",
    r"(ts_rank\s*\([^,]+,\s*\d+\))",
    r"(ts_zscore\s*\([^,]+,\s*\d+\))",
    r"(ts_delta\s*\([^,]+,\s*\d+\))",
]

# ─── Strategy keywords → idea type ────────────────────────────────────────────
STRATEGY_KEYWORDS = {
    "momentum": ["momentum", "trend", "breakout", "returns", "price change"],
    "value": ["value", "book-to-price", "earnings yield", "p/e", "undervalued",
              "fundamental", "balance sheet"],
    "quality": ["quality", "profitability", "roe", "roa", "profit margin",
                "return on equity", "return on assets"],
    "leverage": ["leverage", "debt", "liabilities", "debt-to-equity", "debt ratio"],
    "liquidity": ["liquidity", "cash", "current ratio", "quick ratio"],
    "reversal": ["reversal", "mean reversion", "contrarian", "overreact"],
    "sentiment": ["sentiment", "short interest", "analyst", "forecast",
                  "revision", "news"],
    "technical": ["technical", "rsi", "macd", "bollinger", "moving average",
                  "volatility", "price action"],
    "composite": ["composite", "multi-factor", "combination", "blend"],
}


def extract_expressions_from_text(text: str) -> list:
    """Extract potential alpha expressions from text."""
    found = []
    for pat in EXPR_PATTERNS:
        matches = re.findall(pat, text, re.IGNORECASE | re.DOTALL)
        for m in matches:
            expr = m.strip()
            if len(expr) > 5 and len(expr) < 300:
                found.append(expr)
    return list(set(found))


def detect_strategy_type(text: str) -> str:
    text_lower = text.lower()
    scores = {k: 0 for k in STRATEGY_KEYWORDS}
    for stype, keywords in STRATEGY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[stype] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def detect_data_fields(text: str) -> list:
    found = []
    text_lower = text.lower()
    for field in DATA_FIELDS:
        if field in text_lower:
            found.append(field)
    return found


def detect_operators(text: str) -> list:
    found = []
    text_lower = text.lower()
    for op in ALL_OPERATORS:
        if op in text_lower:
            found.append(op)
    return list(set(found))


def extract_alpha_ideas_from_text(url: str, text: str) -> list:
    """Main extraction function. Returns list of idea dicts."""
    ideas = []

    # 1. Direct expression extraction
    exprs = extract_expressions_from_text(text)
    for expr in exprs:
        ideas.append({
            "source_url": url,
            "idea_type": "direct_expression",
            "expression": expr,
            "description": f"Expression found in page text",
            "data_fields": json.dumps(detect_data_fields(expr)),
            "operators": json.dumps(detect_operators(expr)),
            "expected_logic": "",
            "priority": 9,
        })

    # 2. Strategy pattern extraction from paragraphs
    paragraphs = re.split(r'\n{2,}', text)
    for para in paragraphs:
        para = para.strip()
        if len(para) < 50:
            continue

        fields = detect_data_fields(para)
        ops = detect_operators(para)
        stype = detect_strategy_type(para)

        # Only capture paragraphs mentioning FE concepts
        if not fields and not ops:
            continue

        # Generate alpha template ideas from paragraph context
        if fields and ops:
            ideas.append({
                "source_url": url,
                "idea_type": f"strategy_{stype}",
                "expression": "",  # Will be generated later
                "description": para[:300],
                "data_fields": json.dumps(fields[:5]),
                "operators": json.dumps(ops[:5]),
                "expected_logic": _infer_logic(para, fields, ops),
                "priority": _score_priority(fields, ops, stype),
            })

    return ideas


def _infer_logic(text: str, fields: list, ops: list) -> str:
    """Try to infer the investment logic from paragraph."""
    text_lower = text.lower()
    hints = []
    if "higher" in text_lower or "increase" in text_lower:
        hints.append("positive signal")
    if "lower" in text_lower or "decrease" in text_lower:
        hints.append("negative/inverse signal")
    if "rank" in ops:
        hints.append("cross-sectional rank")
    if any(op.startswith("ts_") for op in ops):
        hints.append("time-series transformation")
    if "group_rank" in ops:
        hints.append("industry-neutral")
    return "; ".join(hints) if hints else "see description"


def _score_priority(fields: list, ops: list, stype: str) -> int:
    """Score idea priority 1-10."""
    score = 5
    # Prefer fundamental fields (low turnover)
    fundamental = {"liabilities", "assets", "equity", "debt", "operating_income",
                   "net_income", "revenue", "sales", "ebitda", "book_value"}
    if any(f in fundamental for f in fields):
        score += 2
    # Prefer cross-sectional ops
    if "rank" in ops or "group_rank" in ops:
        score += 1
    # Deprioritize pure price-action
    price_only = {"close", "open", "high", "low", "volume", "returns"}
    if all(f in price_only for f in fields):
        score -= 1
    return min(10, max(1, score))


def analyze_all_crawled(db_path: Path = DB_PATH) -> list:
    """Scan all crawled pages and extract alpha ideas."""
    conn = sqlite3.connect(str(db_path))

    # Get all done pages
    rows = conn.execute(
        "SELECT url, content_path FROM crawl_queue WHERE status='done' AND alpha_ideas_extracted=0"
    ).fetchall()

    print(f"Analyzing {len(rows)} crawled pages...")
    all_ideas = []

    for url, content_path in rows:
        if not content_path:
            continue
        text_file = Path(content_path) / "text.txt"
        if not text_file.exists():
            continue

        text = text_file.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue

        ideas = extract_alpha_ideas_from_text(url, text)
        for idea in ideas:
            conn.execute("""
                INSERT OR IGNORE INTO alpha_ideas
                (source_url, idea_type, expression, description, data_fields, operators, expected_logic, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                idea["source_url"], idea["idea_type"], idea["expression"],
                idea["description"], idea["data_fields"], idea["operators"],
                idea["expected_logic"], idea["priority"]
            ))
        conn.execute(
            "UPDATE crawl_queue SET alpha_ideas_extracted=1 WHERE url=?", (url,)
        )
        all_ideas.extend(ideas)
        print(f"  {url[:60]}: {len(ideas)} ideas extracted")

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM alpha_ideas").fetchone()[0]
    print(f"\nTotal alpha ideas in DB: {total}")
    conn.close()

    # Save summary
    IDEAS_OUT.write_text(
        json.dumps(all_ideas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return all_ideas


def get_top_ideas(limit: int = 50, db_path: Path = DB_PATH) -> list:
    """Get highest-priority untested ideas."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("""
        SELECT id, source_url, idea_type, expression, description,
               data_fields, operators, expected_logic, priority
        FROM alpha_ideas
        WHERE tested=0
        ORDER BY priority DESC, id ASC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "source_url": r[1], "idea_type": r[2],
            "expression": r[3], "description": r[4],
            "data_fields": json.loads(r[5] or "[]"),
            "operators": json.loads(r[6] or "[]"),
            "expected_logic": r[7], "priority": r[8],
        }
        for r in rows
    ]


if __name__ == "__main__":
    ideas = analyze_all_crawled()
    top = get_top_ideas(20)
    print(f"\nTop {len(top)} ideas (by priority):")
    for idea in top:
        print(f"  [{idea['priority']}] {idea['idea_type']} | {idea['expression'][:60] or idea['description'][:60]}")
