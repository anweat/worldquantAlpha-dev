"""client.py — Synchronous BRAIN API client.

BrainClient is synchronous (requests-based). Asyncio agents call it via
asyncio.get_event_loop().run_in_executor(None, ...) or similar.

Key behaviours preserved from legacy brain_client.py:
- Proxy bypass in session.py (mandatory — Clash breaks BRAIN SSL)
- Cookie loaded from .state/session.json (Playwright storage_state format)
- 429 retry with Retry-After header (max 12 retries)
- simulate() → POST /simulations (201 + Location) → poll until COMPLETE → get_alpha()
- get_alpha() returns IS metrics + embedded is.checks (SELF_CORRELATION included)
- DO NOT call /alphas/{id}/check-submission (returns 404 for TUTORIAL accounts)
"""
from __future__ import annotations

import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import requests

from wq_bus.brain.session import load_session

BASE_URL = "https://api.worldquantbrain.com"

_HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 4,
    "neutralization": "MARKET",
    "truncation": 0.05,
    "pasteurization": "ON",   # NOTE: 'pasteurization', NOT 'pasteurize'
    "nanHandling": "OFF",
    "unitHandling": "VERIFY",
    "language": "FASTEXPR",
    "visualization": False,
}

_MAX_RETRIES = 12          # legacy constant kept for simulate() outer loop
_BACKOFF_RETRIES = 5       # retries inside _request_with_retry
_BACKOFF_BASE = 2          # exponential base (seconds)
_BACKOFF_CAP = 60          # maximum single sleep (seconds)
_HTTP_TIMEOUT = (10, 60)   # (connect, read) seconds — prevents indefinite hangs
_RATE_WINDOW = 300         # 5-minute observation window (seconds)
_PRESSURE_TTL = 600        # auto-expire pressure flag after 10 minutes


