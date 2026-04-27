"""OpenAI API adapter — calls /chat/completions via aiohttp."""
from __future__ import annotations

import asyncio
import os

import aiohttp

from wq_bus.utils.logging import get_logger
from wq_bus.utils.yaml_loader import load_yaml

_log = get_logger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _adapter_cfg() -> dict:
    try:
        return (load_yaml("ai_dispatch").get("adapters") or {}).get("openai") or {}
    except Exception:
        return {}


class OpenAIAdapter:
    """Calls an OpenAI-compatible ``/chat/completions`` endpoint.

    Env var names are resolved from ``config/ai_dispatch.yaml`` →
    ``adapters.openai.{base_url_env,key_env}`` (defaults: ``OPENAI_BASE_URL``
    / ``OPENAI_API_KEY``).

    Handles HTTP 429 with one automatic retry honoring ``Retry-After``.
    """

    def _base_url(self) -> str:
        env_name = _adapter_cfg().get("base_url_env", "OPENAI_BASE_URL")
        return os.environ.get(env_name, _DEFAULT_BASE_URL).rstrip("/")

    def _api_key(self) -> str:
        env_name = _adapter_cfg().get("key_env", "OPENAI_API_KEY")
        return os.environ.get(env_name, "")

    async def call(
        self,
        messages: list[dict],
        model: str,
        depth: str | None = None,
    ) -> str:
        """Send a chat completion request; retry once on HTTP 429.

        Args:
            messages: OpenAI-format message list.
            model: Model identifier string.
            depth: Ignored (included for adapter interface parity).

        Returns:
            The ``choices[0].message.content`` string from the response.
        """
        url = f"{self._base_url()}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        body: dict = {"model": model, "messages": messages}

        async with aiohttp.ClientSession() as session:
            for attempt in range(2):
                async with session.post(url, json=body, headers=headers) as resp:
                    if resp.status == 429 and attempt == 0:
                        retry_after = float(resp.headers.get("Retry-After", "5"))
                        _log.warning("OpenAI 429 — retrying after %.1fs", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]

        raise RuntimeError("OpenAI call failed after retries")
