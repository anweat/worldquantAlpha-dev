"""
build_knowledge_base.py - Compile comprehensive WQ knowledge base from all crawled pages.
Deep analysis of full text content to extract all alpha insights.
"""
import sys, json, re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MANUAL_DIR = ROOT / "data" / "crawl_manual"

# ─── Comprehensive extraction patterns ────────────────────────────────────────
ALPHA_EXPR_PATTERNS = [
    # Code blocks with backticks
    r"`([^`]{5,200})`",
    # Expressions starting with known operators
    r"\b(rank\s*\([^)]{3,150}\))",
    r"\b(group_rank\s*\([^)]{5,200}\))",
    r"\b(ts_rank\s*\([^)]{5,150}\))",
    r"\b(ts_zscore\s*\([^)]{5,150}\))",
    r"\b(ts_delta\s*\([^)]{5,100}\))",
    r"\b(ts_corr\s*\([^)]{5,150}\))",
    r"\b(ts_std_dev\s*\([^)]{5,100}\))",
    r"\b(ts_mean\s*\([^)]{5,100}\))",
    r"\b(ts_sum\s*\([^)]{5,100}\))",
    r"\b(ts_regression_slope\s*\([^)]{5,150}\))",
    r"\b(scale\s*\([^)]{5,150}\))",
    r"\b(log\s*\([^)]{5,100}\))",
    r"\b(vec_sum\s*\([^)]{5,150}\))",
    r"\b(vec_avg\s*\([^)]{5,150}\))",
]

# Submission check names from the API
SUBMISSION_CHECKS = [
    "LOW_SHARPE", "LOW_FITNESS", "HIGH_TURNOVER",
    "LOW_TURNOVER", "CONCENTRATED_WEIGHT",
    "LOW_CORR_WITH_SELF", "SMALL_UNIVERSE", "SELF_CORR",
]

NEUTRALIZATION_OPTIONS = ["NONE", "MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY"]

SETTINGS_FIELDS = [
    "delay", "decay", "neutralization", "truncation",
    "universe", "region", "pasteurization", "nanHandling",
]


def load_page(filename: str) -> dict:
    p = MANUAL_DIR / filename
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def extract_all_expressions(text: str) -> list:
    """Comprehensive expression extraction."""
    found = set()
    for pat in ALPHA_EXPR_PATTERNS:
        for m in re.findall(pat, text, re.IGNORECASE):
            expr = m.strip()
            # Must look like an alpha expression
            if (len(expr) > 4 and len(expr) < 300
                    and any(op in expr.lower() for op in [
                        "rank(", "group_rank(", "ts_", "scale(", "log(",
                        "vec_sum(", "vec_avg(",
                    ])):
                found.add(expr)
    return sorted(found)


def extract_checks_info(text: str) -> dict:
    """Extract check thresholds and descriptions."""
    checks = {}
    for check in SUBMISSION_CHECKS:
        # Find context around each check name
        pattern = rf"{check}[^\n]{{0,200}}"
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            checks[check] = matches[0].strip()[:300]
    return checks


def extract_settings_info(text: str) -> dict:
    """Extract simulation settings information."""
    settings = {}
    for setting in SETTINGS_FIELDS:
        pattern = rf"\b{setting}\b[^\n]{{0,200}}"
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            settings[setting] = matches[0].strip()[:200]
    return settings


def analyze_key_page(page_key: str, text: str) -> dict:
    """Deep analysis of a single page."""
    exprs = extract_all_expressions(text)
    checks = extract_checks_info(text)
    settings = extract_settings_info(text)

    # Extract tables/structured data
    table_lines = []
    for line in text.split("\n"):
        line = line.strip()
        if "|" in line and len(line) > 20:
            table_lines.append(line)

    # Extract all lines that look like alpha examples or tips
    alpha_lines = []
    tip_lines = []
    for line in text.split("\n"):
        line = line.strip()
        if len(line) < 10:
            continue
        if any(op in line for op in ["rank(", "ts_", "group_rank(", "scale("]):
            alpha_lines.append(line[:200])
        if any(kw in line.lower() for kw in [
            "sharpe", "fitness", "turnover", "recommend", "avoid",
            "important", "note:", "tip:", "should", "must",
        ]):
            tip_lines.append(line[:200])

    return {
        "page_key": page_key,
        "expressions": exprs,
        "checks_mentioned": checks,
        "settings_info": settings,
        "table_lines": table_lines[:30],
        "alpha_lines": list(dict.fromkeys(alpha_lines))[:30],
        "tip_lines": list(dict.fromkeys(tip_lines))[:30],
    }


