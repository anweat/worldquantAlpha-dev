"""
Crawl2 - Expanded WorldQuant BRAIN Knowledge Base
Targets: data catalog, datasets, competitions, analyst/news/options data pages
"""
import sys, json, time, re
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(r"D:\codeproject\worldquantAlpha-dev")
SESSION_FILE = r"D:\codeproject\auth-reptile\.state\session.json"
OUT_DIR = ROOT / "data" / "crawl_manual"
OUT_DIR.mkdir(parents=True, exist_ok=True)

KB_FILE = ROOT / "data" / "wq_knowledge_base.json"
SUMMARY_FILE = ROOT / "data" / "crawl2_summary.json"

# All target URLs - Tier1 first, then Tier2
TARGETS = [
    # Tier 1
    "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog",
    "https://platform.worldquantbrain.com/learn/data-and-tools/datasets",
    "https://platform.worldquantbrain.com/learn/data-and-tools/financial-data-overview",
    "https://platform.worldquantbrain.com/learn/competitions",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-examples",
    "https://platform.worldquantbrain.com/competitions",
    "https://platform.worldquantbrain.com/learn/data-and-tools/analysts-data",
    "https://platform.worldquantbrain.com/learn/data-and-tools/news-data",
    "https://platform.worldquantbrain.com/learn/data-and-tools/fundamental-data",
    # Tier 2
    "https://platform.worldquantbrain.com/learn/courses",
    "https://platform.worldquantbrain.com/learn/courses/intermediate",
    "https://platform.worldquantbrain.com/learn/courses/advanced",
    "https://platform.worldquantbrain.com/learn/data-and-tools/expressions",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-performance",
    # Additional targets that might have useful info
    "https://platform.worldquantbrain.com/learn/documentation/understanding-data/data",
    "https://platform.worldquantbrain.com/learn/documentation/advanced-topics/list-must-read-posts-how-improve-your-alphas",
    "https://platform.worldquantbrain.com/learn/operators/datasets",
    "https://platform.worldquantbrain.com/learn/documentation/discover-brain/intermediate-pack-part-1",
    "https://platform.worldquantbrain.com/learn/documentation/discover-brain/intermediate-pack-part-2",
    "https://platform.worldquantbrain.com/learn/documentation/examples/19-alpha-examples",
    "https://platform.worldquantbrain.com/learn/documentation/examples/sample-alpha-concepts",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/options-data",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/sentiment-data",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/price-volume-data",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/company-fundamentals",
    "https://platform.worldquantbrain.com/learn/courses/alpha-examples-data-category",
]

# Patterns to detect data fields
FIELD_PATTERNS = [
    r'\best_[a-z_]+\b',           # est_eps, est_revenue, etc.
    r'\betz_[a-z_]+\b',           # etz_* fields
    r'\bfn_[a-z_]+\b',            # fn_liab_*, fn_* financial
    r'\bscl12_[a-z_]+\b',         # news/sentiment
    r'\bmodel_[a-z_]+\b',         # model outputs
    r'\bvec_[a-z_]+\b',           # vector fields
    r'\bsharadar_[a-z_]+\b',      # Sharadar data
    r'\bhltvol[a-z_]*\b',         # volatility
    r'\bimplied_vol[a-z_]*\b',    # options implied vol
    r'\bparkinson[a-z_]*\b',      # Parkinson volatility
    r'\badv[0-9]+\b',              # average daily volume variants
    r'\bnews_[a-z_]+\b',          # news fields
    r'\bsentiment[a-z_]*\b',      # sentiment fields
    r'\banalyst[a-z_]*\b',        # analyst fields
    # Common standalone fields
    r'\b(close|open|high|low|volume|vwap|returns|shares|cap|adv20|adv60|adv120)\b',
    r'\b(liabilities|assets|equity|sales|revenue|earnings|income|ebitda)\b',
    r'\b(operating_income|net_income|cash|debt|book_value)\b',
    r'\b(pe_ratio|pb_ratio|ps_ratio|ev_ebitda)\b',
]

# Alpha expression patterns
ALPHA_PATTERNS = [
    r'(?:rank|ts_rank|group_rank|ts_corr|ts_std_dev|ts_delta|ts_mean|ts_zscore|ts_sum|ts_skewness|ts_kurtosis|ts_max|ts_min|ts_arg_max|ts_arg_min|ts_backfill|ts_decay_linear|ts_decay_exp_window)\s*\([^)]{5,100}\)',
    r'(?:scale|indneutralize|group_mean|group_zscore|rank_by_side|signed_power|pasteurize|left_tail|right_tail|tail)\s*\([^)]{5,100}\)',
    r'-?\s*ts_rank\([^)]+\)',
    r'group_rank\([^)]+\)',
]

