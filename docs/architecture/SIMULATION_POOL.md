# SIMULATION_POOL — 维度 / 方向 / 模拟池模型

> 本文件定义 alpha 探索状态的存储与决策模型。所有 watchdog 加权、alpha_gen mode 选择、failure_analyzer 复盘均依赖于本模型。

---

## 1. 三层概念

```
维度 (Dimensions)        硬编码、有限、可枚举
   ↓ 解析
向量 (Feature Vector)    每个 alpha 都能算出一个完整向量
   ↓ 投影 (取前 4 维)
方向 (Direction)         维度向量上的一个离散坐标 OR 一段自由描述
                         direction_id 用于 SQL 分组 / 池化记账
```

**核心约定**：原始信息（alpha.expression / settings / raw_description）绝不覆写；feature_vector 与 direction_id 只能新增列。

---

## 2. 维度定义（硬编码）

`src/wq_bus/domain/dimensions.py`：

```python
DATA_FIELD_CLASSES = [
    "fundamental.ratio", "fundamental.absolute",
    "price", "volume", "technical", "macro", "other"
]
OPERATOR_CLASSES = [
    "rank", "group_rank",
    "ts_basic",     # ts_delta/ts_mean/ts_std_dev/...
    "ts_corr",
    "arith",        # +,-,*,/,log,exp
    "logical",      # ?:, if_else
    "winsorize",
    "other"
]
NEUTRALIZATION = ["NONE","MARKET","SECTOR","INDUSTRY","SUBINDUSTRY","COUNTRY","STATISTICAL"]
DECAY_BAND     = ["0","1-4","5-15","16-30",">30"]
TURNOVER_BAND  = ["<5%","5-30%","30-70%",">70%"]

PROJECTION_DIMS = ["data_field_class", "operator_class", "neutralization", "decay_band"]
```

字段→class 映射读 `config/datasets.yaml` 中的 `field_class_map`（已存在可扩）。

---

## 3. 方向的两种表述形式

### ① 轴向投影（自动生成，可 SQL）

```
direction_id = "fundamental.ratio|rank|SUBINDUSTRY|0"
semantic_name = "fund_ratio_industry_neut_lowdecay"
origin = "auto_extract"
raw_description = NULL
```

### ② 自由描述（人/agent 输入，保留原文）

```
direction_id = "<前 4 维投影>"   ← 解析后仍生成，可与①合并去重
semantic_name = "vol_ret_corr_60d_industry_neut"
origin = "manual" 或 "llm_aggregate" 或 "seed"
raw_description = "用 ts_corr 把成交量与收益率做60日相关后行业中性化"
```

两种形式同一行存储；`raw_description` 仅当为②时非空。

---

## 4. Schema（动态多表，每 dataset_tag 一套）

migration `003_pool.sql` 提供模板，运行时 `workspace.ensure(tag)` 用 `.format(TAG=tag)` 实例化：

```sql
CREATE TABLE IF NOT EXISTS directions_{TAG} (
  direction_id        TEXT PRIMARY KEY,
  semantic_name       TEXT,
  raw_description     TEXT,
  origin              TEXT NOT NULL,        -- seed|auto_extract|manual|llm_aggregate
  feature_vector_json TEXT NOT NULL,
  example_alpha_ids   TEXT,                 -- JSON array
  themes_csv          TEXT,                 -- 衍生：从 alpha.themes_csv 聚合，多值 CSV (见 COMPOSITION_RECIPES.md)
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pool_stats_{TAG} (
  direction_id     TEXT PRIMARY KEY REFERENCES directions_{TAG}(direction_id),
  alphas_tried     INTEGER DEFAULT 0,
  alphas_is_passed INTEGER DEFAULT 0,
  alphas_submitted INTEGER DEFAULT 0,
  avg_self_corr    REAL,
  avg_sharpe       REAL,
  avg_fitness      REAL,
  depth            REAL,
  breadth          REAL,
  status           TEXT DEFAULT 'active',   -- active|saturated|abandoned|hot
  last_explored_at TEXT
);

-- 全局加列
ALTER TABLE alphas ADD COLUMN direction_id TEXT;
ALTER TABLE alphas ADD COLUMN feature_vector_json TEXT;
ALTER TABLE alphas ADD COLUMN themes_csv TEXT;             -- 由 recipe matcher 写入 (见 COMPOSITION_RECIPES.md)
ALTER TABLE alphas ADD COLUMN cluster_id TEXT;     -- phase 3 才填
```

