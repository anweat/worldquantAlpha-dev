"""similarity_review.py — Review self-correlation pairs among local alphas.

Finds alpha pairs whose sc_value meets the threshold and lets you inspect or
auto-mark duplicates.

Usage:
    python scripts/similarity_review.py [--threshold 0.5] [--limit 50]
        [--auto-mark-duplicate] [--export-csv path.csv] [--dataset USA_TOP3000]

Flags:
    --threshold 0.5         SC threshold (default 0.5)
    --limit 50              Max pairs to show (default 50)
    --auto-mark-duplicate   For the LATER alpha in each pair, set
                            status='duplicate_blocked'.  Does NOT delete rows.
    --export-csv path.csv   Export full pair list to CSV.
    --dry-run               Show changes without writing.

Output: test_results/sc_review_<timestamp>.json (atomic write)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TS = time.strftime("%Y%m%d_%H%M%S", time.gmtime())

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pair discovery
# ---------------------------------------------------------------------------

def _find_pairs(tag: str, threshold: float, limit: int) -> list[dict]:
    """Return list of {alpha_id_a, alpha_id_b, sc_value, direction_id_a, direction_id_b,
    expression_a, expression_b, created_at_a, created_at_b} for sc_value >= threshold.

    Strategy:
    1. Try self-join on alphas.sc_value (alpha has sc_value stored from simulation).
    2. Each row's sc_value indicates its self-correlation with the broader pool.
       Since we don't store pairwise SC values per se, we find all alphas with
       sc_value >= threshold and treat every distinct expression-pair as a candidate.
    3. If a self_corr table exists we use that instead (more precise).
    """
    from wq_bus.data._sqlite import open_knowledge
    with open_knowledge() as conn:
        # Check for dedicated self_corr table
        has_sc_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='self_corr'"
        ).fetchone() is not None

        if has_sc_table:
            rows = conn.execute(
                """SELECT sc.alpha_id_a, sc.alpha_id_b, sc.sc_value,
                          a.direction_id AS direction_id_a, b.direction_id AS direction_id_b,
                          a.expression AS expression_a, b.expression AS expression_b,
                          a.created_at AS created_at_a, b.created_at AS created_at_b
                   FROM self_corr sc
                   JOIN alphas a ON sc.alpha_id_a = a.alpha_id AND a.dataset_tag = ?
                   JOIN alphas b ON sc.alpha_id_b = b.alpha_id AND b.dataset_tag = ?
                   WHERE sc.sc_value >= ? AND sc.dataset_tag = ?
                   ORDER BY sc.sc_value DESC
                   LIMIT ?""",
                (tag, tag, threshold, tag, limit),
            ).fetchall()
            return [dict(r) for r in rows]

        # Fallback: use high-SC alphas and do an expression-similarity heuristic
        # Any alpha with sc_value >= threshold is potentially conflicting with the pool.
        rows = conn.execute(
            """SELECT alpha_id, direction_id, expression, sc_value, created_at, status
               FROM alphas
               WHERE dataset_tag=? AND sc_value >= ?
                 AND status NOT IN ('legacy', 'duplicate_blocked')
               ORDER BY sc_value DESC
               LIMIT ?""",
            (tag, threshold, limit * 2),
        ).fetchall()
        candidates = [dict(r) for r in rows]

    # Build self-join pairs: pair each candidate with every other candidate
    pairs: list[dict] = []
    seen: set[tuple] = set()
    for i, a in enumerate(candidates):
        for j, b in enumerate(candidates):
            if i >= j:
                continue
            pair_key = tuple(sorted((a["alpha_id"], b["alpha_id"])))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            # Use max of the two sc_values as an approximation
            sc = max(float(a.get("sc_value") or 0), float(b.get("sc_value") or 0))
            if sc >= threshold:
                pairs.append({
                    "alpha_id_a": a["alpha_id"],
                    "alpha_id_b": b["alpha_id"],
                    "sc_value": round(sc, 4),
                    "direction_id_a": a.get("direction_id"),
                    "direction_id_b": b.get("direction_id"),
                    "expression_a": a.get("expression", ""),
                    "expression_b": b.get("expression", ""),
                    "created_at_a": a.get("created_at"),
                    "created_at_b": b.get("created_at"),
                })
            if len(pairs) >= limit:
                break
        if len(pairs) >= limit:
            break

    return pairs


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------

def _recommend(pair: dict) -> str:
    """Suggest a mutation strategy for a correlated pair."""
    expr_a = pair.get("expression_a", "")
    expr_b = pair.get("expression_b", "")
    dir_a = pair.get("direction_id_a") or ""
    dir_b = pair.get("direction_id_b") or ""

    # Same direction → fields are probably overlapping
    if dir_a and dir_b and dir_a == dir_b:
        return "same direction — consider varying neutralization or decay"

    # Identical operator patterns
    def _ops(expr: str) -> set[str]:
        import re
        return set(re.findall(r"\b[a-z_]+\s*\(", expr.lower()))

    ops_a = _ops(expr_a)
    ops_b = _ops(expr_b)
    if ops_a == ops_b and ops_a:
        return "operator chain identical — substitute ts_delta/ts_std_dev with ts_corr or group_rank"

    # Both use same fundamental field (simple substring check)
    common_fields = [
        f for f in ("assets", "liabilities", "sales", "operating_income",
                    "close", "volume", "sharesout")
        if f in expr_a.lower() and f in expr_b.lower()
    ]
    if common_fields:
        return f"field overlap: {', '.join(common_fields[:3])} — try orthogonal fields"

    return "expressions differ in minor transformations — try different universe/neutralization"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review self-correlation pairs among local alphas."
    )
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="SC threshold for pair inclusion (default 0.5).")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max pairs to display (default 50).")
    parser.add_argument("--auto-mark-duplicate", action="store_true",
                        help="Mark the LATER alpha in each pair as 'duplicate_blocked'.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show changes without writing to DB.")
    parser.add_argument("--export-csv", metavar="PATH",
                        help="Export pair list to CSV file.")
    parser.add_argument("--dataset", default="USA_TOP3000",
                        help="Dataset tag (default USA_TOP3000).")
    args = parser.parse_args()

    tag = args.dataset.upper()
    threshold = args.threshold
    limit = args.limit

    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()

    # Set tag context so DAOs work
    from wq_bus.utils.tag_context import with_tag
    with with_tag(tag):
        _run(args, tag, threshold, limit)


def _run(args, tag: str, threshold: float, limit: int) -> None:
    from wq_bus.data._sqlite import open_knowledge

    print(f"[sc_review] dataset={tag}  threshold={threshold}  limit={limit}")
    print(f"[sc_review] auto_mark={args.auto_mark_duplicate}  dry_run={args.dry_run}")
    print("-" * 72)

    pairs = _find_pairs(tag, threshold, limit)
    print(f"[sc_review] Found {len(pairs)} pair(s) with sc_value >= {threshold}")

    if not pairs:
        print("[sc_review] No SC pairs to review.")
        _save_report(args, tag, pairs, {}, [])
        return

    # ---- Group by direction ----
    direction_density: dict[str, int] = defaultdict(int)
    for p in pairs:
        for did in (p.get("direction_id_a"), p.get("direction_id_b")):
            if did:
                direction_density[did] += 1

    # ---- Print pairs ----
    marked: list[str] = []
    report_pairs: list[dict] = []

    print(f"\n{'pair':>4}  {'sc':>5}  {'dir_match':>9}  {'alpha_a':>20}  {'alpha_b':>20}")
    print("-" * 72)

    for i, pair in enumerate(pairs, 1):
        aid_a = pair["alpha_id_a"]
        aid_b = pair["alpha_id_b"]
        sc = pair["sc_value"]
        dir_match = (
            pair.get("direction_id_a") == pair.get("direction_id_b")
            and pair.get("direction_id_a") is not None
        )
        expr_a_short = (pair.get("expression_a") or "")[:40]
        expr_b_short = (pair.get("expression_b") or "")[:40]
        recommendation = _recommend(pair)

        print(f"{i:4d}  {sc:5.3f}  {'YES' if dir_match else 'no':>9}  "
              f"{aid_a[:20]:>20}  {aid_b[:20]:>20}")
        print(f"      expr_a: {expr_a_short}")
        print(f"      expr_b: {expr_b_short}")
        print(f"      REC: {recommendation}")
        print()

        # Decide which alpha to mark (later = higher created_at)
        ca_a = float(pair.get("created_at_a") or 0)
        ca_b = float(pair.get("created_at_b") or 0)
        later_id = aid_b if ca_b >= ca_a else aid_a

        report_pairs.append({
            **pair,
            "direction_match": dir_match,
            "recommendation": recommendation,
            "later_alpha_id": later_id,
        })

        if args.auto_mark_duplicate and not args.dry_run:
            marked.append(later_id)

    # ---- Direction saturation summary ----
    print("\n[sc_review] Direction saturation (# high-SC pairs per direction):")
    for did, count in sorted(direction_density.items(), key=lambda x: -x[1])[:10]:
        print(f"  {did:<50}  {count} pair(s)")

    # ---- Auto-mark duplicates ----
    if args.auto_mark_duplicate:
        if args.dry_run:
            print(f"\n[sc_review] DRY-RUN: would mark {len(pairs)} later alphas as 'duplicate_blocked'")
        else:
            with open_knowledge() as conn:
                for alpha_id in marked:
                    conn.execute(
                        "UPDATE alphas SET status='duplicate_blocked', updated_at=? "
                        "WHERE alpha_id=? AND dataset_tag=? AND status NOT IN ('legacy', 'submitted')",
                        (time.time(), alpha_id, tag),
                    )
            print(f"\n[sc_review] Marked {len(marked)} alpha(s) as 'duplicate_blocked'.")

    # ---- Export CSV ----
    if args.export_csv:
        csv_path = Path(args.export_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "alpha_id_a", "alpha_id_b", "sc_value", "direction_match",
                "direction_id_a", "direction_id_b",
                "expression_a", "expression_b", "recommendation", "later_alpha_id"
            ])
            writer.writeheader()
            writer.writerows(report_pairs)
        print(f"[sc_review] CSV exported: {csv_path}")

    _save_report(args, tag, report_pairs, direction_density, marked)


def _save_report(args, tag: str, pairs: list[dict],
                 direction_density: dict, marked: list[str]) -> None:
    out_dir = _ROOT / "test_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sc_review_{_TS}.json"
    tmp = out_path.with_suffix(".tmp")
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset_tag": tag,
        "threshold": args.threshold,
        "dry_run": args.dry_run,
        "auto_mark_duplicate": args.auto_mark_duplicate,
        "pairs_found": len(pairs),
        "marked_duplicate_blocked": marked,
        "direction_saturation": dict(direction_density),
        "pairs": pairs,
    }
    tmp.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    os.replace(tmp, out_path)
    print(f"[sc_review] Report saved: {out_path}")


if __name__ == "__main__":
    main()
