# BUS_ARCHITECTURE — 总线核心（重写 v2）

> 旧版（含"顶层数据流"误称）已重命名为 `BUS_ARCHITECTURE_legacy.md` 仅供历史参考。本文是 v3 重构后的权威。
>
> 总线本身只关心：事件分发、订阅、trace 注入、主题注册。**所有 pipeline / AI 决策 / 池化逻辑都在 agent 和 dispatcher 层**，不在总线层。

---

## 1. 总线层只有四件事

```
┌──────────────────── wq_bus.bus ────────────────────┐
│  EventBus       (asyncio pub/sub, fan-out)         │
│  TopicRegistry  (动态注册, payload schema)         │
│  TraceContext   (contextvars 传播 trace_id)        │
│  EventStore     (events 表镜像, 用于 replay/审计)  │
└────────────────────────────────────────────────────┘
        ▲                    ▲
        │subscribe           │emit
        ▼                    │
   AgentRegistry        bus.start_task() → TaskHandle
```

总线**不关心**：
- AI 怎么调（→ AI_DISPATCHER.md）
- 任务什么时候触发（→ WatchdogPolicy in SIMULATION_POOL.md）
- 数据怎么按 dataset 分（→ workspace 在 AGENT_INTERFACE.md）
- 方向/主题/recipe（→ SIMULATION_POOL.md / COMPOSITION_RECIPES.md）

---

## 2. 关键 API

```python
# 订阅（持续 / 一次性 / 带过滤器）
bus.subscribe(topic, callback, *, once=False, filter=None) -> unsubscribe_fn

# 发布
await bus.emit(topic, **payload)

# 起 task（核心入口，详见 TRACE_AS_TASK.md）
handle = bus.start_task(kind, payload, origin, parent=None) -> TaskHandle

# 主题登记
events.register_topic(name, payload_schema=...)
```

emit 时自动从 contextvars 读取 `trace_id` 注入 payload；缺失 `dataset_tag` → 抛 `EventValidationError`。

---

## 3. trace_id 生成与传播

- 由 `bus.start_task` **唯一签发**：`tr_<utc_compact>_<6char_random>`，例 `tr_20260426T140012Z_a3f2c1`
- 起 task 时把 trace_id 写入 contextvar；该 contextvar 是 asyncio-aware，子任务自动继承
- 被动响应事件的 handler 不创建新 trace_id，沿用 event.trace_id
- subagent_packer 起子 trace 时传 `parent=<父 trace_id>`，trace 表 `parent_trace_id` 列形成森林

详细行为见 `TRACE_AS_TASK.md`。

---

## 4. 数据层布局（多 workspace）

```
data/
  state.db                     # 共享：events / queue / locks / trace / ai_calls / manual_calls
  knowledge.db                 # 共享：alphas / fingerprints / pnl_series / learnings / crawl_docs / crawl_summaries
                               #       directions_<TAG>, pool_stats_<TAG> (动态)
  ai_cache/<package_id>/       # AI 中断恢复缓存（详见 AI_DISPATCHER.md §8）
  snapshots/                   # 周期写入的只读 JSON（前端用，phase 后置）
  workspaces/<TAG>/            # 后置可选：独立 workspace 数据库（phase 2 才考虑）
memory/<TAG>/                  # 每 dataset 独立目录
logs/                          # jsonl 日志（详见 EXPORT_FORMATS.md）
  <TAG>/...
```

- 默认所有 dataset 共表，按 `dataset_tag` 列分行 + 索引
- 高频写入或 dataset 数 ≥ 5 时可启用 workspace 分库（在 `config/data.yaml` 设 `workspace_db: true`，phase 2 实装）
- DAO 一律 `require_tag()`（见 `wq_bus.utils.tag_context`）

---

## 5. 事件镜像（EventStore）

每个 emit 后异步写一行到 `state.events`：

```sql
events(
  event_id PK,
  topic, payload_json,
  dataset_tag, trace_id, publisher,
  emitted_at, persisted_at
)
```

用途：trace tree 重建 / 调试 / dead-letter replay（phase 2）。

---

## 6. 最常用 task 流（示例 — 不是顶层架构）

> 下图只是一个**典型 task 流**，便于直观理解。它是 alpha_gen→sim→submit 这一条 pipeline 的事件链；其它 task（爬虫、复盘、组合分析）用同一总线但走不同 topic。

```
[CLI / watchdog]
   │ bus.start_task(kind=generate, origin=watchdog)
   ▼
GENERATE_REQUESTED ──► alpha_gen.handle()
                          │ emit ALPHA_DRAFTED  (continues trace)
                          ▼
                       sim_executor.handle()
                          │ emit IS_RESULT
                          │ if pass: emit IS_PASSED
                          ▼
                       self_corr_checker.handle()
                          │ emit SC_CHECKED (queue=true if pass)
                          ▼
                       (CLI / scheduler)
                          │ bus.start_task(kind=submit, ...)
                          │ emit QUEUE_FLUSH_REQUESTED
                          ▼
                       submitter.handle()
                          │ emit SUBMITTED / SUBMIT_REJECTED
                          ▼
                       portfolio_analyzer (订阅 SUBMITTED)
```

爬虫支线、复盘支线、组合分析支线都是平级独立 task 流，不互相耦合。

---

## 7. 多 task 并发与隔离

- 总线本身天然并发（asyncio 协程）
- 全局 AI 并发上限由 dispatcher 信号量控制（≤ 4，见 AI_DISPATCHER.md）
- 同 dataset 同 task_kind 的去重锁在 `state.locks` 表（phase 1 已有）
- 跨 dataset 互不干扰，因为 payload 必带 tag + DAO require_tag

---

## 8. 容错降级

- 任何 handler 抛异常 → 总线 catch + 落 jsonl + emit `TASK_FAILED` + 不杀 agent
- payload 缺非关键字段 → fill default + WARN（见 `config/defaults.yaml`）
- emit 时 topic 未注册 → strict 模式 raise / lenient 模式 register 再 WARN
- TraceContext 取不到 trace_id → 自动起一个 `tr_orphan_<rand>`（标 origin=orphan，便于排查）

---

## 9. 与其他文档的接口契约

| 关注点 | 唯一来源 |
|---|---|
| Agent 协议 / workspace_rules / task package | AGENT_INTERFACE.md |
| trace 生成、TaskHandle、supervisor | TRACE_AS_TASK.md |
| AI 调用、billing_mode、strength、缓存恢复 | AI_DISPATCHER.md |
| 维度 / 方向 / direction_id / WatchdogPolicy | SIMULATION_POOL.md |
| 主题 / recipe 池 / 算子组合匹配 | COMPOSITION_RECIPES.md |
| 事件目录 / payload schema | EVENT_CATALOG.md |
| 日志 / JSON 导出 / 状态 schema | EXPORT_FORMATS.md |

本文（BUS_ARCHITECTURE）只覆盖总线核心机制，**不重复**其它文档内容。

---

## 10. 不变量

- 总线协程内不阻塞调 IO 或 AI（必须走 `loop.run_in_executor` 或 dispatcher）
- 每个 emit payload 必带 `dataset_tag` + 自动注入 `trace_id` + `publisher`
- 已注册 topic 不可改名/删除（兼容性）
- trace_id 全局唯一，可作为审计追踪 key
- 事件镜像写入 `state.events` 是异步但保序（按 emit 顺序）
