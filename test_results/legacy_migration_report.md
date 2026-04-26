# Legacy Migration Report

**Generated**: 2026-04-26T18:00:48Z  
**Trace ID**: `tr_legacy_migration_1777226446`  
**Mode**: LIVE  

---

## Discovery Summary

| Type | Count |
| --- | --- |
| SQLite DBs | 4 |
| JSON files | 249 |
| Markdown files | 16 |
| PDF files | 2 |

### JSON Bucket Breakdown

| Bucket | Count |
| --- | --- |
| alpha-list | 94 |
| crawl-doc | 132 |
| failure | 4 |
| pipeline-state | 5 |
| portfolio | 5 |
| submission-queue | 3 |
| unknown | 6 |

### DB Contents

**archive\2026-04-26_pre_bus\data_and_memory\alpha_kb.db**
- `alphas`: 1256 rows
- `expr_hashes`: 1886 rows
- `daily_stats`: 2 rows
- `learnings`: 65 rows
- `submission_queue`: 104 rows

**archive\2026-04-26_pre_bus\data_and_memory\crawl_state.db**
- `crawl_queue`: 89 rows
- `crawl_links`: 0 rows
- `alpha_ideas`: 0 rows

**archive\2026-04-26_pre_bus\data_and_memory\memory_kb.db**
- `memories`: 0 rows
- `memory_changelog`: 4 rows

**archive\2026-04-26_pre_bus\data_and_memory\unified_kb.db**
- `crawl_queue`: 89 rows
- `crawl_links`: 0 rows
- `alphas`: 1256 rows
- `expr_hashes`: 1256 rows
- `submission_queue`: 0 rows
- `learnings`: 0 rows
- `daily_stats`: 2 rows
- `alpha_ideas`: 0 rows

---

## Alpha Migration

| Source | Found | Inserted | Skipped |
| --- | --- | --- | --- |
| alpha_kb.db | 1256 | 1256 | 0 |
| unified_kb.db | 1256 | 1256 | 0 |
| unsubmitted_alphas_all.json | 135 | 135 | 0 |
| unsubmitted_alphas.json | 100 | 100 | 0 |

**Total alphas inserted**: 2747

---

## Crawl Doc Migration

| Source | Found | Inserted |
| --- | --- | --- |
| Legacy DBs (crawl_queue) | 89 | 89 |
| JSON crawl files | 45 | 45 |
| MD files (crawl keyword) | 1 | 1 |

**crawl_summaries placeholders**: 1  
**Next step**: `wqbus drain-docs --dataset USA_TOP3000 --max-batches 5`

---

## Session Migration

- session.json: already in .state/ (legacy source not found)
- credentials.json: already in .state/ (legacy source not found)
- Auth check: `session_file_readable_with_cookies`

---

## File Copies

- Markdown files copied to `memory/_legacy/`: 16
- PDF files copied to `data/legacy/pdfs/`: 2

---

## Summary

| Metric | Value |
| --- | --- |
| Alphas inserted | 2747 |
| Crawl docs inserted | 135 |
| Crawl summary placeholders | 1 |
| MD files copied | 16 |
| PDF files copied | 2 |
| Total errors | 0 |
