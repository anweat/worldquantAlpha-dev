"""Build docs/manifest.generated.yaml.

Merges the handwritten ``docs/manifest.yaml`` with an auto-scan of ``docs/``
and ``memory/<tag>/`` for known doc/memory file types. For each entry it fills
``size`` (bytes), ``mtime`` (ISO date) and ``summary`` (first non-empty line of
content, trimmed). Entries discovered by scan but absent from the handwritten
file get auto-tags inferred from the path and ``priority=4``.

Idempotent: rerun any time. Outputs YAML sorted by (priority, path) for stable
diffs. Use via ``python scripts/manifest_builder.py`` or ``wqbus manifest build``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HANDWRITTEN = PROJECT_ROOT / "docs" / "manifest.yaml"
GENERATED = PROJECT_ROOT / "docs" / "manifest.generated.yaml"

# Where we scan
SCAN_ROOTS = [
    ("docs",   {".md"}),
    ("memory", {".md", ".json"}),
]

# Skip these subtrees
SKIP_DIR_PARTS = {"_legacy", "archive", "summaries", "_index", "_global"}


def _first_nonempty_line(p: Path, max_chars: int = 160) -> str:
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                # Strip markdown heading marks and trailing punctuation noise
                line = line.lstrip("#").strip()
                if line:
                    return line[:max_chars]
    except Exception:
        return ""
    return ""


def _summary_for(path: Path) -> str:
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return ""
        if isinstance(data, dict):
            for k in ("description", "summary", "title"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()[:160]
            keys = ",".join(list(data.keys())[:6])
            return f"json keys: {keys}"
        if isinstance(data, list):
            return f"json array (len={len(data)})"
        return ""
    return _first_nonempty_line(path)


def _infer_tags(rel_path: str) -> list[str]:
    parts = rel_path.replace("\\", "/").lower().split("/")
    tags: list[str] = []
    if "memory" in parts:
        tags.append("runtime")
    if "docs" in parts:
        tags.append("reference")
    if "architecture" in parts:
        tags.append("architecture")
    name = parts[-1]
    for kw in ("failure", "portfolio", "insight", "expression", "recap",
               "iteration", "operator", "metric", "field", "recipe"):
        if kw in name:
            tags.append(kw)
    return sorted(set(tags)) or ["misc"]


def _scan_files() -> dict[str, dict[str, Any]]:
    """Return {rel_path_template: file_meta}.

    For per-tag memory files we collapse all ``memory/<tag>/foo.md`` into one
    template ``memory/{tag}/foo.md`` and pick the freshest tag's metadata as
    representative.
    """
    found: dict[str, dict[str, Any]] = {}
    for root_name, exts in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix not in exts:
                continue
            if any(part in SKIP_DIR_PARTS for part in p.parts):
                continue
            rel = p.relative_to(PROJECT_ROOT).as_posix()
            template = rel
            scope = "global"
            # Collapse per-tag memory paths into {tag} templates
            parts = rel.split("/")
            if parts[0] == "memory" and len(parts) >= 3 and parts[1] != "iteration_notes.md":
                template = f"memory/{{tag}}/{'/'.join(parts[2:])}"
                scope = "per_tag"
            try:
                st = p.stat()
            except OSError:
                continue
            mtime = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc).strftime("%Y-%m-%d")
            existing = found.get(template)
            if existing and existing["_mtime_raw"] >= st.st_mtime:
                continue
            found[template] = {
                "path": template,
                "_actual_path": rel,
                "_mtime_raw": st.st_mtime,
                "size": st.st_size,
                "mtime": mtime,
                "summary": _summary_for(p),
                "scope": scope,
            }
    return found


def _load_handwritten() -> list[dict[str, Any]]:
    if not HANDWRITTEN.exists():
        return []
    raw = yaml.safe_load(HANDWRITTEN.read_text(encoding="utf-8")) or {}
    return list(raw.get("entries") or [])


def build(write: bool = True) -> dict[str, Any]:
    handwritten = {str(e.get("path")): dict(e) for e in _load_handwritten()
                   if isinstance(e, dict) and e.get("path")}
    scanned = _scan_files()

    merged: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    # 1) Enrich handwritten with size/mtime/summary from a representative actual file
    for path, entry in handwritten.items():
        meta = scanned.get(path)
        if meta:
            entry.setdefault("size", meta["size"])
            entry.setdefault("mtime", meta["mtime"])
            if not entry.get("summary"):
                entry["summary"] = meta["summary"]
        # else: per-tag entry whose underlying file isn't materialised yet — keep as-is
        merged.append(entry)
        seen_paths.add(path)

    # 2) Auto-add scanned files not in handwritten (priority=4)
    for path, meta in scanned.items():
        if path in seen_paths:
            continue
        merged.append({
            "path": path,
            "title": Path(meta["_actual_path"]).stem.replace("_", " "),
            "applies_to_modes": ["*"],
            "tags": _infer_tags(meta["_actual_path"]),
            "scope": meta["scope"],
            "priority": 4,
            "size": meta["size"],
            "mtime": meta["mtime"],
            "summary": meta["summary"],
        })

    merged.sort(key=lambda e: (int(e.get("priority", 5)), str(e.get("path", ""))))

    out = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "scripts/manifest_builder.py",
        "entries": merged,
    }
    if write:
        GENERATED.write_text(
            yaml.safe_dump(out, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build docs/manifest.generated.yaml")
    ap.add_argument("--dry-run", action="store_true", help="Print summary, do not write file")
    args = ap.parse_args()
    out = build(write=not args.dry_run)
    n = len(out["entries"])
    where = "(dry-run)" if args.dry_run else f"→ {GENERATED.relative_to(PROJECT_ROOT)}"
    print(f"manifest_builder: {n} entries {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
