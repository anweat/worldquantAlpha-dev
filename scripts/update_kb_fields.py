"""Update KB with all 2663 discovered data fields and generate alpha ideas."""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
from datetime import datetime

ROOT = Path(r"D:\codeproject\worldquantAlpha-dev")
FIELDS_FILE = ROOT / 'data/all_data_fields.json'
KB_FILE = ROOT / 'data/wq_knowledge_base.json'

# Load all fields
all_data = json.loads(FIELDS_FILE.read_text(encoding='utf-8'))
fields = all_data['fields']

# Categorize
cats = {}
for k in fields:
    prefix = k.split('_')[0]
    if prefix not in cats:
        cats[prefix] = []
    cats[prefix].append(k)

# Load KB
kb = json.loads(KB_FILE.read_text(encoding='utf-8'))

# Update data fields section
kb['data_fields_catalog'] = {
    'total': len(fields),
    'crawled_at': datetime.now().isoformat(),
    'categories': {k: len(v) for k, v in sorted(cats.items(), key=lambda x: -len(x[1]))},
    'all_field_ids': sorted(fields.keys()),
}

# Add structured field reference
kb['premium_fields'] = {
    'fscore': {
        'description': 'Pre-built Piotroski-style quality/value/momentum scores',
        'fields': [k for k in fields if k.startswith('fscore')],
        'usage': 'rank(fscore_total) + MARKET/INDUSTRY. Also group_rank(fscore_total, sector)+NONE',
        'expected_performance': 'Sharpe 1.5-2.5, TO 2-10%',
        'notes': 'fscore_bfl_total = BFL composite, fscore_total = standard composite'
    },
    'rp_css': {
        'description': 'RavenPack Composite Sentiment Scores by news category',
        'fields': [k for k in fields if k.startswith('rp_css')],
        'usage': 'ts_rank(rp_css_earnings, 20) + INDUSTRY',
        'expected_performance': 'Sharpe 1.0-1.8, TO 30-60% (high turnover - use decay)',
        'notes': 'Event-driven signals. rp_css_insider/earnings/credit_ratings most predictive'
    },
    'pcr_oi': {
        'description': 'Put/Call Ratio by open interest at various maturities',
        'fields': [k for k in fields if k.startswith('pcr_oi')],
        'usage': 'rank(-pcr_oi_30) + INDUSTRY (contrarian: low PCR = bullish)',
        'expected_performance': 'Sharpe 0.8-1.5, TO 10-30%',
        'notes': 'Contrarian signal. Use 30-120d maturities. group_rank for sector-neutral'
    },
    'implied_vol': {
        'description': 'Implied volatility (call) at various maturities',
        'fields': [k for k in fields if k.startswith('implied_volatility_call')],
        'usage': 'implied_volatility_call_120/parkinson_volatility_120 + SECTOR + TOP200',
        'expected_performance': 'Sharpe 1.0-1.5 on TOP200',
        'notes': 'Term structure: call_120/call_30 for slope alpha. Use smaller universes'
    },
    'snt1': {
        'description': 'Sentiment1 dataset: analyst estimates + earnings surprises + sentiment',
        'fields': [k for k in fields if k.startswith('snt1')],
        'usage': 'ts_rank(snt1_d1_stockrank, 20) + INDUSTRY + TOP1000 + decay=2',
        'notes': 'Coverage ~2000 stocks. stockrank, earningsrevision, netrecpercent are key'
    },
    'pv13_hierarchy': {
        'description': 'Revere supply-chain hierarchy groupings (use as GROUP parameter)',
        'fields': [k for k in fields if k.startswith('pv13') and 'hierarchy' in k][:10],
        'usage': 'group_rank(expr, pv13_hierarchy_min10_sector)',
        'notes': 'Alternative grouping to sector/industry. Revere supply-chain classification'
    },
    'nws12': {
        'description': 'News dataset with event-level data (vector fields)',
        'fields': [k for k in fields if k.startswith('nws12')][:20],
        'usage': 'ts_rank(vec_count(nws12_afterhsz_120_min), 20) + INDUSTRY + decay=4',
        'notes': 'Vector type - MUST use vec_count/vec_avg etc. Raw TO=130-200%'
    },
    'fnd6': {
        'description': 'Compustat fundamental data (838 fields - most comprehensive)',
        'sample_fields': [k for k in fields if k.startswith('fnd6')][:20],
        'notes': 'Abbreviated field names. Most are quarterly/annual financial items'
    }
}

# Add alpha ideas for next batches
kb['alpha_ideas_new'] = {
    'batch6_priority_HIGH': [
        {'expr': 'rank(fscore_total)', 'settings': 'MARKET/decay4', 'rationale': 'Pre-built composite quality score'},
        {'expr': 'group_rank(fscore_total, sector)', 'settings': 'NONE', 'rationale': 'Sector-relative quality'},
        {'expr': 'rank(fscore_bfl_total)', 'settings': 'INDUSTRY', 'rationale': 'BFL composite quality'},
        {'expr': 'ts_rank(rp_css_earnings, 20)', 'settings': 'INDUSTRY', 'rationale': 'Earnings news momentum'},
        {'expr': 'ts_rank(rp_css_insider, 20)', 'settings': 'MARKET', 'rationale': 'Insider trading news'},
        {'expr': 'rank(-pcr_oi_30)', 'settings': 'INDUSTRY', 'rationale': 'Low put/call = bullish contrarian'},
        {'expr': 'rank(snt1_d1_stockrank)', 'settings': 'INDUSTRY+TOP1000', 'rationale': 'Sentiment stock rank'},
        {'expr': 'ts_rank(snt1_d1_earningsrevision, 63)', 'settings': 'INDUSTRY+TOP1000', 'rationale': 'Earnings revision momentum'},
    ],
    'batch7_next': [
        {'expr': 'group_rank(fscore_total + fscore_bfl_total, sector)', 'settings': 'NONE'},
        {'expr': 'rank(fscore_quality * fscore_value)', 'settings': 'INDUSTRY'},
        {'expr': 'group_rank(ts_rank(rp_css_earnings + rp_css_revenue, 63), sector)', 'settings': 'NONE'},
        {'expr': 'rank(-pcr_oi_30 + fscore_total)', 'settings': 'INDUSTRY', 'rationale': 'Options+quality combo'},
        {'expr': 'group_rank(rp_css_credit_ratings, sector)', 'settings': 'NONE'},
    ]
}

KB_FILE.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"KB updated! Size: {KB_FILE.stat().st_size // 1024}KB")
print(f"Total fields cataloged: {len(fields)}")
print(f"\nTop categories:")
for cat, count in sorted(cats.items(), key=lambda x: -len(x[1]))[:15]:
    print(f"  {cat}: {count}")
