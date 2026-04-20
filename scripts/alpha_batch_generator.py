"""
alpha_batch_generator.py - Generate and test alpha expressions in batches of 2000.

Usage:
  python scripts/alpha_batch_generator.py --batch 1 --count 2000
  python scripts/alpha_batch_generator.py --ideas   (use extracted ideas from DB)
  python scripts/alpha_batch_generator.py --stats

Architecture:
  - Reads alpha ideas from crawl_state.db OR uses built-in template library
  - Generates expression variants via parameter sweep
  - Tests each via BrainClient.simulate_and_get_alpha()
  - Saves results to results/batch_N_*.json + SQLite
"""
import sys, json, time, sqlite3, itertools
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "crawl_state.db"
RESULTS_DIR = ROOT / "results"
SESSION_FILE = r"D:\codeproject\auth-reptile\.state\session.json"
RESULTS_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─── Alpha Template Library ────────────────────────────────────────────────────
# Each template: (expression_template, hypothesis, category, settings_key)
# {field} = data field placeholder, {window} = time window, {n} = neutralization

FUNDAMENTAL_TEMPLATES = [
    # Leverage / Balance sheet
    ("rank(liabilities/assets)",                       "Debt burden", "leverage", "fund"),
    ("rank(-equity/assets)",                           "Low equity ratio bearish",     "leverage", "fund"),
    ("rank(total_debt/equity)",                        "Debt-to-equity",               "leverage", "fund"),
    ("rank(-cash_and_equivalents/liabilities)",        "Low cash coverage bearish",    "liquidity", "fund"),
    ("rank(cash_and_equivalents/assets)",              "Cash to assets",               "liquidity", "fund"),
    ("rank(operating_income/assets)",                  "Asset efficiency",             "quality", "fund"),
    ("rank(operating_income/sales)",                   "Operating margin",             "quality", "fund"),
    ("rank(net_income/assets)",                        "ROA",                          "quality", "fund"),
    ("rank(net_income/equity)",                        "ROE",                          "quality", "fund"),
    ("rank(gross_profit/assets)",                      "Gross profit efficiency",      "quality", "fund"),
    ("rank(book_value/market_cap)",                    "Book-to-price (value)",        "value",   "fund"),
    ("rank(sales/assets)",                             "Asset turnover",               "quality", "fund"),
    ("rank(retained_earnings/assets)",                 "Retained earnings density",    "quality", "fund"),
    ("rank(-total_debt/ebitda)",                       "Debt/EBITDA (lower=better)",   "leverage", "fund"),
    ("rank(ebitda/assets)",                            "EBITDA yield",                 "quality", "fund"),
    ("rank(cash_flow_from_operations/liabilities)",    "Cash-to-debt coverage",        "liquidity", "fund"),
    ("rank(cash_flow_from_operations/assets)",         "Operating CF yield",           "quality", "fund"),
    ("rank(operating_income/liabilities)",             "Earnings vs debt",             "leverage", "fund"),
    ("rank(revenue/assets)",                           "Revenue/assets efficiency",    "quality", "fund"),
    ("rank(-liabilities/equity)",                      "Inverse debt-to-equity",       "leverage", "fund"),
    # Composite fundamental
    ("rank(operating_income/assets - liabilities/equity)", "ROA minus leverage",       "composite", "fund"),
    ("rank(cash_and_equivalents/liabilities - total_debt/equity)", "Net liquidity score", "composite", "fund"),
    ("rank(net_income/sales * sales/assets)",          "DuPont ROA decomp",            "quality", "fund"),
    ("rank(operating_income/sales - liabilities/assets)", "Margin minus leverage",     "composite", "fund"),
]

TECHNICAL_TEMPLATES = [
    # Momentum / time-series
    ("rank(ts_mean(returns, {w}))",                    "Short-term momentum",          "momentum", "tech"),
    ("rank(-ts_std_dev(returns, {w}))",                "Low vol anomaly",              "technical", "tech"),
    ("rank(ts_rank(close, {w}))",                      "Price percentile rank",        "momentum", "tech"),
    ("rank(ts_delta(close, {w})/ts_std_dev(close, {w}))", "Normalized price change",  "momentum", "tech"),
    ("rank(ts_corr(volume, returns, {w}))",            "Volume-return correlation",    "technical", "tech"),
    ("rank(-ts_corr(close, volume, {w}))",             "Price-volume divergence",      "reversal", "tech"),
    ("rank(ts_zscore(close - vwap, {w}))",             "Price vs VWAP zscore",         "technical", "tech"),
    ("rank(ts_delta(volume, {w}) / volume)",           "Volume acceleration",          "technical", "tech"),
    ("rank(ts_ir(returns, {w}))",                      "Information ratio of returns", "momentum", "tech"),
]

