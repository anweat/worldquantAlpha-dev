"""
crawl_orchestrator.py - Iterative WQ platform crawler orchestrator.

Manages crawl state in data/crawl_state.db.
Each run:
  1. Gets N pending URLs from DB
  2. Crawls them (Playwright)
  3. Extracts content + new links
  4. Runs content analysis to extract alpha ideas
  5. Prints summary and any new URLs found

Usage:
  python scripts/crawl_orchestrator.py --seed          # Add seed URLs
  python scripts/crawl_orchestrator.py --round 1       # Run crawl round 1
  python scripts/crawl_orchestrator.py --stats         # Show progress
  python scripts/crawl_orchestrator.py --ideas         # Show top alpha ideas
  python scripts/crawl_orchestrator.py --continuous N  # Run N rounds auto
"""
import sys, json, time, argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wq_crawler import (
    init_db, seed_db, SEED_URLS, get_pending_urls,
    crawl_batch, get_stats, DB_PATH
)
from wq_content_analyzer import analyze_all_crawled, get_top_ideas


def run_round(round_num: int, batch_size: int = 8, max_depth: int = 4) -> dict:
    """Single crawl round."""
    print(f"\n{'='*60}")
    print(f"CRAWL ROUND {round_num} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    pending = get_pending_urls(limit=batch_size, max_depth=max_depth)
    if not pending:
        print("No pending URLs to crawl.")
        return {"round": round_num, "crawled": 0, "new_urls": 0}

    print(f"Crawling {len(pending)} URLs (depth ≤ {max_depth}):")
    for u in pending:
        print(f"  {u[:80]}")

    results = crawl_batch(pending)

    # Extract alpha ideas from newly crawled pages
    print("\nExtracting alpha ideas from new content...")
    ideas = analyze_all_crawled()

    stats = get_stats()
    print(f"\nCrawl DB stats: {json.dumps(stats, indent=2)}")
    print(f"Alpha ideas extracted this round: {len(ideas)}")

    return {
        "round": round_num,
        "crawled": len(results["crawled"]),
        "new_urls": len(results["new_urls"]),
        "errors": len(results["errors"]),
        "total_ideas": stats.get("alpha_ideas", 0),
        "db_stats": stats,
    }


def show_ideas(limit: int = 30):
    ideas = get_top_ideas(limit)
    print(f"\nTop {len(ideas)} Alpha Ideas (by priority):")
    print(f"{'#':>3} {'Pri':>3} {'Type':<20} {'Expression/Description':<60}")
    print("-" * 90)
    for i, idea in enumerate(ideas, 1):
        display = idea["expression"] or idea["description"][:60]
        print(f"{i:>3} [{idea['priority']:>2}] {idea['idea_type']:<20} {display[:60]}")


def show_stats():
    stats = get_stats()
    print("\n=== Crawl Progress ===")
    print(f"  Pending: {stats.get('pending', 0)}")
    print(f"  Done:    {stats.get('done', 0)}")
    print(f"  Error:   {stats.get('error', 0)}")
    print(f"  Total links discovered: {stats.get('total_links', 0)}")
    print(f"  Alpha ideas extracted:  {stats.get('alpha_ideas', 0)}")


def run_continuous(rounds: int, batch_size: int = 8, delay_sec: int = 5):
    """Run multiple crawl rounds until done or max rounds reached."""
    history = []
    for r in range(1, rounds + 1):
        result = run_round(r, batch_size=batch_size)
        history.append(result)
        if result["crawled"] == 0:
            print(f"\nNo more URLs to crawl. Stopping after round {r}.")
            break
        if r < rounds:
            print(f"\nWaiting {delay_sec}s before round {r+1}...")
            time.sleep(delay_sec)

    # Save history
    out = ROOT / "data" / "crawl_history.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"\nCrawl history saved to {out}")
    show_stats()
    show_ideas(20)
    return history


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WQ Platform Crawler Orchestrator")
    parser.add_argument("--seed", action="store_true", help="Seed DB with initial URLs")
    parser.add_argument("--round", type=int, help="Run a single crawl round N")
    parser.add_argument("--continuous", type=int, metavar="N", help="Run N continuous rounds")
    parser.add_argument("--stats", action="store_true", help="Show crawl stats")
    parser.add_argument("--ideas", type=int, default=30, metavar="N", help="Show top N alpha ideas")
    parser.add_argument("--batch-size", type=int, default=8, help="URLs per round")
    parser.add_argument("--max-depth", type=int, default=4, help="Max crawl depth")
    args = parser.parse_args()

    conn = init_db()

    if args.seed:
        seed_db(conn, SEED_URLS)
        print(f"Seeded {len(SEED_URLS)} URLs")

    conn.close()

    if args.stats:
        show_stats()

    if args.round is not None:
        run_round(args.round, batch_size=args.batch_size, max_depth=args.max_depth)
        show_stats()

    if args.continuous:
        run_continuous(args.continuous, batch_size=args.batch_size)

    if args.ideas and not args.round and not args.continuous:
        show_ideas(args.ideas)
