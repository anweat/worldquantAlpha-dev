"""Transform registry for chain_hook (AI_DISPATCHER.md §11).

Each transform module under this package must expose:

    def transform(prev_output: dict, ctx: dict) -> str:
        '''Return a text snippet to inject into the next task's prompt.'''
        ...

The optional module attribute ``NAME`` overrides the registry key (defaults
to the module's basename).
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Callable

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)

TransformFn = Callable[[dict, dict], str]
_REGISTRY: dict[str, TransformFn] = {}
_DISCOVERED = False


def register(name: str, fn: TransformFn) -> None:
    if not callable(fn):
        raise TypeError(f"transform {name!r} must be callable")
    _REGISTRY[name] = fn


def discover(force: bool = False) -> dict[str, TransformFn]:
    """Scan this package for transform functions and register them."""
    global _DISCOVERED
    if _DISCOVERED and not force:
        return dict(_REGISTRY)

    pkg_path = __path__  # type: ignore[name-defined]
    for mod_info in pkgutil.iter_modules(pkg_path):
        if mod_info.name.startswith("_"):
            continue
        full = f"{__name__}.{mod_info.name}"
        try:
            mod = importlib.import_module(full)
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("transforms.discover: failed to import %s: %s", full, exc)
            continue
        fn = getattr(mod, "transform", None)
        if not callable(fn):
            continue
        name = getattr(mod, "NAME", mod_info.name)
        _REGISTRY[name] = fn  # type: ignore[assignment]
        _log.debug("transforms.discover: registered %s", name)

    _DISCOVERED = True
    return dict(_REGISTRY)


def get(name: str) -> TransformFn | None:
    if not _DISCOVERED:
        discover()
    return _REGISTRY.get(name)


def apply(name: str, prev_output: dict, ctx: dict | None = None) -> str:
    """Run a transform; empty string on missing/error (soft failure)."""
    fn = get(name)
    if fn is None:
        _log.warning("transforms.apply: unknown transform %r", name)
        return ""
    try:
        out = fn(prev_output or {}, ctx or {})
        return out if isinstance(out, str) else str(out)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("transforms.apply: %r raised: %s", name, exc)
        return ""


def list_names() -> list[str]:
    if not _DISCOVERED:
        discover()
    return sorted(_REGISTRY)


__all__ = ["register", "discover", "get", "apply", "list_names", "TransformFn"]
