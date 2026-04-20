"""
build_final_kb.py - Build the definitive WQ BRAIN knowledge base from all crawled content.
This is the final compilation pass with full text analysis.
"""
import sys, json, re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(__file__).parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MANUAL_DIR = ROOT / "data" / "crawl_manual"


def load_all_pages() -> dict:
    pages = {}
    for p in sorted(MANUAL_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            pages[p.stem] = d
        except Exception:
            pass
    return pages


def build_kb(pages: dict) -> dict:
    """Build the final comprehensive knowledge base."""

    # ─── Alpha Expressions (manually curated from page analysis) ──────────────
    # These are the real expressions found in the official documentation
    official_alpha_examples = [
        # From "19 Alpha Examples for Beginners"
        {
            "expression": "ts_rank(operating_income, 252)",
            "settings": {"decay": 0, "neutralization": "Subindustry", "truncation": 0.08},
            "hypothesis": "If the operating income of a company is currently higher than its past 1 year history, buy the stock.",
            "category": "fundamental",
            "source": "19_alpha_examples",
            "priority": "HIGH",
        },
        {
            "expression": "-ts_rank(fn_liab_fair_val_l1_a, 252)",
            "settings": {"decay": 0, "neutralization": "Subindustry", "truncation": 0.08},
            "hypothesis": "An increase in fair value of liabilities indicates higher cost than expected, leading to lower profitability.",
            "category": "fundamental",
            "source": "19_alpha_examples",
            "priority": "HIGH",
        },
        {
            "expression": "liabilities/assets",
            "settings": {"decay": 0, "neutralization": "Market", "truncation": 0.01},
            "hypothesis": "Companies with high liability-to-asset ratios that use leverage strategically deliver outsized returns.",
            "category": "fundamental",
            "source": "19_alpha_examples",
            "priority": "HIGH",
        },
        {
            "expression": "group_rank(ts_rank(est_eps/close, 60), industry)",
            "settings": {"decay": 0, "neutralization": "Industry", "truncation": 0.08},
            "hypothesis": "Stocks whose earnings yield has been high more often over last quarter, relative to their history, may be undervalued.",
            "category": "analyst",
            "source": "19_alpha_examples",
            "priority": "HIGH",
        },
        {
            "expression": "-ts_std_dev(scl12_buzz, 10)",
            "settings": {"decay": 0, "neutralization": "Market", "truncation": 0.08},
            "hypothesis": "High short-term standard deviation of sentiment volume means unstable investor attention → underperformance.",
            "category": "sentiment",
            "source": "19_alpha_examples",
            "priority": "MEDIUM",
        },
        # From "Alpha Examples for Bronze Users"
        {
            "expression": "group_rank(-ts_zscore(enterprise_value/cashflow, 63), industry)",
            "settings": {"decay": 0, "neutralization": "Industry", "truncation": 0.08},
            "hypothesis": "Lower EV/CF suggests company is becoming cheaper relative to cash-generating ability.",
            "category": "fundamental",
            "source": "bronze_examples",
            "priority": "HIGH",
        },
        {
            "expression": "-ts_corr(est_ptp, est_fcf, 252)",
            "settings": {"decay": 0, "neutralization": "Market", "truncation": 0.08},
            "hypothesis": "High positive correlation between price targets and FCF estimates signals market has fully priced in expectations.",
            "category": "analyst",
            "source": "bronze_examples",
            "priority": "MEDIUM",
        },
        {
            "expression": "implied_volatility_call_120/parkinson_volatility_120",
            "settings": {"decay": 0, "neutralization": "Sector", "universe": "TOP2000", "truncation": 0.08},
            "hypothesis": "Lower Parkinson volatility + higher implied volatility suggests bullish sentiment.",
            "category": "options",
            "source": "bronze_examples",
            "priority": "MEDIUM",
        },
        # From documentation examples
        {
            "expression": "rank(-returns)",
            "settings": {"decay": 0, "neutralization": "Market"},
            "hypothesis": "Mean reversion: buy stocks with lower recent returns, sell stocks with higher recent returns.",
            "category": "price_volume",
            "source": "how_brain_works",
            "priority": "MEDIUM",
        },
        {
            "expression": "rank(sales/assets)",
            "settings": {"decay": 4, "neutralization": "Market"},
            "hypothesis": "Asset turnover ratio: companies with higher sales/assets have better capital efficiency → outperform.",
            "category": "fundamental",
            "source": "intermediate_pack",
            "priority": "HIGH",
        },
        {
            "expression": "ts_delta(close, 5)",
            "settings": {"decay": 4, "neutralization": "Market"},
            "hypothesis": "5-day price change momentum signal.",
            "category": "price_volume",
            "source": "first_alpha",
            "priority": "LOW",
        },
        {
            "expression": "rank(ebit/capex)",
            "settings": {"decay": 0, "neutralization": "Industry"},
            "hypothesis": "Companies generating high EBIT relative to capital expenditures are more capital efficient.",
            "category": "fundamental",
            "source": "neutralization_doc",
            "priority": "HIGH",
        },
        # From simulation settings doc
        {
            "expression": "ts_zscore(est_eps, 252)",
            "settings": {"decay": 0, "neutralization": "Industry"},
            "hypothesis": "EPS estimate z-score over trailing year captures earnings momentum.",
            "category": "analyst",
            "source": "simulation_settings",
            "priority": "MEDIUM",
        },
        {
            "expression": "ts_zscore(etz_eps, 252)",
            "settings": {"decay": 0, "neutralization": "Industry"},
            "hypothesis": "EPS estimate revision z-score captures analyst sentiment change.",
            "category": "analyst",
            "source": "simulation_settings",
            "priority": "MEDIUM",
        },
        {
            "expression": "group_rank(sales_growth, sector)",
            "settings": {"decay": 0, "neutralization": "Sector"},
            "hypothesis": "Rank stocks by sales growth within their sector.",
            "category": "fundamental",
            "source": "simulation_settings",
            "priority": "HIGH",
        },
    ]

    # ─── Derived alpha ideas (not in docs but suggested by patterns) ──────────
    derived_alpha_ideas = [
        # Value ratios - fundamental, low turnover
        "rank(operating_income/assets)",  # Return on assets proxy
        "rank(gross_profit/revenue)",     # Gross margin
        "rank(net_income/equity)",        # ROE proxy
        "rank(free_cash_flow/market_cap)",  # FCF yield
        "rank(book_value/market_cap)",     # Book-to-price
        "rank(earnings_per_share/close)",  # Earnings yield
        "rank(-total_debt/equity)",        # Leverage (negative = less debt is better)
        "rank(cash_and_equivalents/total_debt)",  # Cash coverage
        "rank(operating_income/revenue)",  # Operating margin
        "rank(-liabilities/assets)",       # Asset quality (low liabilities)
        # Industry-neutral versions
        "group_rank(operating_income/assets, industry)",
        "group_rank(-liabilities/assets, subindustry)",
        "group_rank(net_income/equity, industry)",
        "group_rank(free_cash_flow/market_cap, industry)",
        # Time-series fundamental
        "ts_rank(sales, 252)",             # Sales momentum over 1 year
        "ts_rank(net_income, 252)",        # Earnings growth
        "ts_rank(free_cash_flow, 252)",    # FCF growth
        "ts_rank(gross_profit/revenue, 252)",  # Margin expansion
        # Price/volume patterns
        "rank(-ts_std_dev(returns, 20))",  # Low volatility (inverse)
        "ts_rank(volume, 60)",             # Volume momentum
    ]

    # ─── Submission criteria (from documentation) ─────────────────────────────
    submission_criteria = {
        "description": "Tests run during In-Sample (IS) simulation. Only passing alphas can be submitted for Out-of-Sample (OS) testing.",
        "tests": {
            "FITNESS": {
                "threshold_delay1": "> 1.0 (Average or above)",
                "threshold_delay0": "> 1.3",
                "ratings": {
                    "Spectacular": "> 2.5 (delay-1), > 3.25 (delay-0)",
                    "Excellent": "> 2.0 (delay-1), > 2.6 (delay-0)",
                    "Good": "> 1.5 (delay-1), > 1.95 (delay-0)",
                    "Average": "> 1.0 (delay-1), > 1.3 (delay-0)",
                    "Needs Improvement": "<= 1.0 (delay-1)",
                },
                "formula": "Fitness = Sharpe * sqrt(abs(Returns) / max(Turnover, 0.125))",
                "tips": [
                    "Increase Sharpe (more consistent returns) → raises Fitness",
                    "Reduce Turnover → raises Fitness (since max(T,0.125) is denominator)",
                    "Fundamental alphas naturally have low turnover → high Fitness",
                    "At 70% turnover, Fitness ≈ 40-60% of Sharpe",
                ],
            },
            "SHARPE": {
                "threshold_delay1": "> 1.25",
                "threshold_delay0": "> 2.0",
                "formula": "Sharpe = IR * sqrt(252) ≈ 15.8 * IR, where IR = mean(daily_PnL) / std(daily_PnL)",
                "tips": [
                    "Higher Sharpe = more consistent alpha",
                    "Use neutralization to reduce systematic risk exposure",
                    "Use decay to smooth signal and reduce noise",
                    "Fundamental factors tend to have more stable Sharpe",
                ],
            },
            "TURNOVER": {
                "threshold_min_pct": 1.0,
                "threshold_max_pct": 70.0,
                "definition": "Daily Turnover = Dollar trading volume / Book size",
                "tips": [
                    "Decay (e.g. decay=4) reduces turnover by smoothing the signal",
                    "group_rank() instead of rank() reduces cross-sectional noise",
                    "Fundamental data naturally has low turnover (quarterly updates)",
                    "Technical signals (ts_delta) have HIGH turnover (30-90%)",
                    "Target turnover: 5-30% for good fitness",
                ],
            },
            "WEIGHT": {
                "threshold": "Max weight in any stock < 10%",
                "tips": [
                    "Use truncation=0.05 to cap max weight at 5%",
                    "Avoid rank(-assets) or rank(cap) which concentrate in big/small stocks",
                    "Ensure sufficient stocks have weight each day",
                ],
            },
            "SUB_UNIVERSE": {
                "formula": "subuniverse_sharpe >= 0.75 * sqrt(subuniverse_size / alpha_universe_size) * alpha_sharpe",
                "example": "TOP3000 alpha also tested on TOP1000. Cutoff = 0.75 * sqrt(1000/3000) * alpha_sharpe",
                "tips": [
                    "Avoid size multipliers like rank(-assets) or rank(cap) - they concentrate in non-liquid stocks",
                    "If failing, try decay-separate liquid vs non-liquid: ts_decay_linear(signal,5)*rank(volume*close) + ts_decay_linear(signal,10)*(1-rank(volume*close))",
                    "Sub-universe test ensures alpha is robust across liquidity tiers",
                ],
            },
            "SELF_CORRELATION": {
                "threshold": "< 0.7 PnL correlation",
                "alternative": "OR Sharpe at least 10% greater than correlated alphas",
                "tips": [
                    "Use different data fields/datasets to ensure diversity",
                    "Can submit correlated alpha if Sharpe is ≥10% better than existing",
                    "Self-correlation operates on 4-year window",
                ],
            },
        },
        "alpha_types": {
            "ATOM": "Uses fields from only 1 dataset",
            "Pyramid": "Multi-layer alpha structure",
            "Power_Pool": "Combines multiple alphas with specific pooling",
        },
    }

    # ─── Operator catalog (from operators page) ─────────────────────────────
    op_text = ""
    for key in ["learn_operators_operators", "learn_operators"]:
        if key in pages:
            op_text = pages[key].get("raw_text", "")
            if len(op_text) > 1000:
                break

    # Parse operators from the text
    operator_catalog = _parse_operators(op_text)

    # ─── Simulation settings guide ──────────────────────────────────────────
    simulation_guide = {
        "default_settings": {
            "instrumentType": "EQUITY",
            "region": "USA",
            "universe": "TOP3000",
            "delay": 1,
            "decay": 4,
            "neutralization": "MARKET",
            "truncation": 0.05,
            "pasteurization": "ON",
            "nanHandling": "OFF",
            "unitHandling": "VERIFY",
            "language": "FASTEXPR",
        },
        "parameter_details": {
            "delay": {
                "description": "Lag between data availability and trade execution",
                "delay_0": "Trade at market close on same day (aggressive)",
                "delay_1": "Trade next day (conservative, standard for Fitness > 1.0)",
                "recommendation": "Use Delay 1 for most strategies",
            },
            "decay": {
                "description": "Linear decay over past N days: ts_decay_linear(x, N)",
                "formula": "decay_N(x, d) = x[t]*N + x[t-1]*(N-1) + ... + x[t-N+1]*1",
                "effect_on_turnover": "Higher decay = lower turnover",
                "effect_on_signal": "Higher decay = attenuates signal",
                "recommendation": "Use decay=0 for fundamental alphas, decay=4 for price-based",
                "tip": "Decay reduces turnover but also attenuates signal - balance carefully",
            },
            "neutralization": {
                "description": "Makes alpha long-short neutral within a group",
                "formula": "Alpha = Alpha - mean(Alpha) within group",
                "options": {
                    "NONE": "No neutralization (manual only)",
                    "MARKET": "Subtract market mean - removes market beta",
                    "SECTOR": "Neutral within GICS sectors",
                    "INDUSTRY": "Neutral within GICS industries (more granular than sector)",
                    "SUBINDUSTRY": "Most granular - ideal for fundamental factors",
                },
                "by_dataset": {
                    "fundamental": "SUBINDUSTRY (fundamentals vary within industry)",
                    "analyst": "INDUSTRY (analyst estimates are industry-comparable)",
                    "price_volume": "MARKET or SECTOR (generic ideas work across industries)",
                    "news_sentiment": "SUBINDUSTRY (news impact varies significantly)",
                    "options": "MARKET or SECTOR (options impact broadly similar)",
                    "model": "Experiment with all levels",
                },
            },
            "truncation": {
                "description": "Max weight for any single stock",
                "recommendation": "0.05 to 0.08 (5-8%)",
                "effect": "Guards against concentration in individual stocks",
            },
            "pasteurization": {
                "description": "Replaces values for stocks NOT in universe with NaN",
                "ON": "Only universe stocks have values (recommended)",
                "OFF": "All available stocks contribute to cross-sectional calculations",
                "tip": "Use pasteurize() operator for manual control when pasteurization=OFF",
            },
            "universe": {
                "TOP3000": "3000 most liquid US stocks (standard)",
                "TOP2000": "2000 most liquid US stocks",
                "TOP1000": "1000 most liquid US stocks (most liquid)",
                "recommendation": "Start with TOP3000, test sub-universe robustness",
            },
        },
        "recommended_by_strategy": {
            "fundamental_value": {
                "decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08,
                "rationale": "Quarterly data = low natural turnover; industry neutral removes sector bias",
            },
            "analyst_estimates": {
                "decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08,
                "rationale": "Estimates comparable within industries",
            },
            "price_momentum": {
                "decay": 4, "neutralization": "MARKET", "truncation": 0.05,
                "rationale": "Need decay to reduce high turnover of daily price data",
            },
            "sentiment": {
                "decay": 2, "neutralization": "SUBINDUSTRY", "truncation": 0.08,
                "rationale": "News/social media impact varies by subindustry",
            },
        },
    }

    # ─── Neutralization deep dive ────────────────────────────────────────────
    neutralization_guide = {
        "overview": "Neutralization makes the Alpha long-short neutral within groups, reducing systematic risk exposure",
        "formula": "Alpha = Alpha - mean(Alpha) within group. Results in sum=0, equal long/short",
        "hierarchy": "MARKET ⊃ SECTOR ⊃ INDUSTRY ⊃ SUBINDUSTRY",
        "equivalent_to": "group_neutralize(x, group) operator with None neutralization in settings",
        "tips": [
            "Always use some neutralization unless manually neutralizing in expression",
            "Larger groups (Market) for more liquid universes",
            "Smaller groups (Subindustry) for fundamental data",
            "group_rank() automatically neutralizes within the group",
            "Use group_rank(expr, sector) instead of rank(expr) for industry-neutral cross-sectional",
            "If using group_neutralize() in expression, set neutralization=None in settings",
        ],
    }

    # ─── Data field catalog ───────────────────────────────────────────────────
    data_catalog = {
        "price_volume": {
            "close": {"description": "Daily closing price", "freq": "daily", "turnover_impact": "HIGH"},
            "open": {"description": "Daily opening price", "freq": "daily", "turnover_impact": "HIGH"},
            "high": {"description": "Daily high price", "freq": "daily", "turnover_impact": "HIGH"},
            "low": {"description": "Daily low price", "freq": "daily", "turnover_impact": "HIGH"},
            "volume": {"description": "Daily trading volume (shares)", "freq": "daily", "turnover_impact": "HIGH"},
            "vwap": {"description": "Volume-weighted average price", "freq": "daily", "turnover_impact": "HIGH"},
            "returns": {"description": "Daily stock returns", "freq": "daily", "turnover_impact": "HIGH"},
            "adv20": {"description": "20-day average daily dollar volume", "freq": "daily", "turnover_impact": "MEDIUM"},
            "adv60": {"description": "60-day average daily dollar volume", "freq": "daily", "turnover_impact": "LOW"},
            "cap": {"description": "Market capitalization (daily)", "freq": "daily", "turnover_impact": "LOW"},
        },
        "fundamental": {
            "assets": {"description": "Total assets", "freq": "quarterly", "turnover_impact": "LOW"},
            "liabilities": {"description": "Total liabilities", "freq": "quarterly", "turnover_impact": "LOW"},
            "equity": {"description": "Total shareholders equity", "freq": "quarterly", "turnover_impact": "LOW"},
            "debt": {"description": "Total debt", "freq": "quarterly", "turnover_impact": "LOW"},
            "total_debt": {"description": "Total debt (alternative field)", "freq": "quarterly", "turnover_impact": "LOW"},
            "cash_and_equivalents": {"description": "Cash and cash equivalents", "freq": "quarterly", "turnover_impact": "LOW"},
            "operating_income": {"description": "Operating income (EBIT)", "freq": "quarterly", "turnover_impact": "LOW"},
            "net_income": {"description": "Net income", "freq": "quarterly", "turnover_impact": "LOW"},
            "revenue": {"description": "Total revenue", "freq": "quarterly", "turnover_impact": "LOW"},
            "sales": {"description": "Net sales", "freq": "quarterly", "turnover_impact": "LOW"},
            "ebitda": {"description": "EBITDA", "freq": "quarterly", "turnover_impact": "LOW"},
            "ebit": {"description": "EBIT (operating income)", "freq": "quarterly", "turnover_impact": "LOW"},
            "gross_profit": {"description": "Gross profit", "freq": "quarterly", "turnover_impact": "LOW"},
            "book_value": {"description": "Book value per share", "freq": "quarterly", "turnover_impact": "LOW"},
            "shares_outstanding": {"description": "Shares outstanding", "freq": "quarterly", "turnover_impact": "LOW"},
            "earnings_per_share": {"description": "Basic EPS", "freq": "quarterly", "turnover_impact": "LOW"},
            "dividends": {"description": "Dividends per share", "freq": "quarterly", "turnover_impact": "LOW"},
            "retained_earnings": {"description": "Retained earnings", "freq": "quarterly", "turnover_impact": "LOW"},
            "inventory": {"description": "Inventory", "freq": "quarterly", "turnover_impact": "LOW"},
            "accounts_receivable": {"description": "Accounts receivable", "freq": "quarterly", "turnover_impact": "LOW"},
            "accounts_payable": {"description": "Accounts payable", "freq": "quarterly", "turnover_impact": "LOW"},
            "cash_flow_from_operations": {"description": "Operating cash flow", "freq": "quarterly", "turnover_impact": "LOW"},
            "capital_expenditures": {"description": "Capital expenditures", "freq": "quarterly", "turnover_impact": "LOW"},
            "capex": {"description": "Capital expenditures (short)", "freq": "quarterly", "turnover_impact": "LOW"},
            "free_cash_flow": {"description": "Free cash flow = CFO - CapEx", "freq": "quarterly", "turnover_impact": "LOW"},
            "cashflow": {"description": "Cash flow (general)", "freq": "quarterly", "turnover_impact": "LOW"},
            "enterprise_value": {"description": "Enterprise value = market_cap + debt - cash", "freq": "quarterly", "turnover_impact": "LOW"},
            "market_cap": {"description": "Market capitalization", "freq": "daily", "turnover_impact": "LOW"},
            "fn_liab_fair_val_l1_a": {"description": "Level 1 fair value liabilities (financial instruments)", "freq": "quarterly", "turnover_impact": "LOW"},
            "return_on_equity": {"description": "Return on equity (computed ratio)", "freq": "quarterly", "turnover_impact": "LOW"},
            "return_on_assets": {"description": "Return on assets (computed ratio)", "freq": "quarterly", "turnover_impact": "LOW"},
            "net_profit_margin": {"description": "Net profit margin", "freq": "quarterly", "turnover_impact": "LOW"},
        },
        "analyst_estimates": {
            "est_eps": {"description": "Consensus EPS estimate", "freq": "daily", "turnover_impact": "MEDIUM"},
            "est_ptp": {"description": "Consensus price target estimate", "freq": "daily", "turnover_impact": "MEDIUM"},
            "est_fcf": {"description": "Consensus free cash flow estimate", "freq": "daily", "turnover_impact": "MEDIUM"},
            "sales_growth": {"description": "Sales growth estimate", "freq": "quarterly", "turnover_impact": "LOW"},
            "etz_eps": {"description": "EPS estimate revision (change in consensus)", "freq": "daily", "turnover_impact": "MEDIUM"},
        },
        "sentiment": {
            "scl12_buzz": {"description": "Social media buzz/volume score (Sentiment1 dataset)", "freq": "daily", "turnover_impact": "HIGH"},
            "short_interest": {"description": "Short interest ratio", "freq": "weekly", "turnover_impact": "MEDIUM"},
        },
        "options": {
            "implied_volatility_call_120": {"description": "120-day call option implied volatility", "freq": "daily", "turnover_impact": "MEDIUM"},
            "parkinson_volatility_120": {"description": "120-day Parkinson historical volatility", "freq": "daily", "turnover_impact": "MEDIUM"},
        },
        "risk": {
            "beta": {"description": "Market beta", "freq": "daily", "turnover_impact": "LOW"},
        },
    }

    # ─── Best practices (from all pages) ────────────────────────────────────
    best_practices = [
        # Submission criteria
        "Sharpe ≥ 1.25 (delay-1) and Fitness ≥ 1.0 are minimum submission requirements",
        "Fitness = Sharpe * sqrt(|Returns| / max(Turnover, 0.125)) - optimize both Sharpe and low turnover",
        "Turnover must be between 1% and 70%; above 70% fails HIGH_TURNOVER check",
        "Max single stock weight < 10% (use truncation=0.05-0.08)",
        "Sub-universe test: alpha must work on TOP1000 if simulated on TOP3000",
        "Self-correlation < 0.7 OR new alpha Sharpe must be ≥10% higher than correlated existing alphas",
        # Fundamental strategies
        "Fundamental alphas (quarterly data) naturally have 1-5% turnover → high Fitness",
        "Use SUBINDUSTRY neutralization for fundamental factors (company fundamentals vary by industry)",
        "Use INDUSTRY neutralization for analyst estimates",
        "Set decay=0 for fundamental alphas (data already changes slowly)",
        "rank(fundamental_ratio) is the simplest HIGH fitness pattern",
        "group_rank(fundamental_ratio, industry) adds industry neutralization → more robust",
        # Technical strategies
        "Technical alphas (daily price data) have 20-90% turnover → difficult to pass Fitness",
        "For price-based signals, use decay=4 or higher to reduce turnover",
        "ts_rank(x, 252) over 1-year window has lower turnover than ts_delta",
        "Combine ts_rank with group_rank for industry-neutral time-series signals",
        # Improving alphas
        "To improve Fitness: reduce turnover by adding decay, or improve Sharpe by neutralizing better",
        "Try Subindustry neutralization for fundamental data, Market for price/volume",
        "NaN Handling=OFF (default) preserves NaN values - handle manually with pasteurize() if needed",
        "Pasteurize=ON (default) ensures only universe stocks contribute to cross-sectional calculations",
        "Avoid rank(-assets) or 1-rank(cap) in sub-universe tests (concentrates in non-liquid stocks)",
        "PnL should trend upward consistently over the 5-year IS period",
        "Drawdown should be kept to minimum - consistent returns are better than high but volatile",
        # Operator tips
        "rank() normalizes to [0,1] - apply to any ratio to control extreme values",
        "group_rank(x, group) = rank within industry/sector group = industry-neutral version",
        "ts_rank(x, d) = rank of current value within past d days of the same stock",
        "ts_zscore(x, d) = (x - mean(x, d)) / std(x, d) over past d days",
        "ts_delta(x, d) = x[t] - x[t-d] = change over d days (HIGH turnover)",
        "ts_corr(x, y, d) = rolling correlation between two fields over d days",
        "scale(x) normalizes values to sum to 1 (like softmax without normalization)",
        "pasteurize(x) manually NaN-out stocks not in universe",
        "Use log() to transform right-skewed fundamental data",
        "signed_power(x, 0.5) = sqrt with sign preservation",
        # Data and diversification
        "Diversify across data categories: price_volume, fundamental, analyst, sentiment, options",
        "Try different lookback windows: 20d, 60d, 126d, 252d for time-series operators",
        "Fundamental ratio numerator should be an income/flow field, denominator a stock/size field",
        "EV/CF, P/E, P/B, P/S ratios are classic value factors",
        "Operating income / assets = ROA proxy (strong Fitness fundamental factor)",
        "Use group_rank instead of rank to reduce noise from between-sector differences",
    ]

    # ─── Alpha patterns ranked by priority ───────────────────────────────────
    alpha_patterns = [
        {
            "pattern_name": "fundamental_ratio_rank",
            "pattern": "rank(fundamental_field_a / fundamental_field_b)",
            "priority": "HIGH",
            "expected_turnover": "1-5% (quarterly data)",
            "expected_fitness": "High (1.5-3.0)",
            "examples": [
                "rank(sales/assets)",
                "rank(operating_income/assets)",
                "rank(net_income/equity)",
                "rank(free_cash_flow/market_cap)",
                "rank(ebit/capex)",
                "rank(-liabilities/assets)",
            ],
            "recommended_settings": {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08},
            "tips": "Best fitness pattern. Use ratios that normalize by size. Negate if high is bad.",
        },
        {
            "pattern_name": "industry_neutral_fundamental",
            "pattern": "group_rank(expression, industry)",
            "priority": "HIGH",
            "expected_turnover": "1-10%",
            "expected_fitness": "Very high (2.0+)",
            "examples": [
                "group_rank(ts_rank(est_eps/close, 60), industry)",
                "group_rank(-ts_zscore(enterprise_value/cashflow, 63), industry)",
                "group_rank(operating_income/assets, industry)",
                "group_rank(sales_growth, sector)",
                "group_rank(-liabilities/assets, subindustry)",
            ],
            "recommended_settings": {"decay": 0, "neutralization": "NONE", "truncation": 0.08},
            "tips": "Use group_rank() as the outermost operator with neutralization=NONE in settings to avoid double-neutralization.",
        },
        {
            "pattern_name": "ts_rank_fundamental",
            "pattern": "ts_rank(fundamental_field, 252)",
            "priority": "HIGH",
            "expected_turnover": "2-10%",
            "expected_fitness": "High (1.5-2.5)",
            "examples": [
                "ts_rank(operating_income, 252)",
                "-ts_rank(fn_liab_fair_val_l1_a, 252)",
                "ts_rank(net_income, 252)",
                "ts_rank(free_cash_flow, 252)",
                "ts_rank(est_eps/close, 60)",
            ],
            "recommended_settings": {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08},
            "tips": "Compares current fundamental value to its own 1-year history. Low turnover since quarterly updates.",
        },
        {
            "pattern_name": "ts_zscore_analyst",
            "pattern": "ts_zscore(analyst_field, 252)",
            "priority": "MEDIUM",
            "expected_turnover": "10-30%",
            "expected_fitness": "Medium (1.0-2.0)",
            "examples": [
                "ts_zscore(est_eps, 252)",
                "ts_zscore(etz_eps, 252)",
                "ts_zscore(enterprise_value/cashflow, 63)",
                "-ts_zscore(enterprise_value/cashflow, 63)",
            ],
            "recommended_settings": {"decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08},
            "tips": "Z-score standardizes analyst estimates. Shorter windows (63d) = more responsive but higher turnover.",
        },
        {
            "pattern_name": "simple_rank_momentum",
            "pattern": "rank(-returns)",
            "priority": "MEDIUM",
            "expected_turnover": "20-50%",
            "expected_fitness": "Low-medium (0.5-1.5)",
            "examples": [
                "rank(-returns)",
                "rank(-ts_std_dev(returns, 20))",
            ],
            "recommended_settings": {"decay": 4, "neutralization": "MARKET", "truncation": 0.05},
            "tips": "Reversal strategy. Use decay to reduce turnover. High turnover is the main challenge.",
        },
        {
            "pattern_name": "ts_corr_signal",
            "pattern": "-ts_corr(field_a, field_b, 252)",
            "priority": "MEDIUM",
            "expected_turnover": "15-40%",
            "expected_fitness": "Medium (1.0-1.8)",
            "examples": [
                "-ts_corr(est_ptp, est_fcf, 252)",
            ],
            "recommended_settings": {"decay": 0, "neutralization": "MARKET", "truncation": 0.08},
            "tips": "Correlation between two signals can capture relationship changes. Try shorter windows.",
        },
        {
            "pattern_name": "options_volatility_arb",
            "pattern": "implied_vol / historical_vol",
            "priority": "MEDIUM",
            "expected_turnover": "10-30%",
            "expected_fitness": "Medium",
            "examples": [
                "implied_volatility_call_120/parkinson_volatility_120",
            ],
            "recommended_settings": {"decay": 0, "neutralization": "SECTOR", "universe": "TOP2000", "truncation": 0.08},
            "tips": "Volatility arbitrage. Higher implied vs historical vol → bullish signal.",
        },
        {
            "pattern_name": "ts_delta_momentum",
            "pattern": "ts_delta(field, d)",
            "priority": "LOW",
            "expected_turnover": "40-90%",
            "expected_fitness": "Low (usually fails Fitness without heavy decay)",
            "examples": [
                "ts_delta(close, 5)",
            ],
            "recommended_settings": {"decay": 8, "neutralization": "MARKET", "truncation": 0.05},
            "tips": "Pure momentum/change signal. Usually requires heavy decay. Rarely passes Fitness check.",
        },
    ]

    # ─── Compile all pages summary ────────────────────────────────────────────
    pages_summary = []
    for key, data in sorted(pages.items()):
        text = data.get("raw_text", "")
        if len(text) > 200:
            pages_summary.append({
                "key": key,
                "title": data.get("title", ""),
                "url": data.get("url", ""),
                "text_length": len(text),
            })
    pages_summary.sort(key=lambda x: -x["text_length"])

    return {
        "compiled_at": datetime.now().isoformat(),
        "crawled_pages": len(pages),
        "version": "2.0",

        # Official alpha examples from documentation
        "official_alpha_examples": official_alpha_examples,

        # Derived alpha ideas (patterns to explore)
        "derived_alpha_ideas": derived_alpha_ideas,

        # Alpha patterns by category
        "alpha_patterns": alpha_patterns,

        # Submission criteria (comprehensive)
        "submission_criteria": submission_criteria,

        # Simulation settings guide
        "simulation_settings_guide": simulation_guide,

        # Neutralization guide
        "neutralization_guide": neutralization_guide,

        # Operator catalog
        "operator_catalog": operator_catalog,

        # Data field catalog
        "data_field_catalog": data_catalog,

        # Best practices
        "best_practices": best_practices,

        # Pages crawled
        "pages_crawled": pages_summary[:30],

        # URLs discovered but not yet crawled
        "future_crawl_urls": _get_uncrawled_urls(pages),
    }


def _parse_operators(text: str) -> dict:
    """Parse operator catalog from the operators page text."""
    catalog = {}
    if not text:
        return catalog

    # Split by known operator categories
    lines = text.split("\n")
    current_op = None
    current_desc = []

    for line in lines:
        line = line.strip()
        if not line or line in ["Show more", "Show less", "Arithmetic", "Logical",
                                  "Time Series", "Cross Sectional", "Operator", "Description"]:
            if current_op and current_desc:
                catalog[current_op["name"]] = {
                    "signature": current_op["signature"],
                    "description": " ".join(current_desc)[:400],
                    "category": current_op.get("category", "base"),
                    "params": current_op.get("params", ""),
                }
                current_desc = []
            if line in ["Arithmetic", "Logical", "Time Series", "Cross Sectional"]:
                current_op = None
            continue

        # Check if this is an operator signature
        m = re.match(r'^([a-z_][a-z0-9_]*)\s*\(([^)]*)\)', line, re.IGNORECASE)
        if m:
            # Save previous op
            if current_op and current_desc:
                catalog[current_op["name"]] = {
                    "signature": current_op["signature"],
                    "description": " ".join(current_desc)[:400],
                    "category": current_op.get("category", "base"),
                    "params": current_op.get("params", ""),
                }
                current_desc = []

            op_name = m.group(1).lower()
            params = m.group(2)
            category = "base"
            if "expert" in line.lower():
                category = "expert"
            elif "master" in line.lower():
                category = "master"

            current_op = {
                "name": op_name,
                "signature": f"{op_name}({params})",
                "params": params,
                "category": category,
            }
        elif current_op and len(line) > 5:
            # This might be the category or description
            if line.lower() in ["base", "expert", "master", "grandmaster"]:
                current_op["category"] = line.lower()
            else:
                current_desc.append(line[:200])

    # Save last op
    if current_op and current_desc:
        catalog[current_op["name"]] = {
            "signature": current_op["signature"],
            "description": " ".join(current_desc)[:400],
            "category": current_op.get("category", "base"),
            "params": current_op.get("params", ""),
        }

    return catalog


def _get_uncrawled_urls(pages: dict) -> list:
    crawled = {data.get("url", "") for data in pages.values()}
    found = set()
    for data in pages.values():
        for lnk in data.get("new_links", []):
            url = lnk.get("url", "")
            if url and url not in crawled and "/learn/" in url:
                found.add(url)
    return sorted(found)[:30]


if __name__ == "__main__":
    pages = load_all_pages()
    print(f"Loaded {len(pages)} pages")

    kb = build_kb(pages)

    kb_path = ROOT / "data" / "wq_knowledge_base.json"
    kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*70}")
    print("FINAL KNOWLEDGE BASE BUILT")
    print(f"  Pages: {kb['crawled_pages']}")
    print(f"  Official examples: {len(kb['official_alpha_examples'])}")
    print(f"  Derived ideas: {len(kb['derived_alpha_ideas'])}")
    print(f"  Alpha patterns: {len(kb['alpha_patterns'])}")
    print(f"  Operators documented: {len(kb['operator_catalog'])}")
    print(f"  Best practices: {len(kb['best_practices'])}")
    print(f"  Data fields cataloged: {sum(len(v) for v in kb['data_field_catalog'].values())}")
    print(f"\nSaved to: {kb_path}")
    print(f"File size: {kb_path.stat().st_size / 1024:.1f} KB")

    print(f"\n{'='*70}")
    print("OFFICIAL ALPHA EXAMPLES:")
    for i, ex in enumerate(kb["official_alpha_examples"], 1):
        print(f"  {i:>2}. [{ex['priority']:<6}] [{ex['category']:<14}] {ex['expression']}")
        print(f"      {ex['hypothesis'][:80]}")

    print(f"\n{'='*70}")
    print("ALPHA PATTERNS:")
    for p in kb["alpha_patterns"]:
        print(f"  [{p['priority']:<6}] {p['pattern_name']:<30} turnover={p['expected_turnover']}")
        for ex in p["examples"][:3]:
            print(f"    {ex}")

    print(f"\n{'='*70}")
    print(f"Submission criteria thresholds:")
    for check, info in kb["submission_criteria"]["tests"].items():
        threshold = info.get("threshold_delay1") or info.get("threshold") or info.get("formula", "")
        print(f"  {check:<25}: {threshold}")
