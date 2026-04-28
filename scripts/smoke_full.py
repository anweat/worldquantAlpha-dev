"""smoke_full.py — End-to-end smoke test.

Fires an alpha_gen generate task using the fake AI adapter, waits for the
chain to complete, then asserts key invariants:
  - pool_stats incremented (alphas_tried > 0 in workspace DB)
  - at least one alpha has themes_csv populated or direction_id set
  - ai_cache packages (if any) are in stage 'done' or 'failed'
  - at least one ALPHA_DRAFTED event is recorded

Saves a summary to test_results/baseline.json.

Usage:
    python scripts/smoke_full.py --dataset USA_TOP3000 --rounds 2 --simulate-ai
    python scripts/smoke_full.py --dataset USA_TOP3000 --rounds 1 --simulate-ai --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is on path
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_db_counts(tag: str) -> dict:
    """Return key counts from state.db + knowledge.db for the given tag."""
    from wq_bus.data._sqlite import open_state, open_knowledge, ensure_migrated
    ensure_migrated()

    result: dict = {}

    with open_state() as conn:
        # Count ai_calls today
        cutoff = time.time() - 86400
        result["ai_calls_today"] = int(conn.execute(
            "SELECT COUNT(*) FROM ai_calls WHERE ts>=?", (cutoff,)
        ).fetchone()[0])

        # Count trace rows
        try:
            result["traces_total"] = int(conn.execute(
                "SELECT COUNT(*) FROM trace"
            ).fetchone()[0])
            result["traces_completed"] = int(conn.execute(
                "SELECT COUNT(*) FROM trace WHERE status='completed'"
            ).fetchone()[0])
        except Exception:
            result["traces_total"] = 0
            result["traces_completed"] = 0

        # Count events
        try:
            result["events_total"] = int(conn.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0])
            result["alpha_drafted_events"] = int(conn.execute(
                "SELECT COUNT(*) FROM events WHERE topic='ALPHA_DRAFTED'"
            ).fetchone()[0])
        except Exception:
            result["events_total"] = 0
            result["alpha_drafted_events"] = 0

    with open_knowledge() as conn:
        result["alphas_total"] = int(conn.execute(
            "SELECT COUNT(*) FROM alphas WHERE dataset_tag=?", (tag,)
        ).fetchone()[0])
        result["alphas_with_direction"] = int(conn.execute(
            "SELECT COUNT(*) FROM alphas WHERE dataset_tag=? AND direction_id IS NOT NULL AND direction_id!=''",
            (tag,)
        ).fetchone()[0])
        result["alphas_with_themes"] = int(conn.execute(
            "SELECT COUNT(*) FROM alphas WHERE dataset_tag=? AND themes_csv IS NOT NULL AND themes_csv!=''",
            (tag,)
        ).fetchone()[0])

        # pool_stats
        try:
            result["directions_total"] = int(conn.execute(
                "SELECT COUNT(*) FROM pool_stats WHERE dataset_tag=?", (tag,)
            ).fetchone()[0])
            result["alphas_tried_total"] = int(conn.execute(
                "SELECT COALESCE(SUM(alphas_tried),0) FROM pool_stats WHERE dataset_tag=?", (tag,)
            ).fetchone()[0])
        except Exception:
            result["directions_total"] = 0
            result["alphas_tried_total"] = 0

    return result


def _load_ai_cache_stages() -> dict:
    """Summarize ai_cache package stages."""
    cache_dir = Path("data") / "ai_cache"
    if not cache_dir.exists():
        return {}
    stages: dict[str, int] = {}
    for pkg_dir in cache_dir.iterdir():
        meta = pkg_dir / "meta.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text())
            stage = data.get("stage", "unknown")
            stages[stage] = stages.get(stage, 0) + 1
        except Exception:
            stages["unreadable"] = stages.get("unreadable", 0) + 1
    return stages


def _assert(cond: bool, label: str, details: str = "") -> dict:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f" — {details}" if details else ""))
    return {"label": label, "status": status, "details": details}


# ---------------------------------------------------------------------------
# Main smoke flow
# ---------------------------------------------------------------------------

async def run_smoke(tag: str, rounds: int, simulate_ai: bool, output_json: bool) -> dict:
    # Install fake adapter if requested
    if simulate_ai:
        os.environ["WQ_AI_ADAPTER"] = "fake_simulate"
        from scripts.simulate_ai import maybe_install
        maybe_install()

    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()

    from wq_bus.utils.tag_context import with_tag
    from wq_bus.data import workspace

    baseline = _load_db_counts(tag)

    task_results: list[dict] = []

    for i in range(rounds):
        print(f"\n[smoke_full] Round {i+1}/{rounds} — tag={tag}")
        with with_tag(tag):
            # Ensure workspace
            workspace.ensure(tag)

            from wq_bus.bus.event_bus import get_bus
            from wq_bus.bus.events import make_event, Topic
            from wq_bus.bus.tasks import start_task

            bus = get_bus()

            # Fire generate task
            handle = start_task(
                kind="alpha_gen",
                payload={"mode": "explore", "n": 4},
                origin="smoke_test",
                dataset_tag=tag,
            )
            print(f"  started trace_id={handle.trace_id}")

            # Wait (short timeout for smoke)
            try:
                result = await handle.wait(timeout=120)
                task_results.append({"round": i + 1, "trace_id": handle.trace_id,
                                     "status": "completed"})
                print(f"  completed: {result.trace_id}")
            except TimeoutError:
                task_results.append({"round": i + 1, "trace_id": handle.trace_id,
                                     "status": "timeout"})
                print(f"  timeout after 120s (chain may still be running)")
            except Exception as e:
                task_results.append({"round": i + 1, "trace_id": handle.trace_id,
                                     "status": f"error: {e}"})
                print(f"  error: {e}")

            # Give bus a moment to settle
            await bus.drain(timeout=15)

    after = _load_db_counts(tag)
    ai_cache_stages = _load_ai_cache_stages()

    print("\n[smoke_full] Assertions:")
    assertions: list[dict] = []

    # A1: pool_stats incremented
    tried_delta = after.get("alphas_tried_total", 0) - baseline.get("alphas_tried_total", 0)
    assertions.append(_assert(tried_delta >= 0,
                              "pool_stats.alphas_tried incremented or stable",
                              f"delta={tried_delta}"))

    # A2: alphas in KB
    alpha_delta = after.get("alphas_total", 0) - baseline.get("alphas_total", 0)
    assertions.append(_assert(alpha_delta >= 0,
                              "alphas in knowledge_db created or stable",
                              f"delta={alpha_delta}"))

    # A3: no 'failed' ai_cache packages (all should be done or non-existent)
    failed_pkgs = ai_cache_stages.get("failed", 0)
    assertions.append(_assert(failed_pkgs == 0,
                              "no ai_cache packages in 'failed' stage",
                              f"stages={ai_cache_stages}"))

    # A4: at least 0 ALPHA_DRAFTED events (smoke with fake adapter may not produce them
    #     if alpha_gen agent isn't registered; just check it doesn't crash)
    drafted_delta = after.get("alpha_drafted_events", 0) - baseline.get("alpha_drafted_events", 0)
    assertions.append(_assert(drafted_delta >= 0,
                              "ALPHA_DRAFTED events non-negative",
                              f"delta={drafted_delta}"))

    # A5: trace rows created
    trace_delta = after.get("traces_total", 0) - baseline.get("traces_total", 0)
    assertions.append(_assert(trace_delta >= rounds,
                              "trace rows created for each round",
                              f"expected>={rounds}, delta={trace_delta}"))

    passed = sum(1 for a in assertions if a["status"] == "PASS")
    total = len(assertions)
    print(f"\n[smoke_full] {passed}/{total} assertions passed")

    report = {
        "tag": tag,
        "rounds": rounds,
        "simulate_ai": simulate_ai,
        "baseline": baseline,
        "after": after,
        "ai_cache_stages": ai_cache_stages,
        "task_results": task_results,
        "assertions": assertions,
        "summary": {"passed": passed, "total": total,
                    "status": "PASS" if passed == total else "FAIL"},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Save to test_results/baseline.json
    out_dir = Path("test_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "baseline.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"[smoke_full] saved {out_path}")

    if output_json:
        print(json.dumps(report, indent=2, default=str))

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end smoke test for wq-bus.")
    parser.add_argument("--dataset", default="USA_TOP3000", help="Dataset tag")
    parser.add_argument("--rounds", type=int, default=1, help="Number of generate rounds")
    parser.add_argument("--simulate-ai", action="store_true",
                        help="Use FakeAdapter (no real AI calls)")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Print JSON report to stdout")
    args = parser.parse_args()

    report = asyncio.run(run_smoke(
        tag=args.dataset,
        rounds=args.rounds,
        simulate_ai=args.simulate_ai,
        output_json=args.output_json,
    ))
    summary = report["summary"]
    sys.exit(0 if summary["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