GROUP_TEMPLATES = [
    # Industry-neutral versions
    ("group_rank(operating_income/assets, {g})",       "ROA industry-neutral",         "quality", "fund"),
    ("group_rank(net_income/equity, {g})",             "ROE industry-neutral",         "quality", "fund"),
    ("group_rank(operating_income/sales, {g})",        "Op margin industry-neutral",   "quality", "fund"),
    ("group_rank(-liabilities/assets, {g})",           "Low leverage industry-neutral","leverage","fund"),
    ("group_rank(cash_and_equivalents/assets, {g})",   "Cash ratio industry-neutral",  "liquidity","fund"),
    ("group_rank(book_value/market_cap, {g})",         "Book-to-price sector-neutral", "value",   "fund"),
    ("group_rank(ebitda/assets, {g})",                 "EBITDA yield industry-neutral","quality", "fund"),
    ("group_rank(sales/assets, {g})",                  "Asset turnover ind-neutral",   "quality", "fund"),
    ("group_rank(retained_earnings/assets, {g})",      "Retained earnings neutral",    "quality", "fund"),
    ("group_rank(ts_rank(close, {w}), {g})",           "Price rank in sector",         "momentum","tech"),
    ("group_rank(ts_mean(returns, {w}), {g})",         "Momentum in sector",           "momentum","tech"),
    ("group_rank(-ts_std_dev(returns, {w}), {g})",     "Low vol in sector",            "technical","tech"),
]

TS_ON_FUNDAMENTAL_TEMPLATES = [
    # Time-series rank on fundamental fields
    ("group_rank(ts_rank({f}, {w}), {g})",             "TS-rank fundamental field group-neutral", "quality", "ts_fund"),
    ("group_rank(ts_zscore({f}, {w}), {g})",           "TS-zscore fundamental field group-neutral","quality","ts_fund"),
    ("rank(ts_rank({f}, {w}))",                        "TS-rank fundamental global",   "quality", "ts_fund"),
    ("rank(ts_delta({f}, {w}) / {f})",                 "Fundamental momentum",         "momentum","ts_fund"),
    ("rank(ts_zscore({f}/{f2}, {w}))",                 "Ratio time-series zscore",     "quality", "ts_fund"),
]

# Parameter grids
WINDOWS = [21, 63, 126, 252, 504]
GROUPS = ["industry", "sector", "subindustry"]
FUND_FIELDS = [
    "operating_income", "net_income", "sales", "assets",
    "cash_flow_from_operations", "ebitda", "revenue",
    "liabilities", "equity",
]
FUND_FIELD_PAIRS = [
    ("operating_income", "assets"),
    ("net_income", "equity"),
    ("operating_income", "sales"),
    ("cash_flow_from_operations", "liabilities"),
    ("ebitda", "assets"),
]