def build_operator_catalog(operators_text: str) -> dict:
    """Parse operator catalog from the operators page."""
    catalog = {}

    # Split by operator entries
    # Pattern: operator_name(params)\ndescription
    op_blocks = re.split(r'\n(?=[a-z_]+\()', operators_text)

    for block in op_blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if not lines:
            continue

        # First line should be: func_name(params) [category]
        first = lines[0]
        m = re.match(r'^([a-z_][a-z0-9_]*)\s*\(([^)]*)\)', first, re.IGNORECASE)
        if not m:
            continue

        op_name = m.group(1).lower()
        params = m.group(2).strip()
        rest_text = " ".join(lines[1:])

        # Skip very short entries
        if len(rest_text) < 5 and len(lines) < 2:
            continue

        # Extract category (base/expert/master/etc)
        category = ""
        for cat in ["base", "expert", "master", "grandmaster"]:
            if cat in first.lower() or (len(lines) > 1 and cat in lines[1].lower()):
                category = cat
                break

        # Description is the non-boilerplate lines
        desc_parts = []
        for line in lines[1:]:
            if line.lower() in ["show more", "show less", "base", "expert"]:
                continue
            if len(line) > 10:
                desc_parts.append(line)
                if len(" ".join(desc_parts)) > 300:
                    break

        description = " ".join(desc_parts)[:400]

        catalog[op_name] = {
            "signature": f"{op_name}({params})",
            "description": description,
            "category": category,
            "params": params,
        }

    return catalog


