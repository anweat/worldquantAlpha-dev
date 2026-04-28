"""Prompt template registry — load + render templates from config/prompts/.

Each prompt_kind maps to a YAML file with `system`, `user`, and `variables`
sections. Rendering is plain ``{{var}}`` substitution (no jinja loops/filters)
to keep templates auditable and avoid execution surprises in AI prompts.

Usage:
    from wq_bus.ai.prompt_registry import render
    rendered = render("alpha_gen.explore", {"dataset_tag": "usa_top3000",
                                            "n": 5, ...})
    # rendered.system, rendered.user, rendered.meta
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from wq_bus.utils.yaml_loader import load_yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class PromptError(Exception):
    """Raised when a prompt template / variable / kind is malformed."""


@dataclass(frozen=True)
class PromptMeta:
    kind: str
    default_model: str
    adapter_hint: Optional[str]
    response_format: str       # "json" | "text"
    timeout_secs: int
    description: str


@dataclass(frozen=True)
class RenderedPrompt:
    system: str
    user: str
    meta: PromptMeta
    variables: tuple[str, ...]   # required vars from the template


@lru_cache(maxsize=1)
def _index() -> dict:
    raw = load_yaml("prompts/index") or {}
    return {
        "defaults": raw.get("defaults") or {},
        "prompts": raw.get("prompts") or {},
    }


def reload() -> None:
    """Drop caches; re-read prompts/index.yaml + per-kind files."""
    _index.cache_clear()
    _load_template.cache_clear()


def _meta_for(kind: str) -> PromptMeta:
    idx = _index()
    defaults = idx["defaults"]
    entry = (idx["prompts"] or {}).get(kind)
    if entry is None:
        raise PromptError(f"unknown prompt_kind {kind!r} (not in prompts/index.yaml)")
    return PromptMeta(
        kind=kind,
        default_model=str(entry.get("default_model", defaults.get("default_model", "claude-sonnet-4.6"))),
        adapter_hint=entry.get("adapter_hint", defaults.get("adapter_hint")),
        response_format=str(entry.get("response_format", defaults.get("response_format", "json"))),
        timeout_secs=int(entry.get("timeout_secs", defaults.get("timeout_secs", 120))),
        description=str(entry.get("description", "")),
    )


@lru_cache(maxsize=64)
def _load_template(kind: str) -> dict:
    """Load config/prompts/<kind>.yaml. Raises PromptError if missing."""
    p = PROMPTS_DIR / f"{kind}.yaml"
    if not p.exists():
        raise PromptError(f"prompt template file missing: {p}")
    raw = load_yaml(f"prompts/{kind}") or {}
    if not isinstance(raw, dict):
        raise PromptError(f"prompt {kind}: yaml is not a mapping")
    if "system" not in raw or "user" not in raw:
        raise PromptError(f"prompt {kind}: requires 'system' and 'user' keys")
    return raw


def _render_str(template: str, vars: dict[str, Any]) -> tuple[str, set[str]]:
    """Return (rendered, missing_var_names)."""
    missing: set[str] = set()

    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name not in vars:
            missing.add(name)
            return m.group(0)
        v = vars[name]
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            import json
            return json.dumps(v, ensure_ascii=False, default=str)
        return str(v)

    return _VAR_RE.sub(repl, template), missing


def render(kind: str, vars: Optional[dict[str, Any]] = None,
           *, strict: bool = True) -> RenderedPrompt:
    """Render *kind* template with *vars*. ``strict=True`` raises if any
    declared variable is missing (defensive default; flip for free-form)."""
    vars = dict(vars or {})
    meta = _meta_for(kind)
    tpl = _load_template(kind)
    declared = tuple(str(v) for v in (tpl.get("variables") or []))
    if strict:
        missing_declared = [v for v in declared if v not in vars]
        if missing_declared:
            raise PromptError(
                f"prompt {kind}: missing declared variables {missing_declared}"
            )
    sys_text, miss_sys = _render_str(str(tpl["system"]), vars)
    usr_text, miss_usr = _render_str(str(tpl["user"]),   vars)
    if strict and (miss_sys | miss_usr):
        raise PromptError(
            f"prompt {kind}: unresolved {{...}} references: "
            f"{sorted((miss_sys | miss_usr))}"
        )
    return RenderedPrompt(system=sys_text, user=usr_text, meta=meta, variables=declared)


def list_kinds() -> list[str]:
    return sorted((_index()["prompts"] or {}).keys())


def validate() -> list[str]:
    """Return list of validation errors across all registered prompts."""
    errs: list[str] = []
    for kind in list_kinds():
        try:
            tpl = _load_template(kind)
        except PromptError as e:
            errs.append(str(e))
            continue
        # warn on unknown {{var}} not in declared variables
        declared = set(str(v) for v in (tpl.get("variables") or []))
        used: set[str] = set()
        for k in ("system", "user"):
            for m in _VAR_RE.finditer(str(tpl.get(k, ""))):
                used.add(m.group(1))
        undeclared = used - declared
        if undeclared:
            errs.append(
                f"prompt {kind}: uses undeclared variables {sorted(undeclared)}"
            )
    return errs
