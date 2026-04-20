"""
deep_crawl.py - Deep iterative crawl of WorldQuant BRAIN platform.
Crawls priority pages, extracts alpha research insights, discovers new links,
and compiles everything into data/wq_knowledge_base.json.

Usage:
    python scripts/deep_crawl.py
"""
import sys, json, re, time, hashlib, sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SESSION_FILE = r"D:\codeproject\auth-reptile\.state\session.json"
MANUAL_DIR = ROOT / "data" / "crawl_manual"
MANUAL_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = ROOT / "data" / "crawl_state.db"

PRIORITY_URLS = [
    "https://platform.worldquantbrain.com/learn",
    "https://platform.worldquantbrain.com/learn/data-and-tools/fast-expression-language-overview",
    "https://platform.worldquantbrain.com/learn/data-and-tools/operators",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-getting-started",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-improving",
    "https://platform.worldquantbrain.com/learn/data-and-tools/submission-criteria",
    "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog",
    "https://platform.worldquantbrain.com/learn/data-and-tools/financial-data-overview",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-checking",
    "https://platform.worldquantbrain.com/learn/data-and-tools/about-competitions",
    "https://platform.worldquantbrain.com/help",
    "https://platform.worldquantbrain.com/faq",
    "https://www.worldquant.com/brain",
]

ALLOWED_PATTERNS = [
    r"platform\.worldquantbrain\.com/learn",
    r"platform\.worldquantbrain\.com/help",
    r"platform\.worldquantbrain\.com/faq",
    r"worldquant\.com/brain",
]
SKIP_PATTERNS = [
    r"\.(png|jpg|jpeg|gif|svg|ico|css|js|pdf|zip|woff|ttf|map)(\?|$)",
    r"//cdn\.", r"//static\.",
    r"sign-in", r"logout", r"#", r"mailto:", r"javascript:",
    r"/simulate$", r"/alphas$", r"/research$", r"/profile",
    r"/settings", r"/notifications",
]

# ─── Extraction patterns ───────────────────────────────────────────────────────
KNOWN_OPERATORS = [
    "rank", "group_rank", "group_zscore", "scale", "vector_neut",
    "ts_rank", "ts_zscore", "ts_delta", "ts_corr", "ts_std_dev",
    "ts_mean", "ts_sum", "ts_min", "ts_max", "ts_skewness",
    "ts_kurtosis", "ts_regression_slope", "ts_ir",
    "ts_percentage_change", "ts_covariance", "ts_decay_linear",
    "ts_decay_exp_window", "ts_arg_max", "ts_arg_min",
    "log", "abs", "sign", "sqrt", "power", "min", "max",
    "if_else", "clamp", "sigmoid", "tanh",
]

KNOWN_FIELDS = [
    "close", "open", "high", "low", "volume", "vwap", "returns",
    "liabilities", "assets", "equity", "debt", "cash_and_equivalents",
    "operating_income", "net_income", "revenue", "sales", "ebitda",
    "book_value", "market_cap", "shares_outstanding",
    "cash_flow_from_operations", "capital_expenditures", "free_cash_flow",
    "gross_profit", "net_profit_margin", "return_on_equity", "return_on_assets",
    "earnings_per_share", "dividends", "retained_earnings",
    "short_interest", "total_debt", "inventory",
    "accounts_receivable", "accounts_payable",
    "beta", "adv20", "adv60", "enterprise_value",
    "price_to_book", "price_to_earnings", "price_to_sales",
    "debt_to_equity", "current_ratio",
]