class BrainClient:
    """Synchronous WorldQuant BRAIN REST API client."""

    # ------------------------------------------------------------------
    # Class-level rate-pressure state (shared across all instances, thread-safe)
    # ------------------------------------------------------------------
    _pressure_lock: threading.Lock = threading.Lock()
    _recent_429s: deque = deque()        # timestamps of 429/503 within last _RATE_WINDOW
    _total_calls_5min: deque = deque()   # timestamps of every request within last _RATE_WINDOW
    is_pressured: bool = False
    _pressure_until: float = 0.0

    def __init__(self, state_path: Path | None = None, *, auto_login: bool = True) -> None:
        if auto_login:
            try:
                from wq_bus.brain.auth import ensure_session
                ensure_session(force=False)
            except Exception:
                pass  # fall through; load_session below will raise if truly missing
        self.session: requests.Session = load_session(state_path)
        self._state_path = state_path
        # Set by sim_executor before running in executor so we can call_soon_threadsafe
        self._main_loop = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        stream: bool = False,
    ) -> requests.Response:
        """Execute a request with adaptive exponential backoff on 429/503.

        Retries up to _BACKOFF_RETRIES times. On each 429 or 503:
        - Sleeps min(60, base * 2^attempt + jitter), honouring Retry-After.
        - Tracks 429s in a 5-min deque; emits RATE_PRESSURE event and sets
          class-level is_pressured=True if rate > 20%.
        - After _BACKOFF_RETRIES, makes one final attempt and returns.
        """
        url = f"{BASE_URL}{path}"

        for attempt in range(_BACKOFF_RETRIES):
            now = time.time()
            # Track call timestamp for rate denominator
            with BrainClient._pressure_lock:
                BrainClient._total_calls_5min.append(now)
                cutoff = now - _RATE_WINDOW
                while BrainClient._recent_429s and BrainClient._recent_429s[0] < cutoff:
                    BrainClient._recent_429s.popleft()
                while BrainClient._total_calls_5min and BrainClient._total_calls_5min[0] < cutoff:
                    BrainClient._total_calls_5min.popleft()

            resp = self.session.request(
                method, url, headers=_HEADERS, params=params, json=json,
                stream=stream, timeout=_HTTP_TIMEOUT,
            )

            if resp.status_code not in (429, 503):
                return resp

            # ---- 429 / 503 handling ----
            ts = time.time()
            emit_pressure = False
            rate = 0.0
            with BrainClient._pressure_lock:
                BrainClient._recent_429s.append(ts)
                cutoff = ts - _RATE_WINDOW
                n_recent = sum(1 for t in BrainClient._recent_429s if t >= cutoff)
                n_total = max(1, sum(1 for t in BrainClient._total_calls_5min if t >= cutoff))
                rate = n_recent / n_total
                if rate > 0.20 and (
                    not BrainClient.is_pressured or ts >= BrainClient._pressure_until
                ):
                    BrainClient.is_pressured = True
                    BrainClient._pressure_until = ts + _PRESSURE_TTL
                    emit_pressure = True

            if emit_pressure:
                self._emit_rate_pressure(rate)

            retry_after = float(resp.headers.get("Retry-After", 0) or 0)
            backoff = min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1))
            wait = max(retry_after, backoff)
            print(
                f"  [{resp.status_code}] backoff {wait:.1f}s "
                f"(attempt {attempt + 1}/{_BACKOFF_RETRIES}, rate_429={rate:.1%}) ..."
            )
            time.sleep(wait)

        # Final attempt — no more retries; return whatever comes back
        return self.session.request(
            method, url, headers=_HEADERS, params=params, json=json,
            stream=stream, timeout=_HTTP_TIMEOUT,
        )

    # Keep _request as an alias so any external callers (tests, etc.) still work
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        stream: bool = False,
    ) -> requests.Response:
        return self._request_with_retry(method, path, params=params, json=json, stream=stream)

    def _emit_rate_pressure(self, rate: float) -> None:
        """Best-effort: emit RATE_PRESSURE on the bus (lazy import to avoid cycle).

        Called from a worker thread, so we use call_soon_threadsafe if the main
        asyncio event loop reference is stored on the instance.
        """
        try:
            from wq_bus.bus.event_bus import get_bus
            from wq_bus.bus.events import make_event
            from wq_bus.utils.tag_context import get_tag
            tag = get_tag() or "UNKNOWN"
            event = make_event(
                "RATE_PRESSURE", tag,
                rate_429=round(rate, 3),
                window_secs=_RATE_WINDOW,
                max_concurrent_new=1,
            )
            loop = self._main_loop
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(get_bus().emit, event)
            else:
                # No async context available; flag is already set — skip emit
                pass
        except Exception:
            pass  # emission is best-effort; pressure flag already set

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._request_with_retry("GET", path, params=params)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _post(self, path: str, payload: Any = None) -> requests.Response:
        return self._request_with_retry("POST", path, json=payload or {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_auth(self) -> bool:
        """Return True if the current session is authenticated (GET /authentication).

        On 401/expired, attempts a one-shot re-login using stored credentials and
        retries the check. Returns False if re-login is impossible.
        """
        resp = self._request("GET", "/authentication")
        if resp.status_code == 200:
            return True
        # Try auto-recovery (only once per call) using stored credentials
        try:
            from wq_bus.brain.auth import ensure_session
            if ensure_session(force=True):
                self.session = load_session(self._state_path)
                resp2 = self._request("GET", "/authentication")
                return resp2.status_code == 200
        except Exception:
            pass
        return False

    def simulate(
        self,
        expression: str,
        settings: dict | None = None,
        *,
        poll_interval: int = 8,
        max_wait: int = 600,
    ) -> dict:
        """Submit a simulation and poll until COMPLETE; returns the alpha record.

        Settings are merged onto DEFAULT_SETTINGS (caller overrides take precedence).
        On success, automatically calls get_alpha() and returns the full alpha record.
        Returns a dict with key 'error' on failure.
        """
        merged = {**DEFAULT_SETTINGS, **(settings or {})}
        payload = {"type": "REGULAR", "settings": merged, "regular": expression}

        # Submit simulation — _request_with_retry handles 429/503 with adaptive backoff.
        resp = self._post("/simulations", payload)
        if resp.status_code != 201:
            return {"error": resp.status_code, "body": resp.text}

        sim_url = resp.headers.get("Location", "")
        sim_id = sim_url.rstrip("/").split("/")[-1] if sim_url else None
        if not sim_id:
            return {"error": "no_sim_id", "location": sim_url}

        # Honour the server's Retry-After hint before first poll
        initial_wait = float(resp.headers.get("Retry-After", poll_interval))
        time.sleep(initial_wait)

        # Poll until terminal state
        sim_result = self._poll(sim_id, poll_interval=poll_interval, max_wait=max_wait)
        if "error" in sim_result:
            return sim_result

        alpha_id = sim_result.get("alpha")
        if not alpha_id:
            return {"error": "no_alpha_id", "sim": sim_result}

        return self.get_alpha(alpha_id)

    def _poll(self, sim_id: str, *, poll_interval: int, max_wait: int) -> dict:
        """Poll GET /simulations/{id} until terminal status."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                data = self._get(f"/simulations/{sim_id}")
            except requests.HTTPError:
                time.sleep(poll_interval)
                continue

            status = data.get("status", "UNKNOWN")
            if status == "COMPLETE":
                return data
            if status in ("ERROR", "FAILED"):
                return {"error": "simulation_error", "data": data}
            # UNKNOWN / PENDING / WARNING → keep polling
            time.sleep(poll_interval)

        return {"error": "timeout", "sim_id": sim_id}

    def get_alpha(self, alpha_id: str) -> dict:
        """GET /alphas/{id} — returns IS metrics + embedded is.checks."""
        return self._get(f"/alphas/{alpha_id}")

    def submit_alpha(self, alpha_id: str) -> dict:
        """POST /alphas/{id}/submit — submit an alpha for review."""
        resp = self._post(f"/alphas/{alpha_id}/submit")
        return {"status": resp.status_code, "body": resp.json() if resp.content else {}}

    def get_pnl(self, alpha_id: str) -> list[tuple[str, float]]:
        """GET /alphas/{id}/recordsets/pnl — returns [(date, pnl), ...].

        Parses the response's schema.properties + records arrays.
        Returns empty list on any failure (tolerant).
        """
        try:
            data = self._get(f"/alphas/{alpha_id}/recordsets/pnl")
        except Exception:
            return []

        try:
            schema = data.get("schema", {})
            props = schema.get("properties", {})
            # Build column index: find which column index maps to 'date' and 'pnl'
            # properties is typically {"date": {"index": 0}, "pnl": {"index": 1}}
            date_idx: int | None = None
            pnl_idx: int | None = None
            for col_name, col_info in props.items():
                lc = col_name.lower()
                if lc == "date":
                    date_idx = col_info.get("index")
                elif lc in ("pnl", "cum_pnl", "returns", "ret"):
                    pnl_idx = col_info.get("index")

            if date_idx is None or pnl_idx is None:
                # Fallback: assume first two columns are date, pnl
                date_idx, pnl_idx = 0, 1

            records = data.get("records", [])
            result: list[tuple[str, float]] = []
            for row in records:
                try:
                    result.append((str(row[date_idx]), float(row[pnl_idx])))
                except (IndexError, TypeError, ValueError):
                    continue
            return result
        except Exception:
            return []

    def get_operators(self) -> list[dict]:
        """GET /operators?limit=200 — returns list of operator definitions."""
        data = self._get("/operators", params={"limit": 200})
        if isinstance(data, list):
            return data
        return data.get("results", data.get("operators", []))

    def get_user_alphas(
        self, user_id: str = "self", limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """GET /users/{user_id}/alphas — returns list of alpha records."""
        data = self._get(
            f"/users/{user_id}/alphas",
            params={"limit": limit, "offset": offset},
        )
        if isinstance(data, list):
            return data
        return data.get("results", data.get("alphas", []))
