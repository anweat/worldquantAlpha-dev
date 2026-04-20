"""
deep_crawl_phase2.py - Phase 2: Target high-value documentation and alpha example pages.
Focus on: documentation/examples, documentation/create-alphas, documentation/interpret-results,
          documentation/advanced-topics, quantcepts lessons, operators page.
"""
import sys, json, re, time, hashlib, sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Import helpers from deep_crawl
from deep_crawl import (
    crawl_page, analyze_page, save_manual_page,
    update_crawl_db, add_to_crawl_db, compile_knowledge_base,
    MANUAL_DIR, KNOWN_OPERATORS, KNOWN_FIELDS, is_allowed
)

SESSION_FILE = r"D:\codeproject\auth-reptile\.state\session.json"

PHASE2_PRIORITY = [
    # Alpha examples - HIGHEST priority
    "https://platform.worldquantbrain.com/learn/documentation/examples/19-alpha-examples",
    "https://platform.worldquantbrain.com/learn/documentation/examples/sample-alpha-concepts",
    # Create alphas
    "https://platform.worldquantbrain.com/learn/documentation/create-alphas/running-your-first-alpha",
    "https://platform.worldquantbrain.com/learn/documentation/create-alphas/simulation-settings",
    "https://platform.worldquantbrain.com/learn/documentation/create-alphas/another-sample-alpha",
    "https://platform.worldquantbrain.com/learn/documentation/create-alphas/how-brain-platform-works",
    "https://platform.worldquantbrain.com/learn/documentation/create-alphas/test-period",
    # Submission / interpret results
    "https://platform.worldquantbrain.com/learn/documentation/interpret-results/alpha-submission",
    "https://platform.worldquantbrain.com/learn/documentation/interpret-results/parameters-simulation-results",
    # Advanced topics
    "https://platform.worldquantbrain.com/learn/documentation/advanced-topics/list-must-read-posts-how-improve-your-alphas-are-submitted",
    "https://platform.worldquantbrain.com/learn/documentation/advanced-topics/neut-cons",
    # Understanding data
    "https://platform.worldquantbrain.com/learn/documentation/understanding-data/data",
    "https://platform.worldquantbrain.com/learn/documentation/understanding-data/vector-datafields",
    "https://platform.worldquantbrain.com/learn/documentation/understanding-data/getting-started-sentiment1-dataset",
    "https://platform.worldquantbrain.com/learn/documentation/understanding-data/how-use-data-explorer",
    # Operators full list
    "https://platform.worldquantbrain.com/learn/operators/operators",
    "https://platform.worldquantbrain.com/learn/operators/datasets",
    # Quantcepts video lessons (may have transcripts)
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/company-fundamentals",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/momentum-alphas",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/types-alpha-ideas",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/how-assess-alpha",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/price-volume-data",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/sentiment-data",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/options-data",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/what-alpha",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/holding-periods",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/seasonality",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/diversity",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/how-diversify-alphas",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/how-do-you-make-risk-neutral-alphas",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/why-eliminate-risk-exposure",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/why-use-delayed-data",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/what-market-neutral-investing",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/what-are-factor-risks",
    # Alpha examples courses
    "https://platform.worldquantbrain.com/learn/courses/alpha-examples-data-category/alpha-examples-data-category-part-1",
    "https://platform.worldquantbrain.com/learn/courses/alpha-examples-data-category/alpha-examples-data-category-part-2",
    "https://platform.worldquantbrain.com/learn/courses/alpha-examples-idea-type-and-delay/alpha-examples-idea-type",
    "https://platform.worldquantbrain.com/learn/courses/alpha-examples-idea-type-and-delay/alphas-holding-frequencies-and-delays",
    # Introduction alphas
    "https://platform.worldquantbrain.com/learn/courses/introduction-alphas/alpha",
    "https://platform.worldquantbrain.com/learn/courses/introduction-alphas/alpha-expression-to-pnl",
    "https://platform.worldquantbrain.com/learn/courses/introduction-alphas/making-alpha-simulating-alpha",
    "https://platform.worldquantbrain.com/learn/courses/introduction-alphas/making-alpha-simulation-settings",
    "https://platform.worldquantbrain.com/learn/courses/introduction-alphas/simulation-results",
    # IQC / competition
    "https://platform.worldquantbrain.com/learn/courses/international-quant-championship-2026/iqc-scoring-merged-alpha-performance-criteria",
    "https://platform.worldquantbrain.com/learn/courses/international-quant-championship-2026/test-period",
    # Basic operator lessons
    "https://platform.worldquantbrain.com/learn/courses/basic-operators/correlation-rank-operators",
    "https://platform.worldquantbrain.com/learn/courses/basic-operators/product-rank-signed-power-operators",
    "https://platform.worldquantbrain.com/learn/courses/basic-operators/step-sum-indneutralize-operators",
    "https://platform.worldquantbrain.com/learn/courses/basic-operators/scale-groupmean-operators",
]