EXPR_PATTERNS = [
    r"```(?:fastexpr|fe|alpha|plain)?\n?((?:rank|group_rank|ts_\w+|scale|log|abs|sign)[^`]{3,200}?)```",
    r"`((?:rank|group_rank|ts_\w+|scale)[^`]{3,150}?)`",
    r"\b(rank\s*\(\s*[-\w\s/\*\+\-\(\)]+?\))",
    r"\b(group_rank\s*\([^)]{5,100}\))",
    r"\b(ts_rank\s*\([^,)]{3,60},\s*\d+\))",
    r"\b(ts_zscore\s*\([^,)]{3,60},\s*\d+\))",
    r"\b(ts_delta\s*\([^,)]{3,60},\s*\d+\))",
    r"\b(ts_corr\s*\([^)]{5,100}\))",
    r"\b(ts_std_dev\s*\([^,)]{3,60},\s*\d+\))",
    r"\b(ts_mean\s*\([^,)]{3,60},\s*\d+\))",
    r"\b(scale\s*\([^)]{5,100}\))",
]

SUBMISSION_KEYWORDS = [
    "sharpe", "fitness", "turnover", "returns", "decay",
    "neutralization", "truncation", "pasteurization",
    "delay-1", "delay 1", "submission", "criteria",
    "high_turnover", "low_sharpe", "low_fitness",
    "1.25", "0.125", "70%", "top3000", "universe",
]

BEST_PRACTICE_PATTERNS = [
    r"(?:you should|we recommend|best practice|tip:|note:|important:)[^\n.]{10,200}[.\n]",
    r"(?:avoid|don't|do not|never)[^\n.]{10,150}[.\n]",
    r"(?:to improve|to increase|to boost)[^\n.]{10,150}[.\n]",
    r"sharpe (?:>|>=|above|at least) [\d.]+",
    r"fitness (?:>|>=|above|at least) [\d.]+",
    r"turnover (?:<|<=|below|under) [\d%]+",
]


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def safe_filename(url: str) -> str:
    path = urlparse(url).path.strip("/").replace("/", "_") or "root"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", path)[:80]


def is_allowed(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    for pat in SKIP_PATTERNS:
        if re.search(pat, url, re.I):
            return False
    for pat in ALLOWED_PATTERNS:
        if re.search(pat, url):
            return True
    return False


def normalize_url(href: str, base: str) -> str | None:
    try:
        full = urljoin(base, href)
        parsed = urlparse(full)
        clean = parsed._replace(fragment="", query="").geturl()
        return clean if clean.startswith("http") else None
    except Exception:
        return None


def crawl_page(url: str) -> dict:
    """Crawl a single page using Playwright. Returns extracted content."""
    print(f"  [Crawl] {url[:90]}")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=SESSION_FILE)
            page = ctx.new_page()

            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                page.wait_for_timeout(5000)

            time.sleep(3)

            title = page.title()

            # Try different content selectors
            text_content = ""
            html_content = page.content()
            for sel in ["main", "article", "[class*='content']", "[class*='article']",
                        "[class*='learn']", "[class*='docs']", "body"]:
                try:
                    el = page.query_selector(sel)
                    if el:
                        t = el.inner_text()
                        if len(t) > len(text_content):
                            text_content = t
                        if sel in ["main", "article"] and len(t) > 100:
                            break
                except Exception:
                    pass

            # Extract links
            links = []
            seen_hrefs = set()
            for a in page.query_selector_all("a[href]"):
                try:
                    href = a.get_attribute("href") or ""
                    txt = a.inner_text().strip()[:120]
                    norm = normalize_url(href, url)
                    if norm and norm not in seen_hrefs:
                        seen_hrefs.add(norm)
                        links.append({"href": norm, "text": txt, "raw": href})
                except Exception:
                    pass

            # Extract code blocks
            code_blocks = []
            for el in page.query_selector_all("code, pre"):
                try:
                    code = el.inner_text().strip()
                    if len(code) > 5:
                        code_blocks.append(code)
                except Exception:
                    pass

            browser.close()

            return {
                "url": url, "title": title,
                "text": text_content, "html": html_content,
                "links": links, "code_blocks": code_blocks,
                "error": None,
                "crawled_at": datetime.now().isoformat(),
            }
    except Exception as e:
        print(f"    ERROR: {e}")
        return {
            "url": url, "title": "", "text": "", "html": "",
            "links": [], "code_blocks": [], "error": str(e),
            "crawled_at": datetime.now().isoformat(),
        }