def build_full_knowledge_base():
    """Build the comprehensive knowledge base."""
    print(f"\n{'='*70}")
    print("Building Comprehensive WQ Knowledge Base")
    print(f"{'='*70}")

    # Load all pages
    all_pages = {}
    for p in sorted(MANUAL_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            all_pages[p.stem] = d
        except Exception as e:
            print(f"  Error loading {p.name}: {e}")

    print(f"Loaded {len(all_pages)} pages")

    # ─── Deep analysis of key pages ────────────────────────────────────────────
    key_analyses = {}
    for page_key, data in all_pages.items():
        text = data.get("raw_text", "")
        if len(text) > 300:
            key_analyses[page_key] = analyze_key_page(page_key, text)

    # ─── Operator catalog from operators page ─────────────────────────────────
    print("Building operator catalog...")
    op_text = ""
    for key in ["learn_operators_operators", "learn_operators"]:
        if key in all_pages:
            op_text = all_pages[key].get("raw_text", "")
            if len(op_text) > 1000:
                break

    operator_catalog = build_operator_catalog(op_text)
    print(f"  Extracted {len(operator_catalog)} operator definitions")

    # ─── Collect all alpha expressions ────────────────────────────────────────
    print("Collecting alpha expressions...")
    all_expressions = {}  # expr -> {sources, category}
    for page_key, analysis in key_analyses.items():
        for expr in analysis["expressions"]:
            if expr not in all_expressions:
                all_expressions[expr] = {
                    "sources": [],
                    "category": _classify_expression(expr),
                }
            all_expressions[expr]["sources"].append(page_key)

    print(f"  Found {len(all_expressions)} unique expressions")

    # ─── Submission criteria ────────────────────────────────────────────────────
    print("Extracting submission criteria...")
    submission_page = all_pages.get("learn_documentation_interpret-results_alpha-submission", {})
    submission_text = submission_page.get("raw_text", "")
    submission_analysis = analyze_key_page("submission", submission_text)
    submission_checks_detail = _parse_submission_checks(submission_text)

    # ─── Simulation settings ─────────────────────────────────────────────────
    print("Extracting simulation settings...")
    settings_page = all_pages.get("learn_documentation_create-alphas_simulation-settings", {})
    settings_text = settings_page.get("raw_text", "")

    # ─── Neutralization guide ────────────────────────────────────────────────
    neut_page = all_pages.get("learn_documentation_advanced-topics_neut-cons", {})
    neut_text = neut_page.get("raw_text", "")

    # ─── How BRAIN works ────────────────────────────────────────────────────
    brain_works_page = all_pages.get("learn_documentation_create-alphas_how-brain-platform-works", {})
    brain_works_text = brain_works_page.get("raw_text", "")

    # ─── 19 Alpha examples ──────────────────────────────────────────────────
    examples_page = all_pages.get("learn_documentation_examples_19-alpha-examples", {})
    examples_text = examples_page.get("raw_text", "")

    # ─── Sample alpha concepts (Bronze) ──────────────────────────────────────
    sample_page = all_pages.get("learn_documentation_examples_sample-alpha-concepts", {})
    sample_text = sample_page.get("raw_text", "")

    # ─── Compile all alpha patterns ──────────────────────────────────────────
    alpha_patterns = _build_alpha_patterns(all_expressions)

    # ─── Best practices aggregation ──────────────────────────────────────────
    all_tips = []
    for page_key, analysis in key_analyses.items():
        for tip in analysis.get("tip_lines", []):
            all_tips.append(tip)
    best_practices = list(dict.fromkeys(all_tips))[:60]

    # ─── Data field catalog ──────────────────────────────────────────────────
    data_field_catalog = _build_data_catalog(all_pages)

    # ─── Compile pages summary ───────────────────────────────────────────────
    pages_by_value = []
    for page_key, data in all_pages.items():
        text = data.get("raw_text", "")
        exprs = key_analyses.get(page_key, {}).get("expressions", [])
        pages_by_value.append({
            "key": page_key,
            "title": data.get("title", ""),
            "url": data.get("url", ""),
            "text_length": len(text),
            "expressions_count": len(exprs),
            "expressions": exprs,
        })
    pages_by_value.sort(key=lambda x: (-x["text_length"], -x["expressions_count"]))

    # ─── Build final KB ───────────────────────────────────────────────────────
    kb = {
        "compiled_at": datetime.now().isoformat(),
        "crawled_pages": len(all_pages),
        "total_unique_expressions": len(all_expressions),
        "total_operators_documented": len(operator_catalog),

        # Core reference data
        "operator_catalog": operator_catalog,
        "data_field_catalog": data_field_catalog,

        # Alpha patterns organized by type
        "alpha_patterns": alpha_patterns,

        # All unique alpha expressions found
        "all_expressions": [
            {
                "expression": expr,
                "category": data["category"],
                "sources": data["sources"][:3],
            }
            for expr, data in sorted(
                all_expressions.items(),
                key=lambda x: _priority_score(x[0])
            )
        ],

        # Submission criteria
        "submission_criteria": {
            "known_thresholds": {
                "sharpe_min": 1.25,
                "fitness_min": 1.0,
                "turnover_min_pct": 1.0,
                "turnover_max_pct": 70.0,
                "delay_standard": 1,
                "universe_standard": "TOP3000",
                "region_standard": "USA",
            },
            "fitness_formula": "Sharpe * sqrt(|Returns| / max(Turnover, 0.125))",
            "checks_detail": submission_checks_detail,
            "full_text": submission_text[:3000],
        },

        # Simulation settings guide
        "simulation_settings_guide": {
            "default_settings": {
                "instrumentType": "EQUITY",
                "region": "USA",
                "universe": "TOP3000",
                "delay": 1,
                "decay": 4,
                "neutralization": "MARKET",
                "truncation": 0.05,
                "pasteurization": "ON",
                "nanHandling": "OFF",
                "unitHandling": "VERIFY",
                "language": "FASTEXPR",
            },
            "fundamental_recommended": {
                "decay": 0,
                "neutralization": "SUBINDUSTRY",
                "truncation": 0.08,
                "note": "Fundamental factors have quarterly updates, low natural turnover",
            },
            "settings_text": settings_text[:2000],
        },

        # Neutralization guide
        "neutralization_guide": {
            "options": NEUTRALIZATION_OPTIONS,
            "full_text": neut_text[:2000],
            "tips": [
                "MARKET: neutralize vs whole market (removes market beta)",
                "SECTOR: neutralize within sector (good for cross-sector signals)",
                "INDUSTRY: neutralize within industry (more granular)",
                "SUBINDUSTRY: most granular, good for fundamental factors",
                "Use group_rank() to achieve industry-neutral alphas",
            ],
        },

        # How BRAIN works
        "brain_platform_overview": brain_works_text[:3000],

        # Alpha examples from official documentation
        "official_alpha_examples": {
            "beginner_examples": _extract_structured_examples(examples_text),
            "bronze_examples": _extract_structured_examples(sample_text),
            "raw_beginner_text": examples_text,
            "raw_bronze_text": sample_text,
        },

        # Best practices
        "best_practices": best_practices,

        # High-value pages for reference
        "top_pages_by_content": pages_by_value[:20],

        # All discovered URLs (not yet crawled)
        "uncrawled_urls": _get_uncrawled_urls(all_pages),
    }

    return kb


def _classify_expression(expr: str) -> str:
    expr_lower = expr.lower()
    if "group_rank" in expr_lower:
        return "industry_neutral"
    if "ts_corr" in expr_lower:
        return "correlation"
    if "ts_zscore" in expr_lower:
        return "ts_zscore"
    if "ts_rank" in expr_lower:
        if "/" in expr_lower:
            return "ts_rank_ratio"
        return "ts_rank"
    if "ts_delta" in expr_lower:
        return "ts_delta"
    if "ts_std_dev" in expr_lower:
        return "ts_volatility"
    if "rank(" in expr_lower:
        if "/" in expr_lower or "*" in expr_lower:
            return "rank_ratio"
        return "simple_rank"
    if "scale(" in expr_lower:
        return "scaled"
    return "other"


def _priority_score(expr: str) -> int:
    """Higher = better (lower score = shown first in sorted list)."""
    score = 0
    expr_lower = expr.lower()
    # Fundamental fields = high priority
    for field in ["sales", "assets", "liabilities", "equity", "revenue",
                  "operating_income", "net_income", "ebit", "cashflow",
                  "book_value", "enterprise_value", "est_eps", "est_fcf"]:
        if field in expr_lower:
            score -= 3
    # Industry neutral = high priority
    if "group_rank" in expr_lower:
        score -= 2
    # ts operators = medium
    if "ts_rank" in expr_lower or "ts_zscore" in expr_lower:
        score -= 1
    # simple rank = medium
    if "rank(" in expr_lower:
        score -= 1
    return score


def _build_alpha_patterns(all_expressions: dict) -> list:
    """Build structured alpha pattern list."""
    pattern_groups = defaultdict(list)
    for expr, data in all_expressions.items():
        cat = data["category"]
        pattern_groups[cat].append(expr)

    pattern_meta = {
        "rank_ratio": {
            "description": "Cross-sectional rank of a fundamental ratio",
            "example_template": "rank(field_a / field_b)",
            "expected_turnover": "low (1-10%)",
            "expected_fitness": "high",
            "priority": "HIGH",
        },
        "industry_neutral": {
            "description": "Industry-neutral cross-sectional rank",
            "example_template": "group_rank(expression, sector)",
            "expected_turnover": "low-medium (2-20%)",
            "expected_fitness": "high",
            "priority": "HIGH",
        },
        "ts_rank": {
            "description": "Time-series rank over lookback window",
            "example_template": "ts_rank(field, 252)",
            "expected_turnover": "medium (5-30%)",
            "expected_fitness": "medium",
            "priority": "MEDIUM",
        },
        "ts_rank_ratio": {
            "description": "Time-series rank of a ratio",
            "example_template": "ts_rank(field_a/field_b, 252)",
            "expected_turnover": "medium (5-30%)",
            "expected_fitness": "high (ratio reduces noise)",
            "priority": "HIGH",
        },
        "ts_zscore": {
            "description": "Time-series z-score normalization",
            "example_template": "ts_zscore(field, 252)",
            "expected_turnover": "medium (10-40%)",
            "expected_fitness": "medium",
            "priority": "MEDIUM",
        },
        "ts_delta": {
            "description": "Change in variable over time period",
            "example_template": "ts_delta(close, 5)",
            "expected_turnover": "high (30-80%)",
            "expected_fitness": "low-medium (high turnover hurts fitness)",
            "priority": "LOW",
        },
        "correlation": {
            "description": "Time-series correlation between two variables",
            "example_template": "ts_corr(field_a, field_b, 252)",
            "expected_turnover": "medium-high",
            "expected_fitness": "medium",
            "priority": "MEDIUM",
        },
        "ts_volatility": {
            "description": "Volatility-based signal",
            "example_template": "rank(-ts_std_dev(returns, 20))",
            "expected_turnover": "high",
            "expected_fitness": "low",
            "priority": "LOW",
        },
        "simple_rank": {
            "description": "Simple cross-sectional rank of a single field",
            "example_template": "rank(-returns)",
            "expected_turnover": "medium",
            "expected_fitness": "medium",
            "priority": "MEDIUM",
        },
        "scaled": {
            "description": "Scale-normalized expression",
            "example_template": "scale(expression)",
            "expected_turnover": "varies",
            "expected_fitness": "varies",
            "priority": "MEDIUM",
        },
    }

    result = []
    for cat, exprs in sorted(pattern_groups.items(),
                              key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(
                                  pattern_meta.get(x[0], {}).get("priority", "LOW"), 2)):
        meta = pattern_meta.get(cat, {})
        result.append({
            "pattern_type": cat,
            "description": meta.get("description", ""),
            "example_template": meta.get("example_template", ""),
            "expected_turnover": meta.get("expected_turnover", ""),
            "expected_fitness": meta.get("expected_fitness", ""),
            "priority": meta.get("priority", "MEDIUM"),
            "real_examples": list(dict.fromkeys(exprs))[:8],
        })

    return result


def _parse_submission_checks(text: str) -> dict:
    """Parse submission check details from the alpha-submission page."""
    checks = {}

    # Known checks with their descriptions based on what we expect
    check_patterns = {
        "LOW_SHARPE": r"(?:LOW_SHARPE|Sharpe)[^\n]*\n?([^\n]{20,300})",
        "LOW_FITNESS": r"(?:LOW_FITNESS|Fitness)[^\n]*\n?([^\n]{20,300})",
        "HIGH_TURNOVER": r"(?:HIGH_TURNOVER|Turnover)[^\n]*\n?([^\n]{20,300})",
        "LOW_TURNOVER": r"(?:LOW_TURNOVER)[^\n]*\n?([^\n]{20,300})",
        "CONCENTRATED_WEIGHT": r"(?:CONCENTRATED_WEIGHT|concentrated)[^\n]*\n?([^\n]{20,300})",
        "SELF_CORR": r"(?:SELF_CORR|correlation with self|self-correlation)[^\n]*\n?([^\n]{20,300})",
    }

    for check_name, pattern in check_patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            checks[check_name] = m.group(0)[:300].strip()

    # Also extract numbered lists / tables
    lines_with_checks = [
        line.strip() for line in text.split("\n")
        if any(c in line.upper() for c in SUBMISSION_CHECKS)
        and len(line.strip()) > 10
    ]
    if lines_with_checks:
        checks["_raw_check_lines"] = lines_with_checks[:20]

    return checks


def _extract_structured_examples(text: str) -> list:
    """Extract structured alpha examples from documentation text."""
    examples = []
    if not text:
        return examples

    # Split into sections by headers or double newlines
    sections = re.split(r"\n#{1,3}\s+|\n{3,}", text)

    for section in sections:
        section = section.strip()
        if len(section) < 30:
            continue

        # Find expressions in this section
        exprs = extract_all_expressions(section)
        if not exprs:
            continue

        # Extract description (non-expression lines)
        desc_lines = []
        for line in section.split("\n"):
            line = line.strip()
            if not any(op in line for op in ["rank(", "ts_", "group_rank(", "scale("]):
                if len(line) > 15:
                    desc_lines.append(line)

        description = " ".join(desc_lines[:3])[:300]

        for expr in exprs:
            examples.append({
                "expression": expr,
                "context": description,
                "category": _classify_expression(expr),
            })

    return examples


def _build_data_catalog(all_pages: dict) -> dict:
    """Build data field catalog."""
    catalog = {}

    # Fields we know about with their metadata
    known_fields = {
        # Price/Volume
        "close": {"type": "price", "freq": "daily", "description": "Daily closing price"},
        "open": {"type": "price", "freq": "daily", "description": "Daily opening price"},
        "high": {"type": "price", "freq": "daily", "description": "Daily high price"},
        "low": {"type": "price", "freq": "daily", "description": "Daily low price"},
        "volume": {"type": "volume", "freq": "daily", "description": "Daily trading volume"},
        "vwap": {"type": "price", "freq": "daily", "description": "Volume-weighted average price"},
        "returns": {"type": "price", "freq": "daily", "description": "Daily stock returns"},
        "adv20": {"type": "volume", "freq": "daily", "description": "20-day average daily volume"},
        "adv60": {"type": "volume", "freq": "daily", "description": "60-day average daily volume"},
        "cap": {"type": "fundamental", "freq": "daily", "description": "Market capitalization"},
        # Fundamentals
        "assets": {"type": "fundamental", "freq": "quarterly", "description": "Total assets"},
        "liabilities": {"type": "fundamental", "freq": "quarterly", "description": "Total liabilities"},
        "equity": {"type": "fundamental", "freq": "quarterly", "description": "Shareholders equity"},
        "debt": {"type": "fundamental", "freq": "quarterly", "description": "Total debt"},
        "cash_and_equivalents": {"type": "fundamental", "freq": "quarterly", "description": "Cash and cash equivalents"},
        "operating_income": {"type": "fundamental", "freq": "quarterly", "description": "Operating income (EBIT)"},
        "net_income": {"type": "fundamental", "freq": "quarterly", "description": "Net income"},
        "revenue": {"type": "fundamental", "freq": "quarterly", "description": "Total revenue"},
        "sales": {"type": "fundamental", "freq": "quarterly", "description": "Total sales"},
        "ebitda": {"type": "fundamental", "freq": "quarterly", "description": "EBITDA"},
        "ebit": {"type": "fundamental", "freq": "quarterly", "description": "Earnings before interest and taxes"},
        "book_value": {"type": "fundamental", "freq": "quarterly", "description": "Book value per share"},
        "market_cap": {"type": "fundamental", "freq": "daily", "description": "Market capitalization"},
        "shares_outstanding": {"type": "fundamental", "freq": "quarterly", "description": "Shares outstanding"},
        "cash_flow_from_operations": {"type": "fundamental", "freq": "quarterly", "description": "Operating cash flow"},
        "capital_expenditures": {"type": "fundamental", "freq": "quarterly", "description": "Capital expenditures"},
        "free_cash_flow": {"type": "fundamental", "freq": "quarterly", "description": "Free cash flow"},
        "gross_profit": {"type": "fundamental", "freq": "quarterly", "description": "Gross profit"},
        "earnings_per_share": {"type": "fundamental", "freq": "quarterly", "description": "EPS"},
        "dividends": {"type": "fundamental", "freq": "quarterly", "description": "Dividends per share"},
        "retained_earnings": {"type": "fundamental", "freq": "quarterly", "description": "Retained earnings"},
        "total_debt": {"type": "fundamental", "freq": "quarterly", "description": "Total debt"},
        "inventory": {"type": "fundamental", "freq": "quarterly", "description": "Inventory"},
        "accounts_receivable": {"type": "fundamental", "freq": "quarterly", "description": "Accounts receivable"},
        "accounts_payable": {"type": "fundamental", "freq": "quarterly", "description": "Accounts payable"},
        "enterprise_value": {"type": "fundamental", "freq": "quarterly", "description": "Enterprise value"},
        "capex": {"type": "fundamental", "freq": "quarterly", "description": "Capital expenditures (short form)"},
        # Analyst estimates
        "est_eps": {"type": "analyst", "freq": "daily", "description": "Analyst EPS estimate"},
        "est_ptp": {"type": "analyst", "freq": "daily", "description": "Analyst price target"},
        "est_fcf": {"type": "analyst", "freq": "daily", "description": "Analyst free cash flow estimate"},
        "sales_growth": {"type": "analyst", "freq": "quarterly", "description": "Sales growth estimate"},
        "etz_eps": {"type": "analyst", "freq": "daily", "description": "Earnings estimate revision"},
        # Other
        "fn_liab_fair_val_l1_a": {"type": "fundamental", "freq": "quarterly", "description": "Level 1 fair value liabilities"},
        "cashflow": {"type": "fundamental", "freq": "quarterly", "description": "Cash flow"},
        "beta": {"type": "risk", "freq": "daily", "description": "Beta vs market"},
        "short_interest": {"type": "sentiment", "freq": "weekly", "description": "Short interest ratio"},
        # Sentiment
        "scl12_buzz": {"type": "sentiment", "freq": "daily", "description": "Social media buzz score (Sentiment1)"},
    }

    for field, meta in known_fields.items():
        catalog[field] = meta

    # Also add fields found in expressions across pages
    all_expr_text = " ".join([
        data.get("raw_text", "")
        for data in all_pages.values()
    ])

    return catalog


def _get_uncrawled_urls(all_pages: dict) -> list:
    """Get URLs found in links but not yet crawled."""
    crawled_urls = {data.get("url", "") for data in all_pages.values()}
    all_links = set()
    for data in all_pages.values():
        for lnk in data.get("new_links", []):
            url = lnk.get("url", "")
            if url and "/learn/" in url and url not in crawled_urls:
                all_links.add(url)
    return sorted(all_links)[:50]


if __name__ == "__main__":
    kb = build_full_knowledge_base()

    kb_path = ROOT / "data" / "wq_knowledge_base.json"
    kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*70}")
    print("KNOWLEDGE BASE COMPLETE")
    print(f"  Pages analyzed: {kb['crawled_pages']}")
    print(f"  Unique expressions: {kb['total_unique_expressions']}")
    print(f"  Operators documented: {kb['total_operators_documented']}")
    print(f"  Data fields cataloged: {len(kb['data_field_catalog'])}")
    print(f"  Alpha patterns: {len(kb['alpha_patterns'])}")
    print(f"  Best practices: {len(kb['best_practices'])}")
    print(f"  Official examples (beginner): {len(kb['official_alpha_examples']['beginner_examples'])}")
    print(f"  Official examples (bronze): {len(kb['official_alpha_examples']['bronze_examples'])}")
    print(f"\nSaved to: {kb_path}")

    print(f"\n{'='*70}")
    print("ALL ALPHA EXPRESSIONS FOUND:")
    for i, expr_data in enumerate(kb["all_expressions"], 1):
        print(f"  {i:>3}. [{expr_data['category']:<20}] {expr_data['expression'][:80]}")

    print(f"\n{'='*70}")
    print("BEST PRACTICES (top 20):")
    for i, tip in enumerate(kb["best_practices"][:20], 1):
        print(f"  {i:>2}. {tip[:100]}")

    print(f"\n{'='*70}")
    print("OPERATOR CATALOG (first 20):")
    for op, meta in list(kb["operator_catalog"].items())[:20]:
        sig = meta.get("signature", op)
        desc = meta.get("description", "")[:80]
        print(f"  {sig:<40} {desc}")
