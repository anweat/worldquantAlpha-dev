"""
wq_crawler.py - WorldQuant BRAIN Platform Crawler
Uses Playwright with saved session to crawl authenticated pages.
Stores raw HTML + extracted text in data/crawl/ directory.
Tracks state in SQLite (crawl_state.db).
"""
import sys, json, hashlib, time, re, sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

ROOT = Path(__file__).parent.parent
CRAWL_DIR = ROOT / "data" / "crawl"
DB_PATH = ROOT / "data" / "crawl_state.db"
SESSION_FILE = r"D:\codeproject\auth-reptile\.state\session.json"

CRAWL_DIR.mkdir(parents=True, exist_ok=True)

# ─── Seed URLs ────────────────────────────────────────────────────────────────
SEED_URLS = [
    # Learn / Education
    "https://platform.worldquantbrain.com/learn",
    "https://platform.worldquantbrain.com/learn/data-and-tools/fast-expression-language-overview",
    "https://platform.worldquantbrain.com/learn/data-and-tools/data-catalog",
    "https://platform.worldquantbrain.com/learn/data-and-tools/operators",
    "https://platform.worldquantbrain.com/learn/data-and-tools/financial-data-overview",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-getting-started",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-improving",
    "https://platform.worldquantbrain.com/learn/data-and-tools/alpha-checking",
    "https://platform.worldquantbrain.com/learn/data-and-tools/submission-criteria",
    "https://platform.worldquantbrain.com/learn/data-and-tools/about-competitions",
    # Simulate
    "https://platform.worldquantbrain.com/simulate",
    # Research / Ideas
    "https://platform.worldquantbrain.com/research",
    # Alpha examples / community
    "https://platform.worldquantbrain.com/alphas",
    # Help / FAQ
    "https://platform.worldquantbrain.com/help",
    "https://platform.worldquantbrain.com/faq",
    # WorldQuant main site
    "https://www.worldquant.com/brain",
    "https://www.worldquant.com/brain/faq",
]

# URL patterns to follow (internal WQ links)
ALLOWED_PATTERNS = [
    r"platform\.worldquantbrain\.com",
    r"worldquant\.com/brain",
    r"worldquantbrain\.com/learn",
]

# URL patterns to skip
SKIP_PATTERNS = [
    r"\.(png|jpg|jpeg|gif|svg|ico|css|js|pdf|zip|woff|ttf)$",
    r"//cdn\.",
    r"//static\.",
    r"sign-in",
    r"logout",
    r"#",
    r"mailto:",
    r"javascript:",
]


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crawl_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            depth INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            crawled_at TEXT,
            content_hash TEXT,
            content_path TEXT,
            alpha_ideas_extracted INTEGER DEFAULT 0,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crawl_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_url TEXT,
            to_url TEXT,
            link_text TEXT,
            UNIQUE(from_url, to_url)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alpha_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT,
            idea_type TEXT,
            expression TEXT,
            description TEXT,
            data_fields TEXT,
            operators TEXT,
            expected_logic TEXT,
            priority INTEGER DEFAULT 5,
            tested INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def seed_db(conn: sqlite3.Connection, urls: list, depth: int = 0):
    for url in urls:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO crawl_queue (url, depth) VALUES (?, ?)",
                (url, depth)
            )
        except Exception:
            pass
    conn.commit()
    print(f"[Seed] Added {len(urls)} seed URLs to queue")


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


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


def normalize_url(url: str, base: str) -> Optional[str]:
    from urllib.parse import urljoin, urlparse, urlunparse
    try:
        full = urljoin(base, url)
        parsed = urlparse(full)
        # Remove fragment
        clean = urlunparse(parsed._replace(fragment=""))
        return clean if clean.startswith("http") else None
    except Exception:
        return None


