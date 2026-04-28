"""robots.txt gate — checked before every crawler fetch (rev-h6).

Policy (per user requirements):
  * Whitelisted domains (default = WorldQuant) are EXEMPT from robots checks
    — we have account/contract/permission for those.
  * For everything else, fetch /robots.txt (cached 24h) and STRICTLY honour:
      - Disallow rules → fetch is blocked (raises RobotsDisallowed)
      - Crawl-delay → caller sleeps that many seconds before request
  * If robots.txt is unreachable (network error, 5xx) → permissive
    (treated as "no robots") to avoid breaking crawls on transient errors;
    404/410 are treated as "no robots, all allowed" per the standard.

Use:
    gate = get_robots_gate()
    allowed, delay = await gate.is_allowed(url)
    if not allowed:
        raise RobotsDisallowed(url)
    if delay:
        await asyncio.sleep(delay)
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from wq_bus.utils.logging import get_logger
from wq_bus.utils.yaml_loader import load_yaml

log = get_logger(__name__)


class RobotsDisallowed(PermissionError):
    """Raised when robots.txt forbids the URL and the domain is not whitelisted."""


class RobotsGate:
    """Async-safe robots.txt cache with whitelist."""

    def __init__(self, whitelist: list[str], user_agent: str,
                 ttl_secs: int = 86400, fetch_timeout: int = 10) -> None:
        self._whitelist = {d.strip().lower() for d in (whitelist or []) if d.strip()}
        self._user_agent = user_agent
        self._ttl = ttl_secs
        self._fetch_timeout = fetch_timeout
        # host -> (RobotFileParser | None, expires_at)
        self._cache: dict[str, tuple[Optional[RobotFileParser], float]] = {}
        self._lock = asyncio.Lock()

    def _is_whitelisted(self, host: str) -> bool:
        host_only = host.split(":")[0].lower()
        for d in self._whitelist:
            if host_only == d or host_only.endswith("." + d):
                return True
        return False

    async def is_allowed(self, url: str) -> tuple[bool, float]:
        """Return (allowed, crawl_delay_secs).

        - Whitelisted domains: always (True, 0.0), no network call.
        - Other domains: fetch & cache /robots.txt; honour Disallow + Crawl-delay.
        - Unreachable robots: permissive (True, 0.0) — log only.
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return True, 0.0
        host = parsed.netloc
        if not host:
            return True, 0.0
        if self._is_whitelisted(host):
            return True, 0.0
        scheme = parsed.scheme or "https"
        rp = await self._get_or_fetch(scheme, host)
        if rp is None:
            return True, 0.0
        try:
            allowed = rp.can_fetch(self._user_agent, url)
        except Exception:
            log.exception("robots can_fetch raised for %s — defaulting to allow", url)
            allowed = True
        try:
            delay = rp.crawl_delay(self._user_agent) or 0.0
        except Exception:
            delay = 0.0
        return bool(allowed), float(delay)

    async def _get_or_fetch(self, scheme: str, host: str) -> Optional[RobotFileParser]:
        now = time.time()
        async with self._lock:
            entry = self._cache.get(host)
            if entry and entry[1] > now:
                return entry[0]

        rp = await self._fetch_robots(scheme, host)
        async with self._lock:
            self._cache[host] = (rp, time.time() + self._ttl)
        return rp

    async def _fetch_robots(self, scheme: str, host: str) -> Optional[RobotFileParser]:
        url = f"{scheme}://{host}/robots.txt"
        try:
            import aiohttp
        except ImportError:
            log.warning("aiohttp not available — skipping robots check for %s", host)
            return None
        try:
            async with aiohttp.ClientSession(
                trust_env=False,
                timeout=aiohttp.ClientTimeout(total=self._fetch_timeout),
                headers={"User-Agent": self._user_agent},
            ) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status in (404, 410):
                        # No robots.txt published → all allowed (per RFC 9309 §2.3.1.3).
                        rp = RobotFileParser()
                        rp.parse([])
                        return rp
                    if resp.status >= 400:
                        log.info("robots.txt %s returned %d — treating as permissive",
                                 url, resp.status)
                        return None
                    text = await resp.text(errors="replace")
        except Exception as e:  # noqa: BLE001
            log.info("robots.txt fetch failed for %s: %s — treating as permissive",
                     url, e)
            return None
        rp = RobotFileParser()
        try:
            rp.parse(text.splitlines())
        except Exception:
            log.exception("robots.txt parse failed for %s", host)
            return None
        return rp

    def clear_cache(self) -> None:
        """For tests / config reload."""
        self._cache.clear()


# ---------------------------------------------------------------------------
# Module-level singleton — one gate per process, configured from crawler.yaml
# ---------------------------------------------------------------------------

_GATE: RobotsGate | None = None
# Default whitelist: all WorldQuant BRAIN domains (we have explicit permission).
_DEFAULT_WHITELIST = [
    "platform.worldquantbrain.com",
    "api.worldquantbrain.com",
    "support.worldquantbrain.com",
    "wqplatform.zendesk.com",
]
_DEFAULT_USER_AGENT = "wq-bus-crawler/1.0 (+contact: research)"


def get_robots_gate() -> RobotsGate:
    """Return the process-wide RobotsGate, building from config on first call."""
    global _GATE
    if _GATE is None:
        try:
            cfg = load_yaml("crawler") or {}
        except Exception:
            cfg = {}
        crawler_cfg = cfg.get("crawler") or {}
        whitelist = list(crawler_cfg.get("robots_whitelist_domains", _DEFAULT_WHITELIST))
        ua = crawler_cfg.get("user_agent") or _DEFAULT_USER_AGENT
        ttl = int(crawler_cfg.get("robots_cache_ttl_secs", 86400))
        _GATE = RobotsGate(whitelist=whitelist, user_agent=ua, ttl_secs=ttl)
    return _GATE


def reset_gate() -> None:
    """For tests / config reload."""
    global _GATE
    _GATE = None


def is_robots_check_enabled() -> bool:
    """Read crawler.respect_robots_txt at call time (no caching)."""
    try:
        cfg = load_yaml("crawler") or {}
    except Exception:
        return True
    crawler_cfg = cfg.get("crawler") or {}
    return bool(crawler_cfg.get("respect_robots_txt", True))
