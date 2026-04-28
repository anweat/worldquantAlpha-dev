"""check_copilot_cli.py — Pre-flight check for the GitHub Copilot CLI.

Spawns a 1-token probe ("reply OK"), waits up to 30 seconds.
Exits 0 if the CLI responds, exits 1 with a diagnostic if it hangs or is absent.

Auto-detects supported flags by parsing `copilot --help`.

Usage:
    python scripts/check_copilot_cli.py [--binary PATH] [--timeout 30]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def _find_binary(user_bin: str | None) -> str:
    if user_bin:
        return user_bin
    env_bin = os.environ.get("WQBUS_COPILOT_BIN")
    if env_bin:
        return env_bin
    # Try to read from config/ai_dispatch.yaml
    try:
        _root = Path(__file__).parent.parent
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from wq_bus.utils.yaml_loader import load_yaml
        cfg = load_yaml("ai_dispatch").get("adapters", {}).get("copilot", {})
        return cfg.get("binary", "copilot")
    except Exception:
        return "copilot"


def _probe_flags(binary: str) -> tuple[bool, bool]:
    """Return (supports_allow_all_tools, supports_no_color)."""
    try:
        result = subprocess.run(
            [binary, "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
        help_text = result.stdout + result.stderr
        return "--allow-all-tools" in help_text, "--no-color" in help_text
    except FileNotFoundError:
        return False, False
    except subprocess.TimeoutExpired:
        return False, False
    except Exception:
        return False, False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check GitHub Copilot CLI availability")
    parser.add_argument("--binary", default=None, help="Path to copilot binary.")
    parser.add_argument("--timeout", default=30, type=int, help="Probe timeout in seconds.")
    args = parser.parse_args()

    binary = _find_binary(args.binary)
    print(f"[check_copilot_cli] binary: {binary!r}")

    # Step 1: verify binary exists
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
        version_info = (result.stdout + result.stderr).strip()
        print(f"[check_copilot_cli] version: {version_info[:120]}")
    except FileNotFoundError:
        print(
            f"[check_copilot_cli] ERROR: binary not found: {binary!r}\n"
            "  Install GitHub Copilot CLI and make sure it is on PATH,\n"
            "  or set WQBUS_COPILOT_BIN env var to the full path.\n"
            "  See README.md §First-time copilot CLI setup.",
            file=sys.stderr,
        )
        return 1
    except subprocess.TimeoutExpired:
        print(f"[check_copilot_cli] WARN: --version timed out", file=sys.stderr)

    # Step 2: detect supported flags
    supports_allow_all_tools, supports_no_color = _probe_flags(binary)
    print(f"[check_copilot_cli] --allow-all-tools supported: {supports_allow_all_tools}")
    print(f"[check_copilot_cli] --no-color supported:         {supports_no_color}")

    # Step 3: 1-token probe
    probe_prompt = "reply OK"
    cmd = [binary, "-p", probe_prompt]
    if supports_allow_all_tools:
        cmd.append("--allow-all-tools")
    if supports_no_color:
        cmd.append("--no-color")

    extra_env = {
        **os.environ,
        "WQBUS_NONINTERACTIVE": "1",
        "CI": "1",
        "COPILOT_NO_TELEMETRY": "1",
        "NO_COLOR": "1",
        "TERM": "dumb",
    }

    print(f"[check_copilot_cli] running probe (timeout={args.timeout}s)…")
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
            env=extra_env,
        )
        elapsed = time.time() - start
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if proc.returncode == 0:
            print(f"[check_copilot_cli] OK — responded in {elapsed:.1f}s")
            print(f"  stdout[:200]: {stdout[:200]}")
            return 0
        else:
            print(
                f"[check_copilot_cli] WARN: probe exited {proc.returncode} in {elapsed:.1f}s",
                file=sys.stderr,
            )
            if stderr:
                print(f"  stderr: {stderr[:300]}", file=sys.stderr)
            # Non-zero but responded — CLI is present, may just need login
            if "login" in (stdout + stderr).lower() or "auth" in (stdout + stderr).lower():
                print(
                    "[check_copilot_cli] HINT: CLI requires authentication.\n"
                    "  Run: copilot auth login\n"
                    "  See README.md §First-time copilot CLI setup.",
                    file=sys.stderr,
                )
            return 1
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(
            f"[check_copilot_cli] ERROR: probe hung after {elapsed:.1f}s\n"
            "  Possible causes:\n"
            "    1. copilot CLI waiting for interactive input (not logged in)\n"
            "    2. Network / proxy blocking outbound connections\n"
            "  Fix: run `copilot auth login` in a terminal with full console access.\n"
            "  See README.md §First-time copilot CLI setup.",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError:
        print(f"[check_copilot_cli] ERROR: binary not found: {binary!r}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[check_copilot_cli] ERROR: unexpected: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
