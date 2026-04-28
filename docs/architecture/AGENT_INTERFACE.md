# AGENT_INTERFACE — Agent 协议、Task 包、Workspace 规则

> 本文件是 wq-bus 重构 v3 的 **接口契约**。任何新 agent 必须满足本文件描述的协议；任何 dispatcher / 总线变更不得破坏这些约定。

---

## 1. AgentBase 协议

```python
from abc import ABC, abstractmethod
from typing import ClassVar, Iterable, Literal
from wq_bus.bus import BusEvent

class AgentBase(ABC):
    name: ClassVar[str]                  # e.g. "alpha_gen"
    subscribes: ClassVar[list[str]]      # e.g. ["GENERATE_REQUESTED"]
    modes: ClassVar[list[str]] = []      # e.g. ["explore","specialize","review_failure","track_news"]

    workspace_rules: ClassVar[dict] = {  # 强制声明，启动时校验
        "reads":        [],              # 表名/记忆文件名
        "writes":       [],
        "memory_files": [],
    }

    billing_hint: ClassVar[str] = "either"  # per_call|per_token|either
    enforcement: Literal["strict","lenient"] = "lenient"   # 启动时可调

    @abstractmethod
    async def handle(self, event: BusEvent) -> Iterable[BusEvent]:
        """处理一个总线事件，可 yield 0..N 个新事件"""

    async def health(self) -> dict:
        """返回 {"ok": bool, "lag_secs": int, "queue": int, ...}"""
        return {"ok": True}

    async def dry_run(self, event: BusEvent) -> Iterable[BusEvent]:
        """走 fake adapter，不调真 AI / 不写 knowledge.db"""
        return await self.handle(event)
```

> **注意**：agent **不**参与 AI 模型/强度选择。所有 AI 调用强度由 dispatcher 通过 `strength_routing[agent][mode]` 集中解析（详见 `AI_DISPATCHER.md §2-§3`）。agent 在产出 task 时只声明 `agent + mode`。

启动时 `AgentRegistry.register(MyAgent)` 校验：
- `name` 唯一
- `subscribes` 中 topic 已在 topic registry（动态/枚举）注册
- `workspace_rules` schema 合法
- 实现了 `handle`

**lenient 模式下校验失败仅 WARN 不阻止启动**（详见 §9）。

---

## 2. Subagent Task Package Schema

dispatcher 在 `billing_mode=per_call` 时把多 task 打包成一次 AI 调用；`per_token` 时直发。Task package JSON：

```json
{
  "package_id": "pk_2026...",
  "parent_trace_id": "tr_root_xxx",
  "billing_mode": "per_call",
  "max_concurrent_subagents": 4,
  "tasks": [
    {
      "id": "t1",
      "agent": "alpha_gen",
      "mode": "explore",
      "dataset_tag": "USA_TOP3000",
      "prompt_template": "explore_v1",
      "context_index_ref": "wsidx_xxx",
      "chain_hook": null
    },
    {
      "id": "t2",
      "agent": "failure_analyzer",
      "dataset_tag": "USA_TOP3000",
      "prompt_template": "review_failure_v1",
      "chain_hook": {
        "from": "t1",
        "transform": "summarize_low_fitness",
        "fallback": "skip"
      }
    }
  ]
}
```

- `chain_hook.from` 必须指向同 package 内更早 task id；同 package 内 chain 串行
- `chain_hook.transform` 名字解析到 `src/wq_bus/ai/transforms/<name>.py` 的函数 `def transform(prev_output: dict, ctx: dict) -> str`
- `chain_hook.fallback`: `skip` | `error` | `passthrough`
- 包内子任务的输出形式由 packer 保证为同结构 JSON 数组，按 `id` 索引

---

## 3. Workspace 规则

每 `dataset_tag`（命名规则 `<REGION>_<UNIVERSE>` 大写）拥有独立 workspace：

```
data/state.db        共享，按 tag 分行
data/knowledge.db    共享，按 tag 分行
                     额外：directions_<TAG>, pool_stats_<TAG> 动态表
memory/<TAG>/        独立目录，含 insights.md / failure_patterns.json / portfolio.json / context_index.json
logs/<TAG>/*.jsonl   独立日志
```

新 dataset_tag 首次出现：`workspace.ensure(tag)` 自动建表+目录+模板。

### 3.1 workspace_rules schema

```python
{
    "reads":  ["pool_stats", "learnings", "insights.md"],
    "writes": ["alphas", "pool_stats", "ai_calls"],
    "memory_files": ["insights.md", "failure_patterns.json"],
}
```

启动时校验 reads/writes 命中已存在的表/文件名（白名单防 typo）。

### 3.2 context_index 协议

agent 调 AI 前调用 `workspace.build_context(tag)`：

```python
{
    "dataset_tag": "USA_TOP3000",
    "pool_summary": [{"direction_id":..., "depth":..., "is_pass_rate":...}, ...],
    "recent_learnings": [...],
    "recent_crawl_summaries": [...],
    "recent_failures": [...],
    "directions_seed": [...],
    "as_of": "2026-04-26T22:00:00Z"
}
```

dispatcher 把 context_index 注入 system prompt（不重复存在 task 里，节约 token）。

---

## 4. Tag 命名规则（硬约束）

```
<REGION>_<UNIVERSE>        # 全大写
USA_TOP3000  CHN_TOP2000  EUR_TOP1200  ASI_MINVOL1500
```

