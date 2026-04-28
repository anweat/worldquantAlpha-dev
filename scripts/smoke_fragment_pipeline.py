"""E2E dry-run smoke for fragment pipeline.

Run: python scripts/smoke_fragment_pipeline.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ["WQBUS_DRY"] = "1"

from wq_bus.bus.event_bus import EventBus
from wq_bus.bus.events import Topic, make_event
from wq_bus.agents.alpha_gen import AlphaGen
from wq_bus.ai.dispatcher import Dispatcher
from wq_bus.ai.ai_service import AIService
from wq_bus.utils.tag_context import with_tag


async def main() -> int:
    bus = EventBus()
    disp = Dispatcher(dry_run=True)
    ais = AIService(bus, disp)
    ais.start()
    ag = AlphaGen(bus, disp)

    drafted: list[dict] = []
    batch_done: list[dict] = []

    async def _cap(ev):
        drafted.append(dict(ev.payload))

    async def _bd(ev):
        batch_done.append(dict(ev.payload))

    bus.subscribe(Topic.ALPHA_DRAFTED, _cap)
    bus.subscribe(Topic.BATCH_DONE, _bd)

    print("=" * 60)
    print("Test 1: mode=specialize (expect ~30-200 ALPHA_DRAFTED)")
    print("=" * 60)
    ev = make_event(Topic.GENERATE_REQUESTED, "usa_top3000",
                    n=8, mode="specialize", hint="smoke")
    with with_tag("usa_top3000"):
        await ag.on_generate_requested(ev)
    await bus.drain(timeout=10.0)
    print(f"  ALPHA_DRAFTED count: {len(drafted)}")
    print(f"  BATCH_DONE events:   {len(batch_done)}")
    if batch_done:
        print(f"  Last BATCH_DONE:     {batch_done[-1]}")
    if drafted:
        print(f"  First drafted expr:  {drafted[0].get('expression','')[:80]}")
        # Strategy distribution from rationale
        strats = {}
        for d in drafted:
            r = d.get("rationale", "")
            tag = "[other]"
            for k in ("[passthrough]", "[linear_2leg]", "[filtered]",
                     "[weighted]", "[variant]"):
                if k in r:
                    tag = k
                    break
            strats[tag] = strats.get(tag, 0) + 1
        print(f"  Strategy distribution: {strats}")

    drafted.clear()
    batch_done.clear()

    print()
    print("=" * 60)
    print("Test 2: mode=explore (expect ~50-100)")
    print("=" * 60)
    ev = make_event(Topic.GENERATE_REQUESTED, "usa_top3000",
                    n=20, mode="explore", hint="smoke")
    with with_tag("usa_top3000"):
        await ag.on_generate_requested(ev)
    await bus.drain(timeout=10.0)
    print(f"  ALPHA_DRAFTED count: {len(drafted)}")

    drafted.clear()
    batch_done.clear()

    print()
    print("=" * 60)
    print("Test 3: mode=review_failure")
    print("=" * 60)
    ev = make_event(Topic.GENERATE_REQUESTED, "usa_top3000",
                    n=10, mode="review_failure", hint="smoke")
    with with_tag("usa_top3000"):
        await ag.on_generate_requested(ev)
    await bus.drain(timeout=10.0)
    print(f"  ALPHA_DRAFTED count: {len(drafted)}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
