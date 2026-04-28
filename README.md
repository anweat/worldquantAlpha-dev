# WorldQuant BRAIN Alpha 自动化流水线（wq-bus）

> 事件驱动总线 + 多 agent 协作的 Alpha 因子全自动研究、回测、提交系统。
> 支持 GitHub Copilot CLI / OpenAI / GLM 多 AI 后端，**子代理通过 doc manifest 自主取文**，
> 内置 fragment 组合管线、变异管线、组合分析、爬虫总结、API 健康看门狗、Web 监控台。

---

## 🚀 60 秒上手

```powershell
# 0) 首次：登录 Copilot CLI（必须在带交互终端的 PowerShell 里）
copilot auth login
python scripts/check_copilot_cli.py    # 通过则 exit 0

# 1) 后台启动 daemon
.\scripts\start.ps1 -Detach

# 2) 打开交互控制台
.\scripts\console.ps1

# 3) 一次性看状态
python -m wq_bus.cli admin status
python -m wq_bus.cli trace --recent 5

# 4) Web 监控（http://127.0.0.1:8765）
python -m wq_bus.cli web
```

干跑模式（不消耗 AI 配额、不触达 BRAIN，纯链路演练）：

```powershell
.\scripts\start.ps1 -DryRun -Detach
```

---

## 🧩 核心命令一览

`python -m wq_bus.cli <COMMAND>` 或 `wqbus <COMMAND>`（已安装入 entry_point）。

### 🚌 Daemon / 任务触发

| 命令 | 用途 |
|------|------|
| `daemon` | 长驻进程：注册全部 agent + watchdog + auto-resume |
| `daemon --no-auto-gen` | 不自动 generate（仅响应外部触发） |
| `task <agent> [--mode M] [-n N] [--dataset TAG]` | 一次性触发任意 agent（自动映射到正确触发 topic） |
| `agent-task <agent>` | 旧版直接触发（不推荐，保留兼容） |
| `run --rounds N` | 同步 generate → simulate → SC → submit（不依赖 daemon） |
| `generate [N] [hint]` | 投递 `GENERATE_REQUESTED` |
| `submit-flush` | 手动冲刷提交队列 |
| `drain-docs --max-batches 5` | 手动批次排空 doc_summarizer |
| `emit <TOPIC> --json '{...}'` | 投递任意事件 |

支持的 alpha_gen mode：`explore` / `specialize` / `review_failure` / `track_news` / `fragments`（fragment 管线）。

### 🔍 Trace / 调试

| 命令 | 用途 |
|------|------|
| `trace --recent N` | 最近 N 个 trace（events + ai_calls + alphas 一行串起） |
| `trace <trace_id> [--full]` | 完整链路（含完整 prompt+response） |
| `trace --alpha <ALPHA_ID>` | 一个 alpha 怎么来的 |
| `trace-tree show <trace_id>` | 树形展示父子 trace |
| `trace-tree alpha <ALPHA_ID>` | 按 alpha 反查 trace 树 |
| `trace-prune --days 7` | 清理 7 天前已终结 trace |
| `alpha <ALPHA_ID>` | alpha 详情（IS、check、提交状态） |

### 🛡️ 健康 / 配额

| 命令 | 用途 |
|------|------|
| `health [--once] [--kind auth\|simulate\|untested_alpha]` | BRAIN API 健康看门狗，自动暂停/恢复 alpha_gen+submitter |
| `admin status` | 队列 / AI 用量 / 今日提交 / IS-eligible 数 |
| `admin reset-cap` | 把今日 ai_calls 时间戳回拨 25h（开发用） |
| `db migrate` | 幂等执行迁移 |
| `kb prune [--keep-days N]` | KB 保留策略 |
| `sim-dlq list / requeue` | 模拟死信队列 |
| `queue list / requeue / drop` | 提交队列管理 |

### 📚 知识库 / Manifest

| 命令 | 用途 |
|------|------|
| `manifest build` | 扫描 `docs/` + `memory/<tag>/` 重建 `docs/manifest.generated.yaml` |
| `manifest show [--mode M] [--tag T]` | 查看 sub-agent 当前可见的文档列表 |
| `crawl <target>` | 触发单个爬虫目标 |
| `summarize <mode>` | 触发 doc_summarizer（recipe / failure / portfolio / daily / longterm） |
| `recipe list / show / approve <id>` | composition recipe 管理 |
| `datafields fetch` | 拉取并缓存数据集字段表 |
| `dataset switch <TAG>` | 切换 active dataset（不同 region 记忆完全隔离） |