非法 tag → `workspace.ensure` 抛 `InvalidTagError`。任何 BusEvent payload 不带合法 tag → `bus.emit` 拒收。

---

## 5. Topic 动态注册

`src/wq_bus/bus/events.py` 提供：

```python
TOPIC_REGISTRY = {}
def register_topic(name: str, *, payload_schema: dict | None = None) -> str:
    name = name.upper()
    if name in TOPIC_REGISTRY: return name
    TOPIC_REGISTRY[name] = {"payload_schema": payload_schema, "registered_at": now()}
    return name

# 兼容性：保留现有常量
GENERATE_REQUESTED = register_topic("GENERATE_REQUESTED", payload_schema=...)
```

新 agent 在 import 时自行 register_topic 即可，无需改 events.py 主体。

---

## 6. Manual vs Auto 调用约定

```python
dispatcher.call(task_pkg, source: Literal["manual","auto"])
```

- `source="manual"`: 不计 daily_ai_cap；写入 `manual_calls` 表（独立保留）；trace.origin="manual_cli"
- `source="auto"`: 计入 daily_ai_cap；写入 `ai_calls` 表；trace.origin 来自 watchdog/crawler/dispatcher_pack

---

## 7. 新 agent 接入 Checklist

1. 继承 `AgentBase`，声明 `name / subscribes / modes / workspace_rules / billing_hint`
2. 实现 `handle()`、可选 `health()` / `dry_run()`
3. 在 `config/agent_profiles.yaml` 注册 adapter 绑定
4. 若需新 topic，import 时 `register_topic("MY_TOPIC")`
5. 若需新表/记忆文件，在 `workspace.ensure` 中扩展模板
6. 写 fake adapter 单测（`scripts/simulate_ai.py` 一律覆盖）
7. 文档：在 `docs/architecture/AGENT_<NAME>.md` 描述 mode、prompt 模板、输出 schema

---

## 8. 不变量（防回归）

- 任何事件 payload 必须有合法 dataset_tag
- 原始信息绝不覆写（expression / settings / raw_description / prompt / response）
- 全局 dispatcher 并行度 ≤ 4
- subagent 同包内串行（chain_hook）
- 手动调用不计 daily_ai_cap
- 新 agent 必须声明 `workspace_rules`，未声明的读写在 strict 模式下报错

---

## 9. 容错与降级（lenient by default）

agent 启动模式：
- `strict`: 任何契约违规直接抛异常拒启动（用于 CI / 单测）
- `lenient`（默认）: 缺失/非法字段走默认值 + WARN 日志，不阻断

`config/defaults.yaml` 集中维护所有默认值：

```yaml
agent_defaults:
  alpha_gen:
    n_per_request: 4
    timeout_secs: 600
  doc_summarizer:
    batch_threshold: 5
    timeout_secs: 600

payload_defaults:
  GENERATE_REQUESTED:
    n: 4
    mode: explore

workspace_defaults:
  reads:  []
  writes: []
  memory_files: []
```

### 9.1 handle 异常包装

```python
async def _safe_handle(self, event):
    try:
        return await self.handle(event)
    except Exception as e:
        logger.error(...)                  # jsonl 落盘
        await bus.emit("TASK_FAILED",
                       trace_id=event.trace_id,
                       error=repr(e),
                       agent=self.name)
        # agent 不退出，下一个事件继续
```

异常细类：
- `ContextMissingError` → 用 default context 重试 1 次
- `WorkspaceRuleViolation` (lenient) → WARN + 继续；(strict) → re-raise
- `AdapterUnavailable` → 标记 task TASK_FAILED，让 supervisor 走重试

### 9.2 手动状态修复

```bash
wqbus agent dump-state <name> [--json]                 # 看内存/缓存
wqbus agent reload-state <name>                        # 从 DB 重载
wqbus agent set-mode <name> --strict | --lenient
wqbus pool fix-row --tag T --direction-id D ...        # 手动改池
```

任何手动修改写到 `manual_calls` 表（note 字段说明改了什么）以便审计。

### 9.3 日志要求

每个 agent 至少记录：
- on_start / on_event_start / on_event_end / on_error
- 包含字段：`agent / dataset_tag / trace_id / topic / duration_ms / outcome`
- 全部走 jsonl，schema 见 `EXPORT_FORMATS.md §2.2`

---

## 10. 与 AI 调用强度的关系（重要）

**Agent 不感知模型/强度**。流程：

1. Agent.handle 决定要发哪些 task → 写入 task pkg：仅 `{agent, mode, dataset_tag, prompt_template, payload}`
2. 提交给 dispatcher
3. dispatcher 通过 `strength_routing[agent][mode]` 解析出 strength
4. dispatcher 按 `(adapter, strength)` 分桶打包，每桶选对应 model 调用 adapter
5. unpack 后回调写回各 agent

**禁止**：
- agent 在 task pkg 写 `strength` / `model` / `tier` 字段（dispatcher 忽略并 WARN）
- agent 引用 `strength_tiers` 配置

**可做**（受控）：
- 通过 `wqbus ai strength set` CLI 临时调档（人工/policy）
- 修改 `config/agent_profiles.yaml` 的 `strength_routing` 表（重启生效）

如需动态升档（例如 explore 多轮 0 通过自动升 high），由 **WatchdogPolicy** 调 `StrengthRouter.set_override(...)` 实现，agent 自身无此权限。详见 `AI_DISPATCHER.md §3.2`。