def crawl_url_playwright(url: str, session_file: str = SESSION_FILE) -> dict:
    """Crawl a single URL using Playwright with saved session."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=session_file)
            page = ctx.new_page()

            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(2)  # Let JS render

            title = page.title()
            html = page.content()

            # Extract all links
            links = []
            for a in page.query_selector_all("a[href]"):
                try:
                    href = a.get_attribute("href")
                    text = a.inner_text().strip()[:100]
                    if href:
                        links.append({"href": href, "text": text})
                except Exception:
                    pass

            # Extract main text content
            text_content = ""
            for sel in ["main", "article", ".content", "#content", "body"]:
                el = page.query_selector(sel)
                if el:
                    try:
                        text_content = el.inner_text()
                        break
                    except Exception:
                        pass

            browser.close()

            return {
                "url": url,
                "title": title,
                "html": html,
                "text": text_content,
                "links": links,
                "error": None,
            }
    except Exception as e:
        return {"url": url, "title": "", "html": "", "text": "", "links": [], "error": str(e)}


def save_page(url: str, content: dict) -> str:
    """Save page content to disk, return file path."""
    uid = url_hash(url)
    page_dir = CRAWL_DIR / uid
    page_dir.mkdir(exist_ok=True)

    meta = {
        "url": url,
        "title": content.get("title", ""),
        "crawled_at": datetime.now().isoformat(),
        "error": content.get("error"),
    }

    (page_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (page_dir / "text.txt").write_text(content.get("text", ""), encoding="utf-8")
    (page_dir / "links.json").write_text(
        json.dumps(content.get("links", []), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return str(page_dir)


def crawl_batch(urls: list, max_depth: int = 3, db_path: Path = DB_PATH) -> dict:
    """Crawl a batch of URLs, discover new links, update DB."""
    conn = init_db(db_path)
    results = {"crawled": [], "new_urls": [], "errors": []}

    for url in urls:
        print(f"  [Crawl] {url[:80]}")
        content = crawl_url_playwright(url)

        if content["error"]:
            print(f"    ERROR: {content['error'][:80]}")
            conn.execute(
                "UPDATE crawl_queue SET status='error', error=?, crawled_at=? WHERE url=?",
                (content["error"][:200], datetime.now().isoformat(), url)
            )
            results["errors"].append(url)
            conn.commit()
            continue

        path = save_page(url, content)
        content_hash = hashlib.md5(content["text"].encode()).hexdigest()[:16]

        conn.execute(
            "UPDATE crawl_queue SET status='done', crawled_at=?, content_hash=?, content_path=? WHERE url=?",
            (datetime.now().isoformat(), content_hash, path, url)
        )

        # Discover new links
        current_depth = conn.execute(
            "SELECT depth FROM crawl_queue WHERE url=?", (url,)
        ).fetchone()
        curr_depth = current_depth[0] if current_depth else 0

        new_count = 0
        for link in content["links"]:
            raw_href = link.get("href", "")
            norm = normalize_url(raw_href, url)
            if norm and is_allowed(norm):
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO crawl_queue (url, depth) VALUES (?, ?)",
                        (norm, curr_depth + 1)
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO crawl_links (from_url, to_url, link_text) VALUES (?, ?, ?)",
                        (url, norm, link.get("text", "")[:100])
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] > 0:
                        results["new_urls"].append(norm)
                        new_count += 1
                except Exception:
                    pass

        conn.commit()
        results["crawled"].append({
            "url": url,
            "title": content["title"],
            "text_len": len(content["text"]),
            "new_links": new_count,
        })
        print(f"    OK: {len(content['text'])} chars, {new_count} new links")

    conn.close()
    return results


def get_pending_urls(limit: int = 10, max_depth: int = 4,
                     db_path: Path = DB_PATH) -> list:
    """Get next batch of pending URLs from DB."""
    conn = init_db(db_path)
    rows = conn.execute(
        "SELECT url FROM crawl_queue WHERE status='pending' AND depth <= ? ORDER BY depth, id LIMIT ?",
        (max_depth, limit)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_stats(db_path: Path = DB_PATH) -> dict:
    conn = init_db(db_path)
    stats = {}
    for status in ["pending", "done", "error"]:
        n = conn.execute(
            "SELECT COUNT(*) FROM crawl_queue WHERE status=?", (status,)
        ).fetchone()[0]
        stats[status] = n
    stats["total_links"] = conn.execute("SELECT COUNT(*) FROM crawl_links").fetchone()[0]
    stats["alpha_ideas"] = conn.execute("SELECT COUNT(*) FROM alpha_ideas").fetchone()[0]
    conn.close()
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="Seed DB with initial URLs")
    parser.add_argument("--crawl", type=int, default=5, help="Crawl N pending URLs")
    parser.add_argument("--stats", action="store_true", help="Show DB stats")
    parser.add_argument("--max-depth", type=int, default=4)
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = init_db()

    if args.seed:
        seed_db(conn, SEED_URLS)
        conn.close()

    if args.stats:
        conn.close()
        print(json.dumps(get_stats(), indent=2))
        sys.exit(0)

    conn.close()

    if args.crawl:
        pending = get_pending_urls(limit=args.crawl, max_depth=args.max_depth)
        print(f"Crawling {len(pending)} URLs...")
        results = crawl_batch(pending)
        print(f"\nDone: {len(results['crawled'])} crawled, {len(results['new_urls'])} new URLs, {len(results['errors'])} errors")
        print("Stats:", json.dumps(get_stats(), indent=2))
