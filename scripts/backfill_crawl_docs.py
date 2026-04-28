"""Backfill historical crawl JSONs into knowledge.db.crawl_docs.

Reads archive/2026-04-26_pre_bus/data_and_memory/crawl_manual/*.json and inserts
them as crawl_docs rows for the active dataset tag, so the doc_summarizer and
alpha_gen agents have base BRAIN documentation to reference.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wq_bus.data import knowledge_db  # noqa: E402
from wq_bus.utils.tag_context import with_tag  # noqa: E402

CRAWL_DIR = ROOT / "archive" / "2026-04-26_pre_bus" / "data_and_memory" / "crawl_manual"
TAG = "usa_top3000"


def _md(doc: dict) -> str:
    parts = [f"# {doc.get('title','')}"]
    txt = doc.get("raw_text", "")
    if txt:
        parts.append(txt)
    if doc.get("operator_definitions"):
        parts.append("\n## Operators\n")
        for k, v in doc["operator_definitions"].items():
            parts.append(f"- **{k}**: {v}")
    if doc.get("alpha_expressions_found"):
        parts.append("\n## Sample Expressions\n")
        for e in doc["alpha_expressions_found"]:
            parts.append(f"- `{e}`")
    if doc.get("best_practices"):
        parts.append("\n## Best Practices\n")
        for b in doc["best_practices"]:
            parts.append(f"- {b}")
    return "\n".join(parts)


def main() -> int:
    files = sorted(CRAWL_DIR.glob("*.json"))
    print(f"Found {len(files)} crawl JSONs")
    n_loaded = 0
    with with_tag(TAG):
        for f in files:
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  skip {f.name}: {e}")
                continue
            url = doc.get("url") or f"file://{f.name}"
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
            body = _md(doc)
            if len(body) < 80:
                continue
            knowledge_db.save_crawl_doc(
                url_hash=url_hash,
                source="brain_manual",
                url=url,
                title=doc.get("title", f.stem),
                body_md=body,
                meta={"file": f.name, "crawled_at": doc.get("crawled_at")},
            )
            n_loaded += 1
    print(f"Loaded {n_loaded} docs into knowledge.db crawl_docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