# Settings presets
SETTINGS_PRESETS = {
    "fund": {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08},
    "fund_ind": {"decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08},
    "fund_mkt": {"decay": 0, "neutralization": "MARKET", "truncation": 0.05},
    "tech": {"decay": 4, "neutralization": "SUBINDUSTRY", "truncation": 0.05},
    "tech_mkt": {"decay": 4, "neutralization": "MARKET", "truncation": 0.05},
    "ts_fund": {"decay": 2, "neutralization": "SUBINDUSTRY", "truncation": 0.08},
}


def generate_alpha_list(target: int = 2000) -> list:
    """Generate up to `target` alpha expression dicts."""
    alphas = []

    # 1. Fundamental templates × settings variants
    for expr, hyp, cat, skey in FUNDAMENTAL_TEMPLATES:
        for neut_key, (settings_name, settings) in enumerate([
            ("SIN", SETTINGS_PRESETS["fund"]),
            ("IND", SETTINGS_PRESETS["fund_ind"]),
            ("MKT", SETTINGS_PRESETS["fund_mkt"]),
        ]):
            short_expr = expr[:22].replace("(","").replace(")","").replace("/","_").replace("-","n").replace(" ","")
            alphas.append({
                "name": f"{cat[:4]}_{short_expr}_{settings_name}",
                "expr": expr,
                "settings": settings,
                "hypothesis": hyp,
                "category": cat,
            })
            if len(alphas) >= target:
                return alphas

    # 2. Group templates × group × settings
    for expr_tmpl, hyp, cat, skey in GROUP_TEMPLATES:
        for g in GROUPS:
            for w in [63, 252]:
                expr = expr_tmpl.replace("{g}", g).replace("{w}", str(w))
                alphas.append({
                    "name": f"{cat[:4]}_{g[:3]}_{w}",
                    "expr": expr,
                    "settings": SETTINGS_PRESETS[skey],
                    "hypothesis": hyp,
                    "category": cat,
                })
                if len(alphas) >= target:
                    return alphas

    # 3. Technical templates × windows × settings
    for expr_tmpl, hyp, cat, skey in TECHNICAL_TEMPLATES:
        for w in WINDOWS:
            expr = expr_tmpl.replace("{w}", str(w))
            for settings_name, settings in [
                ("tech", SETTINGS_PRESETS["tech"]),
                ("mkt", SETTINGS_PRESETS["tech_mkt"]),
            ]:
                alphas.append({
                    "name": f"{cat[:4]}_w{w}_{settings_name}",
                    "expr": expr,
                    "settings": settings,
                    "hypothesis": hyp,
                    "category": cat,
                })
                if len(alphas) >= target:
                    return alphas

    # 4. TS on fundamental fields
    for expr_tmpl, hyp, cat, skey in TS_ON_FUNDAMENTAL_TEMPLATES:
        for g in GROUPS:
            for w in [63, 126, 252]:
                for f in FUND_FIELDS:
                    if "{f2}" in expr_tmpl:
                        continue
                    expr = expr_tmpl.replace("{f}", f).replace("{w}", str(w)).replace("{g}", g)
                    alphas.append({
                        "name": f"tsf_{f[:6]}_{w}_{g[:3]}",
                        "expr": expr,
                        "settings": SETTINGS_PRESETS["ts_fund"],
                        "hypothesis": hyp,
                        "category": cat,
                    })
                    if len(alphas) >= target:
                        return alphas

    # 5. TS on fundamental ratio pairs
    for expr_tmpl, hyp, cat, skey in TS_ON_FUNDAMENTAL_TEMPLATES:
        if "{f2}" not in expr_tmpl:
            continue
        for (f, f2) in FUND_FIELD_PAIRS:
            for w in [63, 126, 252]:
                expr = expr_tmpl.replace("{f}", f).replace("{f2}", f2).replace("{w}", str(w))
                alphas.append({
                    "name": f"tsr_{f[:5]}_{f2[:5]}_{w}",
                    "expr": expr,
                    "settings": SETTINGS_PRESETS["ts_fund"],
                    "hypothesis": hyp,
                    "category": cat,
                })
                if len(alphas) >= target:
                    return alphas

    return alphas


def run_batch(batch_number: int, alphas: list, max_count: int = 50,
              db_path: Path = DB_PATH) -> dict:
    """
    Run a batch of alpha simulations.
    max_count: max per run (due to time constraints, ~3 min each)
    """
    from brain_client import BrainClient

    c = BrainClient(state_file=SESSION_FILE)
    auth = c.check_auth()
    if auth["status"] != 200:
        raise RuntimeError(f"Auth failed: {auth['status']}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alpha_batch_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_number INTEGER,
            expression TEXT,
            settings TEXT,
            alpha_id TEXT,
            sharpe REAL,
            fitness REAL,
            turnover REAL,
            returns REAL,
            status TEXT,
            fail_reasons TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    # Get already-tested expressions to skip
    done_exprs = set(r[0] for r in conn.execute(
        "SELECT expression FROM alpha_batch_results"
    ).fetchall())

    results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"batch_{batch_number}_{timestamp}.json"

    tested = 0
    for alpha in alphas:
        if tested >= max_count:
            break
        expr = alpha["expr"]
        if expr in done_exprs:
            print(f"  [SKIP] Already tested: {expr[:50]}")
            continue

        print(f"  [{tested+1}/{max_count}] Testing: {expr[:60]}")
        try:
            result = c.simulate_and_get_alpha(expr, alpha.get("settings"))
            if "error" in result:
                print(f"    ERROR: {result['error']}")
                conn.execute("""
                    INSERT INTO alpha_batch_results
                    (batch_number, expression, settings, status)
                    VALUES (?, ?, ?, ?)
                """, (batch_number, expr, json.dumps(alpha.get("settings", {})), "error"))
                conn.commit()
                tested += 1
                continue

            is_data = result.get("is", {}) or {}
            sharpe = is_data.get("sharpe", 0) or 0
            fitness = is_data.get("fitness", 0) or 0
            turnover = (is_data.get("turnover", 0) or 0) * 100
            returns = (is_data.get("returns", 0) or 0) * 100
            alpha_id = result.get("id", "")

            checks = is_data.get("checks", [])
            failed = [c["name"] for c in checks if c.get("result") == "FAIL"]
            status = "PASS" if not failed else "FAIL"

            print(f"    {status} Sharpe={sharpe:.3f} Fitness={fitness:.3f} TO={turnover:.1f}%")

            conn.execute("""
                INSERT OR IGNORE INTO alpha_batch_results
                (batch_number, expression, settings, alpha_id, sharpe, fitness, turnover, returns, status, fail_reasons)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                batch_number, expr, json.dumps(alpha.get("settings", {})),
                alpha_id, sharpe, fitness, turnover / 100, returns / 100,
                status, json.dumps(failed)
            ))
            conn.commit()

            entry = {**alpha, "alpha": result}
            results.append(entry)

            # Auto-submit if passing
            if status == "PASS" and alpha_id:
                print(f"    → Auto-submitting {alpha_id}...")
                sub = c.submit_alpha(alpha_id)
                print(f"    Submit: {sub.get('status')}")

        except Exception as e:
            print(f"    EXCEPTION: {e}")

        tested += 1
        done_exprs.add(expr)

    conn.close()
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBatch {batch_number} done. {len(results)} results saved to {out_file.name}")

    # Summary
    passing = [r for r in results if not r.get("alpha", {}).get("error")]
    p_count = sum(
        1 for r in passing
        if all(c.get("result") in ("PASS", "PENDING")
               for c in (r.get("alpha", {}).get("is", {}) or {}).get("checks", []))
    )
    print(f"Passing: {p_count}/{len(results)}")
    return {"batch": batch_number, "tested": tested, "results": len(results), "passing": p_count}


def get_batch_stats(db_path: Path = DB_PATH) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        total = conn.execute("SELECT COUNT(*) FROM alpha_batch_results").fetchone()[0]
        passing = conn.execute("SELECT COUNT(*) FROM alpha_batch_results WHERE status='PASS'").fetchone()[0]
        by_batch = conn.execute(
            "SELECT batch_number, COUNT(*), SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) FROM alpha_batch_results GROUP BY batch_number"
        ).fetchall()
    except Exception:
        total, passing, by_batch = 0, 0, []
    conn.close()
    return {"total": total, "passing": passing, "by_batch": by_batch}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1, help="Batch number")
    parser.add_argument("--count", type=int, default=2000, help="Total alphas to generate")
    parser.add_argument("--run", type=int, default=30, help="How many to actually test this run")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--list", action="store_true", help="Just list generated alphas (no testing)")
    args = parser.parse_args()

    if args.stats:
        print(json.dumps(get_batch_stats(), indent=2, default=str))
        sys.exit(0)

    alphas = generate_alpha_list(target=args.count)
    print(f"Generated {len(alphas)} alpha expressions")

    if args.list:
        for i, a in enumerate(alphas[:50], 1):
            print(f"  {i:4d}. [{a['category']:<10}] {a['expr'][:70]}")
        print(f"  ... ({len(alphas)} total)")
        sys.exit(0)

    run_batch(args.batch, alphas, max_count=args.run)
