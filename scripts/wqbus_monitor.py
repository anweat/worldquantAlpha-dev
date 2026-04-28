"""scripts/wqbus_monitor.py — 持续运行的监控/汇报循环。

目标：在后台持续 generate -> simulate -> SC-check -> submit，直到达到目标提交数。

用法：
    python scripts/wqbus_monitor.py --target 4 --interval 60 --batch 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wq_bus.bus.event_bus import get_bus  # noqa: E402
from wq_bus.bus.events import Topic, make_event  # noqa: E402
from wq_bus.data import knowledge_db, state_db  # noqa: E402
from wq_bus.utils.logging import get_logger, setup as setup_logging  # noqa: E402
from wq_bus.utils.tag_context import with_tag  # noqa: E402
from wq_bus.utils.yaml_loader import load_yaml  # noqa: E402

log = get_logger("monitor")
STATUS_FILE = PROJECT_ROOT / "logs" / "monitor_status.json"


def _count_submitted(tag: str) -> int:
    with with_tag(tag):
        return len(knowledge_db.list_submitted_alpha_ids())


def _write_status(payload: dict) -> None:
    STATUS_FILE.parent.mkdir(exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


async def _run(args):
    tag = args.dataset
    bus = get_bus()
    # Build dispatcher + brain client + agents (lazy imports)
    from wq_bus.ai.dispatcher import get_dispatcher
    from wq_bus.brain.client import BrainClient
    from wq_bus.agents.alpha_gen import AlphaGen
    from wq_bus.agents.sim_executor import SimExecutor
    from wq_bus.agents.self_corr_checker import SelfCorrChecker
    from wq_bus.agents.failure_analyzer import FailureAnalyzer
    from wq_bus.agents.submitter import Submitter
    from wq_bus.agents.portfolio_analyzer import PortfolioAnalyzer

    dispatcher = get_dispatcher(override_model=args.model, override_depth=args.depth, dry_run=args.dry_run)
    brain = BrainClient()
    if not brain.check_auth() and not args.dry_run:
        log.error("BRAIN session invalid")
        _write_status({"status": "auth_failed", "ts": time.time()})
        return
    AlphaGen(bus, dispatcher)
    sim_exec = SimExecutor(bus, brain, dispatcher=dispatcher)
    SelfCorrChecker(bus, brain)
    FailureAnalyzer(bus, dispatcher)
    Submitter(bus, brain)
    PortfolioAnalyzer(bus, brain)

    start_ts = time.time()
    round_idx = 0
    initial_submitted = _count_submitted(tag)
    log.info("monitor start: tag=%s target=%d initial_submitted=%d",
             tag, args.target, initial_submitted)

    while True:
        round_idx += 1
        if round_idx > args.max_rounds:
            log.warning("max-rounds (%d) reached — exiting to protect AI budget.", args.max_rounds)
            break
        # Reset per-round AI quota each cycle
        try:
            dispatcher._limiter.reset_round()
        except Exception:
            pass
        with with_tag(tag):
            current = _count_submitted(tag)
            new_subs = current - initial_submitted
            queue_size = state_db.queue_size("pending")
            _write_status({
                "round": round_idx,
                "ts": time.time(),
                "elapsed_secs": round(time.time() - start_ts, 1),
                "tag": tag,
                "target": args.target,
                "submitted_this_session": new_subs,
                "queue_pending": queue_size,
                "ai_calls_today": state_db.count_ai_calls_today(),
            })
            log.info("[round %d] submitted_session=%d/%d  queue_pending=%d",
                     round_idx, new_subs, args.target, queue_size)
            if new_subs >= args.target:
                log.info("TARGET REACHED — stopping.")
                break

            # Trigger generation if queue is small
            if queue_size < args.target - new_subs:
                bus.emit(make_event(Topic.GENERATE_REQUESTED, tag,
                                    n=args.batch, hint=args.hint, source="monitor"))
                await bus.drain(timeout=900)
                await sim_exec.emit_batch_done()
                await bus.drain(timeout=300)

            # Always try to flush
            bus.emit(make_event(Topic.QUEUE_FLUSH_REQUESTED, tag))
            await bus.drain(timeout=300)

        await asyncio.sleep(args.interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--target", type=int, default=4)
    ap.add_argument("--batch", type=int, default=10,
                    help="Expressions to request per round (1 AI call generates N).")
    ap.add_argument("--interval", type=int, default=1800,
                    help="Seconds between rounds (default: 30 min).")
    ap.add_argument("--max-rounds", type=int, default=8,
                    help="Hard cap on rounds — protects daily AI budget.")
    ap.add_argument("--hint", default="")
    ap.add_argument("--model", default=None)
    ap.add_argument("--depth", default=None, choices=["low", "medium", "high"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.dataset:
        ds = load_yaml("datasets")
        args.dataset = ds.get("default_tag") or "usa_top3000"
    setup_logging()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