def extract_alpha_expressions(text: str, code_blocks: list) -> list:
    """Extract alpha expression examples."""
    found = set()
    # From code blocks first (most reliable)
    for code in code_blocks:
        for pat in EXPR_PATTERNS:
            for m in re.findall(pat, code, re.IGNORECASE | re.DOTALL):
                expr = m.strip()
                if 5 < len(expr) < 400 and any(op in expr.lower() for op in ["rank", "ts_", "scale"]):
                    found.add(expr)
    # From text
    for pat in EXPR_PATTERNS:
        for m in re.findall(pat, text, re.IGNORECASE | re.DOTALL):
            expr = m.strip()
            if 5 < len(expr) < 400:
                found.add(expr)
    return sorted(found)


def extract_operators_mentioned(text: str) -> list:
    text_lower = text.lower()
    return [op for op in KNOWN_OPERATORS if op + "(" in text_lower or op + " " in text_lower]


def extract_data_fields_mentioned(text: str) -> list:
    text_lower = text.lower()
    found = []
    for field in KNOWN_FIELDS:
        # More precise matching to avoid false positives
        if re.search(r'\b' + re.escape(field) + r'\b', text_lower):
            found.append(field)
    return found


def extract_investment_logic(text: str) -> list:
    """Extract investment logic descriptions."""
    logic = []
    paragraphs = re.split(r'\n{2,}', text)
    for para in paragraphs:
        para = para.strip()
        if len(para) < 60 or len(para) > 800:
            continue
        has_finance = any(kw in para.lower() for kw in [
            "alpha", "signal", "return", "factor", "momentum", "value",
            "quality", "leverage", "correlation", "sharpe", "fitness",
            "neutraliz", "rank", "portfolio", "long", "short",
        ])
        has_quant = any(kw in para.lower() for kw in [
            "rank", "ts_", "scale", "score", "quantile",
        ])
        if has_finance or has_quant:
            logic.append(para[:300])
    return logic[:15]


def extract_best_practices(text: str) -> list:
    """Extract tips and rules."""
    tips = []
    for pat in BEST_PRACTICE_PATTERNS:
        for m in re.findall(pat, text, re.IGNORECASE):
            tip = m.strip()
            if len(tip) > 15:
                tips.append(tip)
    # Also grab submission criteria numbers
    for line in text.split("\n"):
        line = line.strip()
        if any(kw in line.lower() for kw in SUBMISSION_KEYWORDS) and len(line) > 20:
            tips.append(line[:200])
    return list(dict.fromkeys(tips))[:20]  # deduplicate


def extract_operator_definitions(text: str) -> dict:
    """Try to extract operator definitions from structured content."""
    ops = {}
    # Pattern: operator name followed by description
    patterns = [
        r'`(\w+)\(`[^\n]*\n([^\n]{20,300})',
        r'\*\*(\w+)\*\*\s*[-:]\s*([^\n]{20,200})',
        r'#+\s+`?(\w+)`?\s*\n+([^\n#]{20,400})',
        r'(\w+)\(([^)]{3,60})\)\s*[-:]\s*([^\n]{10,200})',
    ]
    for pat in patterns:
        for m in re.findall(pat, text):
            if isinstance(m, tuple) and len(m) >= 2:
                op_name = m[0].lower().strip()
                if op_name in KNOWN_OPERATORS or op_name.startswith("ts_"):
                    desc = m[-1].strip()[:200]
                    if op_name not in ops:
                        ops[op_name] = {"description": desc, "examples": []}
    return ops


