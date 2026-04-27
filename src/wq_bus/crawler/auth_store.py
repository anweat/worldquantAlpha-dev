"""Credential and cookie management for crawler sources.

Reads from .secrets/crawl_accounts.yaml (gitignored) and
.secrets/cookies/{source}.json (Playwright storage_state OR plain {name: value}).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SECRETS_DIR = _PROJECT_ROOT / ".secrets"
_COOKIES_DIR = _SECRETS_DIR / "cookies"
_ACCOUNTS_FILE = _SECRETS_DIR / "crawl_accounts.yaml"


def get_credential(source: str) -> dict | None:
    """Return credential dict for *source* from crawl_accounts.yaml, or None."""
    if not _ACCOUNTS_FILE.exists():
        return None
    try:
        with _ACCOUNTS_FILE.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except Exception:
        return None
    accounts = data.get("accounts", {})
    entry = accounts.get(source)
    if entry is None:
        return None
    return dict(entry) if isinstance(entry, dict) else {}


def load_cookies(source: str) -> dict | None:
    """Load cookies for *source* from .secrets/cookies/{source}.json.

    Handles both Playwright storage_state format (has 'cookies' list with
    'name'/'value' keys) and a plain {name: value} dict.
    Returns a flat {name: value} dict suitable for requests.Session.cookies.update(),
    or None if the file is missing.
    """
    path = _COOKIES_DIR / f"{source}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            raw: Any = json.load(f)
    except Exception:
        return None

    if isinstance(raw, dict) and "cookies" in raw:
        # Playwright storage_state: {"cookies": [{"name": ..., "value": ..., ...}]}
        return {c["name"]: c["value"] for c in raw["cookies"] if "name" in c and "value" in c}

    if isinstance(raw, dict):
        return raw

    return None


def save_cookies(source: str, cookies: dict) -> None:
    """Persist *cookies* (plain {name: value}) to .secrets/cookies/{source}.json."""
    _COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    path = _COOKIES_DIR / f"{source}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
