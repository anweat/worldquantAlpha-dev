# Phase 2 Plan — Polish, Recipe Synthesis, Real Run

## Problem
Phase 1 architecture stable. Now must (a) close functional gaps so真实生成-回测-总结闭环, (b) run real cycle to hit 12 IS+SC-passing alphas as a stress test, (c) audit every agent's context bundle for completeness, (d) prompt-tune to drive 10% submit rate.

## Approach
Three sequential waves. T1 = fix gaps; T2 = real run; T3 = audit + tune.

---

## Wave T1 — Functional Completeness (must finish before real run)

### T1-A `006_recipe_review.sql`
ALTER `composition_recipes` ADD: `status TEXT DEFAULT 'approved'` (seeds=approved by default), `proposed_by TEXT`, `proposed_at TEXT`, `reviewed_by TEXT`, `reviewed_at TEXT`, `review_notes TEXT`, `support_count INTEGER`, `sample_alpha_ids_json TEXT`. Idempotent ALTERs.

### T1-B `legacy_status_fix`
`scripts/fix_legacy_status.py`: re-mark all alphas under trace prefix `tr_legacy_migration_*` from 'submitted' → 'legacy'. Add 'legacy' to allowed status enum. Update queue/budget logic to ignore legacy when counting "today submitted".

### T1-C `core_pattern_extractor`
`src/wq_bus/domain/pattern_extractor.py`:
- `strip_wrappers(expr)` removes outer cosmetic wrappers (rank/group_rank/zscore/scale/winsorize/decay_linear/quantile/normalize) recursively until content stable
- `extract_core_tokens(expr)` returns canonical core form + field set + operator set
- `group_repeated_cores(alphas, min_support=3)` returns `[{core_form, support, sample_alpha_ids, top_metrics, direction_ids}]`
- CLI: `wqbus recipe extract --tag USA_TOP3000 --min-support 3 --out data/recipe_candidates_<TAG>.json`

### T1-D `doc_summarizer_modes`
Refactor `agents/doc_summarizer.py` to multi-mode dispatcher:
- mode `crawl_summary` (existing, was `batch`) — INPUT: pending crawl_docs, OUTPUT: prose summary → crawl_summaries
- mode `recipe_synthesis` — INPUT: recipe_candidates JSON, OUTPUT: `{recipe_id, semantic_name, pattern_regex, theme_tags, economic_hypothesis, sample_alpha_ids}` → composition_recipes(status='proposed')
- mode `failure_synthesis` — INPUT: recent N failures (BRAIN errors + SC fails), OUTPUT: pattern list + mutation_tasks → memory/<TAG>/failure_patterns.json
- mode `portfolio_review` — INPUT: pool_stats + direction histogram + correlation summary, OUTPUT: overcrowded/gap directions + suggestions → memory/<TAG>/portfolio_analysis.json
Triggered by topics: `DOC_FETCHED` (crawl), `RECIPE_CANDIDATES_READY` (synthesis), `FAILURE_BATCH_READY` (>=10 failures), `POOL_STATS_UPDATED` (portfolio, throttled). Strength routing per mode in agent_profiles.yaml.

### T1-E `recipe_review_cli`
`wqbus recipe list --status proposed`, `wqbus recipe show <id>`, `wqbus recipe approve <id> [--notes]`, `wqbus recipe reject <id> --reason X`, `wqbus recipe diff <id>` (show what new alphas would be matched). alpha_gen consumes only `status='approved'` (where seeds default to approved); `proposed` requires manual approval before influencing generation.

### T1-F `copilot_noninteractive_guard`
- Add `--allow-all-tools --no-color` (verify flags exist via `copilot --help` capture)
- Append `WQBUS_NONINTERACTIVE=1` env, `CI=1`, `COPILOT_NO_TELEMETRY=1`
- Boot validator: `scripts/check_copilot_cli.py` runs a 1-token probe and refuses to start daemon if it stalls > 30s
- Document in README: how to first-time login the CLI before using daemon

### T1-G `triggers_yaml_extension`
config/triggers.yaml — add the 3 new topics (`RECIPE_CANDIDATES_READY` / `FAILURE_BATCH_READY` / `POOL_STATS_UPDATED`) with cooldown + min_batch settings. Watchdog policy: when `pending_failures >= 10` emit FAILURE_BATCH_READY; when `pool_stats updated >=20 new directions` emit POOL_STATS_UPDATED; when extractor writes recipe_candidates emit RECIPE_CANDIDATES_READY.

