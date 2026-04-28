# wq-bus 架构总览

## 顶层数据流

```
   ┌─────────────┐  GENERATE_REQUESTED   ┌──────────┐
   │  CLI/cron   │ ───────────────────► │ alpha_gen│
   └─────────────┘                       └────┬─────┘
                                              │ ALPHA_DRAFTED
                                              ▼
   ┌──────────────┐    IS_PASSED        ┌─────────────┐
   │self_corr_chk │ ◄─────────────────  │ sim_executor│
   └──────┬───────┘                     └─────┬───────┘
          │ SC_CHECKED (queue=true)           │ IS_RESULT
          ▼                                   ▼
   ┌──────────┐  QUEUE_FLUSH_REQUESTED  ┌──────────────────┐
   │submitter │ ◄────── CLI ─────────── │ failure_analyzer │
   └────┬─────┘                         └──────────────────┘
        │ SUBMITTED
        ▼
   ┌──────────────────┐
   │portfolio_analyzer│
   └──────────────────┘

   爬虫支线：
   CRAWL_REQUESTED → crawler_agent → DOC_FETCHED → doc_summarizer → KNOWLEDGE_UPDATED
```

## 核心组件

| 模块                       | 职责                                                                 |
| -------------------------- | -------------------------------------------------------------------- |
| `wq_bus.bus`               | asyncio 进程内总线；事件主题枚举；关键事件镜像到 state.db。          |
| `wq_bus.data`              | 双 SQLite：`state.db`（事件/队列/AI 调用/锁） + `knowledge.db`（alpha/SC/PnL/学习/爬虫文档），全部按 `dataset_tag` 强隔离。 |
| `wq_bus.utils.tag_context` | contextvars-based dataset tag propagation；DAO 内 `require_tag()` 自动作用域。 |
| `wq_bus.ai`                | dispatcher → router → batch_buffer → packer → adapter（copilot/openai/glm）。统一 daily + per-round 速率配额。 |
| `wq_bus.brain`             | `requests`-based REST 客户端；强制代理绕过；429 重试；轮询 simulation 直到 COMPLETE。 |
| `wq_bus.analysis`          | 表达式指纹去重、SC 解析、PnL 两两 Pearson、过拟合启发分析。          |
| `wq_bus.crawler`           | aiohttp+Playwright 抓取；PDF 下载/OCR；按文档数阈值触发摘要。        |
| `wq_bus.agents`            | 7 个 agent 全部继承 `AgentBase`，订阅指定 topic，dispatch 到 `on_<topic>`。 |

## 关键设计决策

- **总线 vs 工作流**：去除中心 orchestrator；agent 通过事件解耦；唯一中心是 CLI（手动触发）+ 监控脚本（轮询触发）。
- **数据集隔离**：`make_event` 强制 `dataset_tag` 非空；DAO 全部 require_tag；memory 文件按 tag 分目录（`memory/{tag}/`）。
- **AI 成本控制**：batch_buffer 按 size 或 secs flush，packer 把多任务塞进一个 prompt（pack/unpack）；rate_limiter 双阈值（日/round）。
- **自相似 3 层**：
  1. 前端：`expression_fingerprint`（SHA-1 of normalized expr）→ duplicate 不模拟；
  2. 中端：`is.checks` 中 SELF_CORRELATION 字段，阈值 0.7；
  3. 后端：`pnl_correlation` 提交后两两 Pearson，超阈值进 learning。
- **AI 调用记账**：每次 adapter 调用写入 `state.db.ai_calls`（agent_type/model/depth/n_packed/duration_ms/success/error/dataset_tag）。

## 配置一览

| 文件                     | 用途                                          |
| ------------------------ | --------------------------------------------- |
| `config/datasets.yaml`   | 数据集标签库（region/universe/经验/字段）。   |
| `config/submission.yaml` | Sharpe/Fitness/Turnover 阈值 + daily_max。    |
| `config/analysis.yaml`   | SC 阈值 / PnL 相关性阈值。                    |
| `config/bus.yaml`        | 总线核心配置（drain timeout 等）。            |
| `config/ai_dispatch.yaml`| Rate limits / batch defaults / adapter binary。|
| `config/agent_profiles.yaml`| 各 agent 的 provider/model/depth/batch_size。|
| `config/crawl_targets.yaml`| 爬虫目标 dict（含触发阈值）。               |
| `.secrets/`              | 凭证 + cookie（gitignored，含 .example 模板）。|

## 运行入口

```bash
# 通用
python -m wq_bus.cli check-session
python -m wq_bus.cli --dataset usa_top3000 run -n 4
python -m wq_bus.cli --dataset usa_top3000 generate -n 5
python -m wq_bus.cli --dataset usa_top3000 submit-flush
python -m wq_bus.cli crawl --target arxiv_quant
python -m wq_bus.cli analyze portfolio

# 后台监控（持续到 N 个 alpha 提交）
python scripts/wqbus_monitor.py --target 4 --batch 4 --interval 60

# 一次性数据迁移
python scripts/migrate_to_bus.py --default-tag usa_top3000

# Session 刷新
python scripts/login_basic.py
```

## 已知限制 / 未来工作

- `daily_max` 跨会话计数当前依赖 `state.db.ai_calls`/`knowledge_db.alphas` 查询，不严格原子。
- copilot CLI 子代理暂只支持 `--model`（不接受 `--depth`，已改为提示词前置）。
- 历史 1257 条 alpha 迁移未抽取 sharpe/fitness/turnover（旧库 schema 与新不同），可后续扩展 migration。
