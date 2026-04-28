# AI_DISPATCHER — AI 调用中间层

> dispatcher 是所有 agent ↔ AI 之间的唯一通道。负责：billing 分流、subagent 打包、chain_hook 串行、并发节流、记账、重试、手动/自动分账。

---

## 1. 调用入口

```python
from wq_bus.ai import dispatcher

result = await dispatcher.call(
    task_pkg: TaskPackage,
    source: Literal["manual","auto"] = "auto",
)
```

无 agent 直接 import adapter；统统经 dispatcher。

---

## 2. billing_mode 分流 + 强度集中调度

> **设计决策**：strength（模型档位）由 dispatcher 统一管理，agent **不参与、不输出、不感知**。
> agent 在 task 里只声明 `agent + mode`，dispatcher 通过 `strength_routing` 表决定档位与 model。
> 这样多 task 打包时不会出现"混档"问题——packer 直接按解析后的 strength 分桶。

`config/agent_profiles.yaml`:

```yaml
adapters:
  copilot_cli:
    billing_mode: per_call
    bin: "copilot"
    flags: ["--no-color"]
    strength_tiers:
      high:   {model: "claude-opus-4.7",   depth: deep}
      medium: {model: "claude-sonnet-4.6", depth: normal}
      low:    {model: "claude-haiku-4.5",  depth: shallow}
  openai_gpt5:
    billing_mode: per_token
    model: "gpt-5"
    api_key_env: "OPENAI_API_KEY"
    strength_tiers: null      # 单档，无视档位映射
  glm_4_5:
    billing_mode: per_token
    model: "glm-4.5-flash"
    api_key_env: "ZHIPUAI_API_KEY"
    strength_tiers: null

# (agent, mode) → strength 集中路由表（dispatcher 唯一查询入口）
# 缺失键全走 default
strength_routing:
  default: medium
  alpha_gen:
    explore:        medium
    specialize:     high
    review_failure: medium
    track_news:     low
  failure_analyzer:
    "*":            medium       # 任意 mode
  doc_summarizer:
    "*":            low

agents:
  alpha_gen:        {adapter: copilot_cli}
  failure_analyzer: {adapter: copilot_cli}
  doc_summarizer:   {adapter: copilot_cli}
  dataset_analyst:  {adapter: openai_gpt5}     # phase 3
```

dispatcher 流程：

```
TaskPackage(tasks 仅含 agent + mode，无 strength 字段)
   │
   ▼ ① 解析 strength = StrengthRouter.resolve(agent, mode)
   │   每 task 标注 _resolved_strength（内部字段，不写库）
   │
   ▼ ② 按 adapter.billing_mode 分流
   │
   ├─ per_call  → batch_buffer
   │             ↓
   │             packer 按 (adapter, strength) 分桶 → 多个子包
   │             每子包内 strength 单一 → 选 model → 1 次 adapter 调用
   │
   └─ per_token → 跳过 buffer/packer
                  adapter 单档 → 直接发
                  多档 → 按 strength 选 model 后发
                  → 每 task 1 次调用（仍受全局并发 ≤ 4）
```

**关键不变量**：
- agent 不能写 `strength` / `model` 字段；写了也被 dispatcher 忽略 + WARN
- packer 永不混档：同一子包内所有 task strength 相同
- 运行时调档只能由人工或专用 policy 通过 `strength_overrides` 注入（见 §3.2）

---

## 3. StrengthRouter 路由解析

### 3.1 解析顺序

```python
def resolve(agent: str, mode: str | None) -> str:
    cfg = config.strength_routing
    # 1. 临时 override（人工 / policy 注入，进程内 dict，TTL 可选）
    if (agent, mode) in overrides:
        return overrides[(agent, mode)]
    # 2. 精确 (agent, mode)
    if mode and cfg.get(agent, {}).get(mode):
        return cfg[agent][mode]
    # 3. agent 级通配 "*"
    if cfg.get(agent, {}).get("*"):
        return cfg[agent]["*"]
    # 4. 全局 default
    return cfg.get("default", "medium")
```

adapter 单档（`strength_tiers=null`）：解析仍执行（用于日志/审计），但 adapter 内部忽略，记一次 DEBUG。

### 3.2 运行时 override（受控通道）

```bash
wqbus ai strength set --agent alpha_gen --mode explore --to high [--ttl-min 60]
wqbus ai strength clear --agent alpha_gen --mode explore
wqbus ai strength list [--json]
```

仅以下来源可写 override：
- 人工 CLI（写 `manual_calls.note`）
- WatchdogPolicy（明确策略，例如连续 3 轮 explore 0 通过 → 临时升 high，TTL 30 min）

agent 代码内**禁止**写 override。

---

## 4. batch_buffer（仅 per_call）

```yaml
batch_buffer:
  max_secs: 10
  max_tasks_per_bucket: 6
  flush_on_chain: true     # 包内有 chain_hook 立即 flush，不再等
```

buffer 内部按 `(adapter, strength)` 分桶。每桶独立计数。

flush 触发：任一桶达到 `max_tasks_per_bucket` **或** 达到 `max_secs`（全 buffer）**或** 出现 chain_hook **或** manual_call → 把所有桶分别 flush 成多个 package。

per_token 不进 buffer。

---

## 5. subagent_packer（仅 per_call，单桶单包）

把多个 task 编入同一 prompt：

```
SYSTEM
你将依次完成以下 N 个独立子任务。返回严格 JSON 数组，元素一一对应 tasks[]。
不要解释，不要寒暄。

CONTEXT_INDEX (workspace USA_TOP3000)
{ pool_summary: ..., recent_learnings: ... }

TASKS
[
  {"id":"t1","goal":"...","template":"explore_v1","payload":{...}},
  {"id":"t2","goal":"...","template":"review_failure_v1","payload":{...}}
]

OUTPUT_SCHEMA
[{"id":"t1","status":"ok|error","data":{...}|null,"error":null|"..."}]
```

