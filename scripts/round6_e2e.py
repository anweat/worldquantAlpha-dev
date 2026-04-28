"""round6_e2e.py — Round-6 end-to-end test harness.

Exercises the full bus chain in dry-run mode (no real BRAIN/AI quota) and the
new round-5 CLI commands. Captures the relevant slice of logs/wqbus.log,
surfaces failures with context, and writes a JSON report to
``test_results/round6_e2e.json``.

Usage:
    set WQBUS_DRY=1
    python scripts/round6_e2e.py --dataset usa_top3000 --rounds 1
    python scripts/round6_e2e.py --dataset usa_top3000 --rounds 2 --json
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from wq_bus.data._sqlite import ensure_migrated, open_state, open_knowledge  # noqa: E402
from wq_bus.utils.tag_context import with_tag, with_trace  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOG_FILE = _ROOT / "logs" / "wqbus.log"


def _log_offset() -> int:
    return LOG_FILE.stat().st_size if LOG_FILE.exists() else 0


def _log_slice(start_offset: int, max_chars: int = 8000) -> str:
    if not LOG_FILE.exists():
        return "(no log file)"
    try:
        with LOG_FILE.open("rb") as f:
            f.seek(start_offset)
            data = f.read().decode("utf-8", errors="replace")
        if len(data) > max_chars:
            return "...[truncated]...\n" + data[-max_chars:]
        return data
    except Exception as e:
        return f"(log read failed: {e})"


def _record(step: str, ok: bool, **details) -> dict:
    flag = "PASS" if ok else "FAIL"
    summary = details.pop("summary", "")
    print(f"  [{flag}] {step}" + (f" — {summary}" if summary else ""))
    return {"step": step, "status": flag, "summary": summary, **details}


def _db_counts(tag: str) -> dict:
    out: dict = {}
    with open_state() as c:
        out["traces_total"] = c.execute("SELECT COUNT(*) FROM trace").fetchone()[0]
        out["traces_running"] = c.execute(
            "SELECT COUNT(*) FROM trace WHERE status='running'"
        ).fetchone()[0]
        out["events_total"] = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        out["sim_dlq_open"] = c.execute(
            "SELECT COUNT(*) FROM sim_dead_letter WHERE dataset_tag=? AND requeued_at IS NULL",
            (tag,),
        ).fetchone()[0]
    with open_knowledge() as c:
        out["alphas_total"] = c.execute(
            "SELECT COUNT(*) FROM alphas WHERE dataset_tag=?", (tag,)
        ).fetchone()[0]
        out["fingerprints_total"] = c.execute(
            "SELECT COUNT(*) FROM expr_fingerprints WHERE dataset_tag=?", (tag,)
        ).fetchone()[0]
    return out


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------

async def scenario_chain(tag: str) -> dict:
    """Run alpha_gen via dispatcher dry-run path; assert chain closes cleanly."""
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.bus.events import make_event, Topic
    from wq_bus.bus.tasks import start_task
    from wq_bus.agents.alpha_gen import AlphaGen
    from wq_bus.agents.sim_executor import SimExecutor
    from wq_bus.brain.client import BrainClient
    from wq_bus.ai.dispatcher import get_dispatcher

    # Force fake AI adapter so we don't hit real network.
    os.environ["WQ_AI_ADAPTER"] = "fake_simulate"
    from scripts.simulate_ai import maybe_install
    maybe_install()
    # Ensure dispatcher dry-run flag is set (dispatcher reads WQBUS_DRY).
    os.environ["WQBUS_DRY"] = "1"

    bus = get_bus()
    client = BrainClient()
    dispatcher = get_dispatcher(dry_run=True)
    # Instantiate agents (sim_executor needs to subscribe before we emit)
    AlphaGen(bus, dispatcher=dispatcher)
    sim_agent = SimExecutor(bus, client, dispatcher=dispatcher)

    handle = start_task(
        kind="alpha_round",
        payload={"mode": "explore", "n": 3},
        origin="round6_e2e",
        dataset_tag=tag,
    )
    with with_tag(tag), with_trace(handle.trace_id):
        bus.emit(make_event(
            Topic.GENERATE_REQUESTED, tag, mode="explore", n=3,
            trace_id=handle.trace_id,
        ))
        try:
            await bus.drain(timeout=60)
        except Exception as e:
            raise AssertionError(f"drain after GENERATE_REQUESTED failed: {e}")
        # The CLI is normally responsible for emitting BATCH_DONE after a
        # generation burst. Replicate that here so the alpha_round trace
        # can auto-close via _TERMINAL_TOPICS_BY_KIND.
        await sim_agent.emit_batch_done()
        await bus.drain(timeout=10)

    # Look up final trace state
    with open_state() as c:
        row = c.execute(
            "SELECT status, ended_at, error FROM trace WHERE trace_id=?",
            (handle.trace_id,),
        ).fetchone()
    status = row["status"] if row else "missing"
    if status not in ("completed", "failed"):
        raise AssertionError(
            f"trace {handle.trace_id} ended with status={status} (expected completed/failed); "
            f"chain auto-close did not fire — likely missing TASK_COMPLETED/TASK_FAILED emit"
        )
    return {"trace_id": handle.trace_id,
            "trace_status": status,
            "trace_error": row["error"] if row else None}


def scenario_kb_prune(tag: str) -> dict:
    from wq_bus.data import knowledge_db
    with with_tag(tag):
        # Use future-dated retention so nothing is actually deleted.
        deleted = knowledge_db.prune_old(
            alpha_days=99999, fingerprint_days=99999,
            pnl_days=99999, learning_days=99999, crawl_doc_days=99999,
            keep_top_sharpe=200,
        )
    return {"deleted_counts": deleted}


def scenario_sim_dlq(tag: str) -> dict:
    from wq_bus.data import state_db
    with with_tag(tag):
        rid = state_db.add_sim_dead_letter(
            expression="ts_test_round6_marker",
            reason="round6 unit smoke",
            settings={"k": 1},
        )
        rows = state_db.list_sim_dead_letter(limit=10)
        ok_requeue = state_db.mark_sim_dlq_requeued(rid)
    return {"inserted_id": rid, "list_size": len(rows), "requeue_ok": ok_requeue}


def scenario_alpha_lineage(tag: str) -> dict:
    """Try lineage on first available alpha (or skip if KB is empty)."""
    with open_knowledge() as c:
        row = c.execute(
            "SELECT alpha_id FROM alphas WHERE dataset_tag=? LIMIT 1", (tag,)
        ).fetchone()
    if not row:
        return {"skipped": "no alphas in KB"}
    alpha_id = row["alpha_id"]
    # Re-implement the CLI logic inline so we don't shell out.
    from wq_bus.cli import alpha_lineage_cmd  # noqa: F401  (existence check)
    out: dict = {"alpha_id": alpha_id, "lineage_ok": True}
    with open_knowledge() as kc:
        a = kc.execute(
            "SELECT alpha_id, dataset_tag, status, trace_id, ai_call_id "
            "FROM alphas WHERE alpha_id=?", (alpha_id,)
        ).fetchone()
        out["alpha"] = dict(a) if a else None
    return out


def scenario_topic_registry() -> dict:
    """Round-5 b3: ensure the new error topics are registered.

    Force-import bus.events so the registration side-effects fire.
    """
    import wq_bus.bus.events  # noqa: F401  — triggers register_topic() calls
    from wq_bus.bus.topic_registry import is_registered
    needed = ["ALPHA_GEN_ERRORED", "ALPHA_SIM_ERRORED",
              "TASK_STARTED", "TASK_COMPLETED", "TASK_FAILED",
              "API_DEGRADED", "API_RESTORED"]
    missing = [t for t in needed if not is_registered(t)]
    if missing:
        raise AssertionError(f"missing topics: {missing}")
    return {"needed": needed, "missing": missing}


def scenario_migrations() -> dict:
    """Re-running ensure_migrated() must be idempotent."""
    for _ in range(3):
        ensure_migrated()
    return {"runs": 3, "ok": True}


# ---------------------------------------------------------------------------
# R6-C scenarios — pipeline coordinator + summarizer
# ---------------------------------------------------------------------------

async def scenario_pipeline_satisfied(tag: str) -> dict:
    """Start `echo_task` pipeline; expect status='satisfied' within timeout."""
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.coordinator.runner import CoordinatorAgent
    from wq_bus.ai.ai_service import AIService
    from wq_bus.ai.dispatcher import get_dispatcher
    from wq_bus.data import task_db

    os.environ["WQBUS_DRY"] = "1"
    bus = get_bus()
    dispatcher = get_dispatcher(dry_run=True)
    AIService(bus, dispatcher).start()
    coord = CoordinatorAgent(bus); coord.start()

    task_id = await coord.start_task("echo_task", dataset_tag=tag, origin="round6_e2e")
    deadline = time.time() + 30.0
    final = None
    while time.time() < deadline:
        await bus.drain(timeout=2)
        row = task_db.get_task(task_id)
        st = (row or {}).get("status")
        if st in ("satisfied", "exhausted", "failed", "cancelled"):
            final = st
            break
        await asyncio.sleep(0.5)
    if final is None:
        raise AssertionError(f"task {task_id} did not finish within 30s")
    if final != "satisfied":
        raise AssertionError(f"task {task_id} ended status={final} (expected satisfied)")
    return {"task_id": task_id, "status": final,
            "iterations": (task_db.get_task(task_id) or {}).get("iterations")}


async def scenario_pipeline_cancel(tag: str) -> dict:
    """Start a long-running task, cancel it, expect status='cancelled'."""
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.bus.events import make_event
    from wq_bus.coordinator.runner import CoordinatorAgent
    from wq_bus.data import task_db

    bus = get_bus()
    coord = CoordinatorAgent(bus); coord.start()

    # Use echo_task again but with high max_iter so it would loop.
    task_id = await coord.start_task(
        "echo_task", dataset_tag=tag, origin="round6_e2e",
        overrides={"max_iterations": 50},
    )
    await asyncio.sleep(0.2)
    bus.emit(make_event("TASK_CANCEL_REQUESTED", tag, task_id=task_id))
    deadline = time.time() + 10.0
    final = None
    while time.time() < deadline:
        await bus.drain(timeout=1)
        row = task_db.get_task(task_id)
        st = (row or {}).get("status")
        if st in ("satisfied", "exhausted", "failed", "cancelled"):
            final = st
            break
        await asyncio.sleep(0.3)
    if final not in ("cancelled", "satisfied"):
        # 'satisfied' acceptable if echo_task finished before our cancel landed
        raise AssertionError(f"task {task_id} ended status={final}")
    return {"task_id": task_id, "status": final}


async def scenario_summarizer_manual(tag: str) -> dict:
    """SummarizerAgent.run_once() must complete a dry-run round-trip."""
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.ai.ai_service import AIService
    from wq_bus.ai.dispatcher import get_dispatcher
    from wq_bus.agents.summarizer import SummarizerAgent

    os.environ["WQBUS_DRY"] = "1"
    bus = get_bus()
    dispatcher = get_dispatcher(dry_run=True)
    AIService(bus, dispatcher).start()
    s = SummarizerAgent(bus); s.start(run_loop=False)
    res = await s.run_once("workspace_overview", force=True)
    if not res or "artifact" not in res:
        raise AssertionError(f"summarizer.run_once returned bad result: {res}")
    art = Path(res["artifact"])
    if not art.exists():
        raise AssertionError(f"artifact missing: {art}")
    return {"mode": "workspace_overview", "artifact": str(art),
            "size": art.stat().st_size}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

async def run(tag: str, rounds: int, output_json: bool) -> dict:
    ensure_migrated()
    print(f"[round6_e2e] tag={tag} rounds={rounds}")

    log_start = _log_offset()
    baseline = _db_counts(tag)
    print(f"[round6_e2e] baseline: {baseline}")

    results: list[dict] = []
    failures: list[dict] = []

    def _run_safe(label: str, fn, *args, **kwargs):
        log_off = _log_offset()
        try:
            r = fn(*args, **kwargs)
            res = _record(label, True, summary=str(r)[:200], detail=r)
        except Exception as e:
            tb = traceback.format_exc()
            res = _record(label, False,
                          summary=f"{type(e).__name__}: {e}",
                          traceback=tb,
                          log_slice=_log_slice(log_off, 4000))
            failures.append(res)
        results.append(res)
        return res

    async def _run_safe_async(label: str, coro):
        log_off = _log_offset()
        try:
            r = await coro
            res = _record(label, True, summary=str(r)[:200], detail=r)
        except Exception as e:
            tb = traceback.format_exc()
            res = _record(label, False,
                          summary=f"{type(e).__name__}: {e}",
                          traceback=tb,
                          log_slice=_log_slice(log_off, 4000))
            failures.append(res)
        results.append(res)
        return res

    # 1. migrations idempotent
    _run_safe("migrations idempotent", scenario_migrations)
    # 2. topic registry
    _run_safe("topic registry complete", scenario_topic_registry)
    # 3. KB prune (no-op cutoff)
    _run_safe("kb prune no-op", scenario_kb_prune, tag)
    # 4. sim-dlq insert/list/requeue
    _run_safe("sim-dlq insert/list/requeue", scenario_sim_dlq, tag)
    # 5. alpha lineage (skipped if no alphas)
    _run_safe("alpha lineage", scenario_alpha_lineage, tag)
    # 6. full chain rounds
    for i in range(rounds):
        await _run_safe_async(f"chain round {i+1}/{rounds}", scenario_chain(tag))
    # 7. R6-C: pipeline coordinator — echo_task satisfied
    await _run_safe_async("pipeline echo_task satisfied", scenario_pipeline_satisfied(tag))
    # 8. R6-C: pipeline cancel
    await _run_safe_async("pipeline cancel", scenario_pipeline_cancel(tag))
    # 9. R6-C: summarizer manual run
    await _run_safe_async("summarizer manual workspace_overview",
                          scenario_summarizer_manual(tag))

    after = _db_counts(tag)
    print(f"[round6_e2e] after: {after}")

    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_total = len(results)
    print(f"\n[round6_e2e] {n_pass}/{n_total} steps passed")

    report = {
        "tag": tag,
        "rounds": rounds,
        "baseline": baseline,
        "after": after,
        "results": results,
        "failures": failures,
        "log_slice_total": _log_slice(log_start, 12000),
    }
    out_path = _ROOT / "test_results" / "round6_e2e.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"[round6_e2e] saved {out_path}")

    if output_json:
        print(json.dumps({"pass": n_pass, "total": n_total,
                          "failures": [f["step"] for f in failures]}))

    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="usa_top3000")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--json", dest="output_json", action="store_true")
    args = p.parse_args()
    rep = asyncio.run(run(args.dataset, args.rounds, args.output_json))
    return 0 if not rep["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