---

## 5. 写入流程

```
alpha_gen 产出 raw alpha (expression + settings + prompt_hint)
  → INSERT alphas (原样保留)
  → fv = dimensions.classify(expression, settings)
  → direction_id = projection(fv)
  → themes = recipes.match(expression)            # 见 COMPOSITION_RECIPES.md §3
  → UPDATE alphas SET direction_id, feature_vector_json, themes_csv
  → pool.upsert_direction(tag, direction_id, fv,
                          raw_description=prompt_hint,
                          origin="auto_extract",
                          themes_csv=themes)
  → pool.bump_stats(tag, direction_id, alphas_tried+=1)

sim_executor 完成
  → pool.bump_stats(is_passed += pass?,
                    avg_sharpe/avg_fitness/avg_self_corr 增量更新)

submit_pipeline
  → pool.bump_stats(submitted += 1)

定期重算 direction.themes_csv（每 N 个新 alpha 或周期 task）：
  → 取该 direction 下所有 alpha.themes_csv → 多数票/并集 → 写回
```

种子方向（`config/directions_seed.yaml`）启动时 `pool.ensure_seeds(tag)` 入库，origin=seed。

---

## 6. WatchdogPolicy 加权算法（Default）

输入：`pool_stats` 全表 + 最近 N 轮触发分布 + queue/in-flight 状态。

```python
base = {"explore": 4, "direction": 2, "specialize": 1}  # config/triggers.yaml

# 自适应：补偿最近窗口下未触发的模式
recent_share = recent_window_distribution()
adj = {m: base[m] * (1.0 - recent_share.get(m, 0)) for m in base}

# 信号修正
if any(d.avg_self_corr > 0.6 for d in active): adj["explore"] *= 1.5
if any(d.is_pass_rate > 0.4 and d.submitted < target for d in active):
    adj["specialize"] *= 1.5
if alphas_total_in_pool < 50: adj["explore"] *= 2.0

mode = weighted_random_pick(adj)
direction_hint = pick_direction(mode, pool_stats)
emit GENERATE_REQUESTED(mode=mode, dataset_tag=tag, direction_hint=direction_hint)
```

底线（必须满足才触发）：
- `queue_pending < queue_cap`（默认 2000，config 可调）
- `in_flight_sims == 0`（避免 BRAIN 429 时刷）
- 距上一次同 mode 触发 ≥ `cooldown_min`（默认 30）
- `auto_ai_calls_today < daily_ai_cap`（手动调用不计）

---

## 7. cluster_id（phase 3 占位）

phase 1：`alphas.cluster_id` 列建好留空。
phase 3：clusterer agent 读 alphas + fingerprints + pnl_corr 矩阵 → DBSCAN/KMeans → 写 cluster_id；同时为每 cluster 的代表向量建 representative_alpha_id 索引。

---

## 8. find_underexplored 算法（用于 explore mode）

```python
# 给定 dataset_tag，返回 K 个待探索方向（hint 列表）
def find_underexplored(tag, k=3):
    all_combos = cartesian_product(DATA_FIELD_CLASSES, OPERATOR_CLASSES,
                                   NEUTRALIZATION, DECAY_BAND)
    seen = {row.direction_id for row in directions_<tag>}
    candidates = [c for c in all_combos if direction_id_of(c) not in seen]
    # 按距离已通过方向"不太远"排序（避免完全离谱的组合）
    return sorted(candidates, key=distance_to_passed_centroid)[:k]
```

specialize mode 反向：选 `is_pass_rate > 阈值 且 submitted < target` 的方向。

---

## 9. 不变量

- 维度集合只能增不能改（旧 direction_id 永不重映射）
- 原始 expression/settings/raw_description 不被覆写
- 每条新 alpha 必须有 direction_id（解析失败走 `unknown` direction）
- direction_id 是 stable 字符串，可作为 SQL group key
- LLM 聚合产生的新方向必须 origin=llm_aggregate，且 raw_description 非空
