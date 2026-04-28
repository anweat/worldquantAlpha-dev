"""Composition recipe matching — regex + AST stub.

Per COMPOSITION_RECIPES.md:
- Loads config/composition_recipes_seed.yaml at startup (ensure_seeds()).
- match(expression) -> list of theme tags.
- hint_for_theme(theme, dataset_tag) -> list of Hint dicts.
- AST fallback is stubbed (TODO phase 2).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from wq_bus.utils.logging import get_logger

_log = get_logger(__name__)


from wq_bus.utils.timeutil import utcnow_iso as _utcnow_iso  # noqa: E402


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Recipe:
    recipe_id: str
    semantic_name: str
    pattern_regex: Optional[str]
    pattern_ast_json: Optional[str]
    theme_tags: str            # CSV
    field_slots_json: Optional[str]
    example_expressions: Optional[str]
    origin: str
    enabled: int
    compiled: Optional[re.Pattern] = field(default=None, repr=False)

    @property
    def themes(self) -> list[str]:
        return [t.strip() for t in self.theme_tags.split(",") if t.strip()]


@dataclass
class Hint:
    recipe: Recipe
    candidate_fields: list[str]


# ---------------------------------------------------------------------------
# In-memory cache of compiled recipes
# ---------------------------------------------------------------------------

_compiled_recipes: list[Recipe] = []
_seeds_loaded: bool = False


def _load_from_db() -> list[Recipe]:
    """Load enabled, APPROVED recipes from knowledge.db composition_recipes table.

    Only status='approved' recipes influence alpha_gen.
    proposed/rejected recipes MUST NOT be returned here.
    """
    try:
        from wq_bus.data._sqlite import open_knowledge
        with open_knowledge() as conn:
            rows = conn.execute(
                """SELECT * FROM composition_recipes
                   WHERE enabled=1
                     AND (status IS NULL OR status='approved')
                   ORDER BY recipe_id"""
            ).fetchall()
            recipes = []
            for row in rows:
                r = dict(row)
                rx = r.get("pattern_regex")
                compiled = None
                if rx:
                    try:
                        compiled = re.compile(rx, re.IGNORECASE)
                    except re.error as e:
                        _log.warning("Invalid regex for recipe %s: %s", r["recipe_id"], e)
                recipes.append(Recipe(
                    recipe_id=r["recipe_id"],
                    semantic_name=r.get("semantic_name", ""),
                    pattern_regex=rx,
                    pattern_ast_json=r.get("pattern_ast_json"),
                    theme_tags=r.get("theme_tags", ""),
                    field_slots_json=r.get("field_slots_json"),
                    example_expressions=r.get("example_expressions"),
                    origin=r.get("origin", "builtin"),
                    enabled=1,
                    compiled=compiled,
                ))
            return recipes
    except Exception:
        _log.exception("Failed to load recipes from DB")
        return []


def _ensure_compiled() -> list[Recipe]:
    global _compiled_recipes, _seeds_loaded
    if not _seeds_loaded:
        ensure_seeds()
    if not _compiled_recipes:
        _compiled_recipes = _load_from_db()
    return _compiled_recipes


def _reload() -> None:
    """Force reload of recipe cache from DB."""
    global _compiled_recipes
    _compiled_recipes = _load_from_db()


# ---------------------------------------------------------------------------
# Seed loader
# ---------------------------------------------------------------------------

def ensure_seeds() -> None:
    """Load builtin recipes from config/composition_recipes_seed.yaml into DB.

    Idempotent: uses INSERT OR IGNORE so existing rows are not overwritten.
    """
    global _seeds_loaded
    _seeds_loaded = True  # prevent recursive calls
    try:
        from wq_bus.utils.yaml_loader import load_yaml
        seeds = load_yaml("composition_recipes_seed") or []
        if not seeds:
            return
        from wq_bus.data._sqlite import open_knowledge
        ts = _utcnow_iso()
        with open_knowledge() as conn:
            for s in seeds:
                rid = s.get("recipe_id")
                if not rid:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO composition_recipes
                       (recipe_id, semantic_name, pattern_regex, pattern_ast_json,
                        theme_tags, field_slots_json, example_expressions, origin,
                        enabled, created_at, updated_at, notes)
                       VALUES (?,?,?,?,?,?,?,?,1,?,?,?)""",
                    (
                        rid,
                        s.get("semantic_name", ""),
                        s.get("pattern_regex"),
                        s.get("pattern_ast_json"),
                        s.get("theme_tags", ""),
                        json.dumps(s.get("field_slots", [])) if s.get("field_slots") else None,
                        json.dumps(s.get("example_expressions", [])),
                        s.get("origin", "builtin"),
                        ts, ts,
                        s.get("notes"),
                    ),
                )
        _log.info("Loaded %d seed recipes", len(seeds))
    except FileNotFoundError:
        _log.debug("composition_recipes_seed.yaml not found; no seeds loaded")
    except Exception:
        _log.exception("Failed to load recipe seeds")


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

