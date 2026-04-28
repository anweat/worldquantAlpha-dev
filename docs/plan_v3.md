# wq-bus 重构 — 整合后的设计与改造计划 (v3)

> 这份是 v2/v2.1/v2.2/v2.3 反复迭代后的**干净版本**，去掉历史包袱，给你一次完整 review。
> 旧 plan.md 仍保留作为讨论历史备份，本文件是新的源真相。

---

## 1. 已落地的事实（不动）

- **总线架构已经是 asyncio pub/sub + topic events + handlers**：保持不变，本次重构在它之上扩展，不替换。
- **数据层**：`data/state.db`（运行态：events / queue / ai_calls / locks / trace） + `data/knowledge.db`（沉淀：alphas / fingerprints / pnl_series / learnings / crawl_docs / crawl_summaries）。已落地。
- **trace_id 链路**：当前 trace 表已有，记录 ai_call 的 prompt/response。本次扩展（见 §6）。
- **自动登录**：`wq_bus.brain.auth` + `wqbus login` + start.ps1 pre-flight。已落地。
- **Self-correlation 修复**：`is.checks` 中 SC 字段优先 result 枚举，PENDING 不再乐观放行。已落地。
- **Copilot CLI 子进程崩溃修复**：CREATE_NO_WINDOW + DEVNULL stdin。已落地。
- **BRAIN 并发限流**：sim_executor 内 Semaphore(3)，可经 submission.yaml 调。已落地。
- **旧代码归档**：`archive/2026-04-26_pre_bus/`。已完成。

---

## 2. 这次要解决的问题（动机）

1. **AI 调用过密**：上轮 daemon 15 min 烧 11 calls。watchdog 60s tick 看到 queue=0 就 emit GENERATE，BRAIN 429 卡住时也算"空"；doc_summarizer 把 71 篇历史 docs 当新货反复触发；crawler agent 实际不存在但 config 里写了。
2. **触发逻辑死板**：单一规则触发，无法表达"探索 vs 专精 vs 复盘 vs 追热点"等不同 alpha 生成意图。
3. **模拟池缺失**：没有方向/维度的池化记账，无法统计某方向的探索深度/广度，watchdog 无依据决定下一步该 explore 还是 specialize。
4. **AI 成本控制粗糙**：所有 agent 各自调 AI，未做按 billing_mode 区分的合并；手动调用也计 cap。
5. **跨 agent 协作链不清**：subagent 内部反馈没有标准 chain_hook；trace 只覆盖单次 AI call，不覆盖整个 task。
6. **数据集隔离弱**：没有"工作区"概念，多 dataset 共表易污染。
7. **接口契约缺**：未来加 dataset_analyst、python 数据分析 agent 等没有标准 spec 可依。

---

## 3. 设计原则（不可妥协）

1. **总线本身不变**：所有新东西都是总线上的事件流 + handler。
2. **dataset_tag 一统**：tag 命名规则=`<region>_<universe>`（如 `USA_TOP3000`）。所有事件 payload 必带 tag；agent context 必带完整 dataset 索引。
3. **手动 vs 自动 AI 调用要分账**：手动 CLI 触发不计 daily cap；自动触发计入。
4. **billing_mode 决定 dispatcher 行为**：per_call（copilot_cli）启用打包/合并；per_token（openai/glm）直发。
5. **接口契约先于功能**：先写 docs/architecture/AGENT_INTERFACE.md 和 SIMULATION_POOL.md，再写代码。
6. **trace 是通用 task 容器**：不再只是 AI call 链路，而是任何"一个完整任务"的事件容器。
7. **绝不引入新的并行模型**：subagent 内部串行（chain_hook），dispatcher 全局并行 ≤ 4。

---

## 4. 概念词典（避免再混淆）

| 概念 | 定义 | 触发源 | trace 行为 |
|---|---|---|---|
| **基础 pipeline** | sim → IS 阈值 → 触发 gen agent 的常驻流程 | watchdog 后台决策 | 每轮 watchdog 起新 trace |
| **crawler 扫描** | 常驻轮询，topic 文档量达阈值时触发 doc_summarizer | 后台轮询周期 | 每个扫描周期起新 trace |
| **手动 task** | CLI / 总线一次性事件，可指定 URL+目标+是否总结 | `wqbus task ...` | 用户/CLI 显式起新 trace |
| **subagent task package** | 同一次 AI 调用内打包多个 agent 目标 + prompts；仅 per_call 启用 | dispatcher 内部 | 共享父 trace，子任务起 sub_trace |
| **chain_hook** | subagent A 输出反馈给主 agent 用于生成 subagent B 的 prompt | dispatcher 内部 | 串行 sub_trace 链 |
| **workspace** | 一个 dataset_tag 对应的表/目录/记忆文件集合 | 首次见到 tag 自动 ensure | — |