def url_to_filename(url: str) -> str:
    """Convert URL to safe filename."""
    path = url.replace("https://platform.worldquantbrain.com/", "")
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', path).strip('_')
    return safe[:120] + ".json"

def extract_fields(text: str) -> list:
    """Extract data field names from text."""
    found = set()
    for pat in FIELD_PATTERNS:
        matches = re.findall(pat, text, re.IGNORECASE)
        found.update(m.lower() for m in matches)
    # Filter out common words that match patterns accidentally
    noise = {'close', 'open', 'high', 'low', 'volume', 'returns', 'shares', 'cap', 
             'assets', 'equity', 'sales', 'revenue', 'earnings', 'income', 'cash', 
             'debt', 'sentiment', 'analyst', 'news'}
    # Keep field-specific matches but also keep structured ones like est_eps
    structured = {f for f in found if '_' in f or f not in noise}
    return sorted(structured)

def extract_alpha_exprs(text: str) -> list:
    """Extract alpha expression snippets from text."""
    found = set()
    for pat in ALPHA_PATTERNS:
        matches = re.findall(pat, text, re.IGNORECASE)
        found.update(m.strip() for m in matches if len(m) > 10)
    return sorted(found)[:20]  # cap at 20

def extract_key_insights(text: str, url: str) -> list:
    """Extract key insights from page text."""
    insights = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    # Look for insightful sentences
    keywords = ['sharpe', 'fitness', 'turnover', 'neutralization', 'decay', 'truncation',
                'subindustry', 'industry', 'market', 'sector', 'fundamental', 'momentum',
                'reversal', 'sentiment', 'analyst', 'options', 'implied', 'delay',
                'submission', 'criteria', 'check', 'pass', 'fail', 'improve',
                'correlation', 'decay', 'alpha', 'signal', 'factor', 'rank',
                'ts_rank', 'group_rank', 'dataset', 'field']
    
    for line in lines:
        if len(line) > 40 and len(line) < 500:
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords):
                insights.append(line)
        if len(insights) >= 30:
            break
    
    return insights[:20]

def crawl_page(page, url: str) -> dict:
    """Crawl a single page, return extracted data."""
    result = {
        "url": url,
        "title": "",
        "crawled_at": datetime.utcnow().isoformat(),
        "raw_text_length": 0,
        "raw_text_preview": "",
        "data_fields_found": [],
        "alpha_expressions_found": [],
        "key_insights": [],
        "new_links": [],
        "error": None
    }
    
    try:
        resp = page.goto(url, wait_until="networkidle", timeout=35000)
        status = resp.status if resp else 0
        
        if status == 404:
            result["error"] = "404 Not Found"
            return result
        
        # Check if redirected to sign-in
        current_url = page.url
        if "sign-in" in current_url or "login" in current_url:
            result["error"] = "SESSION_EXPIRED: redirected to sign-in"
            return result
        
        time.sleep(4)
        result["title"] = page.title()
        
        # Extract text using multiple selectors
        text = ""
        for sel in ["main", "article", "[class*='content']", "[class*='learn']", 
                    "[class*='course']", "[class*='doc']", "body"]:
            try:
                els = page.query_selector_all(sel)
                if els:
                    candidate = els[0].inner_text()
                    if len(candidate) > len(text):
                        text = candidate
                        if len(text) > 500:
                            break
            except Exception:
                pass
        
        result["raw_text_length"] = len(text)
        result["raw_text_preview"] = text[:3000]
        
        # Extract data fields, alpha expressions, and insights
        result["data_fields_found"] = extract_fields(text)
        result["alpha_expressions_found"] = extract_alpha_exprs(text)
        result["key_insights"] = extract_key_insights(text, url)
        
        # Extract links
        links = []
        for a in page.query_selector_all("a[href]"):
            try:
                href = a.get_attribute("href") or ""
                txt = a.inner_text().strip()[:100]
                if href and ("worldquant" in href or href.startswith("/")):
                    if href.startswith("/"):
                        href = "https://platform.worldquantbrain.com" + href
                    links.append({"url": href, "text": txt})
            except Exception:
                pass
        
        # Deduplicate links
        seen_urls = set()
        deduped = []
        for lk in links:
            if lk["url"] not in seen_urls:
                seen_urls.add(lk["url"])
                deduped.append(lk)
        result["new_links"] = deduped[:50]
        
    except Exception as e:
        result["error"] = str(e)
    
    return result