def match(expression: str) -> list[str]:
    """Return a list of theme tags matched by *expression* (union of all hits).

    Uses regex matchers (phase 1). AST fallback is stubbed (TODO phase 2).
    Returns empty list if nothing matches; logs a WARN.
    """
    recipes = _ensure_compiled()
    all_themes: list[str] = []
    for recipe in recipes:
        if recipe.compiled and recipe.compiled.search(expression):
            all_themes.extend(recipe.themes)

    # TODO phase 2: AST fallback for recipes with pattern_ast_json but no regex
    if not all_themes:
        _log.debug("No recipe matched expression (len=%d)", len(expression))

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in all_themes:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def themes_csv(expression: str) -> str | None:
    """Convenience: return CSV string or None if no themes matched."""
    themes = match(expression)
    return ",".join(themes) if themes else None


# ---------------------------------------------------------------------------
# Reverse lookup: hint_for_theme
# ---------------------------------------------------------------------------

def hint_for_theme(theme: str, dataset_tag: str | None = None, k: int = 3) -> list[Hint]:
    """Return up to k recipe hints for *theme* with resolved candidate fields.

    Args:
        theme: Theme tag string (e.g. "momentum.short").
        dataset_tag: Used to restrict candidate fields to available dataset fields.
        k: Max number of hints returned.

    Returns:
        List of Hint objects.
    """
    recipes = _ensure_compiled()
    matched = [
        r for r in recipes
        if r.enabled and theme in r.themes
    ]
    # Randomize order (poor man's diverse sampling)
    import random
    random.shuffle(matched)
    matched = matched[:k]

    return [Hint(recipe=r, candidate_fields=_resolve_slots(r, dataset_tag)) for r in matched]


def _resolve_slots(recipe: Recipe, dataset_tag: str | None) -> list[str]:
    """Return candidate field names for recipe slots.

    Slots in field_slots_json are class names like "<fundamental.absolute>".
    When ``dataset_tag`` is given we resolve each slot to the dataset's
    available fields of that class (via datasets.yaml + field_class_map).
    Without a tag we fall back to the bare slot class names.
    """
    try:
        slots = json.loads(recipe.field_slots_json or "[]")
    except Exception:
        slots = []
    if not slots:
        return []
    # Strip angle brackets and lowercase
    slot_classes = [s.replace("<", "").replace(">", "").lower() for s in slots]
    if not dataset_tag:
        return slot_classes
    try:
        from wq_bus.utils.yaml_loader import load_yaml
        ds_cfg = load_yaml("datasets") or {}
        fcm: dict[str, str] = {k.lower(): v for k, v in (ds_cfg.get("field_class_map") or {}).items()}
        ds_entry = next(
            (d for d in (ds_cfg.get("datasets") or [])
             if d.get("tag") == dataset_tag),
            None,
        )
        if not ds_entry or not fcm:
            return slot_classes
        avail = set((ds_entry.get("field_availability") or []))
        # Inverse map: class → fields available in this dataset
        candidates: list[str] = []
        for slot_cls in slot_classes:
            for field, cls in fcm.items():
                if cls != slot_cls:
                    continue
                # Only include if the field's category is in availability
                # (we accept either the class itself or a coarser tag)
                if not avail or cls in avail or any(cls.startswith(a) for a in avail):
                    candidates.append(field)
        # Fallback to slot class names if nothing resolved
        return candidates or slot_classes
    except Exception:
        _log.exception("recipes._resolve_slots: dataset filter failed; returning bare classes")
        return slot_classes


