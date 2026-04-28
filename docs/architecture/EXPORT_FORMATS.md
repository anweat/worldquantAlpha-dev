# EXPORT_FORMATS — JSON 导出与日志规范

> 所有 CLI 状态/导出命令必须支持 `--json`；所有日志统一 jsonl；为未来 HTML dashboard 准备只读 JSON 数据源。

---

## 1. CLI `--json` 通用规则

- 任何 `wqbus ... status / list / show / dump / tree` 命令必须支持 `--json`
- 输出严格为单个 JSON 对象/数组，无任何额外文本（不带颜色码、不带提示语）
- 错误信息走 stderr，stdout 仅 JSON
- 时间字段一律 ISO 8601 UTC（`2026-04-26T14:00:00Z`）
- 字节大小、duration 字段加 `_bytes` / `_ms` 后缀

样例：

```bash
wqbus status --json
wqbus pool list --tag USA_TOP3000 --json
wqbus task list --status running --json
wqbus trace tree tr_xxx --json
wqbus ai manual list --json
wqbus config dump --json                  # 当前合并后的全量配置快照
wqbus export alphas --since 2026-04-20 --json
```

---

## 2. 日志规范

### 2.1 文件布局

```
logs/
  daemon.jsonl                   全局 daemon 事件
  bus.jsonl                      总线 emit/handle 全量
  ai.jsonl                       dispatcher 调用记录（auto+manual）
  brain.jsonl                    BRAIN REST 调用
  <TAG>/                         按 dataset 分目录
    alpha_gen.jsonl
    sim_executor.jsonl
    crawler.jsonl
```

### 2.2 jsonl 行 schema

每行一个 JSON 对象，必含字段：

```json
{
  "ts": "2026-04-26T14:00:00.123Z",
  "level": "INFO|WARN|ERROR|DEBUG",
  "logger": "wq_bus.agents.alpha_gen",
  "dataset_tag": "USA_TOP3000",
  "trace_id": "tr_xxx",
  "event": "ALPHA_DRAFTED",
  "msg": "...",
  "extra": { ... }
}
```

不符合 schema 的行视为 bug。

### 2.3 旋转

按日 rotate，保留 14 天；超过的归档到 `logs/archive/<date>/`。

---

## 3. 状态导出 schema

### 3.1 `wqbus status --json`

```json
{
  "as_of": "2026-04-26T14:00:00Z",
  "session_valid": true,
  "datasets": [
    {
      "tag": "USA_TOP3000",
      "alphas_total": 1282,
      "alphas_submitted": 2,
      "queue_pending": 0,
      "in_flight_sims": 0,
      "directions_total": 47,
      "ai_today_total": 11,
      "ai_today_auto": 8,
      "ai_today_manual": 3
    }
  ],
  "active_traces": [...],
  "supervisor": {"tick_secs": 15, "running": true}
}
```

### 3.2 `wqbus pool list --tag <T> --json`

```json
{
  "dataset_tag": "USA_TOP3000",
  "directions": [
    {
      "direction_id": "fundamental.ratio|rank|SUBINDUSTRY|0",
      "semantic_name": "fund_ratio_industry_neut_lowdecay",
      "origin": "auto_extract",
      "raw_description": null,
      "alphas_tried": 23,
      "alphas_is_passed": 8,
      "alphas_submitted": 1,
      "avg_self_corr": 0.42,
      "avg_sharpe": 1.31,
      "avg_fitness": 1.05,
      "depth": 0.45, "breadth": 0.31,
      "status": "active",
      "last_explored_at": "..."
    }
  ]
}
```

### 3.3 `wqbus trace tree <id> --json`

```json
{
  "trace_id": "tr_root",
  "kind": "generate", "origin": "watchdog",
  "status": "running", "started_at": "...",
  "events_count": 12, "ai_calls_count": 3,
  "children": [
    {"trace_id": "tr_pack_1", "kind":"...", ...,
     "children": [{...}]}
  ]
}
```

### 3.4 `wqbus ai status --json`

```json
{
  "buffer":      {"size":2, "oldest_age_ms":3400},
  "concurrency": {"global_inflight":1, "global_max":4},
  "rate_limits": {"daily_ai_cap":80, "auto_today":11, "manual_today":3, "remaining":69},
  "adapters":    {"copilot_cli":{"healthy":true}, "openai_gpt5":{"healthy":true}}
}
```

### 3.5 `wqbus config dump --json`

合并所有 yaml 后的最终生效配置（含默认值），未来前端可直接渲染。

---

## 4. 导出命令

```bash
wqbus export alphas      [--since DATE] [--tag TAG] [--json|--csv]
wqbus export ai-calls    [--since DATE] [--source auto|manual] [--json|--csv]
wqbus export traces      [--since DATE] [--kind KIND] [--json]
wqbus export pool        [--tag TAG] [--json|--csv]
wqbus export learnings   [--tag TAG] [--json]
```

`--csv` 用于 Excel；`--json` 是默认/前端用。

---

## 5. 未来 HTML Dashboard 数据源（phase 后置）

约定：dashboard 不直连 SQLite，而是读 dispatcher 周期生成的 `data/snapshots/*.json`：

```
data/snapshots/
  status.json            ← 每 30s 刷新
  pool_<TAG>.json
  traces_recent.json
  ai_calls_recent.json
```

phase 1 不实现 snapshot writer；先确保所有 `--json` CLI 输出 schema 与 snapshot schema 一致。

---

## 6. 不变量

- `--json` 输出永不混入非 JSON 文本
- jsonl schema 必含 ts / level / logger / dataset_tag / trace_id
- 时间一律 ISO 8601 UTC
- 数值字段单位写在字段名里（`_ms` / `_bytes` / `_secs`）
- schema 演进只能加字段，不删/不改字段语义
