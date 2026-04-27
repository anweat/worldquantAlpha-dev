"""Model router — resolves model/depth/batch settings per agent type."""
from __future__ import annotations

from wq_bus.utils.logging import get_logger
from wq_bus.utils.yaml_loader import load_yaml

_log = get_logger(__name__)

_HARDCODED_DEFAULTS: dict = {
    "provider": "copilot",
    "model": "claude-sonnet-4.6",
    "depth": "medium",
    "batch_size": 1,
    "flush_secs": 5.0,
}


class ModelRouter:
    """Resolves dispatch configuration for a given agent type.

    Reads from ``config/agent_profiles.yaml``.  Constructor arguments
    (``override_*``) act as global overrides — useful for CLI ``--model``/
    ``--depth`` flags.  ``override_batch_size`` and ``override_flush_secs``
    are provided for testing and advanced scheduling scenarios.
    """

    def __init__(
        self,
        override_model: str | None = None,
        override_depth: str | None = None,
        override_batch_size: int | None = None,
        override_flush_secs: float | None = None,
    ) -> None:
        self._override_model = override_model
        self._override_depth = override_depth
        self._override_batch_size = override_batch_size
        self._override_flush_secs = override_flush_secs

    def _profiles(self) -> dict:
        return load_yaml("agent_profiles")

    def resolve(self, agent_type: str) -> dict:
        """Return dispatch config dict for *agent_type*.

        Keys returned: ``model``, ``depth``, ``batch_size``, ``flush_secs``,
        ``provider``.  Falls back: agent entry → ``defaults`` section →
        hardcoded defaults.
        """
        cfg = self._profiles()
        agent = cfg.get("agents", {}).get(agent_type, {})
        defaults = cfg.get("defaults", {})

        def _get(key: str):
            return agent.get(key) or defaults.get(key) or _HARDCODED_DEFAULTS.get(key)

        model = self._override_model or _get("model")
        depth = self._override_depth or _get("depth")
        batch_size = self._override_batch_size or _get("batch_size")
        flush_secs = self._override_flush_secs or _get("flush_secs")
        provider = _get("provider")

        return {
            "model": str(model),
            "depth": str(depth),
            "batch_size": int(batch_size),
            "flush_secs": float(flush_secs),
            "provider": str(provider),
        }