### 🌐 Web 控制台

```powershell
python -m wq_bus.cli web --port 8765
```

仅 localhost，无认证。展示队列、trace 列表、AI 用量、近期 alpha + 一键触发。

---

## 🏗️ 总线架构

```
                  ┌── GENERATE_REQUESTED ◄── CLI / web / watchdog / KNOWLEDGE_UPDATED / coordinator
                  │
                  ▼
            ┌─[alpha_gen]───────────────────────┐
            │   modes: explore / specialize     │  ── ai_call ──► dispatcher
            │          / review_failure         │       │  rate_limiter (daily + per-agent + per-round)
            │          / track_news / fragments │       │  StrengthRouter (low/std/high)
            │                                   │       │  PackageCache (crash-safe stages)
            │  fragments → ALPHA_FRAGMENTS_DRAFTED───►[alpha_combiner]
            │                                   │           │ 编译 fragment + 参数扫描 + group_rank 变体
            │                                   │           ▼
            └───────► ALPHA_DRAFTED ◄───────────────────────┘
                      │
                      ▼
              [sim_executor] ── BRAIN /simulations  (concurrency cond + RATE_PRESSURE 自动降速)
                      │
                      ├─► IS_PASSED → [self_corr_checker] ── BRAIN /alphas → enqueue + FLUSH
                      └─► IS_FAILED ─► [alpha_mutator] (可选变异回环)
                              │
                              ▼
                      [submitter] ── BRAIN /alphas/{id}/submit
                              │
                              ▼ SUBMITTED ── [portfolio_analyzer]
                              ▼ BATCH_DONE ─ [failure_analyzer] → LEARNING_DRAFTED → 下轮 alpha_gen 上下文

  侧链 1（爬虫 + 总结）:
    CRAWL_REQUESTED → [crawler] (robots.txt 守门) → DOC_FETCHED
                  (累积 N 篇) → [doc_summarizer] → KNOWLEDGE_UPDATED
                                                ↓
                                  [summarizer]   (workspace/longterm/portfolio 总结)

  侧链 2（健康监控）:
    [api_healthcheck] ── HEALTH_PROBE_DONE / API_DEGRADED / API_RESTORED
                                ↓
                       alpha_gen + submitter 自动 gated

  侧链 3（多 agent 协调）:
    [coordinator]  ── 按 goal 拼装 multi-agent pipeline（goal.py + runner.py）
```

**关键事实**：

- 全部 topic 镜像进 `state.db.events`，自带 `trace_id`（contextvar 自动传播）。
- 同一 trace 串联：events / ai_calls（**含完整 prompt+response**）/ alphas / submission_queue。
- Trace 自动收尾：显式 `TASK_COMPLETED/FAILED` 或 task_kind 命中 `_TERMINAL_TOPICS_BY_KIND`。
- `register_topic` 动态注册；`bus/topic_meta.py` 持有 task_kind/critical 元数据。
- Daemon watchdog：①队列非空 + 长时无 flush → emit FLUSH ②队列空 + 无活动 → emit GENERATE。
- doc_summarizer **不再自循环**（旧 bug），统一用 `wqbus drain-docs`。
- self_corr_checker 入队后自动 emit FLUSH，整链自驱动。

---

## 🤖 AI dispatcher

```yaml
# config/ai_dispatch.yaml（关键字段）
limits:
  daily_cap_total: 200
  daily_cap_per_agent: { alpha_gen: 100, summarizer: 30, ... }
  per_round_cap: { alpha_gen: 8, ... }

adapters:
  copilot:
    binary: copilot
    timeout_secs: 300        # ← claude-sonnet-4.6 真实跑可达 200s+，勿调低
  openai: { base_url_env: OPENAI_BASE_URL, key_env: OPENAI_API_KEY }
  glm:    { base_url_env: WQBUS_GLM_BASE,  key_env: WQBUS_GLM_API_KEY }

adapter_fallbacks:
  copilot_cli:
    on_model_unavailable: gpt-5.4    # premium 模型不可用时自动降级
```

- **Strength routing**：`StrengthRouter` 按 (agent, mode) 选 low/std/high，**绝不混 strength 到一个 batch**。
- **Crash-safe**：`PackageCache` 按 queued→sent→received→unpacked→done/failed 原子推进，启动时 `startup_reissue()` 重发。
- **Backward-compat**：`ai_service.py` 在 strict-render 前自动给缺失模板变量填空字符串，新增变量不会让 buffered AI_CALL_REQUESTED 全部失败。
- **Rate-cap 计数源**：`state.db.ai_calls` 表的 `ts` 字段（24h 滚动）。`admin reset-cap` 一键回拨。

