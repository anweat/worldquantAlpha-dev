"""wqbus CLI — central trigger entry point.

Common subcommands (see `wqbus --help` for full list):

    Daemon / status
        wqbus daemon                 Start the bus daemon (foreground).
        wqbus admin status [--json]  Queue / AI usage / today submitted.
        wqbus check-session          Verify BRAIN session.
        wqbus login [--force]        Refresh BRAIN session via Playwright.

    Triggering
        wqbus generate -n 10         Manually trigger a generation burst.
        wqbus submit-flush           Trigger submission queue flush.
        wqbus crawl --target NAME    Trigger a single crawl target.
        wqbus summarize              Force doc summarization on pending docs.
        wqbus drain-docs --max-batches N --dataset TAG
                                     Manual batched drain of doc_summarizer
                                     (no auto-loop; safe to call repeatedly).
        wqbus emit TOPIC --json '{}' Inject any bus event from CLI.
        wqbus task <agent> --mode M --dataset TAG
                                     Manual one-off agent task (does NOT count
                                     against daily_ai_cap).
        wqbus resume                 Scan state.db and re-fire stalled events.

    Dataset / pool
        wqbus dataset list / active TAG
        wqbus datafields --refresh   Refresh cached BRAIN datafields.

    Recipes (composition_recipes)
        wqbus recipe list [--status proposed|approved]
        wqbus recipe show / approve / reject / diff <id>
        wqbus recipe extract --tag USA_TOP3000 --min-support 3

    Trace / debugging
        wqbus trace --recent 5
        wqbus trace --alpha <ID> --full
        wqbus trace-tree show <trace_id> [--json]
        wqbus trace-tree recent --limit 10
        wqbus trace-tree alpha <alpha_id>

    DB / maintenance
        wqbus db migrate [--json]    Apply migrations 001-006 (idempotent).
        wqbus analyze portfolio      Run portfolio analysis on demand.

Global options:
    --dataset TAG       Override active dataset.
    --model NAME        Override AI model for ALL agents (testing only — strength
                        routing in agent_profiles.yaml is the canonical source).
    --depth low|medium|high
    --dry-run           Skip BRAIN submit + skip AI calls (uses stubs).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from wq_bus.utils.logging import get_logger, setup as setup_logging
from wq_bus.utils.tag_context import with_tag
from wq_bus.utils.yaml_loader import load_yaml

log = get_logger("cli")


def _resolve_dataset(tag: str | None) -> str:
    if tag:
        return tag
    ds = load_yaml("datasets")
    return ds.get("default_tag") or "usa_top3000"


def _build_dispatcher(model: str | None, depth: str | None, dry_run: bool):
    """Defer heavy imports to avoid breaking when optional modules are missing."""
    from wq_bus.ai.dispatcher import get_dispatcher
    return get_dispatcher(override_model=model, override_depth=depth, dry_run=dry_run)


def _build_brain_client():
    from wq_bus.brain.client import BrainClient
    return BrainClient()


def _wire_agents(bus, dispatcher, brain_client):
    """Instantiate and subscribe all agents."""
    from wq_bus.agents.alpha_gen import AlphaGen
    from wq_bus.agents.sim_executor import SimExecutor
    from wq_bus.agents.self_corr_checker import SelfCorrChecker
    from wq_bus.agents.failure_analyzer import FailureAnalyzer
    from wq_bus.agents.submitter import Submitter
    from wq_bus.agents.portfolio_analyzer import PortfolioAnalyzer
    from wq_bus.agents.doc_summarizer import DocSummarizer

    agents = [
        AlphaGen(bus, dispatcher),
        SimExecutor(bus, brain_client, dispatcher=dispatcher),
        SelfCorrChecker(bus, brain_client),
        FailureAnalyzer(bus, dispatcher),
        Submitter(bus, brain_client),
        PortfolioAnalyzer(bus, brain_client),
        DocSummarizer(bus, dispatcher),
    ]
    return agents


@click.group()
@click.option("--dataset", default=None, help="Dataset tag (overrides config default).")
@click.option("--model", default=None, help="Override AI model for all agents.")
@click.option("--depth", default=None, type=click.Choice(["low", "medium", "high"]))
@click.option("--dry-run", is_flag=True, help="Skip real AI + skip submit.")
@click.option("--verbose", "-v", is_flag=True)
@click.pass_context
def cli(ctx, dataset, model, depth, dry_run, verbose):
    setup_logging(level=10 if verbose else 20)
    ctx.ensure_object(dict)
    ctx.obj.update(dict(
        dataset=_resolve_dataset(dataset),
        model=model,
        depth=depth,
        dry_run=dry_run,
    ))


@cli.command()
@click.option("-n", "--n", default=10, type=int, help="How many alphas to draft.")
@click.option("--rounds", default=1, type=int)
@click.option("--hint", default="", help="Free-form hint forwarded to alpha_gen.")
@click.option("--no-flush", is_flag=True, help="Don't call submit-flush at the end.")
@click.pass_context
def run(ctx, n, rounds, hint, no_flush):
    """Generate -> simulate -> SC-check -> (optional) submit, then exit."""
    asyncio.run(_run_main(ctx.obj, n=n, rounds=rounds, hint=hint, do_flush=not no_flush))


async def _run_main(opts, *, n, rounds, hint, do_flush):
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.bus.events import Topic, make_event
    bus = get_bus()
    dispatcher = _build_dispatcher(opts["model"], opts["depth"], opts["dry_run"])
    brain = _build_brain_client()
    if not opts["dry_run"]:
        if not brain.check_auth():
            click.echo("ERROR: BRAIN session invalid — re-login first.", err=True)
            sys.exit(2)
    agents = _wire_agents(bus, dispatcher, brain)
    sim_exec = next(a for a in agents if a.AGENT_TYPE == "sim_executor")

    with with_tag(opts["dataset"]):
        for r in range(rounds):
            click.echo(f"=== Round {r+1}/{rounds} (dataset={opts['dataset']}, n={n}) ===")
            # Reset per-round AI counters so each CLI round gets a fresh budget
            try:
                dispatcher._limiter.reset_round()
            except Exception:
                pass
            bus.emit(make_event(Topic.GENERATE_REQUESTED, opts["dataset"],
                                n=n, hint=hint, source="cli_run"))
            # Wait for alpha drafting + simulation to complete
            await bus.drain(timeout=600)
            await sim_exec.emit_batch_done()
            await bus.drain(timeout=300)

        if do_flush:
            click.echo("=== Flushing submission queue ===")
            bus.emit(make_event(Topic.QUEUE_FLUSH_REQUESTED, opts["dataset"]))
            await bus.drain(timeout=300)

    click.echo("=== Done ===")


@cli.command()
@click.option("-n", "--n", default=5, type=int)
@click.option("--hint", default="")
@click.pass_context
def generate(ctx, n, hint):
    """Trigger a generation burst (does NOT run simulator/submitter)."""
    async def _go():
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import Topic, make_event
        bus = get_bus()
        dispatcher = _build_dispatcher(ctx.obj["model"], ctx.obj["depth"], ctx.obj["dry_run"])
        from wq_bus.agents.alpha_gen import AlphaGen
        AlphaGen(bus, dispatcher)
        with with_tag(ctx.obj["dataset"]):
            bus.emit(make_event(Topic.GENERATE_REQUESTED, ctx.obj["dataset"], n=n, hint=hint))
            await bus.drain(timeout=300)
    asyncio.run(_go())


@cli.command("submit-flush")
@click.pass_context
def submit_flush(ctx):
    """Drain pending submissions."""
    async def _go():
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import Topic, make_event
        bus = get_bus()
        brain = _build_brain_client()
        from wq_bus.agents.submitter import Submitter
        Submitter(bus, brain)
        with with_tag(ctx.obj["dataset"]):
            bus.emit(make_event(Topic.QUEUE_FLUSH_REQUESTED, ctx.obj["dataset"]))
            await bus.drain(timeout=300)
    asyncio.run(_go())


@cli.command()
@click.option("--target", required=True, help="Crawl target name from crawl_targets.yaml.")
@click.pass_context
def crawl(ctx, target):
    """Trigger a single crawl target."""
    async def _go():
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import Topic, make_event
        bus = get_bus()
        try:
            from wq_bus.crawler.crawler_agent import CrawlerAgent
            CrawlerAgent(bus)
        except ImportError as e:
            click.echo(f"crawler not available: {e}", err=True)
            sys.exit(1)
        with with_tag(ctx.obj["dataset"]):
            bus.emit(make_event(Topic.CRAWL_REQUESTED, ctx.obj["dataset"], target=target))
            await bus.drain(timeout=600)
    asyncio.run(_go())


@cli.command()
@click.pass_context
def summarize(ctx):
    """Force doc_summarizer on pending docs."""
    async def _go():
        from wq_bus.bus.event_bus import get_bus
        from wq_bus.bus.events import Topic, make_event
        bus = get_bus()
        dispatcher = _build_dispatcher(ctx.obj["model"], ctx.obj["depth"], ctx.obj["dry_run"])
        from wq_bus.agents.doc_summarizer import DocSummarizer
        DocSummarizer(bus, dispatcher)
        with with_tag(ctx.obj["dataset"]):
            # Fake a DOC_FETCHED to trigger threshold check
            bus.emit(make_event(Topic.DOC_FETCHED, ctx.obj["dataset"],
                                url_hash="manual", source="manual", title="manual"))
            await bus.drain(timeout=300)
    asyncio.run(_go())


@cli.command("analyze")
@click.argument("kind", type=click.Choice(["portfolio"]))
@click.pass_context
def analyze(ctx, kind):
    async def _go():
        from wq_bus.bus.event_bus import get_bus
        bus = get_bus()
        brain = _build_brain_client()
        if kind == "portfolio":
            from wq_bus.agents.portfolio_analyzer import PortfolioAnalyzer
            pa = PortfolioAnalyzer(bus, brain)
            with with_tag(ctx.obj["dataset"]):
                out = await pa.analyze_now(ctx.obj["dataset"])
                click.echo(f"score={out['overfit'].get('score')} "
                           f"high_corr_pairs={len(out['corr_pairs'])}")
    asyncio.run(_go())


@cli.command("check-session")
def check_session_cmd():
    brain = _build_brain_client()
    ok = brain.check_auth()
    click.echo("OK" if ok else "INVALID — re-login required")
    sys.exit(0 if ok else 1)


@cli.command("dataset")
@click.argument("action", type=click.Choice(["list", "show"]))
@click.argument("tag", required=False)
def dataset_cmd(action, tag):
    ds = load_yaml("datasets")
    items = ds.get("datasets") or []
    if action == "list":
        for entry in items:
            t = entry.get("tag") if isinstance(entry, dict) else entry
            click.echo(t)
    elif action == "show":
        click.echo(repr(next((e for e in items if (e.get("tag") if isinstance(e, dict) else e) == tag), None)))


@cli.command("trace-prune")
@click.option("--older-than-days", "days", type=int, required=True,
              help="Delete completed/failed/cancelled traces older than N days.")
@click.option("--include-events/--keep-events", default=True,
              help="Also delete events for pruned traces (default: yes).")
@click.option("--include-ai-calls/--keep-ai-calls", default=False,
              help="Also delete ai_calls for pruned traces (default: keep — billing record).")
@click.option("--dry-run", is_flag=True, help="Report what would be deleted, don't delete.")
def trace_prune_cmd(days, include_events, include_ai_calls, dry_run):
    """Prune old terminal traces (completed/failed/cancelled) from state.db.

    Running traces are never pruned regardless of age.

    Examples:
        wqbus trace-prune --older-than-days 30 --dry-run
        wqbus trace-prune --older-than-days 30
        wqbus trace-prune --older-than-days 7 --include-ai-calls
    """
    import time as _t
    from wq_bus.data._sqlite import open_state, ensure_migrated
    ensure_migrated()
    cutoff_ts = _t.time() - (days * 86400)
    from datetime import datetime as _dt, timezone as _tz
    cutoff_iso = _dt.fromtimestamp(cutoff_ts, _tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open_state() as conn:
        rows = conn.execute(
            """SELECT trace_id FROM trace
               WHERE status IN ('completed','failed','cancelled','timeout')
                 AND (ended_at IS NOT NULL AND ended_at < ?)""",
            (cutoff_iso,),
        ).fetchall()
        trace_ids = [r["trace_id"] for r in rows]
        n = len(trace_ids)
        if n == 0:
            click.echo(f"no terminal traces older than {days}d (cutoff={cutoff_iso})")
            return
        click.echo(f"found {n} terminal traces older than {days}d (cutoff={cutoff_iso})")
        if dry_run:
            for tid in trace_ids[:10]:
                click.echo(f"  would delete: {tid}")
            if n > 10:
                click.echo(f"  ... and {n - 10} more")
            return
        # Real delete — chunk to avoid huge IN-clauses.
        for i in range(0, n, 500):
            chunk = trace_ids[i:i+500]
            placeholders = ",".join(["?"] * len(chunk))
            if include_events:
                conn.execute(f"DELETE FROM events WHERE trace_id IN ({placeholders})", chunk)
            if include_ai_calls:
                conn.execute(f"DELETE FROM ai_calls WHERE trace_id IN ({placeholders})", chunk)
            conn.execute(f"DELETE FROM trace WHERE trace_id IN ({placeholders})", chunk)
        click.echo(f"deleted {n} traces"
                   + (" + their events" if include_events else "")
                   + (" + their ai_calls" if include_ai_calls else ""))


@cli.command("trace")
@click.argument("trace_id", required=False)
@click.option("--alpha", default=None, help="Look up trace_id by alpha_id.")
@click.option("--recent", default=0, type=int, help="Show N most recent traces (with summary).")
@click.option("--full", is_flag=True, help="Print full prompt + response (otherwise truncated).")
def trace_cmd(trace_id, alpha, recent, full):
    """Show the full activity chain for a trace_id.

    Examples:
        wqbus trace abc123def456                # by trace_id
        wqbus trace --alpha vRJzk25a            # find trace from alpha
        wqbus trace --recent 5                  # 5 most recent traces (summary)
    """
    import json
    import time as _time
    import sqlite3
    from wq_bus.data._sqlite import open_state, open_knowledge, ensure_migrated
    ensure_migrated()

    if recent:
        with open_state() as conn:
            rows = conn.execute(
                """SELECT trace_id, MIN(ts) AS started, COUNT(*) AS n_calls,
                          GROUP_CONCAT(DISTINCT agent_type) AS agents
                   FROM ai_calls
                   WHERE trace_id IS NOT NULL
                   GROUP BY trace_id
                   ORDER BY started DESC LIMIT ?""", (recent,)
            ).fetchall()
        for r in rows:
            ago = int(_time.time() - r["started"])
            click.echo(f"{r['trace_id']}  {ago}s ago  calls={r['n_calls']:<3} agents={r['agents']}")
        return

    if alpha and not trace_id:
        with open_knowledge() as conn:
            row = conn.execute(
                "SELECT trace_id FROM alphas WHERE alpha_id=? LIMIT 1", (alpha,)
            ).fetchone()
        if not row or not row["trace_id"]:
            click.echo(f"No trace_id found for alpha {alpha}", err=True)
            return
        trace_id = row["trace_id"]
        click.echo(f"# trace for alpha {alpha}: {trace_id}\n")

    if not trace_id:
        click.echo("Provide trace_id, --alpha ID, or --recent N", err=True)
        return

    # Pull events + ai_calls + alphas + queue rows for this trace
    with open_state() as conn:
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE trace_id=? ORDER BY ts", (trace_id,)
        ).fetchall()]
        calls = [dict(r) for r in conn.execute(
            "SELECT * FROM ai_calls WHERE trace_id=? ORDER BY ts", (trace_id,)
        ).fetchall()]
        queue = [dict(r) for r in conn.execute(
            "SELECT * FROM submission_queue WHERE trace_id=?", (trace_id,)
        ).fetchall()]
    with open_knowledge() as conn:
        alphas = [dict(r) for r in conn.execute(
            "SELECT alpha_id, status, sharpe, fitness, turnover, sc_value FROM alphas WHERE trace_id=?",
            (trace_id,)
        ).fetchall()]

    click.echo(f"=== trace {trace_id} ===")
    click.echo(f"\n[events: {len(events)}]")
    for e in events:
        click.echo(f"  {e['ts']:.0f}  {e['topic']:<22}  payload={e['payload_json'][:100]}")
    click.echo(f"\n[ai_calls: {len(calls)}]")
    for c in calls:
        click.echo(f"  {c['ts']:.0f}  {c['agent_type']:<18} {c['model']:<22} success={c['success']} dur={c['duration_ms']}ms n={c['n_packed']}")
        if full:
            click.echo("  --- prompt ---");   click.echo(c.get("prompt_text") or "(none)")
            click.echo("  --- response ---"); click.echo(c.get("response_text") or "(none)")
        else:
            p = (c.get("prompt_text") or "")[:200].replace("\n", " | ")
            r = (c.get("response_text") or "")[:200].replace("\n", " | ")
            click.echo(f"    prompt[0..200]:   {p}")
            click.echo(f"    response[0..200]: {r}")
    click.echo(f"\n[alphas: {len(alphas)}]")
    for a in alphas:
        click.echo(f"  {a['alpha_id']:<12} status={a['status']:<10} sharpe={a['sharpe']} fitness={a['fitness']} sc={a['sc_value']}")
    click.echo(f"\n[submission_queue: {len(queue)}]")
    for q in queue:
        click.echo(f"  {q['alpha_id']:<12} status={q['status']} sc={q['sc_value']} note={q.get('note','')}")


@cli.command("emit")
@click.argument("topic")
@click.option("--json", "json_payload", default="{}", help='Payload as JSON string, e.g. \'{"n":3}\'.')
@click.option("--wait/--no-wait", default=True, help="Wait for handlers to drain before exiting.")
@click.option("--timeout", default=600, type=int)
@click.pass_context
def emit_cmd(ctx, topic, json_payload, wait, timeout):
    """Emit an arbitrary event onto the bus.

    Examples:
        wqbus emit GENERATE_REQUESTED --json '{"n":3,"hint":"low turnover"}'
        wqbus emit QUEUE_FLUSH_REQUESTED
        wqbus emit BATCH_DONE --json '{"batch_id":"manual","total":10,"is_passed":2}'
        wqbus emit CRAWL_REQUESTED --json '{"target":"arxiv_quant"}'
    """
    import json as _json
    asyncio.run(_emit_main(ctx.obj, topic, _json.loads(json_payload), wait, timeout))


async def _emit_main(opts, topic, payload, wait, timeout):
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.bus.events import Topic, make_event
    bus = get_bus()
    dispatcher = _build_dispatcher(opts["model"], opts["depth"], opts["dry_run"])
    brain = _build_brain_client()
    if not opts["dry_run"] and topic in {"QUEUE_FLUSH_REQUESTED", "ALPHA_DRAFTED", "IS_PASSED"}:
        if not brain.check_auth():
            click.echo("WARN: BRAIN session invalid — submit/simulate will fail.", err=True)
    _wire_agents(bus, dispatcher, brain)

    try:
        topic_enum = Topic(topic.upper())
    except ValueError:
        click.echo(f"Unknown topic: {topic}. Valid: {[t.value for t in Topic]}", err=True)
        sys.exit(2)

    with with_tag(opts["dataset"]):
        ev = make_event(topic_enum, opts["dataset"], **payload)
        click.echo(f"emit {topic_enum.value} trace={ev.trace_id} payload={payload}")
        bus.emit(ev)
        if wait:
            await bus.drain(timeout=timeout)
    click.echo("done")


@cli.command("resume")
@click.option("--max-events", default=200, type=int,
              help="Cap on synthetic events emitted in this catchup.")
@click.pass_context
def resume_cmd(ctx, max_events):
    """Scan DBs and re-emit events for stuck/pending work without spending AI.

    Catchup rules (idempotent — safe to run anytime):
      • IS-eligible alphas not yet in queue   → emit IS_PASSED   (re-runs SC checker)
      • Pending submission_queue rows         → emit QUEUE_FLUSH_REQUESTED (1x)
      • crawl_docs.summarized='pending' >= threshold → emit DOC_FETCHED  (wakes summarizer)

    Does NOT generate new alphas (that costs AI; use `wqbus generate`).
    """
    asyncio.run(_resume_main(ctx.obj, max_events))


async def _resume_main(opts, max_events):
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.bus.events import Topic, make_event
    from wq_bus.data import knowledge_db, state_db
    from wq_bus.data._sqlite import open_knowledge, ensure_migrated
    ensure_migrated()

    bus = get_bus()
    dispatcher = _build_dispatcher(opts["model"], opts["depth"], opts["dry_run"])
    brain = _build_brain_client()
    _wire_agents(bus, dispatcher, brain)

    n_emitted = 0
    with with_tag(opts["dataset"]):
        # 1) Re-run SC for IS-eligible alphas that have neither sc_value nor a queue row.
        with open_knowledge() as conn:
            rows = conn.execute(
                """SELECT alpha_id, expression, settings_json FROM alphas
                   WHERE dataset_tag=? AND status IN ('is_passed','simulated')
                     AND sharpe>=1.25 AND fitness>=1.0
                     AND turnover BETWEEN 0.01 AND 0.7
                     AND alpha_id NOT IN (
                         SELECT alpha_id FROM alphas WHERE dataset_tag=? AND status='submitted'
                     )
                   LIMIT ?""", (opts["dataset"], opts["dataset"], max_events)
            ).fetchall()
        for r in rows:
            ev = make_event(Topic.IS_PASSED, opts["dataset"],
                            alpha_id=r["alpha_id"],
                            alpha_record={"id": r["alpha_id"], "is": {}},
                            source="resume")
            bus.emit(ev); n_emitted += 1
        click.echo(f"[resume] re-emitted IS_PASSED for {len(rows)} eligible alphas")

        # 2) Wake the queue if it has pending rows.
        pending_q = state_db.queue_size("pending")
        if pending_q > 0:
            bus.emit(make_event(Topic.QUEUE_FLUSH_REQUESTED, opts["dataset"], source="resume"))
            n_emitted += 1
            click.echo(f"[resume] queue has {pending_q} pending → emitted QUEUE_FLUSH_REQUESTED")

        # NOTE: doc summarizer self-loop removed — use `wqbus drain-docs` instead.
        await bus.drain(timeout=900)
    click.echo(f"[resume] done. {n_emitted} synthetic events emitted.")


@cli.command("daemon")
@click.option("--idle-secs", default=60, type=int, help="Idle poll interval (only used to print heartbeat).")
@click.option("--auto-resume/--no-auto-resume", default=True,
              help="Run resume() once at startup to pick up stuck work.")
@click.option("--auto-gen/--no-auto-gen", default=True,
              help="When queue empty AND no recent batches, auto-emit GENERATE_REQUESTED.")
@click.option("--auto-gen-n", default=4, type=int, help="Batch size for auto-gen.")
@click.option("--auto-gen-idle-secs", default=900, type=int,
              help="Trigger auto-gen if no BATCH_DONE seen for this many seconds.")
@click.option("--target-submitted", default=4, type=int,
              help="Stop auto-gen once today's submitted count reaches this.")
@click.pass_context
def daemon_cmd(ctx, idle_secs, auto_resume, auto_gen, auto_gen_n,
               auto_gen_idle_secs, target_submitted):
    """Run as a long-lived bus daemon: register agents, optionally resume,
    then idle and let the bus react to incoming events. Press Ctrl-C to stop.

    Compose with `wqbus emit ...` from another terminal to drive it.
    """
    asyncio.run(_daemon_main(ctx.obj, idle_secs, auto_resume,
                             auto_gen, auto_gen_n, auto_gen_idle_secs, target_submitted))


async def _daemon_main(opts, idle_secs, auto_resume, auto_gen, auto_gen_n,
                       auto_gen_idle_secs, target_submitted):
    import signal
    import time as _time
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.bus.events import Topic, make_event
    from wq_bus.data import state_db
    from wq_bus.data._sqlite import open_state, open_knowledge
    bus = get_bus()
    dispatcher = _build_dispatcher(opts["model"], opts["depth"], opts["dry_run"])
    brain = _build_brain_client()
    _wire_agents(bus, dispatcher, brain)

    if auto_resume:
        click.echo("[daemon] running resume() at startup...")
        try:
            await _resume_main(opts, max_events=200)
        except Exception as e:
            click.echo(f"[daemon] resume failed (non-fatal): {e}", err=True)

    click.echo(f"[daemon] idle, waiting for events (Ctrl-C to stop). dataset={opts['dataset']}")
    stop = asyncio.Event()
    paused = {"v": False}
    def _on_signal(*_): stop.set()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try: loop.add_signal_handler(sig, _on_signal)
            except (NotImplementedError, RuntimeError): pass  # Windows
    except Exception: pass

    last_autogen_ts = 0.0
    autogen_cooldown = max(auto_gen_idle_secs, 300)

    def _today_submitted_count() -> int:
        cutoff = _time.time() - 86400
        with open_knowledge() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) AS n FROM alphas WHERE status='submitted' "
                "AND dataset_tag=? AND updated_at >= ?",
                (opts["dataset"], cutoff),
            ).fetchone()["n"])

    def _last_event_age(topic_name: str) -> float:
        with open_state() as conn:
            row = conn.execute(
                "SELECT MAX(ts) AS t FROM events WHERE topic=? AND dataset_tag=?",
                (topic_name, opts["dataset"]),
            ).fetchone()
        if not row or not row["t"]:
            return float("inf")
        return _time.time() - float(row["t"])

    with with_tag(opts["dataset"]):
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=idle_secs)
            except asyncio.TimeoutError:
                qp = state_db.queue_size("pending")
                ai_today = state_db.count_ai_calls_today()
                sub_today = _today_submitted_count()
                click.echo(f"[daemon] tick: queue_pending={qp} ai_today={ai_today} "
                           f"submitted_today={sub_today}/{target_submitted} "
                           f"paused={paused['v']}")

                if paused["v"]:
                    continue
                if qp > 0:
                    # Safety-net: queue has work but nothing flushed it yet.
                    since_flush = _last_event_age("QUEUE_FLUSH_REQUESTED")
                    if since_flush > idle_secs * 2:
                        click.echo(f"[daemon] queue={qp} & no flush in {since_flush:.0f}s → emit QUEUE_FLUSH_REQUESTED")
                        bus.emit(make_event(Topic.QUEUE_FLUSH_REQUESTED, opts["dataset"],
                                            source="daemon_watchdog"))
                    continue  # whether we just emitted or not, give submitter time
                if not auto_gen:
                    continue
                if sub_today >= target_submitted:
                    continue
                since_batch = _last_event_age("BATCH_DONE")
                since_gen = _last_event_age("GENERATE_REQUESTED")
                if since_batch < auto_gen_idle_secs and since_gen < auto_gen_idle_secs:
                    continue  # recent activity, give it time
                if _time.time() - last_autogen_ts < autogen_cooldown:
                    continue  # cooldown
                click.echo(f"[daemon] queue empty + idle {since_batch:.0f}s → auto-gen n={auto_gen_n}")
                bus.emit(make_event(Topic.GENERATE_REQUESTED, opts["dataset"],
                                    n=auto_gen_n, hint="daemon_auto", source="daemon"))
                last_autogen_ts = _time.time()
    click.echo("[daemon] shutting down")


# ---------- admin ----------

@cli.group("admin")
def admin_grp():
    """Admin / maintenance commands."""


@admin_grp.command("reset-ai-cap")
@click.option("--hours", default=25, type=int, help="Backdate today's ai_calls by this many hours.")
@click.option("--agent", default=None, help="Only reset for a specific agent_type.")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def admin_reset_cap(hours, agent, yes):
    """Backdate recent ai_calls so the rolling 24h daily cap clears.

    Useful when you've maxed out the daily cap during testing. The records are
    preserved (for trace/debug), only their timestamps move back.
    """
    import time as _time
    from wq_bus.data._sqlite import open_state, ensure_migrated
    ensure_migrated()
    cutoff = _time.time() - 86400
    sql = "SELECT COUNT(*) AS n FROM ai_calls WHERE ts >= ?"
    params: list = [cutoff]
    if agent:
        sql += " AND agent_type=?"; params.append(agent)
    with open_state() as conn:
        n = int(conn.execute(sql, params).fetchone()["n"])
    if n == 0:
        click.echo("nothing to reset (no ai_calls in last 24h)"); return
    if not yes:
        click.confirm(f"Backdate {n} ai_call rows by {hours}h?", abort=True)
    delta = hours * 3600
    upd = "UPDATE ai_calls SET ts = ts - ? WHERE ts >= ?"
    upd_params: list = [delta, cutoff]
    if agent:
        upd += " AND agent_type=?"; upd_params.append(agent)
    with open_state() as conn:
        conn.execute(upd, upd_params); conn.commit()
    click.echo(f"reset {n} ai_call rows (backdated {hours}h). Daily cap cleared.")


@admin_grp.command("status")
@click.pass_context
def admin_status(ctx):
    """One-shot snapshot: queue, today's AI usage, recent traces, eligible alphas."""
    import time as _time
    from wq_bus.data._sqlite import open_state, open_knowledge, ensure_migrated
    from wq_bus.data import state_db, knowledge_db
    ensure_migrated()
    tag = ctx.obj["dataset"]

    with with_tag(tag):
        click.echo(f"=== wqbus status (dataset={tag}) ===")
        click.echo(f"queue_pending: {state_db.queue_size('pending')}")
        click.echo(f"queue_failed:  {state_db.queue_size('failed')}")
        click.echo(f"ai_today_total: {state_db.count_ai_calls_today()}")
        for ag in ("alpha_gen", "failure_analyzer", "doc_summarizer", "portfolio_analyzer"):
            click.echo(f"  ai_today[{ag}]: {state_db.count_ai_calls_today(agent_type=ag)}")
        cutoff = _time.time() - 86400
        with open_knowledge() as conn:
            sub_today = int(conn.execute(
                "SELECT COUNT(*) FROM alphas WHERE status='submitted' AND dataset_tag=? AND updated_at>=?",
                (tag, cutoff),
            ).fetchone()[0])
            eligible = int(conn.execute(
                """SELECT COUNT(*) FROM alphas WHERE dataset_tag=? AND status IN ('is_passed','simulated')
                   AND sharpe>=1.25 AND fitness>=1.0 AND turnover BETWEEN 0.01 AND 0.7
                   AND alpha_id NOT IN (SELECT alpha_id FROM alphas WHERE dataset_tag=? AND status='submitted')""",
                (tag, tag),
            ).fetchone()[0])
            total_sim = int(conn.execute(
                "SELECT COUNT(*) FROM alphas WHERE dataset_tag=? AND status!='draft'", (tag,)
            ).fetchone()[0])
            total_sub = int(conn.execute(
                "SELECT COUNT(*) FROM alphas WHERE dataset_tag=? AND status='submitted'", (tag,)
            ).fetchone()[0])
        click.echo(f"submitted_today: {sub_today}")
        click.echo(f"is_eligible_not_submitted: {eligible}")
        click.echo(f"alphas_total: {total_sim} simulated / {total_sub} submitted")
        click.echo(f"crawl_pending_docs: {len(knowledge_db.list_pending_docs(limit=999))}")
        with open_state() as conn:
            recent = conn.execute(
                """SELECT trace_id, MIN(ts) AS started, COUNT(*) AS n_calls
                   FROM ai_calls WHERE trace_id IS NOT NULL
                   GROUP BY trace_id ORDER BY started DESC LIMIT 5"""
            ).fetchall()
        click.echo("recent_traces:")
        for r in recent:
            ago = int(_time.time() - r["started"])
            click.echo(f"  {r['trace_id']}  {ago}s ago  calls={r['n_calls']}")