def main():
    from playwright.sync_api import sync_playwright
    
    all_fields = set()
    all_exprs = set()
    all_insights = []
    new_links_found = set()
    pages_crawled = 0
    session_expired = False
    results_per_page = {}
    
    print(f"[crawl2] Starting expanded crawl of {len(TARGETS)} URLs")
    print(f"[crawl2] Output dir: {OUT_DIR}")
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=SESSION_FILE)
        page = ctx.new_page()
        
        for i, url in enumerate(TARGETS):
            fname = url_to_filename(url)
            out_path = OUT_DIR / fname
            
            print(f"\n[{i+1}/{len(TARGETS)}] Crawling: {url}")
            
            result = crawl_page(page, url)
            pages_crawled += 1
            
            if result.get("error"):
                err = result["error"]
                print(f"  ERROR: {err}")
                if "SESSION_EXPIRED" in err:
                    session_expired = True
                    print("[crawl2] Session expired! Stopping.")
                    break
                # Save error result anyway
                out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                continue
            
            print(f"  Title: {result['title']}")
            print(f"  Text length: {result['raw_text_length']}")
            print(f"  Fields found: {len(result['data_fields_found'])}")
            print(f"  Exprs found: {len(result['alpha_expressions_found'])}")
            print(f"  Insights: {len(result['key_insights'])}")
            
            # Accumulate
            all_fields.update(result["data_fields_found"])
            all_exprs.update(result["alpha_expressions_found"])
            all_insights.extend(result["key_insights"][:5])
            for lk in result["new_links"]:
                new_links_found.add(lk["url"])
            
            results_per_page[url] = result
            
            # Save per-page result
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"  Saved: {fname}")
            
            # Save partial summary every 5 pages
            if (i + 1) % 5 == 0:
                _save_partial_summary(pages_crawled, all_fields, all_exprs, all_insights)
            
            # Rate limiting
            time.sleep(3)
        
        browser.close()
    
    # Final summary
    summary = {
        "crawled_at": datetime.utcnow().isoformat(),
        "pages_crawled": pages_crawled,
        "session_expired": session_expired,
        "new_data_fields": sorted(all_fields),
        "new_alpha_examples": sorted(all_exprs),
        "key_discoveries": list(dict.fromkeys(all_insights))[:40],  # deduplicate, keep order
        "urls_still_to_crawl": [],
        "new_links_found": sorted(new_links_found)[:100],
    }
    
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n[crawl2] Summary saved: {SUMMARY_FILE}")
    
    # Update knowledge base
    _update_knowledge_base(all_fields, all_exprs, all_insights, results_per_page)
    
    print(f"\n[crawl2] DONE. Pages: {pages_crawled}, Fields: {len(all_fields)}, Exprs: {len(all_exprs)}")
    
    return summary

def _save_partial_summary(n, fields, exprs, insights):
    partial = {
        "partial": True,
        "pages_so_far": n,
        "fields_so_far": sorted(fields)[:50],
        "exprs_so_far": sorted(exprs)[:20],
    }
    tmp = ROOT / "data" / "crawl2_partial.json"
    tmp.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding='utf-8')

def _update_knowledge_base(all_fields, all_exprs, all_insights, results_per_page):
    """Append new findings to the knowledge base."""
    try:
        kb = json.loads(KB_FILE.read_text(encoding='utf-8'))
    except Exception:
        kb = {}
    
    # Append new data fields
    existing_fields = set(kb.get("additional_data_fields", []))
    existing_fields.update(all_fields)
    kb["additional_data_fields"] = sorted(existing_fields)
    
    # Append new alpha examples
    existing_exprs = kb.get("additional_alpha_examples", [])
    existing_expr_strs = {e.get("expression", e) if isinstance(e, dict) else e 
                          for e in existing_exprs}
    for expr in all_exprs:
        if expr not in existing_expr_strs:
            existing_exprs.append({
                "expression": expr,
                "source": "crawl2_expanded",
                "priority": "MEDIUM"
            })
    kb["additional_alpha_examples"] = existing_exprs
    
    # Competition info
    comp_data = []
    for url, result in results_per_page.items():
        if "competition" in url.lower():
            comp_data.append({
                "url": url,
                "title": result.get("title", ""),
                "insights": result.get("key_insights", [])[:5],
                "text_preview": result.get("raw_text_preview", "")[:500],
            })
    if comp_data:
        kb["competition_info"] = comp_data
    
    # Save updated KB
    kb["kb_updated_at"] = datetime.utcnow().isoformat()
    KB_FILE.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[crawl2] Knowledge base updated: {KB_FILE}")

if __name__ == "__main__":
    main()