---

## 📚 Doc Manifest（sub-agent 自主取文）

```powershell
# 1) 维护 docs/manifest.yaml（手写元数据）
# 2) 重建合并清单
wqbus manifest build

# 3) 看每个 mode 在每个 dataset 下能看到什么
wqbus manifest show --mode explore --tag usa_top3000
```

- `docs/manifest.yaml` — 手写的 `path/title/applies_to_modes/tags/scope/priority`。
- `scripts/manifest_builder.py` — 扫 `docs/` + `memory/<tag>/` 合并，自动填 mtime/size/summary。
- `src/wq_bus/ai/doc_manifest.py` — `load_for_mode(mode, tag)` 过滤 + `render_for_prompt()` 注入。
- `alpha_gen` 的 3 个 prompt（fragments/explore/repair）都在 **OPTIONAL DEEPER CONTEXT** 段列出可见文件，sub-agent 决定是否 `view <path>`，避免把所有文件全文塞进 prompt。

---

## 🧪 测试

```powershell
# 端到端 smoke（确定性 stub AI 适配器，无需 BRAIN session）
python scripts/smoke_full.py --dataset usa_top3000 --rounds 2 --simulate-ai

# Fragment 管线 smoke
python scripts/smoke_fragment_pipeline.py

# 边界测试 B1-B12
python scripts/boundary_tests.py --dataset usa_top3000

# Rate-cap 边界
python scripts/test_rate_cap.py

# Combiner / Mutator 单元测试
python scripts/test_alpha_combiner.py
python scripts/test_alpha_mutator.py

# 查看 stub 响应
python scripts/simulate_ai.py alpha_gen.explore
```

---

## 🔑 提交标准（Delay-1, USA TOP3000）

```
Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))
```

| 指标 | 要求 |
|------|------|
| Sharpe (IS) | ≥ 1.25 |
| Fitness (IS) | ≥ 1.0 |
| Turnover | 1% – 70% |
| SELF_CORRELATION | PASS / PENDING（PENDING 自动轮询最多 6×10s） |

基本面字段（`liabilities/assets`）天然换手 1-5%，易过 Fitness。
技术指标换手 30-90%，需配低换手字段或 `group_rank(..., subindustry)` 中性化。

---

## 📁 项目结构

```
worldquantAlpha-dev/
├── src/wq_bus/
│   ├── cli.py                 # ★ wqbus 主入口
│   ├── bus/                   # event_bus / tasks / supervisor / triggers / topic_registry / topic_meta
│   ├── agents/                # alpha_gen, alpha_combiner, alpha_mutator, sim_executor, self_corr_checker,
│   │                          # submitter, failure_analyzer, portfolio_analyzer, doc_summarizer,
│   │                          # summarizer, api_healthcheck
│   ├── ai/                    # dispatcher, rate_limiter, strength, cache, ai_service,
│   │                          # prompt_registry, doc_manifest, context_curator, adapters/
│   ├── brain/                 # client / auth / session（带代理绕过 + 401 自动重登）
│   ├── crawler/               # fetcher + robots.txt 守门 + pdf_pipeline + auth_store
│   ├── coordinator/           # 多 agent goal-loop pipeline（runner + goal）
│   ├── analysis/              # 自相关 / expression_fingerprint / 组合分析
│   ├── data/                  # state.db / knowledge.db DAO + migrations
│   └── utils/                 # tag_context（dataset+trace ContextVar）, logging, paths, timeutil
├── config/
│   ├── ai_dispatch.yaml       # AI 限额 + adapter 配置
│   ├── prompts/               # 所有 prompt 模板（含 alpha_gen.{fragments,explore,repair}）
│   ├── templates/             # sub-agent pack（_subagent_pack.alpha_gen.md 等）
│   ├── triggers.yaml          # watchdog / cooldown 配置
│   ├── crawler.yaml           # 爬虫目标 + 总结 threshold
│   ├── summarizer.yaml        # 各 summarizer mode 的 cap / threshold
│   ├── datasets.yaml          # 数据集标签库
│   ├── tasks.yaml             # coordinator 多 agent pipeline 定义
│   └── ...
├── docs/
│   ├── manifest.yaml          # ★ 手写文档元数据
│   ├── manifest.generated.yaml # ★ 合并后的清单（脚本生成）
│   ├── 00-13_*.md             # 14 篇学习/经验文档
│   └── architecture/          # AGENT_INTERFACE / AI_DISPATCHER / BUS_ARCHITECTURE /
│                              # COMPOSITION_RECIPES / EVENT_CATALOG / SIMULATION_POOL /
│                              # TRACE_AS_TASK / EXPORT_FORMATS
├── scripts/
│   ├── start.ps1 / stop.ps1 / console.ps1     # daemon 启停 + 控制台
│   ├── manifest_builder.py                     # ★ doc manifest 构建
│   ├── check_copilot_cli.py                    # ★ Copilot CLI 自检
│   ├── smoke_full.py / smoke_fragment_pipeline.py / boundary_tests.py / test_rate_cap.py
│   ├── simulate_ai.py                          # 确定性 stub 适配器
│   ├── monitor_ai_calls.py / live_tail.py / wqbus_monitor.py
│   └── ...
├── web/                       # 本地 Web 控制台（FastAPI + 静态前端）
├── data/                      # state.db / knowledge.db（gitignored）
├── logs/                      # 全局 + per-tag 日志（gitignored）
├── memory/                    # 运行时记忆（gitignored，per-tag）
└── archive/                   # 旧工作流归档
```

