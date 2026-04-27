"""Prompt packing/unpacking for batched sub-agent calls."""
from __future__ import annotations

import json
import re
from pathlib import Path

from wq_bus.utils.logging import get_logger
from wq_bus.utils.yaml_loader import CONFIG_DIR

_log = get_logger(__name__)

_PROMPTS_DIR: Path = CONFIG_DIR / "prompts"

_GENERIC_TEMPLATE = """\
You are processing {N} independent tasks in BATCH MODE.
Return a single JSON array (no markdown fences) of length {N},
where element i is the result for task i.

Tasks:
{TASKS_JSON}

Important: respond with ONLY the JSON array, no additional text."""


def _load_template(agent_type: str) -> str:
    """Load the prompt template for *agent_type*; fall back to generic default."""
    candidates = [
        _PROMPTS_DIR / f"_subagent_pack.{agent_type}.md",
        _PROMPTS_DIR / "_subagent_pack._default.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return _GENERIC_TEMPLATE


def pack(payloads: list[dict], agent_type: str) -> str:
    """Build a single prompt asking the AI to return one result per payload.

    Args:
        payloads: List of task dicts to pack into one request.
        agent_type: Selects the prompt template from ``config/prompts/``.

    Returns:
        Prompt string with ``{N}`` and ``{TASKS_JSON}`` substituted.
    """
    template = _load_template(agent_type)
    tasks_json = json.dumps(payloads, ensure_ascii=False, indent=2)
    return template.replace("{N}", str(len(payloads))).replace("{TASKS_JSON}", tasks_json)


def unpack(response_text: str, n_expected: int) -> list[dict]:
    """Parse a JSON list from AI response text.

    Tolerant of markdown code fences (```json ... ```) and partial output.
    Pads with empty dicts if fewer than *n_expected* items are returned.

    Args:
        response_text: Raw text returned by the AI adapter.
        n_expected: Expected number of result elements.

    Returns:
        List of result dicts, always of length *n_expected*.
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", response_text).strip().rstrip("`").strip()

    # Extract outermost JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            results: list[dict] = [r if isinstance(r, dict) else {} for r in parsed[:n_expected]]
            while len(results) < n_expected:
                results.append({})
            return results
    except json.JSONDecodeError as exc:
        # Try tolerant prefix-decode (raw_decode parses a valid JSON prefix)
        try:
            decoder = json.JSONDecoder()
            obj, _idx = decoder.raw_decode(text.lstrip())
            if isinstance(obj, list):
                results = [r if isinstance(r, dict) else {} for r in obj[:n_expected]]
                while len(results) < n_expected:
                    results.append({})
                _log.info("subagent_packer recovered %d items via raw_decode", len(obj))
                return results
            if isinstance(obj, dict):
                _log.info("subagent_packer recovered single dict via raw_decode")
                return [obj] + [{} for _ in range(n_expected - 1)]
        except json.JSONDecodeError:
            pass
        _log.warning(
            "Failed to parse packed response: %s — raw snippet: %.200s",
            exc, response_text,
        )

    return [{} for _ in range(n_expected)]
