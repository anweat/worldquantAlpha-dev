# Changelog

## [Phase 4] — Doc Manifest + Sub-agent 自主取文 + Web 控制台

### 新增功能

- **Doc Manifest**：`docs/manifest.yaml` 手写元数据 + `scripts/manifest_builder.py` 扫描合并 →
  `docs/manifest.generated.yaml`。`src/wq_bus/ai/doc_manifest.py` 按 mode+tag 过滤。
  `alpha_gen` 三个 prompt 模板（fragments/explore/repair）增加 OPTIONAL DEEPER CONTEXT 段，
  Copilot CLI sub-agent 通过 `view <path>` 自主取文，prompt 体积减约 60%。
- **`wqbus manifest build / show`** CLI。
- **Web 控制台**：`web/server.py` + `web/static/`，`wqbus web --port 8765` 启动，
  仅 localhost 监听，展示队列 / trace / AI 用量 / 一键触发。
- **Coordinator**：`src/wq_bus/coordinator/{goal,runner}.py` —
  多 agent goal-loop pipeline，按 `config/tasks.yaml` 串接任务。
- **Fragment 管线**：`alpha_combiner`（fragment 编译 + 参数扫描 + group_rank 变体）+
  `alpha_mutator`（IS 失败后变异回环）。
- **Robots.txt 守门**：`crawler/robots.py`，所有 `CRAWL_REQUESTED` 通过 robots 检查。
- **API 健康看门狗**：`agents/api_healthcheck.py` + `wqbus health`，按 auth/simulate/untested_alpha
  探测 BRAIN，发 `API_DEGRADED/RESTORED` 自动 gate alpha_gen + submitter。
- **Topic-meta + Prompt-registry**：`bus/topic_meta.py` 持有 task_kind / critical 元数据；
  `ai/prompt_registry.py` 模板注册中心；`ai/ai_service.py` 抽象 prompt 调用层。
- **Context Curator**：`ai/context_curator.py` 智能裁剪上下文体积。
- **Sub-agent Pack**：`config/prompts/_subagent_pack.alpha_gen.md` 等，
  把固定指令从主 prompt 抽出复用。

### Bug 修复

修复来自三轮外审的累计约 50 个 bug：

- `parents[4] → parents[3]` 路径深度修正（cli + pdf_pipeline）
- `analyst_portfolio → portfolio_analyzer` agent 名统一
- `_subagent_pack` 中字段映射补 6 个 tag
- `asyncio.run()` 加 `if __name__ == "__main__"` 保护
- `COALESCE` 参数顺序 `(old,new) → (new,old)` 修复 KB 更新覆盖
- `create_task` 包 try/except RuntimeError，loop 已关闭场景不崩
- 改 `Semaphore` 为 `async with` 防 CancelledError 泄漏槽位
- `batch_buffer` flush 失败保留 payload 不丢
- `daemon_main` 启动调用 `ensure_migrated()`
- `build_state` / `_topic_cooldown` / DB 错误处理强化
- HTTP `raise_for_status()` 调用顺序修正
- `overfitting_signals` 从 yaml 读
- pattern_extractor 用标准 `setdefault`
- `dispatcher.py` DB 错误吞没 → 改成保守阻塞（避免 daily_cap 绕过）
- `tasks.py` `_HANDLES` 孤儿泄漏 + emit 失败兜底
- `event_bus._maybe_close_trace` DB 读失败 → 兜底标 running
- `sim_executor` Condition.wait 超时 + `_pressure_restore_task` 不再 fire-and-forget
- 嵌套 semaphore 死锁、adapter API 调用超时
- `submission_queue` 大小限制
- `executemany` chunking
- **Copilot CLI timeout 120 → 300s**（claude-sonnet-4.6 + sub-agent view 真实可达 200s）
- **`ai_service.py` 模板变量缺失兜底**：strict-render 前自动给所有 declared 变量填空字符串，
  新增 prompt 变量不再让 buffered AI_CALL_REQUESTED 全部失败
- **rate_limiter 计数源澄清**：`state.db.ai_calls`（不是 knowledge.db），重置 cap 走对表

### 测试