# Already crawled in phase 1
ALREADY_CRAWLED = {
    p.stem.replace("_", "/").replace("-", "-")
    for p in MANUAL_DIR.glob("*.json")
}


def get_already_crawled_urls():
    """Get set of already-crawled URLs from saved JSON files."""
    crawled = set()
    for p in MANUAL_DIR.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        url = d.get("url", "")
        if url:
            crawled.add(url)
    return crawled


def crawl_page_extended(url: str) -> dict:
    """
    Crawl page with extended wait and full-text extraction.
    For documentation pages with lot of content.
    """
    print(f"  [CrawlExt] {url[:90]}")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=SESSION_FILE)
            page = ctx.new_page()

            try:
                page.goto(url, wait_until="networkidle", timeout=40000)
            except Exception:
                pass

            # Extended wait for JS rendering
            time.sleep(5)

            # Try to scroll to load lazy content
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1)
            except Exception:
                pass

            title = page.title()

            # Try progressively more specific selectors for content
            text_content = ""
            html_content = page.content()

            # Try to get the richest text block
            content_selectors = [
                "article",
                "main article",
                "[class*='article']",
                "[class*='documentation']",
                "[class*='doc-content']",
                "[class*='markdown']",
                "[class*='content-body']",
                ".content",
                "main",
                "[class*='post-body']",
                "[class*='lesson']",
                "[class*='course-content']",
                "body",
            ]
            for sel in content_selectors:
                try:
                    els = page.query_selector_all(sel)
                    for el in els:
                        t = el.inner_text()
                        if len(t) > len(text_content):
                            text_content = t
                    if len(text_content) > 500 and sel not in ["main", "body"]:
                        break
                except Exception:
                    pass

            # Extract code blocks
            code_blocks = []
            for sel in ["code", "pre", "[class*='code']", "[class*='highlight']"]:
                for el in page.query_selector_all(sel):
                    try:
                        code = el.inner_text().strip()
                        if len(code) > 3:
                            code_blocks.append(code)
                    except Exception:
                        pass

            # Extract links
            links = []
            seen_hrefs = set()
            for a in page.query_selector_all("a[href]"):
                try:
                    href = a.get_attribute("href") or ""
                    txt = a.inner_text().strip()[:120]
                    from deep_crawl import normalize_url
                    norm = normalize_url(href, url)
                    if norm and norm not in seen_hrefs:
                        seen_hrefs.add(norm)
                        links.append({"href": norm, "text": txt, "raw": href})
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


def analyze_page_full(page_data: dict) -> dict:
    """Full analysis with NO truncation of raw_text."""
    from deep_crawl import (
        extract_alpha_expressions, extract_operators_mentioned,
        extract_data_fields_mentioned, extract_investment_logic,
        extract_best_practices, extract_operator_definitions,
        KNOWN_OPERATORS, KNOWN_FIELDS,
    )
    text = page_data.get("text", "")
    code_blocks = page_data.get("code_blocks", [])

    alpha_exprs = extract_alpha_expressions(text, code_blocks)
    operators = extract_operators_mentioned(text)
    data_fields = extract_data_fields_mentioned(text)
    investment_logic = extract_investment_logic(text)
    best_practices = extract_best_practices(text)
    op_defs = extract_operator_definitions(text)

    new_links = [
        {"url": lnk["href"], "text": lnk["text"]}
        for lnk in page_data.get("links", [])
        if is_allowed(lnk["href"])
    ]

    return {
        "url": page_data["url"],
        "title": page_data.get("title", ""),
        "crawled_at": page_data.get("crawled_at", ""),
        "raw_text": text,  # FULL text, no truncation
        "alpha_expressions_found": alpha_exprs,
        "operators_mentioned": operators,
        "data_fields_mentioned": data_fields,
        "investment_logic": investment_logic,
        "best_practices": best_practices,
        "operator_definitions": op_defs,
        "new_links": new_links[:60],
        "code_blocks": code_blocks[:30],
    }


