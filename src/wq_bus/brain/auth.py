"""auth.py — automatic login & session refresh.

Mirrors the legacy `src/login.py` Basic-Auth login flow but exposes a single
:func:`ensure_session` API used by both the CLI (`wqbus login`) and the
BrainClient (auto-recovery on 401).

Credentials are read from ``.state/credentials.json`` (gitignored) which must
contain ``{"email": "...", "password": "..."}``. If the file is missing or
the env vars ``WQBRAIN_EMAIL`` / ``WQBRAIN_PASSWORD`` are not set, callers
must perform an interactive login outside this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import requests

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STATE_DIR = _PROJECT_ROOT / ".state"
_CREDS_PATH = _STATE_DIR / "credentials.json"
_SESSION_PATH = _STATE_DIR / "session.json"

_API_BASE = "https://api.worldquantbrain.com"


def _read_credentials() -> Optional[tuple[str, str]]:
    """Return (email, password) from env or .state/credentials.json, or None."""
    email = os.environ.get("WQBRAIN_EMAIL", "").strip()
    password = os.environ.get("WQBRAIN_PASSWORD", "").strip()
    if email and password:
        return email, password
    if _CREDS_PATH.exists():
        try:
            data = json.loads(_CREDS_PATH.read_text(encoding="utf-8"))
            return str(data.get("email", "")).strip(), str(data.get("password", "")).strip()
        except Exception:
            return None
    return None


def login_with_credentials(email: str, password: str) -> bool:
    """Submit Basic Auth, write fresh storage_state to .state/session.json.

    Returns True on success.
    """
    sess = requests.Session()
    sess.proxies.update({"http": None, "https": None})
    sess.trust_env = False
    resp = sess.post(
        f"{_API_BASE}/authentication",
        auth=(email, password),
        headers={"Accept": "application/json;version=2.0"},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        return False
    cookies = [
        {
            "name": c.name, "value": c.value,
            "domain": c.domain or "api.worldquantbrain.com",
            "path": c.path or "/",
            "expires": c.expires if c.expires else -1,
            "httpOnly": False,
            "secure": bool(c.secure),
            "sameSite": "None",
        }
        for c in sess.cookies
    ]
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _SESSION_PATH.write_text(
        json.dumps({"cookies": cookies, "origins": []}, indent=2),
        encoding="utf-8",
    )
    return True


def session_is_valid() -> bool:
    """Quick check: does .state/session.json exist and authenticate against /authentication?"""
    if not _SESSION_PATH.exists():
        return False
    try:
        from wq_bus.brain.session import load_session
        sess = load_session()
        r = sess.get(f"{_API_BASE}/authentication",
                     headers={"Accept": "application/json;version=2.0"},
                     timeout=15)
        # 200 = authenticated, 401/204 = expired/invalid
        return r.status_code == 200
    except Exception:
        return False


def ensure_session(force: bool = False) -> bool:
    """Ensure a valid session exists. Auto-login from stored credentials if possible.

    Args:
        force: If True, re-login even if the existing session looks valid.

    Returns:
        True if a valid session is in place after the call, False otherwise.
    """
    if not force and session_is_valid():
        return True
    creds = _read_credentials()
    if not creds:
        return False
    email, password = creds
    if not email or not password:
        return False
    return login_with_credentials(email, password)