@admin_grp.command("submit-eligible")
@click.option("--limit", default=10, type=int)
@click.pass_context
def admin_submit_eligible(ctx, limit):
    """Find IS-eligible alphas not yet submitted, enqueue them, flush.

    Bypasses generation entirely — pure submission catchup."""
    asyncio.run(_resume_main(ctx.obj, max_events=limit))


@cli.command("login")
@click.option("--force", is_flag=True, help="Re-login even if current session looks valid.")
@click.option("--email", default=None, help="Override email (else env / .state/credentials.json).")
@click.option("--password", default=None, help="Override password.")
def login_cmd(force, email, password):
    """Refresh BRAIN session via Basic Auth.

    Reads credentials from (in order): CLI args, env vars WQBRAIN_EMAIL/WQBRAIN_PASSWORD,
    .state/credentials.json. Writes fresh session to .state/session.json.
    """
    from wq_bus.brain.auth import (
        ensure_session, login_with_credentials, session_is_valid, _read_credentials,
    )
    if email and password:
        ok = login_with_credentials(email, password)
        click.echo("OK" if ok else "FAILED")
        sys.exit(0 if ok else 1)
    if not force and session_is_valid():
        click.echo("session already valid (use --force to relogin)"); return
    creds = _read_credentials()
    if not creds:
        click.echo("no credentials in env or .state/credentials.json", err=True); sys.exit(2)
    if ensure_session(force=True):
        click.echo("OK — session refreshed")
    else:
        click.echo("FAILED — login rejected", err=True); sys.exit(1)