- `scripts/smoke_full.py` 端到端冒烟（stub AI 适配器）
- `scripts/smoke_fragment_pipeline.py` fragment 管线
- `scripts/test_alpha_combiner.py` / `test_alpha_mutator.py`
- `scripts/test_rate_cap.py` 速率上限边界
- `scripts/boundary_tests.py` B1-B12 边界覆盖

### 文档

- `docs/architecture/AGENT_INTERFACE.md` / `AI_DISPATCHER.md` / `BUS_ARCHITECTURE.md` /
  `COMPOSITION_RECIPES.md` / `EVENT_CATALOG.md` / `SIMULATION_POOL.md` /
  `TRACE_AS_TASK.md` / `EXPORT_FORMATS.md`
- `docs/12_community_insights_and_alpha_experience.md` 社区经验
- `docs/13_alpha_defects_and_community_wisdom.md` 常见缺陷
- 更新 `.github/copilot-instructions.md` 加 R1-R6 工作区交互规则

### 实测端到端验证（trace `tr_20260428T062209Z_505fcc`）

- 4 次 AI 调用全 success（175s + 122s）
- Sub-agent 实测自主调用 `List directory memory\usa_top3000` → `Read dataset_insights.md` + `portfolio.json`
- 40+ ALPHA_DRAFTED → 4 simulated（最佳 sharpe=0.94）
- 整链路 events / ai_calls / alphas / queue 全部一致

---

## [Phase 1-3] — wq-bus 总线重构（Wave A-D + 三轮 review）

### Wave A — 核心基础设施

- `bus/topic_registry.py`：`register_topic()` / `is_registered()` 动态注册
- `bus/events.py`：refactor 加 `TASK_STARTED/COMPLETED/FAILED/TIMEOUT/CANCEL_REQUESTED`、`POOL_UPDATED`
- `bus/tasks.py`：`start_task()` 返回 `TaskHandle`（`.wait/.on_complete/.on_fail/.cancel`）
- `bus/supervisor.py`：trace 超时检测后台 supervisor

### Wave B — Agent 协议 + 数据层

- `agents/base.py`：enforcement field + `_safe_handle` wrapper
- `data/workspace.py`：`ensure / build_context / upsert_direction / bump_stats`
- `domain/dimensions.py`：`classify()` + `project_id()` — 5-key 特征向量
- `domain/recipes.py`：`ensure_seeds / match / hint_for_theme`
- `ai/strength.py`：`StrengthRouter`（override→exact→wildcard→default）+ TTL
- `ai/cache.py`：`PackageCache` 原子 stage（queued→sent→received→unpacked→done/failed）

### Wave C — AI 路由 + 策略 + 模式

- `ai/dispatcher.py` v2：单入口 `call(agent_or_pkg, payload, *, source, force_immediate)`，
  StrengthRouter → BatchBuffer（按 (adapter, strength) 桶）→ PackageCache → adapter；
  全局 `Semaphore(4)`；`daily_ai_cap` 仅对 `source="auto"` 校验；一次重试
- `bus/policies/default_stockpile.py`：4:2:1:1 base + 自适应 bump（high SC → 2× explore）+
  hard floors（queue/in-flight/daily/cooldown）
- `agents/alpha_gen.py`：4 mode（explore/specialize/review_failure/track_news），
  `_classify_and_register` 链入 dimensions + recipes + workspace；
  `ALPHA_DRAFTED` 携 `direction_id/themes_csv/mode`

### Wave D — CLI / Scripts / Docs

- `agents/doc_summarizer.py`：移除自循环 bug（旧版无限 re-emit DOC_FETCHED）
- 新增 `wqbus drain-docs / task / trace-tree / db migrate`
- `scripts/simulate_ai.py` 确定性 stub
- `scripts/smoke_full.py` 端到端
- `docs/architecture/EVENT_CATALOG.md` Phase 1 完成清单

### 三轮外审修复

总计约 60 处问题；详见 git log:
- `d3cea46` round 1 (~26 fixes)
- `1ccbdcd` round 2 (13 fixes + 6 false positive + 10 deferred)
- `d72c29c` round 3 (16 fixes + 9 false positive / deferred)
- `7245c67` 清理遗留 + 死 agent_profiles 项

---

## [Phase 0] — 初始

- `4eebfd0` first commit
- `a621fe8` Operators Reference + Comparison pages
