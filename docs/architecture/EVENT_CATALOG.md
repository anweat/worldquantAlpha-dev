# EVENT_CATALOG — 总线事件目录

> 现有 13 topic + 动态注册机制 + phase 1 新增 6 个 + phase 2/3 预留。

---

## 1. Topic 注册机制

```python
# src/wq_bus/bus/events.py
TOPIC_REGISTRY: dict[str, dict] = {}

def register_topic(name: str, *, payload_schema: dict | None = None) -> str:
    name = name.upper()
    if name in TOPIC_REGISTRY:
        return name
    TOPIC_REGISTRY[name] = {
        "payload_schema": payload_schema,
        "registered_at": utcnow_iso(),
    }
    return name
```

新 agent import 时调用 `register_topic("MY_TOPIC", payload_schema=...)` 自动登记，不必改 events.py 主体。

兼容性：现有 13 topic 用 `register_topic` 保留为模块级常量。

---

## 2. 现有 topic（保留）

| Topic | 主要 publisher | 主要 subscriber | payload 关键字段 |
|---|---|---|---|
| `GENERATE_REQUESTED` | watchdog / CLI | alpha_gen | dataset_tag, mode, n, direction_hint |
| `ALPHA_DRAFTED` | alpha_gen | sim_executor | dataset_tag, alpha_id, expression, settings |
| `IS_RESULT` | sim_executor | self_corr_checker, failure_analyzer | dataset_tag, alpha_id, is.checks, sharpe, fitness |
| `IS_PASSED` | sim_executor | submit_pipeline | dataset_tag, alpha_id |
| `SC_CHECKED` | self_corr_checker | submitter | dataset_tag, alpha_id, self_corr_result |
| `QUEUE_FLUSH_REQUESTED` | CLI | submitter | dataset_tag |
| `SUBMITTED` | submitter | portfolio_analyzer | dataset_tag, alpha_id |
| `SUBMIT_REJECTED` | submitter | failure_analyzer | dataset_tag, alpha_id, reason |
| `CRAWL_REQUESTED` | CLI / scheduler | crawler (phase 2) | target, url, goal, summarize |
| `DOC_FETCHED` | crawler / drain CLI | doc_summarizer | dataset_tag, doc_id |
| `KNOWLEDGE_UPDATED` | doc_summarizer | (notifier) | dataset_tag, summary_id |
| `BUDGET_EXHAUSTED` | dispatcher | watchdog | scope, limit_kind |
| `SESSION_INVALID` | brain.client | (notifier / login) | — |

---

## 3. Phase 1 新增 topic

| Topic | 含义 | publisher | subscriber |
|---|---|---|---|
| `TASK_STARTED` | bus.start_task() 起始事件 | bus core | supervisor, logger |
| `TASK_COMPLETED` | TaskHandle 完成 | agent | TaskHandle.on_complete |
| `TASK_FAILED` | task 失败/超时/取消 | agent / supervisor | TaskHandle.on_fail |
| `TASK_TIMEOUT` | supervisor 检测到 | supervisor | watchdog |
| `TASK_CANCEL_REQUESTED` | 用户/CLI 主动取消 | CLI | 各 agent |
| `POOL_UPDATED` | 模拟池统计更新 | pool DAO | watchdog（用于动态加权） |

### Phase 1 完成清单（Wave C+D）

- **dispatcher-v2**: 单入口 `call()`；StrengthRouter 集成；BatchBuffer 按 `(adapter, strength)` 分桶；PackageCache crash-safe；`daily_ai_cap`（仅 auto）；一次重试；`startup_reissue()`
- **watchdog-policy**: `WatchdogPolicy` ABC + `DefaultStockpile`；4:2:1:1 加权；adaptive bump（avg_self_corr / pool / pass_rate）；StrengthRouter TTL override；冷却期 30min
- **alpha-gen-modes**: 4 种 mode（explore/specialize/review_failure/track_news）；`dimensions.classify()` + `recipes.match()` + `workspace.upsert_direction()`；ALPHA_DRAFTED 携带 `direction_id`/`themes_csv`/`mode`；assert guard 阻止 agent 写 strength/model
- **doc-sum-fix**: 移除 self-loop；改用 `wqbus drain-docs` 手动触发
- **CLI 新命令**: `wqbus drain-docs`, `wqbus task`, `wqbus trace-tree show/recent/alpha`, `wqbus db migrate`
- **scripts**: `scripts/simulate_ai.py`（确定性 stub 适配器）、`scripts/smoke_full.py`（端到端冒烟测试）

---

## 4. 后置 topic 预留（phase 2/3，先在 EVENT_CATALOG 登记不实现）

| Topic | 含义 | 何时实现 |
|---|---|---|
| `DATASET_ANALYZED` | dataset_analyst 输出 | phase 3 |
| `CLUSTER_UPDATED` | clusterer agent | phase 3 |
| `PARAMETER_SUGGESTED` | param optimizer | phase 3 |
| `EXTERNAL_REVIEW_DONE` | critic agent | phase 3 |
| `REGRESSION_REPORT` | regression_tester | phase 3 |
| `MACRO_EVENT_DETECTED` | macro_event agent | phase 3 |
| `DEAD_LETTER` | dispatcher 二次失败 | phase 2 |
| `REPLAY_REQUESTED` | CLI 重放失败事件 | phase 2 |

---

## 5. payload 公共字段

所有 BusEvent payload 必含：

```json
{
  "dataset_tag": "<REGION>_<UNIVERSE>",
  "trace_id":    "tr_xxx",
  "emitted_at":  "ISO 8601 UTC",
  "publisher":   "<agent.name>"
}
```

`bus.emit` 校验缺失字段直接抛 `EventValidationError`。

---

## 6. payload schema 示例

### GENERATE_REQUESTED

```json
{
  "dataset_tag": "USA_TOP3000",
  "trace_id": "tr_xxx",
  "emitted_at": "...",
  "publisher": "watchdog",
  "mode": "explore|specialize|review_failure|track_news",
  "n": 4,
  "direction_hint": {
    "direction_id": "...",
    "raw_description": null
  } | null
}
```

### TASK_STARTED

```json
{
  "dataset_tag": "USA_TOP3000",
  "trace_id": "tr_root",
  "emitted_at": "...",
  "publisher": "bus.core",
  "task_kind": "generate",
  "origin": "watchdog",
  "parent_trace_id": null,
  "payload": { ... }
}
```

---

## 7. 不变量

- topic 名全大写蛇形
- 已登记 topic 的 payload_schema 只能新增字段，不可删/改语义
- 任何 publisher 必须 import 后调一次 `register_topic`（即使是常量重复登记，幂等）
- 事件镜像到 `state.events` 表，便于 trace tree 重建
