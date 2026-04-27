"""CrawlerAgent — subscribes to CRAWL_REQUESTED, fetches docs, saves to knowledge_db.

Flow per event:
  1. Resolve target name → CrawlTarget
  2. Fetch HTML / SPA / PDF based on target.type
  3. Clean and extract text
  4. hash URL (sha256) → save_crawl_doc
  5. Emit DOC_FETCHED per saved doc
  6. call triggers.check_threshold_and_emit
"""
from __future__ import annotations

import hashlib

from wq_bus.bus.event_bus import EventBus
from wq_bus.bus.events import Event, Topic, make_event
from wq_bus.crawler import fetcher, pdf_pipeline, triggers
from wq_bus.crawler.targets_loader import get_target
from wq_bus.data.knowledge_db import save_crawl_doc
from wq_bus.utils.logging import get_logger

log = get_logger(__name__)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class CrawlerAgent:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        bus.subscribe(Topic.CRAWL_REQUESTED, self._on_crawl)
        log.info("CrawlerAgent subscribed to CRAWL_REQUESTED")

    async def _on_crawl(self, event: Event) -> None:
        target_name: str = event.payload.get("target", "")
        dataset_tag: str = event.dataset_tag
        force: bool = event.payload.get("force", False)

        if not target_name:
            log.warning("CRAWL_REQUESTED event missing 'target' field — skipping")
            return

        try:
            target = get_target(target_name)
        except KeyError as exc:
            log.error("CrawlerAgent: %s", exc)
            return

        url = target.url_template
        log.info("CrawlerAgent: fetching target=%s url=%s type=%s", target_name, url, target.type)

        source = target.source if target.source else None

        try:
            if target.type == "pdf":
                await self._handle_pdf(url, source, target_name, dataset_tag, target)
            elif target.type == "spa":
                await self._handle_spa(url, source, target_name, dataset_tag, target)
            else:
                await self._handle_html(url, source, target_name, dataset_tag, target)
        except Exception as exc:
            log.exception("CrawlerAgent fetch failed for target=%s: %s", target_name, exc)
            return

        triggers.check_threshold_and_emit(self._bus, dataset_tag)

    # ------------------------------------------------------------------
    # type-specific handlers
    # ------------------------------------------------------------------

    async def _handle_html(self, url, source, target_name, dataset_tag, target) -> None:
        html, meta = await fetcher.fetch_html(url, source=source)
        status = int(meta.get("status") or 0)
        if not (200 <= status < 300):
            log.warning("skipping html doc target=%s url=%s status=%d", target_name, url, status)
            return
        body_md = fetcher.clean_html(html, target.cleaning_rules)
        title = _extract_title(html) or target_name
        url_hash = _url_hash(url)
        save_crawl_doc(
            url_hash=url_hash,
            source=target.source,
            url=url,
            title=title,
            body_md=body_md,
            meta={**meta, "crawl_type": "html", "target": target_name},
        )
        log.info("saved html doc url_hash=%s title=%r", url_hash[:12], title)
        self._emit_doc_fetched(url_hash, target.source, title, dataset_tag)

    async def _handle_spa(self, url, source, target_name, dataset_tag, target) -> None:
        html, meta = await fetcher.fetch_spa(url, source=source)
        status = int(meta.get("status") or 0)
        if status and not (200 <= status < 300):
            log.warning("skipping spa doc target=%s url=%s status=%d", target_name, url, status)
            return
        body_md = fetcher.clean_html(html, target.cleaning_rules)
        title = _extract_title(html) or target_name
        url_hash = _url_hash(url)
        save_crawl_doc(
            url_hash=url_hash,
            source=target.source,
            url=url,
            title=title,
            body_md=body_md,
            meta={**meta, "crawl_type": "spa", "target": target_name},
        )
        log.info("saved spa doc url_hash=%s title=%r", url_hash[:12], title)
        self._emit_doc_fetched(url_hash, target.source, title, dataset_tag)

    async def _handle_pdf(self, url, source, target_name, dataset_tag, target) -> None:
        path = await pdf_pipeline.download_pdf(url, source=source)
        body_md, pdf_meta = pdf_pipeline.parse_pdf(path)
        title = target_name
        url_hash = _url_hash(url)
        save_crawl_doc(
            url_hash=url_hash,
            source=target.source,
            url=url,
            title=title,
            body_md=body_md,
            meta={**pdf_meta, "crawl_type": "pdf", "target": target_name},
        )
        log.info("saved pdf doc url_hash=%s ocr_required=%s", url_hash[:12], pdf_meta.get("ocr_required"))
        self._emit_doc_fetched(url_hash, target.source, title, dataset_tag)

    def _emit_doc_fetched(self, url_hash: str, source: str, title: str, dataset_tag: str) -> None:
        event = make_event(
            Topic.DOC_FETCHED,
            dataset_tag,
            url_hash=url_hash,
            source=source,
            title=title,
        )
        self._bus.emit(event)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _extract_title(html: str) -> str:
    """Best-effort title extraction from raw HTML."""
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:200]
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if m:
        import re as _re
        return _re.sub(r"<[^>]+>", "", m.group(1)).strip()[:200]
    return ""


def register(bus: EventBus) -> CrawlerAgent:
    """Wire CrawlerAgent into *bus*; called by cli.py."""
    return CrawlerAgent(bus)