**注意区分**：`agent` ≠ `task` ≠ `subagent`。Agent 是常驻的事件订阅者；task 是一次执行单元（trace 容器）；subagent 是 dispatcher 在一次 AI call 内对多任务的拆分。

---

## 5. 模拟池设计（最终版）

### 5.1 模型概念（确认版）

```
维度 (Dimensions) — 硬编码、有限、可枚举
  data_field_class | operator_class | neutralization | decay_band | turnover_band

方向 (Direction) — 两种合法形式可共存
  ① 轴向投影     {data_field_class=..., neutralization=..., decay_band=...}
  ② 自由描述     "用 ts_corr 把成交量与收益率做60日相关后行业中性化"

提取/转换（保留原始 + 衍生表述，不丢源）
  alpha → 解析器(硬编码)        → 维度向量 → 前 K 维投影 = direction_id
  自由描述 → LLM 解析           → 维度向量
  alpha 集合 → LLM 聚合          → 新自由描述（登记为新 seed）
```

**核心原则：原始信息绝不覆写**。alpha 表保留原始 expression / settings / pnl；direction 入库时同时记 raw_description（如有）+ 自动提取的维度向量。

### 5.2 维度定义（硬编码可读）

`src/wq_bus/domain/dimensions.py`：
```python
DATA_FIELD_CLASSES = ["fundamental.ratio", "fundamental.absolute",
                     "price", "volume", "technical", "macro", "other"]
OPERATOR_CLASSES   = ["rank", "group_rank", "ts_basic", "ts_corr",
                     "arith", "logical", "winsorize", "other"]
NEUTRALIZATION     = ["NONE", "MARKET", "SECTOR", "INDUSTRY",
                     "SUBINDUSTRY", "COUNTRY", "STATISTICAL"]
DECAY_BAND         = ["0", "1-4", "5-15", "16-30", ">30"]
TURNOVER_BAND      = ["<5%", "5-30%", "30-70%", ">70%"]

PROJECTION_DIMS = ["data_field_class", "operator_class",
                  "neutralization", "decay_band"]   # 前 4 维做 direction_id
```

字段→class 映射来自 `config/datasets.yaml`（已有可扩）。

### 5.3 schema（动态多表，每 dataset_tag 一套）

```sql
-- migration 003，首次见到 dataset_tag 自动 ensure
CREATE TABLE directions_<TAG> (
  direction_id      TEXT PRIMARY KEY,           -- 前 4 维投影拼接，如 "fundamental.ratio|rank|SUBINDUSTRY|0"
  semantic_name     TEXT,                       -- 人读 slug
  raw_description   TEXT,                       -- 原始自由描述（形式②输入时保留；形式①时为 NULL）
  origin            TEXT,                       -- seed | auto_extract | manual | llm_aggregate
  feature_vector_json TEXT,                     -- 完整多维向量（含 turnover_band 等未投影维度）
  example_alpha_ids TEXT,                       -- JSON array，本方向下代表性 alpha
  created_at        TEXT,
  updated_at        TEXT
);

CREATE TABLE pool_stats_<TAG> (
  direction_id     TEXT PRIMARY KEY REFERENCES directions_<TAG>(direction_id),
  alphas_tried     INTEGER DEFAULT 0,
  alphas_is_passed INTEGER DEFAULT 0,
  alphas_submitted INTEGER DEFAULT 0,
  avg_self_corr    REAL,
  avg_sharpe       REAL,
  avg_fitness      REAL,
  depth            REAL,                        -- alphas_tried 标准化
  breadth          REAL,                        -- distinct fingerprints / sub-cluster count
  status           TEXT,                        -- active|saturated|abandoned|hot
  last_explored_at TEXT
);

-- alphas 表加列（保留 expression/settings 原始字段）
ALTER TABLE alphas ADD COLUMN direction_id TEXT;
ALTER TABLE alphas ADD COLUMN feature_vector_json TEXT;
ALTER TABLE alphas ADD COLUMN cluster_id TEXT;   -- phase 3 才填
```

DAO `pool.upsert_direction(tag, ...)` / `pool.bump_stats(tag, direction_id, ...)` / `pool.list_active(tag, mode_filter)` / `pool.find_underexplored(tag, k)`。

