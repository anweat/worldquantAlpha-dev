"""wq-bus crawler subsystem.

Public API:
  register(bus)  — wires CrawlerAgent into the event bus (call from cli.py)
"""
from wq_bus.crawler.crawler_agent import register

__all__ = ["register"]