---

## 🔧 BRAIN API 与认证

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/authentication`         | 验证 session（200=有效，401=失效） |
| POST | `/simulations`            | 提交模拟，201 + `Location` |
| GET  | `/alphas/{id}`            | IS 指标 + checks（含 SELF_CORRELATION） |
| POST | `/alphas/{id}/submit`     | 提交 |

**认证**：Cookie `t`（JWT），存于 `.state/session.json`（Playwright storage_state，约 12h）。

**自动登录**：把邮箱/密码放入 `.state/credentials.json`（已 gitignore）：

```json
{ "email": "you@example.com", "password": "..." }
```

或导出 `WQBRAIN_EMAIL` / `WQBRAIN_PASSWORD`。然后：

```powershell
python -m wq_bus.cli login            # 检查并按需自动登录
python -m wq_bus.cli login --force    # 强制刷新
```

`scripts\start.ps1` 启动前会自动 `wqbus login`；`BrainClient.check_auth()` 在 401 时也会尝试一次自动重登。

**重要警告**：

- `brain/client.py` 已设 `proxies={"http":None,"https":None}` + `trust_env=False`，绕过 Clash 等本地代理 — **勿删除**，否则 SSL 握手必失败。
- TUTORIAL 账号**不要调** `/alphas/{id}/check-submission`（404）。SELF_CORRELATION 已在主响应的 `is.checks` 中。

---

## 🆕 Copilot CLI Sub-agent 流程

`alpha_gen` 通过 Copilot CLI 调用 claude-sonnet-4.6。Sub-agent 在 prompt 引导下：

1. 读 manifest 列出的可选文件清单（按 mode + tag 过滤）。
2. 对感兴趣的项调用 `view <path>` 自主取文。
3. 综合 task spec、recipe、近期 failure、portfolio gap 生成 fragments / 完整 alpha。

实测：claude-sonnet-4.6 一次 fragments 调用 ~175s（含 2-3 次 view），300s 超时足够。
缩减 prompt 体积约 60%（不再把所有 docs 全文塞 prompt）。

---

## 📖 详细文档

- `docs/architecture/BUS_ARCHITECTURE.md` — 总线设计与拓扑
- `docs/architecture/AGENT_INTERFACE.md` — agent 协议（subscribes / emits / enforcement）
- `docs/architecture/AI_DISPATCHER.md` — strength router / batch / cache
- `docs/architecture/EVENT_CATALOG.md` — 全部 topic 列表 + 字段
- `docs/architecture/SIMULATION_POOL.md` — 模拟池并发与压力反馈
- `docs/architecture/TRACE_AS_TASK.md` — trace = task 模型
- `docs/architecture/COMPOSITION_RECIPES.md` — recipe + fragment 管线
- `docs/architecture/EXPORT_FORMATS.md` — JSON 导出格式
- `docs/05_性能指标与提交标准.md` — Sharpe/Fitness/Turnover 公式
- `docs/12_community_insights_and_alpha_experience.md` — 社区经验
- `docs/13_alpha_defects_and_community_wisdom.md` — 常见缺陷

---

## 🪪 License

内部研究项目，未对外发布。