### 5.4 direction_id 写入流程

```
alpha 产生 (alpha_gen)
  ↓ 写 alphas 表：原始 expression + settings 不动
  ↓ 调用 dimensions.classify(expression, settings) → feature_vector
  ↓ feature_vector → projection → direction_id
  ↓ pool.upsert_direction(tag, direction_id, feature_vector,
                          raw_description=prompt_hint, origin="auto_extract")
  ↓ pool.bump_stats(alphas_tried+=1)

sim_executor 完成
  ↓ pool.bump_stats(is_passed += 1 if 通过, avg_sharpe/fitness/self_corr 更新)

submit_pipeline
  ↓ pool.bump_stats(submitted += 1)
```

种子方向（origin=seed）写在 `config/directions_seed.yaml`，启动时 ensure 入库。

LLM 聚合产生的新方向（origin=llm_aggregate）由 dataset_analyst（phase 3）写入；phase 1 仅预留 origin 列。

### 5.5 cluster_id（phase 1 占位）

alphas.cluster_id 列空着；phase 3 clusterer agent 用 feature_vector + self_corr 矩阵填。

---

## 6. Trace 升级为 Task 容器

### 6.1 schema 变更（migration 004）

```sql
ALTER TABLE trace ADD COLUMN origin TEXT;           -- watchdog|crawler|manual_cli|dispatcher_pack
ALTER TABLE trace ADD COLUMN parent_trace_id TEXT;
ALTER TABLE trace ADD COLUMN task_kind TEXT;        -- generate|simulate|crawl|summarize|analyze|...
ALTER TABLE trace ADD COLUMN task_payload_json TEXT;
```

### 6.2 API

```python
bus.start_task(kind="generate", payload={...}, origin="watchdog", parent=None) -> trace_id
# 内部：写 trace 行 + 用 contextvars 设置 trace_id + emit 起始事件
```

后续在该 contextvar 下任何 emit 自动 attach trace_id。subagent_packer 用 `bus.start_task(parent=parent_trace, origin="dispatcher_pack")` 起子 trace。

### 6.3 CLI

`wqbus trace tree <id>` 输出父子 trace 树（含每个 task 的 ai_calls / events）。

---

## 7. AI Dispatcher 升级

### 7.1 行为按 adapter.billing_mode 分流

```yaml
# config/agent_profiles.yaml 示意
adapters:
  copilot_cli:    {billing_mode: per_call}
  openai_gpt5:    {billing_mode: per_token}
  glm_4_5:        {billing_mode: per_token}

agents:
  alpha_gen:        {adapter: copilot_cli, modes: [explore, specialize, review_failure, track_news]}
  failure_analyzer: {adapter: copilot_cli}
  doc_summarizer:   {adapter: copilot_cli}
```

- per_call → 启用 `batch_buffer`（同 agent_type N 秒/M 条合并） + `subagent_packer`（同 call 内多目标打包成 JSON 数组返回）
- per_token → 跳过打包，每任务独立 call

### 7.2 手动 vs 自动分账

- `dispatcher.call(..., source="manual"|"auto")`，manual 不计 daily_ai_cap
- CLI 触发统统 source=manual；watchdog/crawler 自动触发 source=auto

### 7.3 chain_hook（subagent 串行反馈）

task package schema 里允许声明：
```json
{
  "tasks": [
    {"id": "t1", "agent": "alpha_gen", "mode": "explore", "prompt_template": "..."},
    {"id": "t2", "agent": "failure_analyzer", "chain_hook": {"from": "t1", "transform": "summarize_low_fitness"}}
  ]
}
```

dispatcher 串行执行：t1 完成后用 transform 取 t1 输出 → 拼接进 t2 prompt → 调 t2。**全局并行度 ≤ 4**（不同 task package 之间并行；同一 package 内 chain 串行）。

### 7.4 重试与日志

prompt+response 全文落 ai_calls 表（已有）；失败/超时自动重试 1 次；连续失败标 `dead`（dead-letter 表 phase 2 加）。

---

## 8. WatchdogPolicy 抽象 + 动态加权

### 8.1 接口

```python
class WatchdogPolicy:
    def should_trigger(self, state: WatchdogState) -> list[BusEvent]:
        ...
```

`src/wq_bus/bus/policies/`：
- `default_stockpile.py`：本次 phase 1 主力实现
- 未来加 `dataset_analysis.py` 等