def analyze_page(page_data: dict) -> dict:
    """Full analysis of a crawled page."""
    text = page_data.get("text", "")
    code_blocks = page_data.get("code_blocks", [])

    alpha_exprs = extract_alpha_expressions(text, code_blocks)
    operators = extract_operators_mentioned(text)
    data_fields = extract_data_fields_mentioned(text)
    investment_logic = extract_investment_logic(text)
    best_practices = extract_best_practices(text)
    op_defs = extract_operator_definitions(text)

    # Filter new links
    new_links = [
        {"url": lnk["href"], "text": lnk["text"]}
        for lnk in page_data.get("links", [])
        if is_allowed(lnk["href"])
    ]

    return {
        "url": page_data["url"],
        "title": page_data.get("title", ""),
        "crawled_at": page_data.get("crawled_at", ""),
        "raw_text": text[:5000],  # keep first 5k chars
        "alpha_expressions_found": alpha_exprs,
        "operators_mentioned": operators,
        "data_fields_mentioned": data_fields,
        "investment_logic": investment_logic,
        "best_practices": best_practices,
        "operator_definitions": op_defs,
        "new_links": new_links[:50],
        "code_blocks": code_blocks[:20],
    }


def save_manual_page(analysis: dict):
    fname = safe_filename(analysis["url"]) + ".json"
    out = MANUAL_DIR / fname
    out.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    Saved: {fname}")
    return str(out)


def update_crawl_db(url: str, status: str, error: str = None,
                    content_path: str = None):
    """Update the shared crawl_state.db."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        INSERT OR IGNORE INTO crawl_queue (url, depth, status)
        VALUES (?, 0, 'pending')
    """, (url,))
    if status == "done":
        conn.execute("""
            UPDATE crawl_queue
            SET status='done', crawled_at=?, content_path=?
            WHERE url=?
        """, (datetime.now().isoformat(), content_path or "", url))
    elif status == "error":
        conn.execute("""
            UPDATE crawl_queue
            SET status='error', crawled_at=?, error=?
            WHERE url=?
        """, (datetime.now().isoformat(), (error or "")[:200], url))
    conn.commit()
    conn.close()


def add_to_crawl_db(urls: list, from_url: str = "", depth: int = 1):
    """Add discovered URLs to the shared crawl DB."""
    conn = sqlite3.connect(str(DB_PATH))
    added = 0
    for url in urls:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO crawl_queue (url, depth) VALUES (?, ?)",
                (url, depth)
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                added += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added