unpack：解析 JSON 数组，按 id 回写每 task 的结果到 `manual_calls`/`ai_calls` 表 + 各 agent 的回调。

### chain_hook 串行

包内若 t2 有 `chain_hook.from=t1`：
1. 先单独打包并发出仅含 {t1, t3, ...无依赖} 的 prompt
2. 收到 t1 结果后，调 `transforms.<name>(t1.result, ctx)` 生成 t2 prompt 片段
3. 再打包 {t2} （+其它依赖 t1 完成的）发第二次

同包内最多两层 chain（避免组合爆炸），更深的 chain 拆成多 package。

---

## 6. 全局并发节流

```yaml
concurrency:
  global_max: 4            # dispatcher 全局信号量
  per_adapter_max:
    copilot_cli: 2
    openai_gpt5: 4
```

无论 per_call 还是 per_token 都受此限制。

---

## 7. 速率/配额

```yaml
rate_limits:
  daily_ai_cap: 80         # 仅 source=auto 计入
  per_round_cap: 12        # watchdog 单轮触发上限
  cooldown_min_per_mode: 30
```

`source=manual` 完全不计 cap，但仍写入 `manual_calls` 表。

---

## 8. 记账

### 8.1 ai_calls（auto）
- adapter / model / agent_type / mode / **strength** / depth / n_packed / source / duration_ms / success / error / dataset_tag / trace_id / package_id / cost_estimate

`strength` 字段记录 dispatcher 解析后的最终档位（high|medium|low|n/a），用于事后分析"高档调用是否值得"。

### 8.2 manual_calls（manual，独立表）
- 同上 + `note` / `tags` / `archived`（archive_classifier 用）

migration 005:
```sql
CREATE TABLE manual_calls (
  call_id TEXT PRIMARY KEY,
  adapter TEXT, model TEXT, agent_type TEXT, mode TEXT,
  strength TEXT,                   -- high|medium|low|n/a
  source TEXT DEFAULT 'manual_cli',
  prompt TEXT NOT NULL,            -- 原文保留
  response TEXT,                   -- 原文保留
  dataset_tag TEXT,
  trace_id TEXT,
  duration_ms INTEGER,
  success INTEGER,
  error TEXT,
  note TEXT,
  tags_json TEXT,
  archived INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
```

---

## 9. 中断恢复（文件 cache 驱动）

每个 dispatcher.call 创建 `data/ai_cache/<package_id>/` 目录：

```
data/ai_cache/<package_id>/
  meta.json         ← 写入即建：{trace_id, agents, source, strength, started_at, adapter, model}
  input.json        ← 完整 prompt 与 task pkg
  stage             ← 文本文件: queued|sent|received|unpacked|done|failed
  raw_response.txt  ← 收到立即落，未做 JSON 解析
  result.json       ← unpack 后写
  error.txt         ← 失败原因
```

启动时 dispatcher 扫描：
- `stage=queued` → 重新入队发送
- `stage=sent` 但缺 `raw_response.txt` → 视为未送达，重发（最多 1 次）
- `stage=received` 但缺 `result.json` → 重新 unpack（解析失败再重发 1 次）
- `stage=unpacked` 但 result 缺某 task id → 单独 reissue 那一个 task（沿用原 strength，不重发整包）
- `stage=done` 或 `failed` → 跳过

每次状态变更原子写 `stage` 文件。`done` 后保留 24h 用于 trace tree 还原，再归档到 `data/ai_cache/archive/<YYYY-MM-DD>/`。

CLI：
```bash
wqbus ai cache list [--stage S] [--json]
wqbus ai cache show <package_id> [--json]
wqbus ai cache replay <package_id>           # 强制重发
wqbus ai cache prune --before <date>
```

---

## 10. 失败重试

- 网络/超时/进程崩溃：自动重试 1 次（同 task_pkg）
- 解析失败（JSON 不合法）：让 adapter 加一句 "请严格输出 JSON" 重试 1 次
- subagent 包内某子任务输出缺失：仅重发缺失子任务（沿用原 strength）
- 二次仍失败 → 标 dead，写入 `dead_letter` 表（phase 2）+ emit `TASK_FAILED`

---

## 11. transforms 注册

`src/wq_bus/ai/transforms/<name>.py`：

```python
def transform(prev_output: dict, ctx: dict) -> str:
    """返回拼进下一 task prompt 的文本片段"""
    ...
```

启动时 `transforms.discover()` 扫描目录注册。chain_hook.transform 引用名字。

---

## 12. CLI

```bash
wqbus ai status [--json]                 # 当前 buffer / 并发 / 配额 / cache 待恢复数 / 各 strength 桶大小
wqbus ai cap --reset                     # 手动重置 daily_ai_cap
wqbus ai dump-call <call_id> [--json]
wqbus ai manual list [--unarchived] [--json]
wqbus ai cache list / show / replay / prune
wqbus ai strength list / set / clear     # 见 §3.2
```

---

## 13. 不变量

- 任何 agent 不得绕过 dispatcher 直调 adapter
- prompt/response 全文落库 + cache 文件，绝不裁剪
- chain_hook 只在 per_call 包内有效；per_token 模式下 chain 由调用方自行 await
- 全局并发硬上限 ≤ 4，超出排队
- billing_mode / strength_tiers 是 adapter 属性
- **strength 由 dispatcher 集中解析；agent 不输出 strength / model**
- packer 同包同档：永不混 strength 打包
- ai_cache stage 转换原子（重命名 `.tmp` → 最终名）
