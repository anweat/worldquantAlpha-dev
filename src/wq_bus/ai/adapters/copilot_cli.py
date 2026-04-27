"""Copilot CLI adapter — invokes the GitHub Copilot CLI as a subprocess."""
from __future__ import annotations

import asyncio
import os
import subprocess
from typing import Optional

from wq_bus.utils.logging import get_logger
from wq_bus.utils.yaml_loader import load_yaml

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Probe: detect which flags the installed copilot CLI supports.
# Run once at module import; cache forever in process.
# ---------------------------------------------------------------------------

_PROBED: bool = False
_SUPPORTS_ALLOW_ALL_TOOLS: bool = False
_SUPPORTS_NO_COLOR: bool = False


def _probe_flags() -> None:
    """Run `copilot --help` once and cache which flags are advertised."""
    global _PROBED, _SUPPORTS_ALLOW_ALL_TOOLS, _SUPPORTS_NO_COLOR
    if _PROBED:
        return
    _PROBED = True
    try:
        result = subprocess.run(
            [_resolve_binary(), "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
        help_text = result.stdout + result.stderr
        _SUPPORTS_ALLOW_ALL_TOOLS = "--allow-all-tools" in help_text
        _SUPPORTS_NO_COLOR = "--no-color" in help_text
        _log.debug(
            "copilot flags probe: allow-all-tools=%s no-color=%s",
            _SUPPORTS_ALLOW_ALL_TOOLS, _SUPPORTS_NO_COLOR,
        )
    except Exception as e:
        _log.debug("copilot --help probe failed (non-fatal): %s", e)


def _resolve_binary() -> str:
    env_bin = os.environ.get("WQBUS_COPILOT_BIN")
    if env_bin:
        return env_bin
    try:
        cfg = load_yaml("ai_dispatch").get("adapters", {}).get("copilot", {})
        return cfg.get("binary", "copilot")
    except Exception:
        return "copilot"


def _build_prompt(messages: list[dict]) -> str:
    """Concatenate chat messages into a single prompt string.

    Each message is rendered as ``[ROLE]\\ncontent``.
    """
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


class CopilotAdapter:
    """Runs the Copilot CLI binary as a subprocess to generate completions.

    Binary resolved (in order):
    1. ``WQBUS_COPILOT_BIN`` environment variable.
    2. ``adapters.copilot.binary`` in ``config/ai_dispatch.yaml``.
    3. Hardcoded fallback: ``copilot``.

    Raises :class:`RuntimeError` if the binary is not found or times out.
    """

    def _binary(self) -> str:
        return _resolve_binary()

    def _timeout(self) -> int:
        try:
            cfg = load_yaml("ai_dispatch").get("adapters", {}).get("copilot", {})
            return int(cfg.get("timeout_secs", 120))
        except Exception:
            return 120

    async def call(
        self,
        messages: list[dict],
        model: str,
        depth: str | None = None,
    ) -> str:
        """Invoke the Copilot CLI and return its stdout text.

        Args:
            messages: Chat messages in ``[{"role": ..., "content": ...}]`` format.
            model: Model identifier passed via ``--model``.
            depth: Optional depth/reasoning hint passed via ``--depth``.

        Returns:
            Raw stdout text from the CLI.

        Raises:
            RuntimeError: Binary not found or process timed out.
        """
        # Probe flags once (idempotent)
        _probe_flags()

        prompt = _build_prompt(messages)
        if depth:
            prompt = f"[reasoning depth: {depth}]\n\n" + prompt
        binary = self._binary()
        args = [binary, "-p", prompt, "--model", model]

        # Append optional flags only if supported by this CLI version
        if _SUPPORTS_ALLOW_ALL_TOOLS:
            args.append("--allow-all-tools")
        if _SUPPORTS_NO_COLOR:
            args.append("--no-color")

        _log.debug(
            "Calling copilot CLI binary=%r model=%r prompt_len=%d flags=%r",
            binary, model, len(prompt), args[4:],
        )

        # Non-interactive environment variables
        extra_env = {
            "WQBUS_NONINTERACTIVE": "1",
            "CI": "1",
            "COPILOT_NO_TELEMETRY": "1",
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
        env = {**os.environ, **extra_env}

        # Windows: when the parent (daemon) was launched detached with redirected
        # stdio, copilot.exe inherits no console handle and crashes with 0xC0000005.
        # Use CREATE_NO_WINDOW to give the child its own hidden console, and DEVNULL
        # stdin to avoid inheriting a closed/redirected pipe.
        kwargs: dict = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "stdin":  asyncio.subprocess.DEVNULL,
            "env":    env,
        }
        if os.name == "nt":
            import subprocess as _sp
            # CREATE_NO_WINDOW = 0x08000000 — allocates a hidden console.
            kwargs["creationflags"] = getattr(_sp, "CREATE_NO_WINDOW", 0x08000000)

        try:
            proc = await asyncio.create_subprocess_exec(*args, **kwargs)
        except FileNotFoundError:
            raise RuntimeError(
                f"copilot CLI not available — binary '{binary}' not found. "
                "Set WQBUS_COPILOT_BIN env var or install the copilot CLI."
            )

        timeout = self._timeout()
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Copilot CLI timed out after {timeout}s")

        if proc.returncode != 0:
            stderr_text = stderr.decode(errors="replace")[:800]
            stdout_text = stdout.decode(errors="replace")
            # Empty stdout on non-zero exit → almost always a real error.
            # Non-empty stdout MAY still be usable, so return it but log loudly.
            if not stdout_text.strip():
                raise RuntimeError(
                    f"Copilot CLI exited {proc.returncode} with empty stdout. "
                    f"stderr: {stderr_text}"
                )
            _log.error(
                "Copilot CLI exited %d but produced stdout — using anyway. stderr: %s",
                proc.returncode,
                stderr_text,
            )

        return stdout.decode(errors="replace")
