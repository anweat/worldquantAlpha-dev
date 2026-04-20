"""
Deep SPA crawler for WorldQuant BRAIN platform.
Uses longer JS waits and scroll interactions to load React SPA content.
Saves extracted text + links for knowledge base building.
"""
import asyncio, json, sys, re, time
from pathlib import Path
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

STATE_FILE = r'D:\codeproject\auth-reptile\.state\session.json'
OUTPUT_DIR = Path(r'D:\codeproject\worldquantAlpha-dev\data\spa_crawl')
OUTPUT_DIR.mkdir(exist_ok=True)
KB_FILE = Path(r'D:\codeproject\worldquantAlpha-dev\data\wq_knowledge_base.json')

# Target SPA pages that previously failed (returned too little content)
SPA_TARGETS = [
    ("learn_data_catalog",    "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog"),
    ("learn_datasets",        "https://platform.worldquantbrain.com/learn/data-and-tools/datasets"),
    ("learn_operators",       "https://platform.worldquantbrain.com/learn/data-and-tools/operators"),
    ("learn_alpha_tutorial",  "https://platform.worldquantbrain.com/learn/documentation/fundamentals/alpha-tutorial"),
    ("learn_quick_start",     "https://platform.worldquantbrain.com/learn/documentation/fundamentals/quick-start"),
    ("learn_fundamental",     "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog/fundamental"),
    ("learn_analyst",         "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog/analyst"),
    ("learn_news",            "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog/news"),
    ("learn_sentiment",       "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog/sentiment"),
    ("learn_options",         "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog/options"),
    ("competition_iqc2026",   "https://platform.worldquantbrain.com/competition/IQC2026S1/guidelines"),
    ("data_fields",           "https://platform.worldquantbrain.com/data/data-fields"),
    ("learn_video_series",    "https://platform.worldquantbrain.com/learn/quantcepts"),
]


async def crawl_spa():
    from playwright.async_api import async_playwright

    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=STATE_FILE,
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()
        page.set_default_timeout(30000)

        for name, url in SPA_TARGETS:
            print(f"\n=== Crawling: {name} ===")
            print(f"  URL: {url}")

            out_file = OUTPUT_DIR / f"{name}.json"
            if out_file.exists():
                existing = json.loads(out_file.read_text(encoding='utf-8'))
                if existing.get('content_length', 0) > 3000:
                    print(f"  SKIP (already crawled, {existing['content_length']} chars)")
                    results[name] = existing
                    continue

            try:
                await page.goto(url, wait_until='domcontentloaded')
                # Wait longer for React SPA to load
                await asyncio.sleep(4)

                # Try to scroll to trigger lazy loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)
                await page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(1)

                # Get all visible text
                text = await page.evaluate("""() => {
                    // Remove nav, header, footer, script, style
                    const remove = ['nav', 'header', 'footer', 'script', 'style', '.sidebar', '#sidebar'];
                    remove.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    });
                    return document.body.innerText || '';
                }""")

                # Get all links
                links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({href: a.href, text: a.textContent.trim()}))
                        .filter(l => l.href && l.href.startsWith('http'))
                        .slice(0, 100);
                }""")

                # Get page title
                title = await page.title()

                print(f"  Title: {title}")
                print(f"  Content: {len(text)} chars, {len(links)} links")

                record = {
                    'url': url,
                    'name': name,
                    'title': title,
                    'text': text,
                    'links': links,
                    'content_length': len(text),
                    'crawled_at': datetime.now().isoformat()
                }
                out_file.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
                results[name] = record

                # If content is substantive, extract key facts
                if len(text) > 2000:
                    print(f"  CONTENT FOUND!")
                    preview = text[:500].replace('\n', ' ')
                    print(f"  Preview: {preview}")

            except Exception as e:
                print(f"  ERROR: {e}")
                results[name] = {'url': url, 'error': str(e), 'content_length': 0}

            await asyncio.sleep(1)

        await browser.close()

    return results


def extract_data_fields(text):
    """Extract data field names from crawled text."""
    # Look for patterns like "fieldname" in code blocks or lists
    fields = set()

    # Pattern: words that look like field names (lowercase with underscores)
    field_pattern = re.compile(r'\b([a-z][a-z0-9_]{2,40})\b')
    known_operators = {'rank', 'group_rank', 'ts_rank', 'ts_zscore', 'ts_std_dev', 'ts_corr',
                       'ts_delta', 'ts_backfill', 'ts_decay_linear', 'scale', 'signed_power',
                       'vec_count', 'vec_avg', 'vec_sum', 'vec_max', 'vec_min', 'vec_ir',
                       'group_mean', 'group_zscore', 'min', 'max', 'abs', 'log', 'sqrt'}

    # Look for expressions like rank(FIELD) or group_rank(ts_rank(FIELD, ...))
    expr_pattern = re.compile(r'(?:rank|zscore|std_dev|delta|backfill)\(([a-z][a-z0-9_]*)')
    for match in expr_pattern.finditer(text):
        f = match.group(1)
        if f not in known_operators and len(f) > 2:
            fields.add(f)

    return list(fields)


def analyze_and_update_kb(results):
    """Analyze crawled content and update knowledge base."""
    # Load existing KB
    if KB_FILE.exists():
        kb = json.loads(KB_FILE.read_text(encoding='utf-8'))
    else:
        kb = {}

    new_fields = set()
    new_examples = []
    discoveries = []

    for name, data in results.items():
        text = data.get('text', '')
        if len(text) < 500:
            continue

        # Extract expressions
        expr_pattern = re.compile(r'[a-z_]+\([^()]{5,100}\)')
        for m in expr_pattern.finditer(text):
            expr = m.group(0)
            if any(op in expr for op in ['rank', 'ts_rank', 'group_rank', 'ts_zscore']):
                new_examples.append({'expr': expr, 'source': name})

        # Extract field names
        fields = extract_data_fields(text)
        new_fields.update(fields)

        discoveries.append(f"[{name}] {len(text)} chars, {len(fields)} potential fields")

    # Update KB
    if 'spa_crawl_results' not in kb:
        kb['spa_crawl_results'] = {}

    kb['spa_crawl_results']['timestamp'] = datetime.now().isoformat()
    kb['spa_crawl_results']['pages'] = {k: {'chars': v.get('content_length', 0)} for k, v in results.items()}
    kb['spa_crawl_results']['new_expressions'] = new_examples[:50]
    kb['spa_crawl_results']['potential_fields'] = list(new_fields)[:100]
    kb['spa_crawl_results']['discoveries'] = discoveries

    KB_FILE.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\nKB updated: {len(new_examples)} expressions, {len(new_fields)} potential fields")


if __name__ == '__main__':
    print("Starting SPA crawler...")
    results = asyncio.run(crawl_spa())

    print(f"\n=== SUMMARY ===")
    good = [(k, v) for k, v in results.items() if v.get('content_length', 0) > 2000]
    print(f"Pages with substantial content: {len(good)}/{len(results)}")
    for k, v in good:
        print(f"  {k}: {v.get('content_length', 0)} chars - {v.get('title', '')[:60]}")

    analyze_and_update_kb(results)
