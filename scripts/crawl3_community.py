"""
Crawl3 - Community posts, data-fields, competition pages
High-value targets discovered from crawl2 links
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
SUMMARY_FILE = ROOT / "data" / "crawl3_summary.json"

TARGETS = [
    # Community BRAIN TIPS posts - highest value
    "https://support.worldquantbrain.com/hc/en-us/community/posts/14431641039383--BRAIN-TIPS-Getting-Started-with-Technical-Indicators",
    "https://support.worldquantbrain.com/hc/en-us/community/posts/15053280147223--BRAIN-TIPS-Finite-differences",
    "https://support.worldquantbrain.com/hc/en-us/community/posts/15233993197079--BRAIN-TIPS-Statistics-in-alphas-research",
    "https://support.worldquantbrain.com/hc/en-us/community/posts/8123350778391-How-do-you-get-a-higher-Sharpe-",
    "https://support.worldquantbrain.com/hc/en-us/community/posts/8419305084823--BRAIN-TIPS-Weight-Coverage-common-issues-and-advice",
    "https://support.worldquantbrain.com/hc/en-us/community/topics",
    # Data catalog pages
    "https://platform.worldquantbrain.com/data/data-fields",
    "https://platform.worldquantbrain.com/data/data-sets",
    "https://platform.worldquantbrain.com/data",
    # Competition pages
    "https://platform.worldquantbrain.com/competition/IQC2026S1",
    "https://platform.worldquantbrain.com/competition/challenge",
    "https://platform.worldquantbrain.com/competition/OC2025",
    # Quantcepts advanced
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/what-does-delay-0-alpha-look",
    "https://platform.worldquantbrain.com/learn/courses/quantcepts/how-quants-can-partner-ai",
    # Glossary
    "https://support.worldquantbrain.com/hc/en-us/articles/4902349883927",
    # Weight coverage article
    "https://support.worldquantbrain.com/hc/en-us/articles/19248385997719-Weight-Coverage-common-issues-and-advice",
    # Operators vector section
    "https://platform.worldquantbrain.com/learn/operators/operators",
    # Intermediate/advanced courses from new links
    "https://platform.worldquantbrain.com/learn/courses/implementing-advanced-ideas-brain",
    "https://platform.worldquantbrain.com/learn/courses/combining-alphas-and-risk-management",
    "https://platform.worldquantbrain.com/learn/documentation/understanding-data/getting-started-sentiment1-dataset",
    "https://platform.worldquantbrain.com/learn/documentation/understanding-data/vector-datafields",
    # IQC info
    "https://platform.worldquantbrain.com/learn/courses/international-quant-championship-2026",
]

FIELD_PATTERNS = [
    r'\best_[a-z_0-9]+\b',
    r'\betz_[a-z_0-9]+\b',
    r'\bfn_[a-z_0-9]+\b',
    r'\bscl12_[a-z_0-9]+\b',
    r'\bscl1_[a-z_0-9]+\b',
    r'\bmodel_[a-z_0-9]+\b',
    r'\bvec_[a-z_0-9]+\b',
    r'\bhltvol[a-z0-9_]*\b',
    r'\bimplied_vol[a-z_0-9]*\b',
    r'\bparkinson[a-z_0-9]*\b',
    r'\bnews_[a-z_0-9]+\b',
    r'\bvix[a-z_0-9]*\b',
    r'\badv[0-9]+\b',
    r'\btail_risk[a-z_0-9]*\b',
    r'\bshort_interest[a-z_0-9]*\b',
    r'\bborrow_rate[a-z_0-9]*\b',
    r'\bcpi[a-z_0-9]*\b',
    r'\bgdp[a-z_0-9]*\b',
    r'\b(close|open|high|low|volume|vwap|returns|shares|cap|adv20|adv60|adv120|adv180)\b',
    r'\b(liabilities|assets|equity|sales|revenue|earnings|income|ebitda|cashflow|enterprise_value)\b',
    r'\b(operating_income|net_income|cash|debt|book_value|book_to_price)\b',
    r'\b(pe_ratio|pb_ratio|ps_ratio|ev_ebitda|pcf|peg)\b',
    r'\b(bid|ask|spread|turn|short|borrow)\b',
]

ALPHA_PATTERNS = [
    r'(?:rank|ts_rank|group_rank)\s*\([^)]{5,120}\)',
    r'ts_(?:corr|std_dev|delta|mean|zscore|sum|skewness|kurtosis|max|min|arg_max|arg_min|backfill|decay_linear|decay_exp_window)\s*\([^)]{5,120}\)',
    r'(?:scale|indneutralize|group_mean|group_zscore|rank_by_side|signed_power|pasteurize|left_tail|right_tail|tail)\s*\([^)]{5,120}\)',
    r'-?ts_rank\([^)]+\)',
    r'-?group_rank\([^)]+\)',
    r'-?ts_std_dev\([^)]+\)',
    r'-?ts_corr\([^)]+\)',
    r'-?ts_zscore\([^)]+\)',
]

def url_to_filename(url: str) -> str:
    path = re.sub(r'https?://[^/]+/', '', url)
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', path).strip('_')
    prefix = "support_" if "support.worldquantbrain" in url else ""
    return prefix + safe[:120] + ".json"

def extract_fields(text):
    found = set()
    for pat in FIELD_PATTERNS:
        matches = re.findall(pat, text, re.IGNORECASE)
        found.update(m.lower() for m in matches)
    structured = {f for f in found if '_' in f or f in 
                 {'close','open','high','low','volume','vwap','returns','shares','cap',
                  'liabilities','assets','equity','sales','revenue','earnings','income',
                  'ebitda','cashflow','enterprise_value','operating_income','net_income',
                  'cash','debt','book_value','bid','ask','spread'}}
    return sorted(structured)

def extract_alpha_exprs(text):
    found = set()
    for pat in ALPHA_PATTERNS:
        matches = re.findall(pat, text, re.IGNORECASE)
        found.update(m.strip() for m in matches if len(m) > 10)
    return sorted(found)[:30]

def extract_key_insights(text):
    insights = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    keywords = ['sharpe', 'fitness', 'turnover', 'neutralization', 'decay', 'truncation',
                'subindustry', 'industry', 'market', 'sector', 'fundamental', 'momentum',
                'reversal', 'sentiment', 'analyst', 'options', 'implied', 'delay', 'delay-0',
                'submission', 'criteria', 'check', 'pass', 'fail', 'improve', 'reduce',
                'correlation', 'alpha', 'signal', 'factor', 'rank', 'ts_rank', 'group_rank',
                'dataset', 'field', 'data field', 'weight coverage', 'brain tips',
                'technical indicator', 'finite difference', 'statistics', 'std dev',
                'ts_delta', 'ts_std_dev', 'ts_backfill', 'scale', 'indneutralize',
                'diversif', 'overfitting', 'look-ahead', 'lookahead']
    for line in lines:
        if 40 < len(line) < 600:
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords):
                insights.append(line)
        if len(insights) >= 40:
            break
    return insights[:30]

def crawl_page(page, url):
    result = {
        "url": url, "title": "", "crawled_at": datetime.now().isoformat(),
        "raw_text_length": 0, "raw_text_preview": "",
        "data_fields_found": [], "alpha_expressions_found": [],
        "key_insights": [], "new_links": [], "error": None
    }
    try:
        resp = page.goto(url, wait_until="networkidle", timeout=40000)
        status = resp.status if resp else 0
        if status == 404:
            result["error"] = "404 Not Found"
            return result
        current_url = page.url
        if "sign-in" in current_url or "login" in current_url:
            result["error"] = "SESSION_EXPIRED: redirected to sign-in"
            return result
        time.sleep(5)  # extra wait for SPA content
        result["title"] = page.title()
        
        # For support pages, try different selectors
        text = ""
        selectors = ["main", "article", ".article-body", ".post-body", 
                     "[class*='content']", "[class*='post']", "[class*='community']",
                     "[class*='learn']", "[class*='course']", "[class*='doc']", "body"]
        for sel in selectors:
            try:
                els = page.query_selector_all(sel)
                if els:
                    candidate = els[0].inner_text()
                    if len(candidate) > len(text):
                        text = candidate
                        if len(text) > 1000:
                            break
            except Exception:
                pass
        
        result["raw_text_length"] = len(text)
        result["raw_text_preview"] = text[:5000]
        result["data_fields_found"] = extract_fields(text)
        result["alpha_expressions_found"] = extract_alpha_exprs(text)
        result["key_insights"] = extract_key_insights(text)
        
        links = []
        seen_urls = set()
        for a in page.query_selector_all("a[href]"):
            try:
                href = a.get_attribute("href") or ""
                txt = a.inner_text().strip()[:100]
                if href and ("worldquant" in href or href.startswith("/")):
                    if href.startswith("/"):
                        # Determine domain
                        if "support.worldquant" in url:
                            href = "https://support.worldquantbrain.com" + href
                        else:
                            href = "https://platform.worldquantbrain.com" + href
                    if href not in seen_urls:
                        seen_urls.add(href)
                        links.append({"url": href, "text": txt})
            except Exception:
                pass
        result["new_links"] = links[:60]
    except Exception as e:
        result["error"] = str(e)
    return result

def main():
    from playwright.sync_api import sync_playwright
    
    all_fields = set()
    all_exprs = set()
    all_insights = []
    pages_crawled = 0
    session_expired = False
    results_per_page = {}
    
    print(f"[crawl3] Starting community+data crawl of {len(TARGETS)} URLs")
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=SESSION_FILE)
        page = ctx.new_page()
        
        for i, url in enumerate(TARGETS):
            fname = url_to_filename(url)
            out_path = OUT_DIR / fname
            
            print(f"\n[{i+1}/{len(TARGETS)}] {url}")
            result = crawl_page(page, url)
            pages_crawled += 1
            
            if result.get("error"):
                err = result["error"]
                print(f"  ERROR: {err}")
                if "SESSION_EXPIRED" in err:
                    session_expired = True
                    print("[crawl3] Session expired! Stopping.")
                    break
                out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                continue
            
            print(f"  Title: {result['title']}")
            print(f"  Text: {result['raw_text_length']} chars | Fields: {len(result['data_fields_found'])} | Exprs: {len(result['alpha_expressions_found'])} | Insights: {len(result['key_insights'])}")
            if result['data_fields_found']:
                print(f"  Fields: {result['data_fields_found'][:10]}")
            if result['alpha_expressions_found']:
                print(f"  Exprs: {result['alpha_expressions_found'][:3]}")
            
            all_fields.update(result["data_fields_found"])
            all_exprs.update(result["alpha_expressions_found"])
            all_insights.extend(result["key_insights"][:5])
            results_per_page[url] = result
            
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"  Saved: {fname}")
            time.sleep(3)
        
        browser.close()
    
    summary = {
        "crawled_at": datetime.now().isoformat(),
        "pages_crawled": pages_crawled,
        "session_expired": session_expired,
        "new_data_fields": sorted(all_fields),
        "new_alpha_examples": sorted(all_exprs),
        "key_discoveries": list(dict.fromkeys(all_insights))[:50],
    }
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # Update knowledge base
    kb = json.loads(KB_FILE.read_text(encoding='utf-8'))
    existing_fields = set(kb.get("additional_data_fields", []))
    existing_fields.update(all_fields)
    kb["additional_data_fields"] = sorted(existing_fields)
    
    existing_exprs = kb.get("additional_alpha_examples", [])
    existing_strs = {e.get("expression", e) if isinstance(e, dict) else e for e in existing_exprs}
    for expr in all_exprs:
        if expr not in existing_strs:
            existing_exprs.append({"expression": expr, "source": "crawl3_community", "priority": "MEDIUM"})
    kb["additional_alpha_examples"] = existing_exprs
    
    # Add community insights
    kb["community_insights"] = list(dict.fromkeys(all_insights))[:40]
    
    # Competition info from competition pages
    comp_data = kb.get("competition_info", [])
    for url, result in results_per_page.items():
        if "competition" in url.lower() and result.get("raw_text_length", 0) > 300:
            comp_data.append({
                "url": url, "title": result.get("title", ""),
                "text_preview": result.get("raw_text_preview", "")[:800],
                "insights": result.get("key_insights", [])[:5],
            })
    kb["competition_info"] = comp_data
    kb["kb_updated_at"] = datetime.now().isoformat()
    
    KB_FILE.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n[crawl3] DONE. Pages: {pages_crawled}, Fields: {len(all_fields)}, Exprs: {len(all_exprs)}")
    print(f"Summary: {SUMMARY_FILE}")

if __name__ == "__main__":
    main()
