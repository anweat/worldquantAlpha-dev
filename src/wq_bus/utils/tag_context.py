"""Dataset tag + trace_id context — propagates across async calls.

Two contextvars:
- `_current_tag`: the active dataset_tag (one per logical run / event chain).
- `_current_trace`: a UUID identifying one logical request flowing through the bus,
  inherited by every child event/AI call/alpha/submission.

Both are async-safe (per-task) via :class:`contextvars.ContextVar`.
"""
from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar
from typing import Iterator, Optional

_current_tag: ContextVar[Optional[str]] = ContextVar("wqbus_dataset_tag", default=None)
_current_trace: ContextVar[Optional[str]] = ContextVar("wqbus_trace_id", default=None)


def get_tag() -> Optional[str]:
    return _current_tag.get()


def require_tag() -> str:
    tag = _current_tag.get()
    if not tag:
        raise RuntimeError(
            "No dataset_tag set in current context. "
            "Wrap your call with `with with_tag('usa_top3000'):`"
        )
    return tag


@contextlib.contextmanager
def with_tag(tag: str) -> Iterator[str]:
    token = _current_tag.set(tag)
    try:
        yield tag
    finally:
        _current_tag.reset(token)


# ---------- trace_id ----------

def get_trace_id() -> Optional[str]:
    return _current_trace.get()


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


@contextlib.contextmanager
def with_trace(trace_id: Optional[str] = None) -> Iterator[str]:
    """Set the active trace_id for the duration of the block.

    If *trace_id* is None, generate a fresh one. Re-entrant: nested with_trace
    calls just stack and reset on exit.
    """
    tid = trace_id or new_trace_id()
    token = _current_trace.set(tid)
    try:
        yield tid
    finally:
        _current_trace.reset(token)
