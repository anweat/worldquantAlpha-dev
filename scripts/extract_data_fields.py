"""
Paginated data-fields extractor for WorldQuant BRAIN platform.
Crawls all 134 pages of the data-fields catalog to discover all available fields.
"""
import asyncio, json, sys, re
from pathlib import Path
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

STATE_FILE = r'D:\codeproject\auth-reptile\.state\session.json'
OUTPUT_FILE = Path(r'D:\codeproject\worldquantAlpha-dev\data\all_data_fields.json')
BASE_URL = "https://platform.worldquantbrain.com/data/data-fields"


async def extract_fields_page(page):
    """Extract field rows from current page."""
    fields = []
    # Get all table rows / field links
    field_data = await page.evaluate("""() => {
        const results = [];
        // Find all field links
        const links = document.querySelectorAll('a[href*="/data/data-fields/"]');
        links.forEach(link => {
            const href = link.href;
            const fieldId = href.split('/data/data-fields/')[1];
            if (!fieldId || fieldId.includes('/')) return;
            
            // Try to get description from parent row
            const row = link.closest('tr') || link.closest('[class*="row"]') || link.parentElement;
            let desc = '', fieldType = '', coverage = '', alphaCount = '';
            if (row) {
                const cells = row.querySelectorAll('td') || [];
                if (cells.length >= 3) {
                    desc = cells[1]?.textContent?.trim() || '';
                    fieldType = cells[2]?.textContent?.trim() || '';
                    coverage = cells[3]?.textContent?.trim() || '';
                    alphaCount = cells[5]?.textContent?.trim() || '';
                }
            }
            
            // Fallback: get text from siblings
            if (!desc) {
                const parent = link.parentElement;
                const allText = parent?.parentElement?.innerText || '';
                const parts = allText.split('\\n').map(s => s.trim()).filter(s => s);
                desc = parts.find(s => s.length > 20 && !s.includes('%') && !s.includes(fieldId)) || '';
            }
            
            results.push({id: fieldId, description: desc.substring(0, 150), type: fieldType, coverage: coverage, alphaCount: alphaCount});
        });
        return results;
    }""")
    return field_data


async def get_page_count(page):
    """Get total number of pages."""
    try:
        count_text = await page.evaluate("""() => {
            const text = document.body.innerText;
            const match = text.match(/out of\\s+([\\d,]+)/);
            return match ? match[1] : '0';
        }""")
        total = int(count_text.replace(',', ''))
        page_size = 20  # usually 20 per page
        import math
        return math.ceil(total / page_size), total
    except:
        return 134, 2663  # fallback from known data


async def navigate_to_page(page, page_num):
    """Navigate to a specific page using the pagination buttons or URL."""
    # Try URL parameter approach first
    try:
        # The SPA might support ?page= or ?offset= params
        await page.goto(f"{BASE_URL}?page={page_num}", wait_until='domcontentloaded')
        await asyncio.sleep(3)
        fields = await extract_fields_page(page)
        if fields:
            return True
    except:
        pass

    # Try clicking page number button
    try:
        # Look for page number button
        page_btn = await page.query_selector(f'button:has-text("{page_num}")')
        if not page_btn:
            page_btn = await page.query_selector(f'[data-page="{page_num}"]')
        if page_btn:
            await page_btn.click()
            await asyncio.sleep(2)
            return True
    except:
        pass

    return False


async def click_next_page(page):
    """Click the Next button."""
    try:
        next_btn = await page.query_selector('button:has-text("Next"), a:has-text("Next"), [aria-label="Next"]')
        if next_btn:
            await next_btn.click()
            await asyncio.sleep(2)
            return True
    except:
        pass
    return False


async def crawl_all_fields():
    from playwright.async_api import async_playwright

    all_fields = {}
    datasets = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=STATE_FILE, viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        print(f"Loading data-fields page...")
        await page.goto(BASE_URL, wait_until='domcontentloaded')
        await asyncio.sleep(5)

        # Try to scroll to trigger loading
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # Get page count from page 1
        total_pages, total_fields = await get_page_count(page)
        print(f"Total fields: {total_fields}, Pages: {total_pages}")

        # Extract page 1
        fields_p1 = await extract_fields_page(page)
        print(f"Page 1: {len(fields_p1)} fields")
        for f in fields_p1:
            all_fields[f['id']] = f

        # Try to get page title/dataset names
        text_p1 = await page.evaluate("() => document.body.innerText")
        print(f"Page 1 content: {len(text_p1)} chars")
        print(f"Preview: {text_p1[:300]}")

        # Now try to navigate through all pages
        # Strategy: find Next button and click it
        max_pages = min(total_pages, 50)  # limit to 50 pages for now
        for page_num in range(2, max_pages + 1):
            print(f"  Navigating to page {page_num}...")

            # Try clicking Next
            clicked = await click_next_page(page)
            if not clicked:
                # Try URL approach
                await page.goto(f"{BASE_URL}?page={page_num}", wait_until='domcontentloaded')
                await asyncio.sleep(3)

            await asyncio.sleep(2)
            fields_page = await extract_fields_page(page)
            if not fields_page:
                print(f"  No fields on page {page_num}, stopping")
                break

            for f in fields_page:
                all_fields[f['id']] = f

            print(f"  Page {page_num}: +{len(fields_page)} fields (total: {len(all_fields)})")

            # Save progress every 10 pages
            if page_num % 10 == 0:
                OUTPUT_FILE.write_text(
                    json.dumps({'fields': all_fields, 'total_found': len(all_fields), 'last_page': page_num},
                               indent=2, ensure_ascii=False),
                    encoding='utf-8'
                )
                print(f"  [Progress saved: {len(all_fields)} fields]")

        await browser.close()

    # Final save
    OUTPUT_FILE.write_text(
        json.dumps({
            'crawled_at': datetime.now().isoformat(),
            'total_found': len(all_fields),
            'fields': all_fields
        }, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )

    print(f"\n=== COMPLETE ===")
    print(f"Total fields extracted: {len(all_fields)}")

    # Categorize by dataset prefix
    prefixes = {}
    for fid in all_fields:
        prefix = fid.split('_')[0] if '_' in fid else fid[:4]
        prefixes[prefix] = prefixes.get(prefix, 0) + 1

    print("\nTop field prefixes:")
    for prefix, count in sorted(prefixes.items(), key=lambda x: -x[1])[:20]:
        print(f"  {prefix}: {count} fields")

    return all_fields


if __name__ == '__main__':
    fields = asyncio.run(crawl_all_fields())