# ---------------------------------------------------------------------------
# CLI helpers (list_recipes, show_recipe, approve_recipe, reject_recipe, diff_recipe)
# ---------------------------------------------------------------------------

def list_recipes(theme: str | None = None, status: str | None = None) -> list[dict]:
    """Return recipes (optionally filtered by theme and/or status).

    When *status* is None returns only enabled+approved (production view).
    Pass status='all' to see every row regardless of status.
    """
    if status:
        # Direct DB query for non-default status views (including 'all')
        try:
            from wq_bus.data._sqlite import open_knowledge
            with open_knowledge() as conn:
                if status == "all":
                    rows = conn.execute(
                        "SELECT * FROM composition_recipes ORDER BY recipe_id"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM composition_recipes WHERE status=? ORDER BY recipe_id",
                        (status,),
                    ).fetchall()
            result = []
            for row in rows:
                r = dict(row)
                if theme and theme not in (r.get("theme_tags") or ""):
                    continue
                result.append({
                    "recipe_id":    r["recipe_id"],
                    "semantic_name": r.get("semantic_name", ""),
                    "theme_tags":   r.get("theme_tags", ""),
                    "origin":       r.get("origin", ""),
                    "status":       r.get("status", "approved"),
                    "proposed_by":  r.get("proposed_by"),
                    "has_regex":    bool(r.get("pattern_regex")),
                })
            return result
        except Exception:
            pass

    recipes = _ensure_compiled()
    result = []
    for r in recipes:
        if theme and theme not in r.themes:
            continue
        result.append({
            "recipe_id":    r.recipe_id,
            "semantic_name": r.semantic_name,
            "theme_tags":   r.theme_tags,
            "origin":       r.origin,
            "status":       "approved",
            "has_regex":    bool(r.pattern_regex),
            "has_ast":      bool(r.pattern_ast_json),
        })
    return result


def show_recipe(recipe_id: str) -> dict | None:
    """Return full recipe dict for *recipe_id*, or None if not found.

    Queries DB directly so proposed/rejected recipes are also visible.
    """
    try:
        from wq_bus.data._sqlite import open_knowledge
        with open_knowledge() as conn:
            row = conn.execute(
                "SELECT * FROM composition_recipes WHERE recipe_id=?",
                (recipe_id,),
            ).fetchone()
        if row:
            r = dict(row)
            return {
                "recipe_id":          r["recipe_id"],
                "semantic_name":      r.get("semantic_name", ""),
                "theme_tags":         r.get("theme_tags", ""),
                "pattern_regex":      r.get("pattern_regex"),
                "pattern_ast_json":   r.get("pattern_ast_json"),
                "field_slots":        json.loads(r.get("field_slots_json") or "[]"),
                "example_expressions": json.loads(r.get("example_expressions") or "[]"),
                "origin":             r.get("origin", ""),
                "enabled":            r.get("enabled", 1),
                "status":             r.get("status", "approved"),
                "proposed_by":        r.get("proposed_by"),
                "proposed_at":        r.get("proposed_at"),
                "reviewed_by":        r.get("reviewed_by"),
                "reviewed_at":        r.get("reviewed_at"),
                "review_notes":       r.get("review_notes"),
                "support_count":      r.get("support_count"),
                "sample_alpha_ids":   json.loads(r.get("sample_alpha_ids_json") or "[]"),
                "notes":              r.get("notes"),
            }
    except Exception:
        pass

    # Fallback: search in-memory approved cache
    recipes = _ensure_compiled()
    for r in recipes:
        if r.recipe_id == recipe_id:
            return {
                "recipe_id":          r.recipe_id,
                "semantic_name":      r.semantic_name,
                "theme_tags":         r.theme_tags,
                "pattern_regex":      r.pattern_regex,
                "pattern_ast_json":   r.pattern_ast_json,
                "field_slots":        json.loads(r.field_slots_json or "[]"),
                "example_expressions": json.loads(r.example_expressions or "[]"),
                "origin":             r.origin,
                "enabled":            r.enabled,
                "status":             "approved",
            }
    return None