### 8.2 Default 策略：动态加权选 mode

输入：pool_stats（每 dataset 各方向）+ 队列大小 + 最近 N 轮触发分布。

```
权重计算（base 4:2:1, 自适应）：
  explore_w  = base.explore  * (1 - recent_explore_share)
  direction_w= base.direction* (1 - recent_direction_share)
  specialize_w= base.specialize*(1 - recent_specialize_share)

判定：
  if avg_self_corr > 0.6: bump explore_w
  if any direction has is_passed >= 5 and submitted < target: bump specialize_w
  if dataset alphas_tried < 50: bump explore_w
  weighted random pick mode → emit GENERATE_REQUESTED(mode=..., dataset_tag=...)
```

### 8.3 触发底线（硬约束）

- queue_pending < 2000（可配置 cap）
- in_flight_sims == 0（防止 BRAIN 429 时 watchdog 持续刷）
- cooldown 30min（每 dataset 各自冷却）
- daily_ai_cap 不可越过（自动调用计入；手动不计）

config: `config/triggers.yaml` 全部参数化。

---

## 9. Workspace（dataset 工作区）

### 9.1 自动 ensure

任何 agent 处理事件时如发现 dataset_tag 未注册：
- 调 `workspace.ensure(tag)`：建 `directions_<TAG>` + `pool_stats_<TAG>` 表；建 `memory/<TAG>/` 目录（insights.md / failure_patterns.json / portfolio.json 模板）；写入 `workspaces` 注册表
- tag 命名严格 `<region>_<universe>`（大写）

### 9.2 上下文索引

agent 调 AI 前 `context_index = workspace.build_context(tag)`：
- pool_stats summary（top directions + status）
- recent learnings（按 ts desc）
- recent crawl_summaries（按 ts desc）
- recent failures
- 直接拼进 system prompt

### 9.3 新 agent 必须声明 workspace_rules

`AGENT_INTERFACE.md` 强制要求：
```python
class MyAgent(AgentBase):
    workspace_rules = {
        "reads":  ["pool_stats", "learnings"],
        "writes": ["alphas", "pool_stats"],
        "memory_files": ["insights.md"],
    }
```

---

## 10. 文档先行（Phase 1 必出）

- `docs/architecture/AGENT_INTERFACE.md`：AgentBase 协议 / subagent task package schema (含 chain_hook) / workspace_rules schema / tag 命名规则 / context_index 协议 / topic 动态注册规则
- `docs/architecture/SIMULATION_POOL.md`：directions/pool_stats schema / direction_id 算法 / WatchdogPolicy 加权算法 / cluster_id 占位说明
- `docs/architecture/EVENT_CATALOG.md`：现有 13 topic + 动态注册说明
- `docs/architecture/TRACE_AS_TASK.md`：trace 升级为 task 容器的 API 与示例
- `docs/architecture/AI_DISPATCHER.md`：billing_mode 分流 + manual/auto 分账 + chain_hook 用法

---

## 11. doc_summarizer 修复

- 删 `daemon resume()` 中"看到 ≥1 pending doc 就 emit DOC_FETCHED"逻辑
- 删 doc_summarizer 自循环（"剩余 ≥ threshold 再 emit"）
- 新增 `wqbus drain-docs --max-batches N --dataset TAG` 手动消化历史
- 真正 DOC_FETCHED 唯一来源：phase 2 的 crawler agent

---

## 12. Phase 切分（不要超 phase 1 范围）

### Phase 1（本次）— 骨架 + 契约 + 触发改造
- docs 五份
- migration 003（pool）+ migration 004（trace 升级）
- topic 动态注册中心
- workspace ensure + AGENT_INTERFACE 协议落地（AgentBase 改造）
- alpha_gen modes={explore, specialize, review_failure, track_news} + direction_id 写入
- WatchdogPolicy 抽象 + DefaultStockpile 动态加权 + triggers.yaml
- dispatcher v2：billing_mode 分流 + manual/auto 分账 + chain_hook + 重试1次
- doc_summarizer 修复 + drain-docs CLI
- manual task CLI（`wqbus task <agent> ...`）
- bus.start_task API + trace tree CLI
- scripts/simulate_ai.py（fake adapter）+ scripts/smoke_full.py（端到端校验）
- README + EVENT_CATALOG 更新

### Phase 2 — Crawler + topic 分流 + dead-letter
- src/wq_bus/agents/crawler.py（订阅 CRAWL_REQUESTED + 常驻轮询）
- crawl_targets.yaml topic→tag 分流路由
- .secrets/crawl_accounts.yaml + cookie store
- PDF pipeline（大学账号下载）
- dead-letter 表 + replay CLI