@cli.command("datafields")
@click.option("--refresh", is_flag=True, help="Force-refresh from /search/datafields.")
@click.option("--region", default=None)
@click.option("--universe", default=None)
@click.option("--delay", default=None, type=int)
@click.pass_context
def datafields_cmd(ctx, refresh, region, universe, delay):
    """Fetch and cache the dataset's data fields catalog (used by alpha_gen prompts).

    Cached at data/datafields_<dataset_tag>.json. Re-run with --refresh to update.
    """
    import json as _json
    import time as _time
    tag = ctx.obj["dataset"]
    out_path = Path("data") / f"datafields_{tag}.json"
    if out_path.exists() and not refresh:
        data = _json.loads(out_path.read_text(encoding="utf-8"))
        click.echo(f"cached: {out_path} ({data.get('count', '?')} fields, "
                   f"age={int(_time.time() - data.get('fetched_at', 0))}s)")
        return
    from wq_bus.utils.yaml_loader import load_yaml
    ds = load_yaml("datasets")
    entry = next((e for e in ds.get("datasets", []) if isinstance(e, dict) and e.get("tag") == tag), {})
    region = region or entry.get("region", "USA")
    universe = universe or entry.get("universe", "TOP3000")
    delay = delay if delay is not None else int(entry.get("delay", 1))
    brain = _build_brain_client()
    if not brain.check_auth():
        click.echo("ERROR: session invalid (run `wqbus login`)", err=True); sys.exit(2)
    all_fields: list[dict] = []
    offset = 0
    while True:
        params = {
            "instrumentType": "EQUITY", "region": region, "universe": universe,
            "delay": delay, "limit": 50, "offset": offset,
        }
        try:
            r = brain.session.get(f"{brain.session_base()}/data-fields"
                                  if hasattr(brain, "session_base") else
                                  "https://api.worldquantbrain.com/data-fields",
                                  headers={"Accept": "application/json;version=2.0"},
                                  params=params, timeout=30)
        except Exception as e:
            click.echo(f"fetch error: {e}", err=True); break
        if r.status_code != 200:
            click.echo(f"non-200: {r.status_code} {r.text[:200]}", err=True); break
        body = r.json() if r.content else {}
        items = body.get("results") or body.get("items") or (body if isinstance(body, list) else [])
        if not items:
            break
        all_fields.extend(items)
        if len(items) < 50:
            break
        offset += len(items)
        if offset > 5000:
            break  # safety
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset_tag": tag, "region": region, "universe": universe, "delay": delay,
        "fetched_at": _time.time(), "count": len(all_fields), "fields": all_fields,
    }
    out_path.write_text(_json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    click.echo(f"wrote {out_path} ({len(all_fields)} fields)")


@admin_grp.command("sweep-unsubmitted")
@click.option("--limit", default=100, type=int)
@click.pass_context
def admin_sweep_unsubmitted(ctx, limit):
    """Pull recent IS-pass alphas from BRAIN account, store any that aren't in our KB.

    Useful when alphas were generated outside the bus (manual UI / old scripts).
    """
    tag = ctx.obj["dataset"]
    brain = _build_brain_client()
    if not brain.check_auth():
        click.echo("session invalid", err=True); sys.exit(2)
    try:
        user = brain.session.get(
            "https://api.worldquantbrain.com/users/self",
            headers={"Accept": "application/json;version=2.0"}, timeout=15,
        ).json()
        user_id = user.get("id")
    except Exception as e:
        click.echo(f"users/self failed: {e}", err=True); sys.exit(2)
    r = brain.session.get(
        f"https://api.worldquantbrain.com/users/{user_id}/alphas",
        headers={"Accept": "application/json;version=2.0"},
        params={"limit": limit, "stage": "IS"}, timeout=30,
    )
    if r.status_code != 200:
        click.echo(f"list alphas failed {r.status_code}", err=True); sys.exit(2)
    items = (r.json() or {}).get("results", [])
    from wq_bus.data._sqlite import open_knowledge, ensure_migrated
    from wq_bus.data import knowledge_db
    ensure_migrated()
    seen = set()
    with open_knowledge() as conn:
        for row in conn.execute("SELECT alpha_id FROM alphas WHERE dataset_tag=?", (tag,)):
            seen.add(row[0])
    new = 0
    with with_tag(tag):
        for it in items:
            aid = it.get("id")
            if not aid or aid in seen:
                continue
            knowledge_db.upsert_alpha(
                aid,
                (it.get("regular") or {}).get("code", ""),
                it.get("settings") or {},
                "",
                is_metrics=it.get("is"),
                status="simulated",
            )
            new += 1
    click.echo(f"sweep: {len(items)} BRAIN alphas, {new} new added to KB")


# ---------------------------------------------------------------------------
# drain-docs: manual batch-drain doc_summarizer (todo 14)
# ---------------------------------------------------------------------------

@cli.command("drain-docs")
@click.option("--max-batches", default=5, type=int, help="Max batches to process.")
@click.option("--dataset", "dataset_tag", default=None, help="Dataset tag override.")
@click.option("--json", "output_json", is_flag=True, help="Output JSON result.")
@click.pass_context
def drain_docs_cmd(ctx, max_batches, dataset_tag, output_json):
    """Manually drain pending docs through doc_summarizer (no auto-loop)."""
    import json as _json
    tag = dataset_tag or ctx.obj.get("dataset") or _resolve_dataset(None)
    asyncio.run(_drain_docs_main(ctx.obj, tag, max_batches, output_json))


async def _drain_docs_main(opts, tag, max_batches, output_json):
    import json as _json
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.bus.events import Topic, make_event
    from wq_bus.data import knowledge_db
    bus = get_bus()
    dispatcher = _build_dispatcher(opts.get("model"), opts.get("depth"), opts.get("dry_run", False))
    from wq_bus.agents.doc_summarizer import DocSummarizer
    DocSummarizer(bus, dispatcher)

    results = []
    with with_tag(tag):
        for i in range(max_batches):
            pending = knowledge_db.list_pending_docs(limit=999)
            if not pending:
                break
            click.echo(f"[drain-docs] batch {i+1}: {len(pending)} pending docs")
            bus.emit(make_event(Topic.DOC_FETCHED, tag,
                                url_hash=f"drain_batch_{i}", source="drain_docs",
                                title=f"drain batch {i+1}"))
            await bus.drain(timeout=300)
            results.append({"batch": i + 1, "pending_before": len(pending)})

    if output_json:
        click.echo(_json.dumps({"tag": tag, "batches_processed": len(results),
                                "details": results}, indent=2))
    else:
        click.echo(f"[drain-docs] done. {len(results)} batches processed.")


# ---------------------------------------------------------------------------
# task: manual task dispatch (todo 15)
# ---------------------------------------------------------------------------

# Map agent name → business task_kind (for trace.task_kind column).
# A "task_kind" is a business round (alpha_round, doc_summary, health_probe,
# crawl_summary, portfolio_review), NOT an agent name. Multiple agent CLI
# arguments can map to the same kind (e.g., alpha_gen + failure_analyzer +
# sim_executor + submitter all start an alpha_round).
_AGENT_TO_KIND = {
    "alpha_gen":                       "alpha_round",
    "alpha_round":                     "alpha_round",
    "failure_analyzer":                "alpha_round",
    "sim_executor":                    "alpha_round",
    "submitter":                       "alpha_round",
    "doc_summarizer":                  "doc_summary",
    "doc_summarizer.crawl_summary":    "doc_summary",
    "doc_summarizer.recipe_synthesis": "doc_summary",
    "doc_summarizer.failure_synthesis":"doc_summary",
    "doc_summarizer.portfolio_review": "portfolio_review",
    "doc_summary":                     "doc_summary",
    "portfolio_analyzer":              "portfolio_review",
    "portfolio_review":                "portfolio_review",
    "api_healthcheck":                 "health_probe",
    "health":                          "health_probe",
    "health_probe":                    "health_probe",
    "crawler":                         "crawl_summary",
    "crawl_summary":                   "crawl_summary",
}


def _kind_for_agent(agent: str) -> str:
    return _AGENT_TO_KIND.get(agent.lower(), agent.lower())


def _instantiate_agents_for(agent: str, bus) -> list:
    """Instantiate the agent(s) needed to handle a manual `wqbus task` trigger.

    For chain-style kinds (alpha_round) we wire the *full* chain so the round
    can iterate naturally (failure_analyzer → alpha_gen → sim_executor →
    submitter) without missing handlers. For doc_summarizer we only need the
    DocSummarizer itself.

    Returns the list of instantiated agents (kept alive until drain finishes).
    """
    a = agent.lower()
    out = []
    try:
        from wq_bus.brain.client import BrainClient
    except Exception as e:
        click.echo(f"warn: BrainClient init failed: {e}", err=True)
        BrainClient = None  # type: ignore
    try:
        from wq_bus.ai.dispatcher import Dispatcher
        disp = Dispatcher()
    except Exception as e:
        click.echo(f"warn: Dispatcher init failed: {e}", err=True)
        disp = None

    def _try(label, fn):
        try:
            out.append(fn())
        except Exception as e:
            click.echo(f"warn: {label} init failed: {e}", err=True)

    if a in ("alpha_gen", "alpha_round", "failure_analyzer", "sim_executor",
             "submitter"):
        # Full alpha_round chain so a manual trigger drives end-to-end.
        from wq_bus.agents.alpha_gen import AlphaGen
        from wq_bus.agents.sim_executor import SimExecutor
        from wq_bus.agents.submitter import Submitter
        from wq_bus.agents.failure_analyzer import FailureAnalyzer
        if disp is not None:
            _try("AlphaGen", lambda: AlphaGen(bus, disp))
        if BrainClient is not None:
            _try("SimExecutor", lambda: SimExecutor(bus, BrainClient(), dispatcher=disp))
            _try("Submitter", lambda: Submitter(bus, BrainClient()))
        _try("FailureAnalyzer", lambda: FailureAnalyzer(bus, disp))
    elif a.startswith("doc_summarizer") or a == "doc_summary":
        from wq_bus.agents.doc_summarizer import DocSummarizer
        if disp is not None:
            _try("DocSummarizer", lambda: DocSummarizer(bus, disp))
    elif a in ("portfolio_analyzer", "portfolio_review"):
        from wq_bus.agents.portfolio_analyzer import PortfolioAnalyzer
        if BrainClient is not None:
            _try("PortfolioAnalyzer", lambda: PortfolioAnalyzer(bus, BrainClient()))
    return out


# Map agent name → (topic_to_emit, default_payload_builder).
# Each builder receives (mode, url, goal, summarize, n) and returns a payload
# dict that satisfies the required fields for that topic. Agents listening to
# the topic will then execute as if the trigger came from the watchdog/bus.
def _task_topic_for(agent: str, mode: str, *, url=None, goal=None,
                     summarize=False, n=4) -> tuple[str, dict]:
    """Return (topic, payload) for `wqbus task <agent>`.

    Raises click.ClickException for unknown agents.
    """
    a = agent.lower()
    if a in ("alpha_gen", "alpha_round"):
        return ("GENERATE_REQUESTED",
                {"mode": mode, "n": int(n), "hint": goal or ""})
    if a == "failure_analyzer":
        # Drives the failure_synthesis loop via the BATCH_DONE topic.
        return ("BATCH_DONE",
                {"n_total": 0, "n_is_passed": 0, "manual": True})
    if a in ("doc_summarizer", "doc_summarizer.crawl_summary"):
        return ("DOC_FETCHED",
                {"url_hash": f"manual_{int(__import__('time').time())}",
                 "source": "manual_cli", "title": goal or "manual trigger",
                 "url": url})
    if a == "doc_summarizer.recipe_synthesis":
        return ("RECIPE_CANDIDATES_READY",
                {"out_path": url or "", "n_groups": int(n)})
    if a == "doc_summarizer.failure_synthesis":
        return ("FAILURE_BATCH_READY", {"manual": True})
    if a == "doc_summarizer.portfolio_review":
        return ("POOL_STATS_UPDATED",
                {"manual": True, "total_directions": 0, "new_directions": 0})
    if a == "portfolio_analyzer":
        # SUBMITTED triggers a counter — manual analyze_now() call instead.
        return ("__direct_analyze_now__", {})
    if a == "submitter":
        return ("QUEUE_FLUSH_REQUESTED", {})
    if a == "sim_executor":
        # Needs an actual ALPHA_DRAFTED with expression — require --goal
        if not goal:
            raise click.ClickException("sim_executor task requires --goal '<expression>'")
        return ("ALPHA_DRAFTED",
                {"alpha_id": f"draft_manual_{int(__import__('time').time())}",
                 "expression": goal, "settings": {}})
    if a in ("api_healthcheck", "health", "health_probe"):
        # Direct one-shot probe; topic emitted by the agent itself.
        return ("__direct_health_probe__", {"kind": mode if mode in ("auth","simulate","untested_alpha") else "auth"})
    raise click.ClickException(
        f"unknown agent '{agent}'. Supported: alpha_gen|alpha_round, failure_analyzer, "
        "doc_summarizer[.crawl_summary|.recipe_synthesis|.failure_synthesis|"
        ".portfolio_review], portfolio_analyzer, submitter, sim_executor, "
        "api_healthcheck|health|health_probe"
    )


@cli.command("task")
@click.argument("agent")
@click.option("--mode", "-m", default="explore", help="Agent mode (alpha_gen: explore|specialize|review_failure|track_news).")
@click.option("--dataset", "dataset_tag", default=None, help="Dataset tag.")
@click.option("--url", default=None, help="URL hint (crawl/recipe candidate file).")
@click.option("--goal", default=None, help="Free-form goal / expression / hint.")
@click.option("--summarize", is_flag=True, help="Set summarize=true in payload.")
@click.option("-n", "n", default=4, type=int, help="Batch size hint (alpha_gen N expressions).")
@click.option("--json", "output_json", is_flag=True, help="Output trace_id as JSON.")
@click.pass_context
def task_cmd(ctx, agent, mode, dataset_tag, url, goal, summarize, n, output_json):
    """Dispatch a manual task to an agent.

    Internally:
        1. Resolves agent → trigger topic + payload.
        2. start_task() writes a trace row (origin='manual_cli') and emits
           TASK_STARTED for traceability.
        3. Emits the actual trigger topic so the agent's handler fires
           inheriting the same trace_id.

    Examples:
        wqbus task alpha_gen --mode explore --dataset USA_TOP3000 -n 4
        wqbus task failure_analyzer --dataset USA_TOP3000
        wqbus task doc_summarizer.failure_synthesis --dataset USA_TOP3000
        wqbus task submitter --dataset USA_TOP3000
    """
    import asyncio
    import json as _json
    tag = dataset_tag or ctx.obj.get("dataset")
    if not tag:
        try:
            from wq_bus.utils.yaml_loader import load_yaml
            user_cfg = load_yaml("user") or {}
            tag = user_cfg.get("default_dataset")
        except Exception:
            pass
    if not tag:
        click.echo("ERROR: --dataset TAG required (or set default_dataset in config/user.yaml)",
                   err=True)
        sys.exit(2)

    topic, base_payload = _task_topic_for(agent, mode, url=url, goal=goal,
                                          summarize=summarize, n=n)
    if summarize:
        base_payload["summarize"] = True
    if goal and "hint" not in base_payload and "goal" not in base_payload:
        base_payload["goal"] = goal

    from wq_bus.bus.tasks import start_task
    from wq_bus.bus.events import make_event
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.utils.tag_context import with_trace

    with with_tag(tag):
        kind = _kind_for_agent(agent)
        handle = start_task(kind=kind,
                            payload={"agent": agent, "mode": mode, **base_payload},
                            origin="manual_cli", dataset_tag=tag)

        # For agents that need a direct method call (no bus topic exists),
        # do it inline so manual triggers still work.
        if topic == "__direct_analyze_now__":
            try:
                from wq_bus.brain.client import BrainClient
                from wq_bus.agents.portfolio_analyzer import PortfolioAnalyzer
                from wq_bus.bus.tasks import complete_task, fail_task
                bus = get_bus()
                pa = PortfolioAnalyzer(bus, BrainClient())
                with with_trace(handle.trace_id):
                    asyncio.run(pa.analyze_now(tag))
                complete_task(handle.trace_id, {"agent": "portfolio_analyzer"})
            except Exception as e:
                from wq_bus.bus.tasks import fail_task
                fail_task(handle.trace_id, e)
                click.echo(f"ERROR: portfolio_analyzer.analyze_now failed: {e}", err=True)
                sys.exit(1)
        elif topic == "__direct_health_probe__":
            try:
                from wq_bus.brain.client import BrainClient
                from wq_bus.agents.api_healthcheck import ApiHealthCheck
                from wq_bus.bus.tasks import complete_task
                bus = get_bus()
                hc = ApiHealthCheck(bus, BrainClient(), dataset_tag=tag,
                                    probe_kind=base_payload.get("kind", "auth"))
                with with_trace(handle.trace_id):
                    res = asyncio.run(hc.probe_once())
                click.echo(_json.dumps(res))
                complete_task(handle.trace_id, {"agent": "api_healthcheck", "result": res})
            except Exception as e:
                from wq_bus.bus.tasks import fail_task
                fail_task(handle.trace_id, e)
                click.echo(f"ERROR: api_healthcheck probe failed: {e}", err=True)
                sys.exit(1)
        else:
            # Instantiate the agent(s) so the trigger event has a handler.
            # Without this, emit() would find 0 handlers and the deferred
            # auto-close would still close the trace immediately.
            bus = get_bus()
            _instantiated = _instantiate_agents_for(agent, bus)
            ev = make_event(topic, tag, trace_id=handle.trace_id, **base_payload)
            with with_trace(handle.trace_id):
                async def _emit_and_drain():
                    bus.emit(ev)
                    try:
                        await bus.drain(timeout=180)
                    except Exception as e:
                        click.echo(f"warn: drain failed: {e}", err=True)
                asyncio.run(_emit_and_drain())

    if output_json:
        click.echo(_json.dumps({"trace_id": handle.trace_id, "agent": agent,
                                "topic": topic, "mode": mode, "dataset_tag": tag}))
    else:
        click.echo(f"task started: trace_id={handle.trace_id} agent={agent} "
                   f"topic={topic} mode={mode} tag={tag}")


# ---------------------------------------------------------------------------
# health: long-running BRAIN API watchdog (todo healthcheck-cli)
# ---------------------------------------------------------------------------

@cli.command("health")
@click.option("--dataset", "dataset_tag", default=None, help="Dataset tag (or default_dataset).")
@click.option("--interval", default=60.0, type=float, help="Probe interval seconds (default 60).")
@click.option("--kind", type=click.Choice(["auth", "simulate", "untested_alpha"]),
              default="auth", help="Probe kind. 'auth' is cheapest; 'simulate' exercises sim path; "
                                   "'untested_alpha' picks a queued/drafted alpha and runs get_alpha.")
@click.option("--probe-expr", default=None, help="Override probe expression (kind=simulate).")
@click.option("--window-size", default=5, type=int, help="Rolling window size in samples (default 5).")
@click.option("--failure-threshold", default=0.5, type=float,
              help="Failure rate (0..1) at which to emit RATE_PRESSURE (default 0.5).")
@click.option("--spawn-round/--no-spawn-round", default=False,
              help="Spawn a child alpha_round task on every successful probe (default OFF).")
@click.option("--spawn-n", default=5, type=int,
              help="n value for the spawned alpha_round (default 5).")
@click.option("--spawn-mode", default="explore",
              help="Mode for the spawned alpha_round (explore/specialize/...; default explore).")
@click.option("--once", is_flag=True, help="Run a single probe then exit (no loop).")
@click.option("--with-agents", is_flag=True,
              help="Also instantiate alpha_gen/sim_executor/submitter so spawned "
                   "alpha_round traces actually run end-to-end in this same process.")
@click.pass_context
def health_cmd(ctx, dataset_tag, interval, kind, probe_expr, window_size,
               failure_threshold, spawn_round, spawn_n, spawn_mode, once, with_agents):
    """Run the BRAIN API health-check watchdog.

    Each probe runs inside its own ``health_probe`` trace. With ``--spawn-round``
    every successful probe additionally creates a child ``alpha_round`` trace
    (parent_trace_id = the probe trace) and emits GENERATE_REQUESTED under it,
    giving you a clean parent→child trace tree visible in ``wqbus trace-tree``.

    On rolling failure-rate breach the agent emits ``RATE_PRESSURE`` so
    sim_executor halves its concurrency window. Agents are NOT gated via
    topic subscriptions — coordination is via the trace tree, not topic flags.

    Examples:
        wqbus health --dataset USA_TOP3000                          # default loop
        wqbus health --dataset USA_TOP3000 --once                   # one-shot probe
        wqbus health --dataset USA_TOP3000 --kind simulate --interval 30
        wqbus health --dataset USA_TOP3000 --spawn-round --with-agents
        wqbus health --dataset USA_TOP3000 --kind untested_alpha
    """
    import asyncio as _aio
    from wq_bus.brain.client import BrainClient
    from wq_bus.bus.event_bus import get_bus
    from wq_bus.agents.api_healthcheck import ApiHealthCheck

    tag = dataset_tag or ctx.obj.get("dataset")
    if not tag:
        try:
            from wq_bus.utils.yaml_loader import load_yaml
            user_cfg = load_yaml("user") or {}
            tag = user_cfg.get("default_dataset")
        except Exception:
            pass
    if not tag:
        click.echo("ERROR: --dataset TAG required", err=True)
        sys.exit(2)

    bus = get_bus()
    extra_agents = []
    if with_agents:
        from wq_bus.ai.dispatcher import Dispatcher
        from wq_bus.agents.alpha_gen import AlphaGen
        from wq_bus.agents.sim_executor import SimExecutor
        from wq_bus.agents.submitter import Submitter
        disp = Dispatcher()
        try:
            extra_agents.append(AlphaGen(bus, disp))
        except Exception as e:
            click.echo(f"warn: AlphaGen init failed: {e}", err=True)
        try:
            extra_agents.append(SimExecutor(bus, BrainClient(), dispatcher=disp))
        except Exception as e:
            click.echo(f"warn: SimExecutor init failed: {e}", err=True)
        try:
            extra_agents.append(Submitter(bus, BrainClient()))
        except Exception as e:
            click.echo(f"warn: Submitter init failed: {e}", err=True)

    hc = ApiHealthCheck(
        bus, BrainClient(),
        dataset_tag=tag,
        probe_kind=kind,
        probe_expr=probe_expr,
        interval_secs=interval,
        window_size=window_size,
        failure_threshold=failure_threshold,
        spawn_round=spawn_round,
        spawn_round_n=spawn_n,
        spawn_round_mode=spawn_mode,
    )

    async def _run():
        with with_tag(tag):
            if once:
                res = await hc.run_probe_with_trace()
                click.echo(_json_lib.dumps(res))
                # If we spawned a child alpha_round, drain the bus so the
                # downstream chain (alpha_gen → sim_executor → submitter) actually
                # runs in this same process before we exit.
                if spawn_round and res.get("ok") and with_agents:
                    try:
                        await bus.drain(timeout=120)
                    except Exception as e:
                        click.echo(f"warn: drain failed: {e}", err=True)
                return
            await hc.start()
            click.echo(f"health watchdog running for {tag} (interval={interval}s "
                       f"kind={kind} spawn_round={spawn_round}). Ctrl+C to stop.")
            try:
                while True:
                    await _aio.sleep(3600)
            except _aio.CancelledError:
                pass
            finally:
                await hc.stop()

    import json as _json_lib
    try:
        _aio.run(_run())
    except KeyboardInterrupt:
        click.echo("\nhealth watchdog stopped.")


# ---------------------------------------------------------------------------
# trace tree/recent/alpha subcommands (todo 16)
# ---------------------------------------------------------------------------

@cli.group("trace-tree")
def trace_tree_grp():
    """Trace tree commands — view task + child traces in tree format."""


@trace_tree_grp.command("show")
@click.argument("trace_id")
@click.option("--json", "output_json", is_flag=True)
def trace_tree_show(trace_id, output_json):
    """Show a trace as an indented tree with ai_calls and emitted events."""
    import json as _json
    from wq_bus.data._sqlite import open_state, open_knowledge, ensure_migrated
    ensure_migrated()

    tree = _build_trace_tree(trace_id)
    if output_json:
        click.echo(_json.dumps(tree, indent=2, default=str))
    else:
        _print_trace_tree(tree, indent=0)


@trace_tree_grp.command("recent")
@click.option("--limit", default=10, type=int, help="Max recent traces.")
@click.option("--json", "output_json", is_flag=True)
def trace_tree_recent(limit, output_json):
    """List the most recent traces."""
    import json as _json
    import time as _time
    from wq_bus.data._sqlite import open_state, ensure_migrated
    ensure_migrated()

    with open_state() as conn:
        # Try trace table first (new), fall back to ai_calls
        try:
            rows = conn.execute(
                """SELECT trace_id, task_kind, status, started_at, ended_at, origin
                   FROM trace ORDER BY created_at DESC LIMIT ?""", (limit,)
            ).fetchall()
            traces = [dict(r) for r in rows]
        except Exception:
            rows = conn.execute(
                """SELECT trace_id, MIN(ts) AS started, COUNT(*) AS n_calls,
                          GROUP_CONCAT(DISTINCT agent_type) AS agents
                   FROM ai_calls WHERE trace_id IS NOT NULL
                   GROUP BY trace_id ORDER BY started DESC LIMIT ?""", (limit,)
            ).fetchall()
            traces = [dict(r) for r in rows]

    if output_json:
        click.echo(_json.dumps({"traces": traces, "count": len(traces)}, indent=2, default=str))
    else:
        click.echo(f"{'TRACE_ID':<30} {'KIND':<15} {'STATUS':<12} {'STARTED':<25} ORIGIN")
        for t in traces:
            click.echo(
                f"{t.get('trace_id',''):<30} "
                f"{t.get('task_kind', t.get('agents','')):<15} "
                f"{t.get('status',''):<12} "
                f"{str(t.get('started_at', t.get('started',''))):<25} "
                f"{t.get('origin','')}"
            )


@trace_tree_grp.command("alpha")
@click.argument("alpha_id")
@click.option("--json", "output_json", is_flag=True)
def trace_tree_alpha(alpha_id, output_json):
    """Find the trace for an alpha and display it."""
    import json as _json
    from wq_bus.data._sqlite import open_knowledge, ensure_migrated
    ensure_migrated()

    with open_knowledge() as conn:
        row = conn.execute(
            "SELECT trace_id FROM alphas WHERE alpha_id=? LIMIT 1", (alpha_id,)
        ).fetchone()

    if not row or not row["trace_id"]:
        if output_json:
            click.echo(_json.dumps({"error": f"No trace_id for alpha {alpha_id}"}))
        else:
            click.echo(f"No trace_id found for alpha {alpha_id}", err=True)
        return

    trace_id = row["trace_id"]
    tree = _build_trace_tree(trace_id)
    tree["alpha_id"] = alpha_id

    if output_json:
        click.echo(_json.dumps(tree, indent=2, default=str))
    else:
        click.echo(f"# Trace for alpha {alpha_id}: {trace_id}\n")
        _print_trace_tree(tree, indent=0)


def _build_trace_tree(trace_id: str) -> dict:
    """Build nested trace tree dict."""
    import time as _time
    from wq_bus.data._sqlite import open_state, open_knowledge
    tree: dict = {"trace_id": trace_id}

    with open_state() as conn:
        # Trace row
        try:
            tr = conn.execute(
                "SELECT * FROM trace WHERE trace_id=?", (trace_id,)
            ).fetchone()
            if tr:
                tree["trace"] = dict(tr)
        except Exception:
            pass

        # AI calls
        calls = [dict(r) for r in conn.execute(
            "SELECT id, ts, agent_type, model, success, duration_ms, error, "
            "strength, source, package_id "
            "FROM ai_calls WHERE trace_id=? ORDER BY ts", (trace_id,)
        ).fetchall()]
        tree["ai_calls"] = calls

        # Events
        events = [dict(r) for r in conn.execute(
            "SELECT ts, topic, payload_json FROM events WHERE trace_id=? ORDER BY ts",
            (trace_id,)
        ).fetchall()]
        tree["events"] = events

        # Child traces
        try:
            children_rows = conn.execute(
                "SELECT trace_id FROM trace WHERE parent_trace_id=?", (trace_id,)
            ).fetchall()
            children = [_build_trace_tree(r["trace_id"]) for r in children_rows]
            tree["children"] = children
        except Exception:
            tree["children"] = []

    # Alphas linked to this trace
    try:
        with open_knowledge() as conn:
            alphas = [dict(r) for r in conn.execute(
                "SELECT alpha_id, status, sharpe, fitness, turnover, direction_id, themes_csv "
                "FROM alphas WHERE trace_id=?", (trace_id,)
            ).fetchall()]
        tree["alphas"] = alphas
    except Exception:
        tree["alphas"] = []

    return tree


def _print_trace_tree(tree: dict, indent: int) -> None:
    prefix = "  " * indent
    tr = tree.get("trace") or {}
    trace_id = tree.get("trace_id", "?")
    kind = tr.get("task_kind", "")
    status = tr.get("status", "")
    click.echo(f"{prefix}[trace] {trace_id}  kind={kind} status={status}")
    for evt in tree.get("events", []):
        import json as _j
        pl = (evt.get("payload_json") or "")[:80]
        click.echo(f"{prefix}  [event] {evt.get('topic',''):<22} {pl}")
    for call in tree.get("ai_calls", []):
        click.echo(f"{prefix}  [ai_call] agent={call.get('agent_type','')} "
                   f"model={call.get('model','')} success={call.get('success','')} "
                   f"dur={call.get('duration_ms','')}ms")
    for alpha in tree.get("alphas", []):
        click.echo(f"{prefix}  [alpha] {alpha.get('alpha_id','')} "
                   f"status={alpha.get('status','')} sharpe={alpha.get('sharpe','')} "
                   f"dir={alpha.get('direction_id','')}")
    for child in tree.get("children", []):
        _print_trace_tree(child, indent + 1)


# ---------------------------------------------------------------------------
# db: database management commands (todo 20)
# ---------------------------------------------------------------------------

@cli.group("db")
def db_grp():
    """Database management commands."""


@db_grp.command("migrate")
@click.option("--json", "output_json", is_flag=True, help="Output JSON result.")
def db_migrate_cmd(output_json):
    """Apply all pending migrations to state.db and knowledge.db.

    Idempotent — safe to run multiple times.
    """
    import json as _json
    from wq_bus.data._sqlite import ensure_migrated, MIGRATION_DIR
    try:
        ensure_migrated()
        mig_files = sorted(MIGRATION_DIR.glob("*.sql"))
        result = {
            "status": "ok",
            "migrations_applied": [f.name for f in mig_files],
            "count": len(mig_files),
        }
        if output_json:
            click.echo(_json.dumps(result, indent=2))
        else:
            click.echo(f"migrations applied: {len(mig_files)} files")
            for f in mig_files:
                click.echo(f"  {f.name}")
    except Exception as e:
        if output_json:
            click.echo(_json.dumps({"status": "error", "error": str(e)}))
        else:
            click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


def main():
    cli(obj={})


# ---------------------------------------------------------------------------
# recipe: recipe management commands (Phase 2 T1-E)
# ---------------------------------------------------------------------------

@cli.group("recipe")
def recipe_grp():
    """Manage composition recipes (list / show / approve / reject / diff / extract)."""


@recipe_grp.command("list")
@click.option("--status", default=None,
              help="Filter by status: approved | proposed | rejected | all")
@click.pass_context
def recipe_list_cmd(ctx, status):
    """List composition recipes."""
    from wq_bus.domain.recipes import list_recipes, ensure_seeds
    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()
    ensure_seeds()
    items = list_recipes(status=status)
    click.echo(f"{'recipe_id':<30} {'status':<10} {'origin':<12} semantic_name")
    click.echo("-" * 80)
    for r in items:
        click.echo(
            f"{r['recipe_id']:<30} {r.get('status','approved'):<10} "
            f"{r.get('origin',''):<12} {r.get('semantic_name','')}"
        )
    click.echo(f"\n{len(items)} recipes")


@recipe_grp.command("show")
@click.argument("recipe_id")
def recipe_show_cmd(recipe_id):
    """Show details of a recipe (including proposed/rejected)."""
    import json as _json
    from wq_bus.domain.recipes import show_recipe, ensure_seeds
    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()
    ensure_seeds()
    r = show_recipe(recipe_id)
    if not r:
        click.echo(f"Recipe not found: {recipe_id}", err=True)
        sys.exit(1)
    click.echo(_json.dumps(r, indent=2, ensure_ascii=False, default=str))


@recipe_grp.command("approve")
@click.argument("recipe_id")
@click.option("--notes", default="", help="Optional approval notes.")
def recipe_approve_cmd(recipe_id, notes):
    """Approve a proposed recipe (status → 'approved')."""
    from wq_bus.domain.recipes import approve_recipe, ensure_seeds, _reload
    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()
    ensure_seeds()
    ok = approve_recipe(recipe_id, reviewed_by="cli", notes=notes)
    if ok:
        click.echo(f"approved: {recipe_id}")
    else:
        click.echo(f"not found: {recipe_id}", err=True)
        sys.exit(1)


@recipe_grp.command("reject")
@click.argument("recipe_id")
@click.option("--reason", required=True, help="Reason for rejection.")
def recipe_reject_cmd(recipe_id, reason):
    """Reject a proposed recipe (status → 'rejected')."""
    from wq_bus.domain.recipes import reject_recipe, ensure_seeds
    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()
    ensure_seeds()
    ok = reject_recipe(recipe_id, reason=reason, reviewed_by="cli")
    if ok:
        click.echo(f"rejected: {recipe_id}")
    else:
        click.echo(f"not found: {recipe_id}", err=True)
        sys.exit(1)


@recipe_grp.command("diff")
@click.argument("recipe_id")
@click.pass_context
def recipe_diff_cmd(ctx, recipe_id):
    """Show how many existing alphas would match this recipe's regex."""
    from wq_bus.domain.recipes import diff_recipe, ensure_seeds
    from wq_bus.data._sqlite import ensure_migrated
    ensure_migrated()
    ensure_seeds()
    tag = ctx.obj.get("dataset")
    result = diff_recipe(recipe_id, dataset_tag=tag)
    if "error" in result:
        click.echo(f"error: {result['error']}", err=True)
        sys.exit(1)
    click.echo(f"recipe_id:     {result['recipe_id']}")
    click.echo(f"pattern_regex: {result['pattern_regex']}")
    click.echo(f"n_matched:     {result['n_matched']}")
    if result["sample_alpha_ids"]:
        click.echo(f"sample_ids:    {result['sample_alpha_ids']}")


@recipe_grp.command("extract")
@click.option("--tag", "dataset_tag", default=None, help="Dataset tag (default: active dataset).")
@click.option("--min-support", default=3, type=int, show_default=True)
@click.option("--status", "statuses", default="simulated,is_passed,submitted",
              show_default=True,
              help="Comma-separated alpha statuses to include (legacy always excluded).")
@click.option("--out", "out_path", default=None,
              help="Output JSON path (default: data/recipe_candidates_<TAG>.json).")
@click.option("--no-emit", is_flag=True, help="Skip emitting RECIPE_CANDIDATES_READY.")
@click.pass_context
def recipe_extract_cmd(ctx, dataset_tag, min_support, statuses, out_path, no_emit):
    """Extract repeated core patterns from alphas and write recipe candidates JSON.

    Emits RECIPE_CANDIDATES_READY on the bus after writing (unless --no-emit).
    """
    tag = dataset_tag or ctx.obj.get("dataset") or _resolve_dataset(None)
    status_list = [s.strip() for s in statuses.split(",") if s.strip()]
    out = Path(out_path) if out_path else None
    from wq_bus.domain.pattern_extractor import run_extract_cli
    from wq_bus.data._sqlite import ensure_migrated
    from wq_bus.utils.tag_context import with_tag
    ensure_migrated()
    with with_tag(tag):
        result = run_extract_cli(
            tag=tag,
            min_support=min_support,
            statuses=status_list,
            out_path=out,
            emit_event=not no_emit,
        )
    click.echo(f"Extracted {len(result)} candidate groups (min_support={min_support}, tag={tag})")


# ---------------------------------------------------------------------------
# `wqbus queue` — submission queue admin (requeue, list, peek dead-letter)
# ---------------------------------------------------------------------------
@cli.group("queue")
def queue_grp():
    """Submission queue admin commands."""


@queue_grp.command("list")
@click.option("--status", default="dead_letter",
              help="Status to list (pending|retry_pending|dead_letter|submitted|failed).")
@click.option("--dataset", "dataset_tag", default=None, help="Override dataset tag.")
def queue_list(status: str, dataset_tag: str | None):
    """List queue items in a given status (default: dead_letter)."""
    from wq_bus.utils.tag_context import with_tag
    from wq_bus.utils.yaml_loader import load_yaml
    from wq_bus.data import state_db
    tag = dataset_tag or (load_yaml("datasets") or {}).get("default_tag", "_global")
    with with_tag(tag):
        rows = state_db.list_queue_by_status(status)
    click.echo(f"=== submission_queue (tag={tag}, status={status}, n={len(rows)}) ===")
    for r in rows:
        click.echo(f"  {r['alpha_id']:<14} retry={r.get('retry_count', 0)} "
                   f"updated={r.get('updated_at', 0):.0f} note={(r.get('note') or '')[:40]} "
                   f"err={(r.get('last_error') or '')[:60]}")


@queue_grp.command("requeue")
@click.argument("alpha_id", required=False)
@click.option("--all-deadletter", is_flag=True,
              help="Requeue every dead_letter item for the dataset.")
@click.option("--reset-retry", is_flag=True,
              help="Also reset retry_count to 0 (defeats dead-letter — use sparingly).")
@click.option("--dataset", "dataset_tag", default=None, help="Override dataset tag.")
def queue_requeue(alpha_id: str | None, all_deadletter: bool,
                  reset_retry: bool, dataset_tag: str | None):
    """Move alpha(s) from dead_letter / failed back to pending.

    Examples:
        wqbus queue requeue ALPHA123
        wqbus queue requeue --all-deadletter --reset-retry
    """
    from wq_bus.utils.tag_context import with_tag
    from wq_bus.utils.yaml_loader import load_yaml
    from wq_bus.data import state_db
    tag = dataset_tag or (load_yaml("datasets") or {}).get("default_tag", "_global")
    if not alpha_id and not all_deadletter:
        click.echo("error: provide ALPHA_ID or --all-deadletter", err=True)
        raise click.Abort()
    with with_tag(tag):
        if all_deadletter:
            items = state_db.list_queue_by_status("dead_letter")
            n = 0
            for it in items:
                if state_db.requeue_alpha(it["alpha_id"], reset_retry=reset_retry):
                    n += 1
            click.echo(f"requeued {n}/{len(items)} dead-letter items (reset_retry={reset_retry})")
        else:
            ok = state_db.requeue_alpha(alpha_id, reset_retry=reset_retry)  # type: ignore[arg-type]
            click.echo(f"{'requeued' if ok else 'NOT FOUND'}: {alpha_id} (reset_retry={reset_retry})")


if __name__ == "__main__":
    main()
