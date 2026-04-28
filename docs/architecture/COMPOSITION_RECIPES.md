# COMPOSITION_RECIPES — 算子组合 → 主题映射池

> recipe = "运算符 + 字段槽" 的可匹配模板，用于把 alpha 表达式自动归类到一个或多个主题（theme）。recipe 池独立于 directions / pool_stats，理论上可无限增长。

---

## 1. 核心模型

```
alpha.expression
   │
   ▼  matcher (regex 优先 → AST fallback)
命中 N 条 recipe
   │
   ▼  并集 / 多数票
alpha.themes_csv  ←  写回 alphas 行（衍生列）
   │
   ▼  按 direction 聚合
directions.<TAG>.themes_csv  ←  方向级主题
```

反向：
```
agent 选 theme=momentum.short
   │
   ▼  反查 composition_recipes WHERE theme_tags LIKE '%momentum.short%'
N 条 recipe 模板
   │
   ▼  字段槽位填入候选字段
prompt 给 alpha_gen 当 hint
```

---

## 2. Schema

```sql
-- 全局表（不按 dataset 分），所有 workspace 共享 recipe 池
CREATE TABLE IF NOT EXISTS composition_recipes (
  recipe_id         TEXT PRIMARY KEY,
  semantic_name     TEXT NOT NULL,                 -- "短期动量"
  pattern_regex     TEXT,                          -- 可选 regex
  pattern_ast_json  TEXT,                          -- 可选 AST 描述
  theme_tags        TEXT NOT NULL,                 -- CSV: "momentum.short,reversal"
  field_slots_json  TEXT,                          -- ["<X>","<Y>"] 槽位说明
  example_expressions TEXT,                        -- JSON array
  origin            TEXT NOT NULL,                 -- builtin|user_defined|llm_proposed
  enabled           INTEGER DEFAULT 1,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  notes             TEXT
);
CREATE INDEX idx_recipes_theme ON composition_recipes(theme_tags);

-- alpha 行加列
ALTER TABLE alphas ADD COLUMN themes_csv TEXT;          -- "momentum.short,sentiment.opt"

-- direction 行加列（每 dataset 各自）
ALTER TABLE directions_<TAG> ADD COLUMN themes_csv TEXT;
```

---

## 3. Matcher

### 3.1 regex（优先）

```yaml
# config/composition_recipes_seed.yaml 示例
- recipe_id: ts_delta_short
  semantic_name: "短期动量"
  pattern_regex: "rank\\(ts_delta\\(<X>,([1-5])\\)\\)"
  field_slots: ["<X>"]
  theme_tags: "momentum.short"
  origin: builtin

- recipe_id: vol_ret_corr_60d
  semantic_name: "60日量收相关"
  pattern_regex: "ts_corr\\(<VOL>,<RET>,60\\)"
  field_slots: ["<VOL>","<RET>"]
  theme_tags: "sentiment.liquidity,reversal"
  origin: builtin
```

`<X>` `<VOL>` `<RET>` 等占位由 `field_class_map` 解析（`<VOL>` 必须落在 volume 类字段上）。

### 3.2 AST（fallback）

regex 无法表达嵌套时，用 `pattern_ast_json`：

```json
{
  "op": "rank",
  "args": [{"op": "ts_corr", "args": [{"slot":"<VOL>","class":"volume"},
                                       {"slot":"<RET>","class":"price"},
                                       {"const":60}]}]
}
```

matcher 把 alpha 表达式 parse 成 AST 后做模式 unification。

### 3.3 命中策略

- 一条 alpha 可命中多 recipe → theme_tags 取并集
- 0 命中 → `themes_csv = NULL`（不报错，WARN 日志）
- 多条 recipe 主题冲突 → 全部保留，由 direction 聚合时再决议

---

## 4. 反查（生成模式 hint）

```python
def hint_for_theme(theme: str, dataset_tag: str, k: int = 3) -> list[Hint]:
    rows = db.query("SELECT * FROM composition_recipes "
                    "WHERE theme_tags LIKE ? AND enabled=1 "
                    "ORDER BY RANDOM() LIMIT ?", (f"%{theme}%", k))
    return [Hint(recipe=r, candidate_fields=resolve_slots(r, dataset_tag))
            for r in rows]
```

`resolve_slots` 用当前 dataset 的可用字段填槽（按 field_class_map 限制类别）。

---

## 5. recipe 增长机制

| 来源 | 写入时机 | origin |
|---|---|---|
| 启动 seed | `recipes.ensure_seeds()` 读 `config/composition_recipes_seed.yaml` 入库 | builtin |
| CLI 手动 | `wqbus recipe add --file r.yaml` | user_defined |
| LLM 提议 | dataset_analyst（phase 3）输出 → 待人工 review → enable | llm_proposed |
| 失效 | `wqbus recipe disable <id>` 不删，保留历史 | — |

```bash
wqbus recipe list [--theme T] [--json]
wqbus recipe show <id> [--json]
wqbus recipe match <expression> --json   # 调试 matcher 命中情况
```

---

## 6. 主题命名规则（layered）

```
<group>.<sub>
  momentum.short / momentum.medium / momentum.long
  reversal.short / reversal.long
  sentiment.optimism / sentiment.fear / sentiment.liquidity
  regime.risk_on / regime.risk_off
  event.earnings / event.macro / event.news
  factor.value / factor.quality / factor.size
  technical.breakout / technical.range
```

`config/themes.yaml` 维护合法主题白名单；recipe 中引用未登记主题 → 启动校验 WARN 但不阻止。

---

## 7. 不变量

- recipe 池全局共享（不按 dataset 分），但反查时 `resolve_slots` 必须按 dataset 限制可用字段
- 一旦 recipe 被某 alpha 命中，alpha.themes_csv 写入后不覆写（追加合并）
- recipe 删除走 `enabled=0`，永不物理删除
- direction.themes_csv 由 pool 聚合周期重算，不是 alpha 写入直接同步
- LLM 提议的 recipe 默认 `enabled=0`，需要人工 enable
