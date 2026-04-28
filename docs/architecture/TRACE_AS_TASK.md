# TRACE_AS_TASK — Trace 作为通用 Task 容器

> Trace 不再仅是 AI 调用的链路 ID，而是任何"一个完整任务"的事件容器。

---

## 1. 概念

| 概念 | 定义 |
|---|---|
| **Trace** | 一个 task 的事件容器；含 origin、kind、payload、所有 emit 的事件、所有 ai_calls |
| **Task** | 一次执行单元，由 `bus.start_task()` 创建并产出 trace |
| **TaskHandle** | 调用方持有的 task 句柄；可注册回调、查询状态、取消 |

---

## 2. Schema（migration 004）

```sql
ALTER TABLE trace ADD COLUMN origin TEXT;             -- watchdog|crawler|manual_cli|dispatcher_pack
ALTER TABLE trace ADD COLUMN parent_trace_id TEXT;
ALTER TABLE trace ADD COLUMN task_kind TEXT;          -- generate|simulate|submit|crawl|summarize|analyze|...
ALTER TABLE trace ADD COLUMN task_payload_json TEXT;
ALTER TABLE trace ADD COLUMN status TEXT;             -- running|completed|failed|cancelled|timeout
ALTER TABLE trace ADD COLUMN started_at TEXT;
ALTER TABLE trace ADD COLUMN finished_at TEXT;
ALTER TABLE trace ADD COLUMN error TEXT;

CREATE INDEX idx_trace_parent ON trace(parent_trace_id);
CREATE INDEX idx_trace_status ON trace(status);
```

---

## 3. API

### 3.1 启动 task

```python
trace_id = bus.start_task(
    kind="generate",
    payload={"dataset_tag":"USA_TOP3000","mode":"explore","n":4},
    origin="watchdog",
    parent=None,        # subagent 时传父 trace
)
# 内部：写 trace 行，contextvar 设置当前 trace_id，emit task 起始事件
```

### 3.2 TaskHandle

`bus.start_task()` 在异步上下文返回 `TaskHandle`：

```python
class TaskHandle:
    trace_id: str
    @property
    def status(self) -> Literal["running","completed","failed","cancelled","timeout"]: ...
    def on_complete(self, cb: Callable[[TaskResult], None]) -> None: ...
    def on_fail(self, cb: Callable[[Exception], None]) -> None: ...
    async def wait(self, timeout: float | None = None) -> TaskResult: ...
    def cancel(self) -> None: ...      # 发出 TASK_CANCEL_REQUESTED
```

回调线程安全；多次注册按注册顺序触发。

### 3.3 总线 fire-once 订阅

```python
unsub = bus.subscribe(topic="ALPHA_DRAFTED", callback=cb, once=True, filter=lambda e: e.tag=="USA_TOP3000")
unsub()   # 取消
```

---

## 4. Supervisor（内置组件）

`src/wq_bus/bus/supervisor.py`：

```python
class TraceSupervisor:
    """监控 active trace，超时/卡死/重试超限自动 emit TASK_FAILED"""

    def __init__(self, *, tick_secs=15, default_timeout_secs=900): ...

    async def run(self) -> None:
        while True:
            for trace in db.active_traces():
                if now() - trace.started_at > timeout_for(trace.kind):
                    await bus.emit("TASK_TIMEOUT", trace_id=trace.trace_id)
                    db.mark_trace(trace.trace_id, status="timeout")
            await asyncio.sleep(tick_secs)
```

`config/triggers.yaml` 中按 task_kind 配置 timeout：
```yaml
task_timeouts:
  generate: 600
  simulate: 1200
  crawl: 1800
  summarize: 600
```

---

## 5. CLI

```bash
wqbus task list [--status running] [--kind generate] [--json]
wqbus task watch <trace_id>                       # 实时尾跟随
wqbus trace tree <trace_id> [--json]              # 父子 trace 树
wqbus task cancel <trace_id>                      # 发 cancel 事件
wqbus task replay <trace_id>                      # phase 2: dead-letter 回放
```

`--json` 输出供前端使用，schema 见 EXPORT_FORMATS.md。

---

## 6. 父子关系

- watchdog 触发：`origin=watchdog parent=None`
- watchdog 触发的事件被 dispatcher 打包：dispatcher 起新子 trace `origin=dispatcher_pack parent=<watchdog trace>`
- 子任务 chain_hook 触发的下一个：再起 sub trace `origin=dispatcher_pack parent=<package trace>`
- 跨 agent 异步追加（如 sim_executor 处理 ALPHA_DRAFTED）：**不**新建 trace，沿用 ALPHA_DRAFTED 事件携带的 trace_id

规则：**主动起 task 才新建 trace；被动响应事件继承 trace_id**。

---

## 7. 事件 → trace 关联

所有 BusEvent 自动从 contextvar 取当前 trace_id 写入 `state.events.trace_id` 列。AI 调用同样写 `ai_calls.trace_id`。

trace 树重建：从 trace 表按 `parent_trace_id` 递归 + 按 `state.events.trace_id` 收集事件 + 按 `ai_calls.trace_id` 收集 AI 调用。

---

## 8. 不变量

- 已写入 trace 不可改 (`origin/parent_trace_id/task_kind/task_payload_json` 不变)
- status 转换严格：`running → completed|failed|cancelled|timeout`，无回退
- 取消 task 必须先发 `TASK_CANCEL_REQUESTED` 让 agent 自行 cleanup，再 30s 强制标 cancelled
- supervisor tick 任何异常吞掉但记 ERROR 日志，不致命