### Phase 3 — 智能化 + cluster + dataset_analyst
- self_corr cluster_signature 计算 + 填 cluster_id
- clusterer agent
- dataset_analyst agent（python 代码动态分析）
- 增量加权策略升级（用 pool depth/breadth 决策）
- HTML dashboard（可选）

---

## 13. Phase 1 Todos（已写入 SQL）

按依赖顺序：

1. **docs-agent-iface** — `docs/architecture/AGENT_INTERFACE.md`
2. **docs-sim-pool** — `docs/architecture/SIMULATION_POOL.md`
3. **trace-as-task** — migration 004 + bus.start_task API
4. **topic-registry** — events.py 动态注册改造
5. **mig-003-pool** — migration 003 + DAO
6. **workspace-bootstrap** — workspace.ensure + 自动建表/目录
7. **triggers-yaml** — config/triggers.yaml
8. **watchdog-policy** — WatchdogPolicy 抽象 + DefaultStockpile
9. **dispatcher-v2** — billing_mode + manual/auto + chain_hook + 重试
10. **alpha-gen-modes** — 4 modes + subagent 拆分 + direction_id 写入
11. **doc-sum-fix** — 删自循环 + drain-docs CLI
12. **manual-task-cli** — `wqbus task ...`
13. **trace-tree-cli** — `wqbus trace tree <id>`
14. **simulate-ai** — `scripts/simulate_ai.py`
15. **smoke-full** — `scripts/smoke_full.py`
16. **docs-update** — README + EVENT_CATALOG

后置（不在 phase 1）：crawler-topic-split、dead-letter、cluster_id 实现、dataset_analyst、HTML dashboard。

---

## 14. 不变量 / 防回归清单

- DEFAULT_SETTINGS visualization=False
- check_auth: 200=valid, 204=invalid
- pasteurization（不是 pasteurize）
- requests session: proxies={http:None,https:None} + trust_env=False
- TUTORIAL：不要调 `/alphas/{id}/check-submission`，SC 在 `is.checks` 里
- alphas 表无 submitted_at；24h 计数用 updated_at
- daemon main 必须 with_tag(opts["dataset"]) 包裹
- Copilot CLI 子进程：CREATE_NO_WINDOW + DEVNULL stdin
- sim_executor BRAIN 并发 Semaphore
- 任何事件 payload 必带 dataset_tag

---

## 15. 待你确认的开放点（已闭合）

1. ~~direction_id 算法~~ → §5: 多维向量 + 前 4 维投影做 ID + 完整向量入 directions.feature_vector_json，**原始 expression/settings/raw_description 全保留**
2. ~~direction_id 写入时机~~ → alpha_gen 写完原始 alphas 行后立刻调 `dimensions.classify` 同步算 direction_id；sim_executor / submit 后续只 bump_stats
3. **chain_hook transform 注册**：写在 `src/wq_bus/ai/transforms/` 模块（Python 函数），dispatcher 配置 yaml 里按名引用 — 比放纯 yaml 更灵活
4. **manual_task_cli 默认 dataset_tag**：未指定时**报错**，强制显式（避免误污染）；可在 user-level config 设 `default_dataset` 才允许省略
5. **trace tree CLI**：默认文本树，加 `--json` 给前端用（呼应你 §7 的全面 JSON 导出原则）

### 16 新增条目（来自最新讨论）

- §3 第 8 条原则：**原始信息绝不覆写**（expression/settings/raw_description/prompt/response 全保留，衍生表述只能新增列/表）
- §6 trace 升级：补 `bus.start_task()` 返回 **TaskHandle**，支持 `.on_complete(cb) / .on_fail(cb) / .status / .cancel() / .wait()`
- §6 新增 supervisor 内置组件：监控 active trace 超时/卡死/重试超限自动 emit `TASK_FAILED`
- §7 dispatcher：manual 调用入独立 **`manual_calls` 表**（保留 prompt/response/note/tags），不与 auto 混表；预留 archive_classifier agent 接口
- §10 文档新增：`docs/architecture/EXPORT_FORMATS.md` — 所有 CLI `--json` 输出 schema、jsonl 日志规范、未来前端只读 JSON API 约定
- 全局：所有查询/状态/导出 CLI 都带 `--json`；`logs/*.jsonl` 统一

---