def compile_knowledge_base(all_analyses: list) -> dict:
    """Compile all page analyses into the master knowledge base."""
    kb = {
        "compiled_at": datetime.now().isoformat(),
        "crawled_pages": len(all_analyses),
        "total_links_found": 0,
        "operator_catalog": {},
        "data_field_catalog": {},
        "alpha_patterns": [],
        "submission_rules": {},
        "best_practices": [],
        "investment_logic": [],
        "new_urls_to_crawl": [],
        "pages_summary": [],
    }

    # Aggregate across all pages
    all_exprs = []
    all_best_practices = []
    all_logic = []
    all_op_defs = defaultdict(dict)
    op_mention_count = defaultdict(int)
    field_mention_count = defaultdict(int)
    all_links = set()

    submission_lines = []

    for analysis in all_analyses:
        url = analysis.get("url", "")

        # Count operator mentions
        for op in analysis.get("operators_mentioned", []):
            op_mention_count[op] += 1

        # Count field mentions
        for field in analysis.get("data_fields_mentioned", []):
            field_mention_count[field] += 1

        # Collect expressions
        for expr in analysis.get("alpha_expressions_found", []):
            all_exprs.append({"expr": expr, "source": url})

        # Collect operator definitions
        for op, defn in analysis.get("operator_definitions", {}).items():
            if op not in all_op_defs or not all_op_defs[op].get("description"):
                all_op_defs[op] = defn

        # Collect best practices
        for tip in analysis.get("best_practices", []):
            all_best_practices.append(tip)

        # Detect submission rules
        text = analysis.get("raw_text", "")
        for line in text.split("\n"):
            if any(kw in line.lower() for kw in ["sharpe", "fitness", "turnover", "criteria"]):
                if len(line.strip()) > 20:
                    submission_lines.append(line.strip()[:200])

        # Collect investment logic
        for logic in analysis.get("investment_logic", []):
            all_logic.append({"logic": logic, "source": url})

        # Collect new links
        for lnk in analysis.get("new_links", []):
            all_links.add(lnk["url"])

        kb["pages_summary"].append({
            "url": url,
            "title": analysis.get("title", ""),
            "expressions_found": len(analysis.get("alpha_expressions_found", [])),
            "operators_mentioned": len(analysis.get("operators_mentioned", [])),
            "data_fields_mentioned": len(analysis.get("data_fields_mentioned", [])),
            "best_practices_found": len(analysis.get("best_practices", [])),
        })

    kb["total_links_found"] = len(all_links)
    kb["new_urls_to_crawl"] = sorted(all_links)[:100]

    # Build operator catalog
    for op in KNOWN_OPERATORS:
        count = op_mention_count.get(op, 0)
        defn = all_op_defs.get(op, {})
        # Find example expressions for this operator
        examples = [e["expr"] for e in all_exprs if op + "(" in e["expr"].lower()][:3]
        kb["operator_catalog"][op] = {
            "description": defn.get("description", ""),
            "mention_count": count,
            "examples": examples,
            "usage_notes": "",
        }

    # Build data field catalog
    field_types = {
        "close": ("price", "daily"), "open": ("price", "daily"),
        "high": ("price", "daily"), "low": ("price", "daily"),
        "volume": ("volume", "daily"), "vwap": ("price", "daily"),
        "returns": ("price", "daily"),
        "liabilities": ("fundamental", "quarterly"),
        "assets": ("fundamental", "quarterly"),
        "equity": ("fundamental", "quarterly"),
        "debt": ("fundamental", "quarterly"),
        "cash_and_equivalents": ("fundamental", "quarterly"),
        "operating_income": ("fundamental", "quarterly"),
        "net_income": ("fundamental", "quarterly"),
        "revenue": ("fundamental", "quarterly"),
        "sales": ("fundamental", "quarterly"),
        "ebitda": ("fundamental", "quarterly"),
        "book_value": ("fundamental", "quarterly"),
        "market_cap": ("fundamental", "daily"),
        "shares_outstanding": ("fundamental", "quarterly"),
        "cash_flow_from_operations": ("fundamental", "quarterly"),
        "capital_expenditures": ("fundamental", "quarterly"),
        "free_cash_flow": ("fundamental", "quarterly"),
        "gross_profit": ("fundamental", "quarterly"),
        "earnings_per_share": ("fundamental", "quarterly"),
        "dividends": ("fundamental", "quarterly"),
        "retained_earnings": ("fundamental", "quarterly"),
        "short_interest": ("sentiment", "weekly"),
        "total_debt": ("fundamental", "quarterly"),
        "inventory": ("fundamental", "quarterly"),
        "accounts_receivable": ("fundamental", "quarterly"),
        "accounts_payable": ("fundamental", "quarterly"),
        "beta": ("risk", "daily"),
        "adv20": ("volume", "daily"), "adv60": ("volume", "daily"),
    }
    for field in KNOWN_FIELDS:
        ftype, freq = field_types.get(field, ("unknown", "unknown"))
        kb["data_field_catalog"][field] = {
            "description": "",
            "type": ftype,
            "update_freq": freq,
            "mention_count": field_mention_count.get(field, 0),
        }

    # Build alpha patterns from collected expressions
    pattern_groups = defaultdict(list)
    for e in all_exprs:
        expr = e["expr"]
        # Classify by operator
        if "group_rank" in expr:
            pattern_groups["industry_neutral_rank"].append(expr)
        elif "rank(" in expr and "/" in expr:
            pattern_groups["rank_ratio"].append(expr)
        elif "rank(" in expr and expr.count("(") == 1:
            pattern_groups["simple_rank"].append(expr)
        elif "ts_rank" in expr:
            pattern_groups["ts_rank_signal"].append(expr)
        elif "ts_zscore" in expr:
            pattern_groups["ts_zscore_signal"].append(expr)
        elif "ts_delta" in expr:
            pattern_groups["ts_delta_signal"].append(expr)
        elif "ts_corr" in expr:
            pattern_groups["correlation_signal"].append(expr)
        else:
            pattern_groups["other"].append(expr)

    priority_map = {
        "rank_ratio": "HIGH", "industry_neutral_rank": "HIGH",
        "simple_rank": "MEDIUM", "ts_rank_signal": "MEDIUM",
        "ts_zscore_signal": "MEDIUM", "ts_delta_signal": "LOW",
        "correlation_signal": "LOW", "other": "LOW",
    }
    behavior_map = {
        "rank_ratio": "Low turnover fundamental ratio alpha",
        "industry_neutral_rank": "Industry-neutral, low bias",
        "simple_rank": "Simple cross-sectional rank signal",
        "ts_rank_signal": "Time-series momentum/rank signal, moderate turnover",
        "ts_zscore_signal": "Normalized time-series signal",
        "ts_delta_signal": "Change-in-variable signal, higher turnover",
        "correlation_signal": "Correlation-based signal",
        "other": "Mixed/complex signal",
    }
    for pname, exprs in pattern_groups.items():
        kb["alpha_patterns"].append({
            "pattern": pname,
            "examples": list(dict.fromkeys(exprs))[:5],
            "expected_behavior": behavior_map.get(pname, ""),
            "priority": priority_map.get(pname, "MEDIUM"),
        })

    # Deduplicate best practices
    seen_tips = set()
    for tip in all_best_practices:
        tip_clean = tip.strip()
        if tip_clean and tip_clean not in seen_tips and len(tip_clean) > 20:
            seen_tips.add(tip_clean)
            kb["best_practices"].append(tip_clean)

    # Submission rules (deduplicated)
    seen_rules = set()
    for line in submission_lines:
        if line not in seen_rules:
            seen_rules.add(line)
    kb["submission_rules"] = {
        "raw_lines": sorted(seen_rules)[:30],
        "known_thresholds": {
            "sharpe_min": 1.25,
            "fitness_min": 1.0,
            "turnover_min_pct": 1.0,
            "turnover_max_pct": 70.0,
            "delay": 1,
            "universe": "TOP3000",
        },
        "fitness_formula": "Sharpe * sqrt(|Returns| / max(Turnover, 0.125))",
    }

    # Investment logic (sample)
    kb["investment_logic"] = [
        {"logic": item["logic"][:300], "source": item["source"]}
        for item in all_logic[:30]
    ]

    return kb