def approve_recipe(
    recipe_id: str,
    *,
    reviewed_by: str = "cli",
    notes: str = "",
) -> bool:
    """Set a recipe's status to 'approved'.  Returns True if row was found."""
    ts = _utcnow_iso()
    try:
        from wq_bus.data._sqlite import open_knowledge
        with open_knowledge() as conn:
            cur = conn.execute(
                """UPDATE composition_recipes
                   SET status='approved', reviewed_by=?, reviewed_at=?, review_notes=?
                   WHERE recipe_id=?""",
                (reviewed_by, ts, notes or None, recipe_id),
            )
        if cur.rowcount:
            _reload()  # refresh in-memory cache
            return True
    except Exception:
        pass
    return False


def reject_recipe(
    recipe_id: str,
    *,
    reason: str,
    reviewed_by: str = "cli",
) -> bool:
    """Set a recipe's status to 'rejected'.  Returns True if row was found."""
    ts = _utcnow_iso()
    try:
        from wq_bus.data._sqlite import open_knowledge
        with open_knowledge() as conn:
            cur = conn.execute(
                """UPDATE composition_recipes
                   SET status='rejected', reviewed_by=?, reviewed_at=?, review_notes=?
                   WHERE recipe_id=?""",
                (reviewed_by, ts, reason, recipe_id),
            )
        if cur.rowcount:
            _reload()
            return True
    except Exception:
        pass
    return False


def diff_recipe(recipe_id: str, dataset_tag: str | None = None) -> dict:
    """Return how many existing alphas match the recipe's pattern_regex.

    Returns dict with keys: recipe_id, pattern_regex, n_matched, sample_alpha_ids.
    """
    r = show_recipe(recipe_id)
    if not r:
        return {"error": f"recipe {recipe_id!r} not found"}
    pattern_regex = r.get("pattern_regex")
    if not pattern_regex:
        return {"recipe_id": recipe_id, "pattern_regex": None, "n_matched": 0,
                "sample_alpha_ids": []}
    try:
        compiled = re.compile(pattern_regex, re.IGNORECASE)
    except re.error as e:
        return {"recipe_id": recipe_id, "error": f"invalid regex: {e}"}

    try:
        from wq_bus.data._sqlite import open_knowledge
        tag_clause = "AND dataset_tag=?" if dataset_tag else ""
        params: list = [dataset_tag] if dataset_tag else []
        with open_knowledge() as conn:
            rows = conn.execute(
                f"SELECT alpha_id, expression FROM alphas WHERE 1=1 {tag_clause} LIMIT 5000",
                params,
            ).fetchall()
    except Exception as e:
        return {"recipe_id": recipe_id, "error": str(e)}

    matched_ids = []
    for row in rows:
        expr = row["expression"] or ""
        if compiled.search(expr):
            matched_ids.append(row["alpha_id"])

    return {
        "recipe_id":        recipe_id,
        "pattern_regex":    pattern_regex,
        "n_matched":        len(matched_ids),
        "sample_alpha_ids": matched_ids[:5],
    }
