"""Centralised logging setup.

Conventions:
- Global file handler always writes to ``logs/wqbus.log`` (cross-tag stream).
- A per-tag file handler is attached lazily the first time ``with_tag(TAG)``
  is set on a thread/coroutine; this writes to ``logs/<TAG>/wqbus.log``.
  Both handlers receive the same record, so existing tooling that tails
  ``logs/wqbus.log`` keeps working.
- Records carry an extra ``dataset_tag`` field (defaults to ``"_global"``)
  for downstream filters / structured-log shipping.
"""
from __future__ import annotations

import logging
import sys
from collections import OrderedDict
from pathlib import Path

from wq_bus.utils.paths import PROJECT_ROOT  # noqa: E402
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

_FMT = "%(asctime)s [%(levelname)s] %(name)s [%(dataset_tag)s]: %(message)s"
_configured = False
_tag_handlers: "OrderedDict[str, logging.Handler]" = None  # type: ignore[assignment]
_TAG_HANDLER_CAP = 32  # bound to keep long-running daemons from leaking FDs


class _TagInjector(logging.Filter):
    """Inject the active dataset_tag onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "dataset_tag") or not record.dataset_tag:
            try:
                from wq_bus.utils.tag_context import get_tag
                record.dataset_tag = get_tag() or "_global"
            except Exception:
                record.dataset_tag = "_global"
        return True


class _PerTagFileRouter(logging.Handler):
    """Forward each record to ``logs/<TAG>/wqbus.log`` (created on demand)."""

    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)

    def emit(self, record: logging.LogRecord) -> None:
        tag = getattr(record, "dataset_tag", None) or "_global"
        if tag == "_global":
            return  # global already covered by the root file handler
        global _tag_handlers
        if _tag_handlers is None:
            _tag_handlers = OrderedDict()
        h = _tag_handlers.get(tag)
        if h is None:
            tag_dir = LOG_DIR / tag
            try:
                tag_dir.mkdir(parents=True, exist_ok=True)
                h = logging.FileHandler(tag_dir / "wqbus.log", encoding="utf-8")
                h.setFormatter(logging.Formatter(_FMT))
                _tag_handlers[tag] = h
                # Bound the handler dict — close oldest if over cap.
                while len(_tag_handlers) > _TAG_HANDLER_CAP:
                    _, old = _tag_handlers.popitem(last=False)
                    try:
                        old.close()
                    except Exception:
                        pass
            except Exception:
                return
        else:
            # Mark recently used (LRU-ish behaviour).
            _tag_handlers.move_to_end(tag)
        try:
            h.emit(record)
        except Exception:
            self.handleError(record)


def setup(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    fmt = logging.Formatter(_FMT)
    tag_filter = _TagInjector()

    handler_console = logging.StreamHandler(sys.stderr)
    handler_console.setFormatter(fmt)
    handler_console.addFilter(tag_filter)

    handler_file = logging.FileHandler(LOG_DIR / "wqbus.log", encoding="utf-8")
    handler_file.setFormatter(fmt)
    handler_file.addFilter(tag_filter)

    handler_per_tag = _PerTagFileRouter()
    handler_per_tag.setFormatter(fmt)
    handler_per_tag.addFilter(tag_filter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler_console)
    root.addHandler(handler_file)
    root.addHandler(handler_per_tag)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(name)
