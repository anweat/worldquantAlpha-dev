"""
Resume data fields extraction from page 39 onwards.
Uses click-based navigation with page reset strategy.
"""
import asyncio, json, sys
from pathlib import Path
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

STATE_FILE = r'D:\codeproject\auth-reptile\.state\session.json'
OUTPUT_FILE = Path(r'D:\codeproject\worldquantAlpha-dev\data\all_data_fields.json')
BASE_URL = "https://platform.worldquantbrain.com/data/data-fields"
START_PAGE = 39  # Resume from here


async def extract_fields_page(page):
    fields = await page.evaluate("""() => {
        const results = [];
        const links = document.querySelectorAll('a[href*="/data/data-fields/"]');
        links.forEach(link => {
            const href = link.href;
            const fieldId = href.split('/data/data-fields/')[1];
            if (!fieldId || fieldId.includes('/')) return;
            results.push({id: fieldId});
        });
        return results;
    }""")
    return fields


async def click_page_number(page, target_num):
    """Try to click a specific page number in pagination."""
    try:
        # Try to find the numbered button
        btns = await page.query_selector_all('button, a')
        for btn in btns:
            text = await btn.text_content()
            if text and text.strip() == str(target_num):
                await btn.click()
                await asyncio.sleep(3)
                return True
    except:
        pass
    return False


async def click_next(page):
    try:
        next_btn = await page.query_selector('button:has-text("Next")')
        if not next_btn:
            next_btn = await page.query_selector('[aria-label="Next page"]')
        if next_btn:
            await next_btn.click()
            await asyncio.sleep(2)
            return True
    except:
        pass
    return False


async def crawl_remaining():
    # Load existing data
    existing = {}
    if OUTPUT_FILE.exists():
        data = json.loads(OUTPUT_FILE.read_text(encoding='utf-8'))
        existing = data.get('fields', {})
    print(f"Existing fields: {len(existing)}")

    from playwright.async_api import async_playwright

    new_fields = dict(existing)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=STATE_FILE, viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        # Load page 1 first
        print("Loading page 1...")
        await page.goto(BASE_URL, wait_until='domcontentloaded')
        await asyncio.sleep(5)

        # Navigate to page 38 first (by clicking Next 37 times to get in sync)
        # Actually, let's try to navigate directly using input field if available
        # Or try clicking page numbers in groups

        # Strategy: Click page 39 button from current pagination
        # First get to page 38 area
        print("Fast-navigating to page 38...")

        # Try clicking higher page numbers in the pagination
        # The pagination usually shows: 1, 2, ..., current-1, current, current+1, ..., last
        # Let's click through groups

        current = 1
        target_pages = list(range(START_PAGE, 135))  # 39 to 134

        # Try to jump using the "..." button or specific page numbers
        # First, navigate through by clicking Next many times from page 1
        # This is slow but reliable

        # Check if we can click on page 38 directly from page 1
        jumped = await click_page_number(page, 38)
        if jumped:
            print("Jumped to page 38!")
            current = 38
        else:
            # Manually click Next many times to get to page 38
            print("Clicking Next to reach page 38...")
            for i in range(37):
                clicked = await click_next(page)
                if not clicked:
                    print(f"Lost navigation at page {current+1}")
                    break
                current += 1
                if (current) % 10 == 0:
                    print(f"  At page {current}")

        print(f"Now at page {current}, starting extraction from here...")

        # Now extract remaining pages
        page_num = current
        consecutive_empty = 0

        while page_num <= 134:
            # Click Next
            clicked = await click_next(page)
            if not clicked:
                print(f"Cannot navigate from page {page_num}")
                # Try jumping to next visible page number
                found = False
                for try_num in [page_num + 1, page_num + 2, page_num + 5]:
                    if await click_page_number(page, try_num):
                        page_num = try_num - 1
                        found = True
                        break
                if not found:
                    break

            page_num += 1
            await asyncio.sleep(2)

            fields_page = await extract_fields_page(page)
            if not fields_page:
                consecutive_empty += 1
                print(f"  Page {page_num}: empty ({consecutive_empty} consecutive)")
                if consecutive_empty >= 3:
                    print("Too many empty pages, stopping")
                    break
                continue

            consecutive_empty = 0
            for f in fields_page:
                new_fields[f['id']] = f

            print(f"  Page {page_num}: +{len(fields_page)} (total: {len(new_fields)})")

            if page_num % 10 == 0:
                OUTPUT_FILE.write_text(
                    json.dumps({'crawled_at': datetime.now().isoformat(),
                               'total_found': len(new_fields), 'last_page': page_num,
                               'fields': new_fields},
                               indent=2, ensure_ascii=False),
                    encoding='utf-8'
                )
                print(f"  [Saved: {len(new_fields)} fields]")

        await browser.close()

    OUTPUT_FILE.write_text(
        json.dumps({'crawled_at': datetime.now().isoformat(), 'total_found': len(new_fields),
                   'fields': new_fields}, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )

    added = len(new_fields) - len(existing)
    print(f"\nDone! {added} new fields added. Total: {len(new_fields)}")

    # Show new prefixes
    prefixes = {}
    for fid in new_fields:
        p = fid.split('_')[0]
        prefixes[p] = prefixes.get(p, 0) + 1
    print("\nAll field prefixes:")
    for p, c in sorted(prefixes.items(), key=lambda x: -x[1])[:25]:
        print(f"  {p}: {c}")


if __name__ == '__main__':
    asyncio.run(crawl_remaining())
