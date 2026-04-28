"""StrengthRouter — centralized AI strength (model tier) resolution.

Per AI_DISPATCHER.md §3:
- Reads strength_routing from config/agent_profiles.yaml.
- resolve(agent, mode) -> strength string following override → exact → wildcard → default.
- set_override(agent, mode, strength, ttl_min) for runtime overrides.
- CLI: wqbus ai strength list/set/clear.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)

StrengthLevel = str  # "high" | "medium" | "low" | "n/a"

VALID_STRENGTHS = {"high", "medium", "low", "n/a"}


from wq_bus.utils.timeutil import utcnow_iso as _utcnow_iso  # noqa: E402


class StrengthRouter:
    """Resolves AI strength (model tier) per (agent, mode) pair.

    Resolution order (AI_DISPATCHER.md §3.1):
    1. In-process override (set_override, with optional TTL)
    2. Exact (agent, mode) from strength_routing config
    3. Agent-level wildcard "*"
    4. Global "default"
    """

    def __init__(self) -> None:
        # overrides[(agent, mode)] = {"strength": str, "expires_at": float|None}
        self._overrides: dict[tuple[str, str | None], dict] = {}
        self._cfg: dict = {}
        self._loaded_at: float = 0.0

    def _routing(self) -> dict:
        """Load strength_routing from agent_profiles.yaml (cached 60s)."""
        now = time.monotonic()
        if now - self._loaded_at > 60:
            try:
                from wq_bus.utils.yaml_loader import load_yaml
                profiles = load_yaml("agent_profiles") or {}
                self._cfg = profiles.get("strength_routing") or {}
            except Exception:
                _log.warning("Could not load strength_routing from agent_profiles.yaml")
                self._cfg = {}
            self._loaded_at = now
        return self._cfg

    def resolve(self, agent: str, mode: str | None = None) -> StrengthLevel:
        """Return the resolved strength for *(agent, mode)*.

        Args:
            agent: Agent name (e.g. "alpha_gen").
            mode:  Mode string (e.g. "explore"). None means any mode.

        Returns:
            Strength string: "high" | "medium" | "low" | "n/a".
        """
        # 1. In-process override
        key = (agent, mode)
        # Only fall back to the wildcard (agent, None) entry when there is no
        # mode-specific override; this keeps each entry's TTL independent so
        # an expired (agent, mode) doesn't accidentally drop a still-valid
        # (agent, None) wildcard (or vice versa).
        ov_specific = self._overrides.get(key)
        ov_wildcard = self._overrides.get((agent, None)) if ov_specific is None else None
        override = ov_specific or ov_wildcard
        if override:
            expires = override.get("expires_at")
            if expires is None or expires > time.time():
                _log.debug("strength override: agent=%s mode=%s -> %s", agent, mode, override["strength"])
                return override["strength"]
            else:
                # Expired — remove ONLY the specific entry that was returned.
                if override is ov_specific:
                    self._overrides.pop(key, None)
                else:
                    self._overrides.pop((agent, None), None)

        cfg = self._routing()

        # 2. Exact (agent, mode)
        if mode and agent in cfg and isinstance(cfg[agent], dict):
            exact = cfg[agent].get(mode)
            if exact:
                return str(exact)

        # 3. Agent wildcard "*"
        if agent in cfg and isinstance(cfg[agent], dict):
            wildcard = cfg[agent].get("*")
            if wildcard:
                return str(wildcard)

        # 4. Global default
        return str(cfg.get("default", "medium"))

    def set_override(
        self,
        agent: str,
        mode: str | None,
        strength: str,
        *,
        ttl_min: float | None = None,
        note: str = "",
    ) -> None:
        """Set a runtime override for (agent, mode).

        Args:
            agent: Agent name.
            mode:  Mode string or None (applies to all modes for agent).
            strength: Target strength ("high" | "medium" | "low").
            ttl_min: Optional TTL in minutes; None means permanent until cleared.
            note:  Audit note (written to manual_calls table).
        """
        if strength not in VALID_STRENGTHS:
            raise ValueError(f"Invalid strength {strength!r}; must be one of {VALID_STRENGTHS}")
        expires_at = (time.time() + ttl_min * 60) if ttl_min else None
        self._overrides[(agent, mode)] = {
            "strength": strength,
            "expires_at": expires_at,
            "set_at": _utcnow_iso(),
            "ttl_min": ttl_min,
            "note": note,
        }
        _log.info(
            "strength override set: agent=%s mode=%s strength=%s ttl_min=%s",
            agent, mode, strength, ttl_min,
        )
        # Audit in manual_calls
        self._audit_override(agent, mode, strength, note)

        # Emit bus event
        self._emit_override_event(agent, mode, strength, ttl_min)

    def clear_override(self, agent: str, mode: str | None) -> bool:
        """Clear a previously set override. Returns True if something was removed."""
        removed = self._overrides.pop((agent, mode), None)
        if removed:
            _log.info("strength override cleared: agent=%s mode=%s", agent, mode)
        return removed is not None

    def list_overrides(self) -> list[dict]:
        """Return all active overrides (excluding expired)."""
        now = time.time()
        result = []
        for (agent, mode), ov in list(self._overrides.items()):
            exp = ov.get("expires_at")
            if exp and exp <= now:
                continue  # expired
            result.append({
                "agent": agent,
                "mode": mode,
                "strength": ov["strength"],
                "set_at": ov.get("set_at"),
                "ttl_min": ov.get("ttl_min"),
                "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                              if exp else None,
                "note": ov.get("note", ""),
            })
        return result

    def _audit_override(self, agent: str, mode: str | None, strength: str, note: str) -> None:
        try:
            import uuid
            from wq_bus.data._sqlite import open_state
            from wq_bus.utils.tag_context import get_tag
            tag = get_tag() or "_global"
            call_id = f"ov_{uuid.uuid4().hex[:12]}"
            with open_state() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO manual_calls
                       (call_id, agent_type, mode, strength, source,
                        prompt, dataset_tag, created_at, note, success)
                       VALUES (?,?,?,?,'manual_cli',?,?,?,?,1)""",
                    (call_id, agent, mode, strength,
                     f"strength_override agent={agent} mode={mode} -> {strength}",
                     tag, _utcnow_iso(), note),
                )
        except Exception:
            _log.debug("Failed to audit strength override (table may not exist yet)")

    def _emit_override_event(
        self, agent: str, mode: str | None, strength: str, ttl_min: float | None
    ) -> None:
        try:
            from wq_bus.bus.event_bus import get_bus
            from wq_bus.bus.events import STRENGTH_OVERRIDE_SET, make_event
            from wq_bus.utils.tag_context import get_tag
            tag = get_tag() or "_global"
            get_bus().emit(make_event(
                STRENGTH_OVERRIDE_SET, tag,
                agent=agent, mode=mode, strength=strength, ttl_min=ttl_min,
            ))
        except Exception:
            _log.debug("Failed to emit STRENGTH_OVERRIDE_SET event")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_router: Optional[StrengthRouter] = None


def get_router() -> StrengthRouter:
    global _router
    if _router is None:
        _router = StrengthRouter()
    return _router
