"""Async batch buffer — collects payloads per agent_type and flushes in batches."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)


class BatchBuffer:
    """Buffers async payloads per ``agent_type``; flushes when full or after a timeout.

    Args:
        flusher: Async callable ``(agent_type, payloads) -> list[result]``.
            Called with all buffered payloads for a single flush event.
        config_resolver: Callable ``(agent_type) -> dict`` returning at minimum
            ``batch_size`` (int) and ``flush_secs`` (float).
    """

    def __init__(
        self,
        flusher: Callable[[str, list[dict]], Awaitable[list[Any]]],
        config_resolver: Callable[[str], dict],
    ) -> None:
        self._flusher = flusher
        self._config_resolver = config_resolver
        # Per-agent queue: list of (payload, Future)
        self._queues: dict[str, list[tuple[dict, asyncio.Future]]] = {}
        # Per-agent flush timer tasks
        self._timers: dict[str, asyncio.Task] = {}
        # Per-agent locks (created lazily inside async context)
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, agent_type: str) -> asyncio.Lock:
        """Return (creating if needed) the asyncio.Lock for *agent_type*."""
        if agent_type not in self._locks:
            self._locks[agent_type] = asyncio.Lock()
        return self._locks[agent_type]

    async def submit(self, agent_type: str, payload: dict) -> Any:
        """Submit one payload; suspend until its batch has been flushed.

        Returns the single result dict from the flusher that corresponds
        to this payload.
        """
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        lock = self._get_lock(agent_type)
        to_flush: list | None = None

        async with lock:
            self._queues.setdefault(agent_type, [])
            self._queues[agent_type].append((payload, future))

            cfg = self._config_resolver(agent_type)
            batch_size = int(cfg.get("batch_size", 4))
            flush_secs = float(cfg.get("flush_secs", 20))

            if len(self._queues[agent_type]) >= batch_size:
                # Batch is full — pop immediately
                to_flush = self._queues.pop(agent_type)
                if agent_type in self._timers:
                    self._timers.pop(agent_type).cancel()
            else:
                # Reset timer
                if agent_type in self._timers:
                    self._timers.pop(agent_type).cancel()
                self._timers[agent_type] = asyncio.create_task(
                    self._timer_flush(agent_type, flush_secs)
                )

        if to_flush is not None:
            await self._do_flush(agent_type, to_flush)

        return await future

    async def _timer_flush(self, agent_type: str, flush_secs: float) -> None:
        """Sleep *flush_secs* then flush whatever is still queued for *agent_type*."""
        await asyncio.sleep(flush_secs)
        lock = self._get_lock(agent_type)
        to_flush = None
        async with lock:
            to_flush = self._queues.pop(agent_type, [])
            self._timers.pop(agent_type, None)
        if to_flush:
            await self._do_flush(agent_type, to_flush)

    async def _do_flush(
        self, agent_type: str, entries: list[tuple[dict, asyncio.Future]]
    ) -> None:
        """Invoke flusher with all payloads; resolve each caller's future."""
        payloads = [e[0] for e in entries]
        futures = [e[1] for e in entries]
        _log.debug("Flushing %d payload(s) for agent_type=%s", len(payloads), agent_type)
        try:
            results = await self._flusher(agent_type, payloads)
            for fut, res in zip(futures, results):
                if not fut.done():
                    fut.set_result(res)
        except Exception as exc:
            _log.error("Flush failed for agent_type=%s: %s", agent_type, exc)
            for fut in futures:
                if not fut.done():
                    fut.set_exception(exc)
