"""Login via Basic Auth to obtain a fresh session cookie and write to .state/session.json."""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CREDS = ROOT / ".state" / "credentials.json"
STATE = ROOT / ".state" / "session.json"


def main():
    if not CREDS.exists():
        print(f"missing {CREDS}", file=sys.stderr); sys.exit(2)
    creds = json.loads(CREDS.read_text(encoding="utf-8"))
    s = requests.Session()
    s.proxies.update({"http": None, "https": None})
    s.trust_env = False
    resp = s.post(
        "https://api.worldquantbrain.com/authentication",
        auth=(creds["email"], creds["password"]),
        headers={"Accept": "application/json;version=2.0"},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"login failed: HTTP {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)
    cookies = [
        {"name": c.name, "value": c.value,
         "domain": c.domain or "api.worldquantbrain.com",
         "path": c.path or "/", "expires": c.expires or -1,
         "httpOnly": False, "secure": bool(c.secure), "sameSite": "None"}
        for c in s.cookies
    ]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2), encoding="utf-8")
    print(f"wrote {STATE} with {len(cookies)} cookies")


if __name__ == "__main__":
    main()