def run_deep_crawl():
    """Main crawl loop."""
    print(f"\n{'='*70}")
    print("DEEP CRAWL — WorldQuant BRAIN Platform")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    crawled_analyses = []
    crawled_urls = set()
    queue = list(PRIORITY_URLS)
    discovered_secondary = []
    save_checkpoint_every = 5

    # Round 1: Priority pages
    print(f"\n[Round 1] Crawling {len(PRIORITY_URLS)} priority pages...")
    for i, url in enumerate(queue, 1):
        if url in crawled_urls:
            continue
        print(f"\n[{i}/{len(queue)}] {url}")
        page_data = crawl_page(url)
        crawled_urls.add(url)

        if page_data["error"]:
            update_crawl_db(url, "error", error=page_data["error"])
            print(f"  SKIP (error): {page_data['error'][:60]}")
            continue

        analysis = analyze_page(page_data)
        saved_path = save_manual_page(analysis)
        update_crawl_db(url, "done", content_path=saved_path)
        crawled_analyses.append(analysis)

        # Discover secondary links
        for lnk in analysis["new_links"]:
            lnk_url = lnk["url"]
            if lnk_url not in crawled_urls and lnk_url not in discovered_secondary:
                discovered_secondary.append(lnk_url)

        print(f"  Title: {analysis['title'][:60]}")
        print(f"  Expressions: {len(analysis['alpha_expressions_found'])}")
        print(f"  Operators: {len(analysis['operators_mentioned'])}")
        print(f"  Fields: {len(analysis['data_fields_mentioned'])}")
        print(f"  New links: {len(analysis['new_links'])}")

        # Checkpoint every N pages
        if i % save_checkpoint_every == 0:
            kb = compile_knowledge_base(crawled_analyses)
            kb_path = ROOT / "data" / "wq_knowledge_base.json"
            kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  [Checkpoint] KB saved ({i} pages crawled)")

    print(f"\n[Round 1 Complete] Crawled {len(crawled_analyses)} pages")
    print(f"Discovered {len(discovered_secondary)} secondary URLs")

    # Round 2: Secondary /learn/* pages (depth 1)
    # Filter and prioritize learn pages
    secondary_learn = [
        u for u in discovered_secondary
        if "/learn/" in u and u not in crawled_urls
    ]
    secondary_other = [
        u for u in discovered_secondary
        if "/learn/" not in u and u not in crawled_urls
    ]

    print(f"\n[Round 2] Crawling {min(20, len(secondary_learn))} secondary learn pages...")
    for i, url in enumerate(secondary_learn[:20], 1):
        if url in crawled_urls:
            continue
        print(f"\n[R2-{i}] {url[:80]}")
        page_data = crawl_page(url)
        crawled_urls.add(url)

        if page_data["error"]:
            update_crawl_db(url, "error", error=page_data["error"])
            continue

        analysis = analyze_page(page_data)
        saved_path = save_manual_page(analysis)
        update_crawl_db(url, "done", content_path=saved_path)
        crawled_analyses.append(analysis)

        print(f"  Title: {analysis['title'][:60]}")
        print(f"  Expressions: {len(analysis['alpha_expressions_found'])}")

        if i % save_checkpoint_every == 0:
            kb = compile_knowledge_base(crawled_analyses)
            kb_path = ROOT / "data" / "wq_knowledge_base.json"
            kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  [Checkpoint] KB saved ({len(crawled_analyses)} total pages)")

    # Round 3: Any remaining high-value secondary pages
    print(f"\n[Round 3] Crawling {min(10, len(secondary_other))} other secondary pages...")
    for i, url in enumerate(secondary_other[:10], 1):
        if url in crawled_urls:
            continue
        print(f"\n[R3-{i}] {url[:80]}")
        page_data = crawl_page(url)
        crawled_urls.add(url)

        if page_data["error"]:
            update_crawl_db(url, "error", error=page_data["error"])
            continue

        analysis = analyze_page(page_data)
        saved_path = save_manual_page(analysis)
        update_crawl_db(url, "done", content_path=saved_path)
        crawled_analyses.append(analysis)
        print(f"  Title: {analysis['title'][:60]}")

    # Add all discovered secondary URLs to DB for future crawls
    new_added = add_to_crawl_db(
        [u for u in discovered_secondary + secondary_learn + secondary_other
         if u not in crawled_urls],
        depth=1
    )
    print(f"\nAdded {new_added} new URLs to crawl DB for future runs")

    # Final knowledge base compilation
    print(f"\n{'='*70}")
    print(f"Compiling final knowledge base from {len(crawled_analyses)} pages...")
    kb = compile_knowledge_base(crawled_analyses)
    kb_path = ROOT / "data" / "wq_knowledge_base.json"
    kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*70}")
    print("CRAWL COMPLETE")
    print(f"  Pages crawled: {kb['crawled_pages']}")
    print(f"  Total links found: {kb['total_links_found']}")
    print(f"  Operators cataloged: {len(kb['operator_catalog'])}")
    print(f"  Data fields cataloged: {len(kb['data_field_catalog'])}")
    print(f"  Alpha patterns: {len(kb['alpha_patterns'])}")
    print(f"  Best practices: {len(kb['best_practices'])}")
    print(f"  Saved to: {kb_path}")

    # Print summary of extracted expressions
    print(f"\nAlpha expressions found by pattern type:")
    for pattern in kb["alpha_patterns"]:
        if pattern["examples"]:
            print(f"  [{pattern['priority']}] {pattern['pattern']}: {len(pattern['examples'])} examples")
            for ex in pattern["examples"][:2]:
                print(f"    {ex[:80]}")

    return kb


if __name__ == "__main__":
    kb = run_deep_crawl()
    print("\nDone.")
