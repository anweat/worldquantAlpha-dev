"""HTTP / SPA fetching and HTML cleaning for the crawler subsystem.

fetch_html  — aiohttp, no system proxy, optional cookie injection
fetch_spa   — Playwright async, full JS rendering
clean_html  — BeautifulSoup-based CSS-selector stripping → markdown-ish text

All HTTP fetches go through the robots.txt gate (see robots.py): whitelisted
WorldQuant domains are exempt; other domains have Disallow rules strictly
honoured and Crawl-delay observed via asyncio.sleep().
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from wq_bus.crawler.auth_store import load_cookies
from wq_bus.crawler.robots import (
    RobotsDisallowed, get_robots_gate, is_robots_check_enabled,
)
from wq_bus.utils.logging import get_logger

log = get_logger(__name__)


async def _enforce_robots(url: str) -> None:
    """Block on robots.txt before a request. No-op when check disabled."""
    if not is_robots_check_enabled():
        return
    allowed, delay = await get_robots_gate().is_allowed(url)
    if not allowed:
        log.warning("robots.txt disallows fetch: %s", url)
        raise RobotsDisallowed(f"robots.txt disallow: {url}")
    if delay > 0:
        log.debug("robots.txt crawl-delay=%.1fs for %s", delay, url)
        await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# HTML fetching
# ---------------------------------------------------------------------------

async def fetch_html(
    url: str,
    *,
    source: str | None = None,
    headers: dict | None = None,
) -> tuple[str, dict]:
    """Fetch *url* with aiohttp; return (html_text, meta).

    *meta* keys: final_url, status, content_type.
    System proxies are bypassed via trust_env=False.
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise ImportError("aiohttp is required for fetch_html: pip install aiohttp") from exc

    await _enforce_robots(url)

    cookies: dict[str, Any] = {}
    if source:
        cookies = load_cookies(source) or {}

    req_headers = {"User-Agent": "Mozilla/5.0 wq-bus-crawler/1.0"}
    if headers:
        req_headers.update(headers)

    async with aiohttp.ClientSession(
        trust_env=False,
        headers=req_headers,
        cookies=cookies,
        timeout=aiohttp.ClientTimeout(total=30, connect=10),
    ) as session:
        async with session.get(url, allow_redirects=True) as resp:
            text = await resp.text(errors="replace")
            meta = {
                "final_url": str(resp.url),
                "status": resp.status,
                "content_type": resp.content_type,
            }
            log.debug("fetch_html %s → %d", url, resp.status)
            return text, meta


# ---------------------------------------------------------------------------
# SPA fetching
# ---------------------------------------------------------------------------

async def fetch_spa(
    url: str,
    *,
    source: str | None = None,
) -> tuple[str, dict]:
    """Render *url* with Playwright (chromium, headless); return (html, meta).

    Waits for networkidle so dynamic content is fully loaded.
    Injects cookies from auth_store if *source* is given.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ImportError(
            "playwright is required for fetch_spa: pip install playwright && playwright install chromium"
        ) from exc

    await _enforce_robots(url)

    cookies_dict = {}
    if source:
        cookies_dict = load_cookies(source) or {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(ignore_https_errors=True)

            if cookies_dict:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc
                playwright_cookies = [
                    {"name": name, "value": value, "domain": domain, "path": "/"}
                    for name, value in cookies_dict.items()
                ]
                await ctx.add_cookies(playwright_cookies)

            page = await ctx.new_page()
            response = await page.goto(url, wait_until="networkidle", timeout=30_000)
            html = await page.content()
            meta = {
                "final_url": page.url,
                "status": response.status if response else 0,
                "content_type": "text/html",
            }
            log.debug("fetch_spa %s → %s", url, meta["status"])
            return html, meta
        finally:
            try:
                await browser.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# HTML cleaning
# ---------------------------------------------------------------------------

def clean_html(html: str, rules: list[str]) -> str:
    """Remove elements matching CSS selectors in *rules* and return plain text.

    Uses BeautifulSoup when available; falls back to a regex tag-strip.
    """
    try:
        from bs4 import BeautifulSoup
        return _clean_with_bs4(html, rules)
    except ImportError:
        log.warning("beautifulsoup4 not installed; falling back to regex tag strip")
        return _clean_with_regex(html, rules)


def _clean_with_bs4(html: str, rules: list[str]) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Always remove scripts and styles
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Remove elements matching caller-supplied CSS selectors
    for selector in rules:
        for el in soup.select(selector):
            el.decompose()

    # Convert to readable markdown-ish text
    lines: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "pre", "code", "a"]):
        text = el.get_text(separator=" ", strip=True)
        if not text:
            continue
        tag = el.name
        if tag in ("h1",):
            lines.append(f"# {text}")
        elif tag in ("h2",):
            lines.append(f"## {text}")
        elif tag in ("h3",):
            lines.append(f"### {text}")
        elif tag in ("h4", "h5", "h6"):
            lines.append(f"#### {text}")
        elif tag == "li":
            lines.append(f"- {text}")
        elif tag in ("pre", "code"):
            lines.append(f"`{text}`")
        else:
            lines.append(text)

    # Deduplicate adjacent identical lines
    deduped: list[str] = []
    prev = None
    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line

    return "\n\n".join(deduped).strip()


def _clean_with_regex(html: str, rules: list[str]) -> str:
    """Minimal fallback: strip all HTML tags and return plain text."""
    # Remove entire blocks for simple tag-name rules (e.g. "nav", "script")
    for rule in rules:
        tag_name = rule.lstrip(".#")  # handle .sidebar → sidebar (imprecise but safe)
        html = re.sub(
            rf"<{tag_name}[\s>].*?</{tag_name}>",
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
