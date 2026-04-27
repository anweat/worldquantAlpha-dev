"""PDF download and text extraction for the crawler subsystem.

download_pdf  — aiohttp download → .cache/pdfs/<sha256>.pdf
parse_pdf     — pymupdf (fitz) text extraction; flags ocr_required when sparse
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from wq_bus.crawler.auth_store import load_cookies
from wq_bus.utils.logging import get_logger

log = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CACHE_DIR = _PROJECT_ROOT / ".cache" / "pdfs"

_OCR_THRESHOLD = 200  # chars; below this mark ocr_required


async def download_pdf(
    url: str,
    *,
    source: str | None = None,
    dest_dir: Path | None = None,
) -> Path:
    """Download PDF at *url*; returns local Path.

    Saves to .cache/pdfs/<sha256_of_url>.pdf unless *dest_dir* is given.
    Skips download if file already exists (simple cache hit).
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise ImportError("aiohttp is required for download_pdf: pip install aiohttp") from exc

    cache_dir = dest_dir or _CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    url_hash = hashlib.sha256(url.encode()).hexdigest()
    dest = cache_dir / f"{url_hash}.pdf"

    if dest.exists():
        log.debug("download_pdf cache hit %s", dest.name)
        return dest

    cookies: dict[str, Any] = {}
    if source:
        cookies = load_cookies(source) or {}

    headers = {"User-Agent": "Mozilla/5.0 wq-bus-crawler/1.0"}

    async with aiohttp.ClientSession(trust_env=False, headers=headers, cookies=cookies) as session:
        async with session.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            data = await resp.read()

    dest.write_bytes(data)
    log.info("download_pdf saved %s (%d bytes)", dest.name, len(data))
    return dest


def parse_pdf(path: Path) -> tuple[str, dict]:
    """Extract text from PDF at *path*; returns (text_md, meta).

    *meta* keys: page_count, char_count, ocr_required.
    Raises ImportError if pymupdf is not installed.
    """
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise ImportError(
            "pymupdf is required for parse_pdf: pip install pymupdf"
        ) from exc

    doc = fitz.open(str(path))
    pages: list[str] = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")  # type: ignore[arg-type]
        if text.strip():
            pages.append(f"<!-- page {page_num + 1} -->\n{text.strip()}")
    doc.close()

    text_md = "\n\n".join(pages)
    char_count = len(text_md)
    meta: dict = {
        "page_count": len(doc) if hasattr(doc, "__len__") else len(pages),
        "char_count": char_count,
        "ocr_required": char_count < _OCR_THRESHOLD,
        "source_path": str(path),
    }

    if meta["ocr_required"]:
        log.warning("parse_pdf: sparse text (%d chars) in %s — OCR may be needed", char_count, path.name)

    return text_md, meta