### T1-H verify
- All 12 boundary tests still PASS
- `wqbus db migrate` applies 006 cleanly
- Smoke 5 round still PASS
- New CLI commands produce expected output

---

## Wave T2 — Real Generation Run (target 12 IS+SC PASS)

Budget: `daily_ai_cap=80`, `simulate_budget=300`, dataset=USA_TOP3000.

### T2-pre-A WQ truth sync (`scripts/sync_wq_submitted.py`)
GET /users/self/alphas (paginated) → reconcile local `status` with platform truth. Set local status=submitted ONLY for IDs WQ returns. Drift goes to `test_results/wq_drift_<ts>.json` for review.

### T2-pre-B 429 adaptive policy
BrainClient: on 429 → exp backoff w/ jitter (cap 60s). Track 429 rate per 5min; if >20% emit `RATE_PRESSURE` → sim_executor temporarily reduces concurrency Semaphore 3→1 for 10min then auto-restore.

### T2-pre-C live tail (`scripts/live_tail.py`)
Tail logs/*.log + ai_calls (last 10 every 30s with prompt preview); 10min snapshots → `test_results/realrun_snapshots/`. Show: agent×mode×strength×duration×status.

### T2-pre-D similarity review (`scripts/similarity_review.py`)
For pairs sc_value≥0.5 list expressions side-by-side; `--auto-mark-duplicate` flags (does not delete). Used when SC numbers look suspicious — Copilot can step in to judge ambiguous pairs.

### T2-A pre-flight
- `BrainClient.check_auth()` == True
- AI cache empty / packages all in 'consumed' or 'failed' (no stuck 'sent')
- Reset daily counter for clean accounting
- Snapshot: alphas count, ai_calls count, trace count

### T2-B run
- Start daemon: `python -m wq_bus.cli daemon start --bg`
- Manual seed: emit `ALPHA_GEN_REQUESTED` × 3 with mode=high (one per dimension batch)
- Watchdog auto-fires gen on queue empty; sim_executor runs simulations; submitter checks SC and submits passing
- Stop conditions: 12 alphas with `status='is_passed'` AND SC≥0.7 (whatever the bar is) OR sim budget exhausted OR 90 min wall clock

### T2-C live monitoring (every 10 min)
- `wqbus monitor` snapshot → `test_results/realrun_snapshots/<ts>.json`
- AI freq monitor → 0 alarms required
- traceability audit on last 30 traces
- if any agent silent > 15 min → kick a manual emit

### T2-D post-run
- Run extractor → propose recipes → approve worthwhile ones manually
- Run doc_summarizer in `failure_synthesis` and `portfolio_review` modes
- Generate `test_results/realrun_report.md`: pass rate, time per alpha, AI calls per alpha, top failure causes, recipe candidates surfaced

---

## Wave T3 — Context & Prompt Polish

### T3-A context audit
For each agent (`alpha_gen`, `failure_analyzer`, `doc_summarizer`, `portfolio_analyzer`):
- Dump exact context bundle that was sent in T2 (from ai_calls.prompt_text)
- Score on 5 dims: (1) recent passing alphas of same direction, (2) recent failures with cause, (3) frequency stats / coverage map, (4) gap directions, (5) recipe hints
- Output `test_results/agent_context_audit.md` with concrete gaps

### T3-B prompt refactor
Based on audit, edit `config/prompts/<agent>.yaml`:
- alpha_gen: must show "已知该方向高分模板 / 你不能复用的表达式 / 待探索的 gap dim / 可用 recipe hint"
- failure_analyzer: must show "失败分组 / 同类成功对比 / 推荐变异方向"
- portfolio_review: must show "总览拥挤度 / 相关性簇 / 过去 7 天进度"
Principle: 不增加新 mode，只优化每个 mode 的输入打包与输出 schema。

### T3-C 2nd run for delta
- Same budget as T2 but with new prompts → compare submit-rate
- Goal: ≥10% submit rate (alphas that pass IS+SC out of total simulated)

---

## SQL Todos
See `todos` table inserts.

## Notes
- Strength stays centralized; agents do NOT participate in routing.
- Recipe `proposed` must NOT influence gen until human/auto-approved.
- Legacy alphas count as historical reference, not as fresh submissions.
- Real run is the acceptance test; 12 PASS not optional unless budget runs out + clear cause.