## 18. 对齐修订（最终，覆盖 §3/§5/§7/§10/§13 早期描述）

> 这是 docs 全部写完后回扫 plan 时发现的差异。**冲突时以本节为准**，docs 也已与本节一致。

### 18.1 设计原则补丁（覆盖 §3）

第 8 条：**原始信息绝不覆写**（expression/settings/raw_description/prompt/response 全保留；衍生表述只能新增列/表）。
第 9 条：**AI 强度由 dispatcher 集中调度**。Agent 不输出 strength/model；任何"动态升档"由 WatchdogPolicy 调 `StrengthRouter.set_override(...)` 实现。
第 10 条：**容错降级默认 lenient**。AgentBase 加 `enforcement: strict|lenient`；缺失字段查 `config/defaults.yaml`；handle 异常落 jsonl + emit TASK_FAILED + 不杀 agent。
第 11 条：**AI 中断恢复用文件 cache**。`data/ai_cache/<package_id>/` 下 `meta/input/stage/raw_response/result/error`；启动扫描重发；stage 文件原子转换。

### 18.2 模拟池补丁（覆盖 §5.3）

`directions_<TAG>` 与 `alphas` 加列 **`themes_csv TEXT`** —— 衍生多值列，由独立 `composition_recipes` 池（regex/AST matcher）映射；不进 PROJECTION_DIMS，不影响 direction_id。详见 `COMPOSITION_RECIPES.md`。

`pool_stats_<TAG>` 不加 themes 维度（避免维度爆炸）；按 theme 的统计走视图 / 即时聚合。

### 18.3 AI Dispatcher 补丁（覆盖 §7）

- **strength 集中调度**：`config/agent_profiles.yaml` 新增 `strength_routing` 表（`default` + `(agent,mode)` + `*` 通配），dispatcher 内 `StrengthRouter.resolve(agent, mode)` 唯一入口
- **packer 按 strength 分桶**：buffer 内 `(adapter, strength)` 二维分桶；flush 时一桶一包，**永不混档**
- **运行时 override 受控通道**：仅 CLI 人工 / WatchdogPolicy 可写，agent 禁止
- **记账加 strength 列**：`ai_calls` / `manual_calls` 都加 `strength TEXT`（high|medium|low|n/a）
- **chain_hook transform 注册位置**：`src/wq_bus/ai/transforms/<name>.py`（Python 函数模块），yaml 按名引用

### 18.4 文档清单补丁（覆盖 §10）

最终 7 份正文 + 1 份 legacy：
1. `BUS_ARCHITECTURE.md`（重写，旧版 `BUS_ARCHITECTURE_legacy.md`）
2. `AGENT_INTERFACE.md`
3. `SIMULATION_POOL.md`
4. `EVENT_CATALOG.md`
5. `TRACE_AS_TASK.md`
6. `AI_DISPATCHER.md`
7. `EXPORT_FORMATS.md`
8. `COMPOSITION_RECIPES.md` ← 新增

### 18.5 Phase 1 Todos 补丁（覆盖 §13）

新增/调整：

- `mig-005-recipes` — composition_recipes 表 + manual_calls 表（migration 005，含 strength 字段）
- `recipe-matcher` — `src/wq_bus/domain/recipes.py` regex+AST matcher + `hint_for_theme` 反查；config seed `composition_recipes_seed.yaml`
- `defaults-yaml` — `config/defaults.yaml` 集中默认值 + agent enforcement 模式注入
- `strength-router` — `src/wq_bus/ai/strength.py` StrengthRouter + override CLI（`wqbus ai strength set/clear/list`）
- `ai-cache-recovery` — `data/ai_cache/<package_id>/` 落盘 + 启动扫描重发 + cache CLI
- `dispatcher-v2` 子项澄清：billing_mode 分流 / strength 集中解析 / packer 分桶 / chain_hook / ai_cache / 重试

`alpha-gen-modes` 范围澄清：4 modes + direction_id 写入 + `themes_csv` 写入（调 recipe matcher）+ 不出 strength。

### 18.6 不变量补丁（覆盖 §14）

- agent 不输出 strength/model；dispatcher 集中决定
- packer 同包同档（永不混 strength）
- prompt/response/raw_description 全文落库 + cache 文件，绝不裁剪
- topic 通过 `topic_registry.register()` 动态注册（不再硬编码枚举）
- ai_cache stage 转换原子（rename `.tmp` → final）
- daemon 启动必扫 `data/ai_cache/` 完成 reissue 后才进入 ready

