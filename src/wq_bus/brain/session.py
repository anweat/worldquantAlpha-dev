"""session.py — Load Playwright storage_state, inject cookies into requests.Session.

CRITICAL: proxy bypass is mandatory — system proxies (Clash etc.) break BRAIN SSL.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # src/wq_bus/brain/session.py -> project root
_DEFAULT_STATE_PATH = _PROJECT_ROOT / ".state" / "session.json"


def load_session(state_path: Path | None = None) -> requests.Session:
    """Load Playwright storage_state JSON and return a configured requests.Session.

    Extracts all cookies (especially the JWT cookie named 't') and injects them
    into the session. Proxy bypass is applied unconditionally — system proxies
    such as Clash on 127.0.0.1:7897 break BRAIN API SSL handshakes.

    Args:
        state_path: Path to the Playwright storage_state JSON file.
                    Defaults to .state/session.json at project root.

    Raises:
        FileNotFoundError: If the state file does not exist.
        ValueError: If the state file contains no cookies.
    """
    path = state_path or _DEFAULT_STATE_PATH
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Session file not found: {path}\n"
            "Run the login script (e.g. python src/login.py) to generate it."
        )

    with open(path, encoding="utf-8") as f:
        state = json.load(f)

    cookies = state.get("cookies", [])
    if not cookies:
        raise ValueError(
            f"No cookies found in session file: {path}\n"
            "The session may have expired — re-run the login script."
        )

    session = requests.Session()

    # CRITICAL: disable all system proxies — Clash / system proxies break BRAIN SSL.
    session.proxies.update({"http": None, "https": None})
    session.trust_env = False

    jwt_found = False
    for c in cookies:
        session.cookies.set(
            c["name"],
            c["value"],
            domain=c.get("domain", ""),
        )
        if c["name"] == "t":
            jwt_found = True

    if not jwt_found:
        # Non-fatal warning — the 't' cookie is the JWT, but we continue anyway.
        import warnings
        warnings.warn(
            "Cookie named 't' (JWT) not found in session file. "
            "Authentication may fail.",
            stacklevel=2,
        )

    return session
