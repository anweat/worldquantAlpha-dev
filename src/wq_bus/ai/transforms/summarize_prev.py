"""Default chain_hook transform — emit a compact JSON summary of previous task output."""
from __future__ import annotations

import json

NAME = "summarize_prev"


def transform(prev_output: dict, ctx: dict) -> str:
    if not prev_output:
        return ""
    try:
        body = json.dumps(prev_output, ensure_ascii=False)[:1500]
    except Exception:
        body = str(prev_output)[:1500]
    return f"## Previous task result\n```json\n{body}\n```\n"