def run_phase2():
    print(f"\n{'='*70}")
    print("DEEP CRAWL PHASE 2 — Documentation & Alpha Examples")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    already_crawled = get_already_crawled_urls()
    print(f"Already crawled: {len(already_crawled)} pages")

    all_analyses = []

    # Load existing phase 1 analyses
    for p in sorted(MANUAL_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("url") and d.get("raw_text"):
                all_analyses.append(d)
        except Exception:
            pass
    print(f"Loaded {len(all_analyses)} phase 1 analyses")

    # Phase 2: Crawl priority documentation pages
    to_crawl = [u for u in PHASE2_PRIORITY if u not in already_crawled]
    print(f"\nPhase 2: {len(to_crawl)} new pages to crawl")

    new_analyses = []
    save_every = 5

    for i, url in enumerate(to_crawl, 1):
        print(f"\n[P2-{i}/{len(to_crawl)}] {url[:80]}")
        page_data = crawl_page_extended(url)

        if page_data["error"]:
            update_crawl_db(url, "error", error=page_data["error"])
            print(f"  SKIP (error)")
            continue

        analysis = analyze_page_full(page_data)
        saved_path = save_manual_page(analysis)
        update_crawl_db(url, "done", content_path=saved_path)
        new_analyses.append(analysis)
        all_analyses.append(analysis)

        text_len = len(analysis.get("raw_text", ""))
        exprs = analysis.get("alpha_expressions_found", [])
        ops = analysis.get("operators_mentioned", [])
        fields = analysis.get("data_fields_mentioned", [])
        bp = analysis.get("best_practices", [])

        print(f"  Title: {analysis['title'][:60]}")
        print(f"  Text: {text_len} chars | Exprs: {len(exprs)} | Ops: {len(ops)} | Fields: {len(fields)}")
        if exprs:
            print(f"  Expressions found:")
            for e in exprs[:5]:
                print(f"    {e[:80]}")
        if bp:
            print(f"  Best practices: {len(bp)}")

        if i % save_every == 0:
            kb = compile_knowledge_base(all_analyses)
            kb_path = ROOT / "data" / "wq_knowledge_base.json"
            kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  [Checkpoint] KB saved ({len(all_analyses)} total pages)")

    print(f"\n[Phase 2 Complete] Crawled {len(new_analyses)} new pages")

    # Compile and save final knowledge base
    print(f"\n{'='*70}")
    print(f"Compiling final knowledge base from {len(all_analyses)} total pages...")
    kb = compile_knowledge_base(all_analyses)

    # Enrich with all text from high-value pages
    print("Enriching knowledge base with full text extracts...")
    rich_extracts = []
    for analysis in all_analyses:
        text = analysis.get("raw_text", "")
        if len(text) > 500:
            rich_extracts.append({
                "url": analysis["url"],
                "title": analysis.get("title", ""),
                "text_length": len(text),
                "alpha_expressions": analysis.get("alpha_expressions_found", []),
                "operators": analysis.get("operators_mentioned", []),
                "data_fields": analysis.get("data_fields_mentioned", []),
                "text_excerpt": text[:2000],
            })

    kb["rich_content_pages"] = sorted(rich_extracts, key=lambda x: -x["text_length"])

    kb_path = ROOT / "data" / "wq_knowledge_base.json"
    kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*70}")
    print("PHASE 2 COMPLETE")
    print(f"  Total pages crawled: {kb['crawled_pages']}")
    print(f"  Total links found: {kb['total_links_found']}")
    print(f"  Alpha patterns: {len(kb['alpha_patterns'])}")
    print(f"  Best practices: {len(kb['best_practices'])}")
    print(f"  Rich content pages: {len(kb.get('rich_content_pages', []))}")
    print(f"  Saved to: {kb_path}")

    print(f"\nTop expressions found:")
    for pat in kb["alpha_patterns"]:
        if pat["examples"]:
            print(f"  [{pat['priority']}] {pat['pattern']}: {len(pat['examples'])} examples")
            for ex in pat["examples"][:3]:
                print(f"    {ex[:80]}")

    print(f"\nTop rich content pages:")
    for p in kb.get("rich_content_pages", [])[:10]:
        print(f"  {p['text_length']:>6} chars | {len(p['alpha_expressions']):>3} exprs | {p['title'][:50]}")

    return kb


if __name__ == "__main__":
    kb = run_phase2()
    print("\nDone.")
