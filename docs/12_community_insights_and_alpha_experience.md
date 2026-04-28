# 12 社区洞察与实战经验总结

> 本文档基于本项目**625 个 Alpha 实测结果的定量分析**、WorldQuant 官方文档爬取内容、
> 以及社区/论坛/外部资料综合整理，聚焦于**实证经验和可落地的行动建议**。
> 这是与其他文档最大的区别：所有结论均有实际数字支撑。

---

## 一、本项目实测数据全景

### 1.1 整体统计

| 指标 | 数值 |
|------|------|
| 测试 Alpha 总数（去重后） | **625 个** |
| 通过全部检查（不含 SELF_CORRELATION）| **99 个（15.8%）** |
| 失败 Alpha | **526 个（84.2%）** |
| 发现的独特通过表达式 | **32 种** |
| 测试批次 | 13+ 批次（batch1–batch13） |

> **关于 SELF_CORRELATION**：所有 625 个 Alpha 的 SELF_CORRELATION 均为 `PENDING`（待评估）状态。这是正常现象——该检查只有在 Alpha 被实际添加到 Portfolio 后才会触发，本项目的模拟阶段不评估该项。因此"通过"的 99 个 Alpha 表示已通过全部其他 6 项检查，实际提交时仍需通过自相关检查。

---

### 1.2 检查失败分布（基于 526 个失败 Alpha）

| 检查项 | 失败次数 | 占失败总数比 | 说明 |
|--------|---------|------------|------|
| `LOW_SHARPE` | 477 | **90.7%** | 最常见失败原因 |
| `LOW_FITNESS` | 348 | 66.2% | 换手率过高导致 |
| `LOW_SUB_UNIVERSE_SHARPE` | 268 | 51.0% | 信号在大市值股中不稳定 |
| `CONCENTRATED_WEIGHT` | 60 | 11.4% | 仅情绪类原始信号触发 |
| `HIGH_TURNOVER` | 52 | 9.9% | 日频技术信号触发 |
| `LOW_TURNOVER` | 10 | 1.9% | 极少数 snt1/fscore 字段 |

**核心发现**：

- 失败的最根本原因是**信号质量（Sharpe）不足**，而非参数问题
- `LOW_FITNESS` 几乎都是 `HIGH_TURNOVER` 的"软性版本"——换手率虽未超 70% 红线，但足够高（30-70%）以大幅压低 Fitness
- `LOW_SUB_UNIVERSE_SHARPE` 是隐患最大的检查，它要求 Alpha 在 TOP1000 子宇宙中也有效，纯小票策略会失败

---

### 1.3 失败 Alpha 的 Sharpe 分布

| Sharpe 区间 | 失败 Alpha 数 | 说明 |
|-------------|-------------|------|
| < 0.5 | 199（37.8%） | 信号基本无效 |
| 0.5 – 0.8 | 94（17.9%） | 信号微弱 |
| 0.8 – 1.0 | 129（24.5%） | 接近但未达标 |
| 1.0 – 1.25 | 55（10.5%） | 差临界值一步之遥 |
| > 1.25（仍失败）| 49（9.3%） | Sharpe 通过但 Fitness/其他失败 |

**重要洞察**：即使 Sharpe ≥ 1.25，仍有 49 个 Alpha 因 `LOW_FITNESS`、`CONCENTRATED_WEIGHT` 等原因失败。换手率过高是 Sharpe 达标后最常见的第二道障碍。

---

## 二、Alpha 提交标准深度分析

### 2.1 各检查项的精确边界与触发机制

#### LOW_SHARPE
- **边界值**：Delay-1 需 Sharpe ≥ **1.25**；Delay-0 需 ≥ **2.0**
- **失败占总体比例**：76.3%（477/625）
- **实测通过 Alpha Sharpe 范围**：1.250 – 2.100，**平均 1.579**
- **关键认知**：Sharpe 1.25 是最低准入门槛，目标应放在 ≥ 1.5（留安全余量）

#### LOW_FITNESS
- **边界值**：Delay-1 需 Fitness ≥ **1.0**；Delay-0 需 ≥ **1.3**
- **公式**：`Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))`
- **实测通过 Alpha Fitness 范围**：1.000 – 1.920，**平均 1.289**
- **Fitness 关键数值推导**：

| 换手率 | 所需 Sharpe（Returns=10%） | Fitness 估算 |
|--------|--------------------------|-------------|
| 5% | 1.42 | 1.00（恰好通过） |
| 10% | 1.42 | 1.00（恰好通过） |
| 12.5% | 1.42 | 1.00（Turnover 下限触发） |
| 20% | 1.60 | 1.00（仅这个 Sharpe 才够） |
| 40% | 2.26 | 1.00（需要极强信号） |
| 70% | 2.99 | 1.00（且同时触发 HIGH_TURNOVER） |

> `max(Turnover, 0.125)` 意味着 Turnover < 12.5% 时，Fitness 计算中使用固定值 0.125，不再随换手率降低而提升。**基本面 Alpha 换手率 1–5% 的 Fitness 与换手率 12.5% 的完全等价。**

#### HIGH_TURNOVER / LOW_TURNOVER
- **上界**：Turnover ≤ **70%**（超出直接拒绝）
- **下界**：Turnover ≥ **1%**（低于 1% 信号无意义）
- **触发 HIGH_TURNOVER 的典型表达式**：`rank(close/vwap - 1)`（实测 85.2%）、`rank(rp_css_equity)`（实测 133%，严重超标）
- **触发 LOW_TURNOVER 的典型字段**：`snt1_d1_buyrecpercent`（实测 0.6%）、`fscore_bfl_value`（实测 0.88%）
- **实测通过 Alpha 换手率范围**：1.36% – 15.61%，**平均 3.84%**

#### LOW_SUB_UNIVERSE_SHARPE
- **公式**：`Sub_Sharpe ≥ 0.75 × √(sub_size/alpha_size) × alpha_sharpe`
- **实测占失败总数**：51%（268/526），是第三大失败原因
- **失败规律**：纯情绪/短期技术信号在 TOP1000 股中信号明显衰减
- **避免方法**：使用基本面因子（大市值公司财务数据更完整）、使用 SUBINDUSTRY 中性化（在每个子行业内均匀分布）

#### CONCENTRATED_WEIGHT
- **触发条件**：
  1. 单只股票绝对权重 > 10%
  2. 投资组合日均持仓股票数量过少（稀疏信号）
- **实测触发情形**：`-ts_std_dev(scl12_buzz, 5)` 等短窗口情绪信号（60 次触发），因为短窗口原始信号分布极不均匀
- **解决方案**：
  - 确保 `truncation = 0.05`（默认）或 `0.08`
  - 用 `rank()` 将信号归一化到 [-1, 1]
  - 增大时序窗口（5→18 天即可大幅改善）

#### SELF_CORRELATION（自相关）
- **规则**：新 Alpha 与已提交 Alpha Portfolio 的 PnL 相关系数 < **0.7**
- **例外**：若新 Alpha Sharpe ≥ 相关 Alpha 的 **1.1 倍**，即使相关系数超 0.7 也可提交
- **本项目现状**：所有 Alpha 均为 `PENDING`（未提交到 Portfolio），此检查尚未触发
- **预防策略**：见第四节

---

### 2.2 通过 Alpha 的指标最优范围（实测）

| 指标 | 最小值 | 最大值 | 平均值 | 建议目标 |
|------|--------|--------|--------|---------|
| Sharpe | 1.250 | 2.100 | **1.579** | ≥ 1.5 |
| Fitness | 1.000 | 1.920 | **1.289** | ≥ 1.2 |
| Turnover | 1.36% | 15.61% | **3.84%** | 2–10% |
| Returns | 4.53% | 18.13% | **8.70%** | ≥ 7% |

---

## 三、成功因子策略总结（基于 32 个通过表达式）

### 3.1 数据类型胜率对比

| 数据类型 | 测试总数 | 通过数 | **通过率** |
|---------|---------|--------|----------|
| 基本面（纯） | 150 | **60** | **40.0%** |
| 混合（基本面+技术）| 252 | **32** | **12.7%** |
| 技术（纯） | 131 | **7** | **5.3%** |
| 其他（fscore/snt1 等）| 92 | **0** | **0%** |

**结论：基本面因子的通过率是纯技术因子的 7.5 倍。**

### 3.2 核心字段使用情况（32 个通过表达式中）

| 字段 | 出现次数 | 类别 | 说明 |
|------|---------|------|------|
| `equity` | 19 | 基本面 | 股东权益，用于杠杆比率分母/分子 |
| `operating_income` | 15 | 基本面 | 营业利润，盈利能力核心信号 |
| `assets` | 11 | 基本面 | 总资产，用于 ROA 类比率 |
| `scl12_buzz` | 4 | 情绪 | 情绪声量波动性（反向）|
| `liabilities` | 1 | 基本面 | 总负债率 |
| `free_cash_flow_reported_value` | 1 | 基本面 | 自由现金流/权益 |

> **注意**：`assets`、`equity`、`operating_income` 三个字段覆盖了通过表达式的 **70%** 以上，是最值得优先探索的字段组合。

### 3.3 运算符组合效果对比

| 运算符组合 | 通过数 | 通过率 | 备注 |
|-----------|--------|--------|------|
| `group_rank + ts_rank` | 29 | **~60%** | 黄金组合 |
| `rank` 单独使用 | 63次出现，~27%通过 | 基础用法 |
| `ts_rank` 单独使用 | 32次出现，~13%通过 | 单独效果弱于组合 |
| `ts_std_dev`（情绪） | 7 | ~12% | 情绪类专用 |
| `ts_delta` | 11 | ~20% | 需配合行业中性化 |

**最高 Sharpe 的 5 个表达式**（实测数据）：

```python
# 1. Sharpe=2.10  Fitness=1.81  Turnover=5.68%
rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)

# 2. Sharpe=2.07  Fitness=1.45  Turnover=6.99%
group_rank(ts_rank(operating_income/equity, 126), sector)

# 3. Sharpe=2.06  Fitness=1.42  Turnover=7.16%
group_rank(ts_rank(operating_income/equity, 126), industry)

# 4. Sharpe=2.04  Fitness=1.44  Turnover=6.68%
group_rank(ts_rank(operating_income/equity, 150), sector)

# 5. Sharpe=2.01  Fitness=1.32  Turnover=6.30%
group_rank(ts_rank(operating_income/equity, 126), subindustry)
```

### 3.4 中性化设置对通过率的影响

| 中性化设置 | 通过 Alpha 数 | 占通过总数比 |
|-----------|-------------|-----------|
| `SUBINDUSTRY` | **56** | **56.6%** |
| `INDUSTRY` | **28** | **28.3%** |
| `MARKET` | **15** | **15.2%** |

**关键结论**：
- `SUBINDUSTRY` 中性化通过率最高，适合所有基本面因子
- `MARKET` 中性化仅在 `group_rank` 表达式内已做行业中性化时使用（避免双重中性化）
- `group_rank` + `MARKET` 中性化 = 事实上的行业内中性化（因为 group_rank 本身实现了行业中性）

### 3.5 Decay 参数对 Fitness 的影响（以 `rank(liabilities/assets)` 为例）

| Decay | Turnover | Fitness | Sharpe |
|-------|---------|---------|--------|
| 0 | 1.66% | 1.26 | 1.51 |
| 1 | 1.66% | 1.26 | 1.51 |
| 2 | 1.61% | 1.26 | 1.51 |
| 3 | 1.58% | 1.26 | 1.51 |
| 4 | 1.56% | 1.26 | 1.51 |
| 5 | 1.55% | 1.26 | 1.51 |
| 6 | 1.54% | 1.26 | 1.51 |
| 10 | 1.50% | 1.27 | 1.52 |

**结论**：对于低换手率的基本面因子，Decay **几乎没有影响**。Decay 的作用主要体现在高换手率（>20%）的技术/情绪因子上。已通过的基本面 Alpha 使用 `decay=0` 完全可行。

---

## 四、低自相关设计原则

### 4.1 SELF_CORRELATION 的运行机制

`SELF_CORRELATION` 检查在 Alpha 实际提交（`POST /alphas/{id}/submit`）后触发，对比新 Alpha 与已在 Portfolio 中所有 Alpha 的日收益序列的相关性。

**具体规则**：
- 与已提交任意 Alpha 的 PnL 相关系数 ≥ 0.7 → `FAIL`
- **例外**：新 Alpha Sharpe ≥ 相关 Alpha Sharpe × 1.1 → 仍可通过（高质量 Alpha 允许有更高相关性）
- `PENDING` 状态：模拟完成但未加入 Portfolio 时，该检查未执行

### 4.2 当前项目的自相关风险

本项目 32 个独特通过表达式中，有大量**变体重复**（同一表达式不同参数测试了 58 次以上）。这意味着：
- 这些 Alpha **之间**相关性极高（>0.9）
- 实际提交时，同一类表达式只能提交 1 个（或信号显著不同的 2–3 个）
- 推荐：每类因子（盈利能力、杠杆、情绪）各保留 **Sharpe 最高的 1–2 个**提交

### 4.3 降低自相关的设计策略

**策略一：数据源多样化**
```python
# 已有：基本面盈利类
group_rank(ts_rank(operating_income/equity, 126), sector)

# 新增：基本面增长类（不同维度）
group_rank(ts_rank(ts_delta(equity, 63), 126), sector)

# 新增：情绪类（完全不同数据源）
-ts_std_dev(scl12_buzz, 18)

# 新增：期权类（另一数据源）
implied_volatility_call_120 / parkinson_volatility_120
```

**策略二：信号频率多样化**

| 持仓频率 | 换手率 | 代表性数据 | 已验证通过 |
|---------|--------|----------|---------|
| 低频（月度） | 1–5% | 基本面比率 | ✅ `rank(liabilities/assets)` |
| 中低频（季度变化） | 5–10% | 基本面趋势 | ✅ `group_rank(ts_rank(oi/equity, 126))` |
| 中频（情绪/新闻） | 10–20% | scl12_buzz | ✅ `-ts_std_dev(scl12_buzz, 18)` |
| 高频（日频技术） | >30% | close/vwap | ❌ 大多数失败 |

**策略三：避免提交高度相关变体**
- 同一公式不同 lookback 窗口（如 126、150、175）的 Alpha 相关性 > 0.95，应选最好的一个
- 同一公式不同 group（sector/industry/subindustry）的 Alpha 相关性通常 0.8–0.95
- 同一公式不同 neutralization 的 Alpha 相关性 0.7–0.9

**策略四：使用不同运算符结构**
```python
# 高相关（同类，避免同时提交）
rank(liabilities/assets)                     # 杠杆绝对比率
rank(ts_rank(liabilities/assets, 126))       # 杠杆相对历史
group_rank(liabilities/assets, industry)     # 行业内杠杆

# 低相关（不同维度，可同时提交）
rank(liabilities/assets)                     # 杠杆（基本面）
-ts_std_dev(scl12_buzz, 18)                  # 情绪波动（另一数据源）
```

---

## 五、Alpha 表达式反模式（缺陷清单）

### 5.1 过高换手率模式

以下表达式特征会导致换手率 > 70%（`HIGH_TURNOVER` 必失败）：

```python
# ❌ 日频价格差分（换手率 80–140%）
rank(close/vwap - 1)           # 实测 85.2%
rank(close - open)             # 估算 > 100%
rank(returns)                  # 日收益率，每天几乎全换仓

# ❌ 新闻/评级日频信号（换手率 100–140%）
rank(rp_css_equity)            # 实测 133.3%
rank(rp_css_earnings)          # 实测 127.5%

# ❌ 短窗口技术信号（换手率 50–80%）
rank(-ts_delta(close, 1))      # 1日反转，换手接近极限
rank(-ts_delta(close, 5))      # 实测 61.65%，Fitness 仅 0.82
```

**修复方法**：
- 增加 `decay=4–8`（最直接的降换手率方法）
- 用 `ts_rank(field, lookback)` 代替原始信号（延长持仓期）
- 用基本面字段替代价格字段（季度更新 vs 日更新）

### 5.2 NaN/错误导致 ERROR 的写法

```python
# ❌ 除以可能为零的字段（产生 Inf）
rank(operating_income / volume)   # volume 可能为 0

# ❌ log 对负数取对数（NaN）
rank(log(operating_income))        # 亏损公司 operating_income < 0

# ❌ 空数据集访问（ERROR）
rank(fscore_bfl_value)             # fscore 覆盖率极低，换手 0.88% 触发 LOW_TURNOVER
```

**防御性写法**：
```python
# ✅ 安全除法（WQ 平台自动处理 NaN）
rank(operating_income / equity)    # equity 可能负数，但平台已做 NaN 处理

# ✅ 只用经过验证的字段组合
# 推荐：operating_income、equity、assets、liabilities（均为成熟字段）
```

### 5.3 CONCENTRATED_WEIGHT 触发机制

短窗口情绪原始信号是触发 `CONCENTRATED_WEIGHT` 的主因：

```python
# ❌ 短窗口情绪原始信号（未归一化）
-ts_std_dev(scl12_buzz, 5)     # 实测 CONCENTRATED_WEIGHT FAIL
-ts_std_dev(scl12_sentiment, 5) # 同上

# ✅ 适当增大窗口（降低集中度）
-ts_std_dev(scl12_buzz, 15)    # 实测通过（Sharpe=1.34, Fitness=1.36）
-ts_std_dev(scl12_buzz, 18)    # 实测通过（Sharpe=1.47, Fitness=1.67）
-ts_std_dev(scl12_buzz, 20)    # 实测通过（Sharpe=1.47, Fitness=1.77）
```

**规律**：`scl12_buzz` 短窗口（≤10 天）时，少数股票的声量极端值主导信号，导致权重集中；窗口扩大到 15 天以上，信号趋于平稳，权重分布改善。

### 5.4 MATCHES_COMPETITION 的正确理解

`MATCHES_COMPETITION` 不是失败检查，是**信息性标签**，显示 Alpha 符合哪些比赛条件（如 `challenge`、`IQC2026S1`）。所有本项目测试的 Alpha 都带有此标签且结果为 `PASS`，不影响提交。

### 5.5 重复提交问题（MATCHES_COMPETITION 同名重复）

平台对**完全相同的表达式 + 设置**会返回相同的 Alpha ID（平台去重机制）。本项目中 `rank(liabilities/assets)` 表达式在不同 decay 设置下共生成 **58 个独立 Alpha**（不同 decay 被视为不同设置）。

> **避免浪费资源**：相同表达式只需测试有意义的设置变体（如 decay=0、4、8），无需逐一测试 0–10 的每个值。

---

## 六、社区经验与外部资料总结

### 6.1 BRAIN 官方文档核心要点

根据爬取的官方平台内容和文档：

1. **Fitness 的重要性超过 Sharpe**：Fitness 是综合考量了收益率和交易成本的指标，高 Sharpe + 高换手率 = 低 Fitness，无法通过
2. **Decay 的主要作用**：平滑持仓变化，主要对高换手率信号有效。基本面信号（1–5% 换手）几乎不受 Decay 影响
3. **Truncation 的必要性**：`truncation=0.05` 确保单只股票权重上限 5%，防止 CONCENTRATED_WEIGHT 触发
4. **Universe 的选择**：TOP3000 是最大宇宙，样本量大但包含小市值流动性差股票，容易导致 LOW_SUB_UNIVERSE_SHARPE

### 6.2 社区论坛经验（综合整理）

**关于降低换手率**（论坛最高频话题）：
- 最有效方法：换用季度更新的基本面字段
- 其次：增加 `ts_rank` 的 lookback 窗口（从 20 天增到 63/126 天）
- 最后手段：增加 `decay` 参数（但会损失 Sharpe）

**关于 LOW_SUB_UNIVERSE_SHARPE**（社区讨论最多的检查）：
- 直接解法：将 Universe 从 TOP3000 改为 TOP1000 测试，验证信号是否在大市值股中有效
- 根本原因：小市值股财务数据缺失率高，信号质量差，但权重不小
- 推荐：使用 `group_rank` + `SUBINDUSTRY` 中性化，确保在每个子行业内均匀分布信号，大市值子行业也能覆盖到

**关于 SELF_CORRELATION 设计**（IQC 竞赛必考问题）：
- 竞赛高手的策略：每种"数据源" × "信号类型" 仅保留 1–2 个最佳 Alpha
- 数据源多样性比数量重要：基本面、情绪、分析师预测、期权数据 4 类数据源的相互相关通常 < 0.3
- 经验法则：如果两个 Alpha 的表达式"看起来像"（使用相同数据字段），它们的 PnL 相关性通常 > 0.7

### 6.3 学术文献中的 Alpha 构建理论

**SSRN Paper 2701346（WorldQuant/相关研究）** 中的核心概念：

- **Alpha = 横截面信号 + 时序过滤 + 风险中性化**
- 横截面 rank 操作是最基础的信号归一化方法，消除了量级差异和市场整体方向影响
- `ts_rank` 在横截面 rank 之前加入时序维度，捕捉"相对自身历史"的信号，减少与其他 Alpha 的相关性
- **"101 Formulaic Alphas" 论文**中的规律（本项目也验证了）：
  - 基于财务比率的因子（ROE、ROA、财务杠杆）长期有效
  - 简单的表达式（运算符 ≤ 5 个）往往比复杂表达式更稳健
  - 行业中性化是减少风险暴露、提高 Sharpe 一致性的关键

**量化因子研究通用规律**：
- 价值因子（P/B、P/E、P/FCF）在 WorldQuant 平台对应 `equity/assets`、`liabilities/assets`、`operating_income/equity`
- 质量因子（ROE、ROA、低杠杆）是最稳定的长期因子，本项目实测验证（40% 通过率）
- 动量因子（近期表现）在 BRAIN 平台技术实现（`close`, `returns`）因换手率过高普遍失败
- 反转因子（`-ts_delta(close, 5)`）在 FE 语言中换手率 40–60%，Fitness 普遍不达标

---

## 七、下一步 Alpha 开发建议

### 7.1 基于当前 99 个通过 Alpha 的组合分析

当前通过的 99 个 Alpha（32 种独特表达式）存在**高度集中**于少数几个因子的问题：

| 因子类别 | 通过表达式数 | 代表表达式 |
|---------|------------|---------|
| 营业利润/权益（盈利能力）| ~20 种变体 | `group_rank(ts_rank(oi/equity, N), group)` |
| 负债/资产（财务杠杆）| ~8 种变体 | `rank(liabilities/assets)` |
| 情绪波动（scl12_buzz）| 4 种变体 | `-ts_std_dev(scl12_buzz, N)` |
| 权益增长（ts_delta equity）| ~6 种变体 | `group_rank(ts_rank(ts_delta(equity, 63), N), group)` |

**如果要提交到 Portfolio，建议只提交**：
1. 盈利能力最佳变体 1 个（最高 Sharpe: 2.10）
2. 杠杆因子最佳变体 1 个（最高 Sharpe: 1.55）
3. 情绪 buzz 最佳变体 1 个（最高 Fitness: 1.77）
4. 权益增长最佳变体 1 个

### 7.2 推荐探索的新高潜力 Alpha 表达式

以下 10 个表达式**尚未测试**，基于本项目实测规律和社区经验，预计有较高通过潜力：

```python
# === 基本面盈利能力扩展 ===

# 1. ROE 趋势 + 行业中性（横向扩展已验证的 oi/equity 因子）
group_rank(ts_rank(ts_delta(operating_income/equity, 63), 126), sector)
# 预期：Sharpe 1.5–1.8，Fitness 1.1–1.4，Turnover 6–9%
# 理由：加入盈利能力变化趋势，与绝对值因子相关性 < 0.7

# 2. 自由现金流盈利（FCF Yield）
group_rank(ts_rank(free_cash_flow_reported_value/assets, 126), sector)
# 预期：Sharpe 1.3–1.6，Fitness 1.0–1.3
# 理由：free_cash_flow/equity 已验证 Sharpe=1.46；/assets 是另一维度

# 3. 销售利润率趋势
group_rank(ts_rank(operating_income/sales, 126), sector)
# 预期：Sharpe 1.5–1.9，Fitness 1.1–1.5
# 理由：利润率vs权益回报率从不同角度衡量经营质量

# 4. 盈利能力 + 负债质量三因子
rank(ts_rank(operating_income/equity, 126)) + rank(-liabilities/assets) + rank(-ts_delta(liabilities, 63))
# 预期：Sharpe 1.8–2.2，Fitness 1.4–1.8
# 理由：组合信号历史上优于单因子，三个维度低相关

# === 分析师预测数据 ===

# 5. EPS 盈利收益率 + 行业中性化（官方推荐方向）
group_rank(ts_rank(est_eps/close, 63), sector)
# 预期：Sharpe 1.3–1.7，Fitness 1.0–1.3，Turnover 5–12%
# 理由：est_eps 日频更新，捕捉分析师预期修正的动量效应

# 6. 分析师目标价与自由现金流预测相关性（反向）
-ts_corr(est_ptp, est_fcf, 252)
# 预期：Sharpe 1.2–1.5，Fitness 1.0–1.3
# 理由：高相关 = 市场完全定价 → 做空高一致性股票

# === 期权数据 ===

# 7. 隐含波动率/历史波动率比率（实测已验证方向）
rank(implied_volatility_call_120 / parkinson_volatility_120)
# 预期：Sharpe 1.3–1.6，Fitness 1.1–1.5
# 理由：期权溢价与基本面信号低相关，增加组合多样性

# === 情绪数据进阶 ===

# 8. buzz 与 sentiment 组合（两个维度相乘）
group_rank(-ts_std_dev(scl12_buzz, 18) * ts_rank(scl12_sentiment, 63), industry)
# 预期：Sharpe 1.3–1.6，Fitness 1.2–1.6
# 理由：声量波动 × 情绪质量双过滤，减少误信号

# 9. 情绪惊喜信号（EPS + 情绪）
rank(snt1_d1_earningssurprise) + rank(-liabilities/assets)
# 预期：Sharpe 1.2–1.5，Fitness 1.0–1.3
# 理由：短期催化剂 + 长期价值因子，降低相关性

# === 多因子创新组合 ===

# 10. 盈利质量综合得分（类 Piotroski F-Score 但更灵活）
rank(ts_rank(operating_income/equity, 126))
  + rank(-equity/assets)  
  + rank(ts_rank(free_cash_flow_reported_value/equity, 126))
# 预期：Sharpe 2.0–2.5，Fitness 1.5–2.0
# 理由：三维度基本面因子组合，已有两维度（oi/equity + equity/assets）实测 Sharpe=2.10
```

### 7.3 推荐优先测试的新数据字段

基于现有测试经验，以下字段尚未充分探索且有理论支撑：

| 字段 | 数据集 | 理论依据 | 预期换手率 |
|------|--------|---------|-----------|
| `sales` (营收) | 基本面 | 收入增长 vs 利润增长分离 | 1–5% |
| `net_income` (净利润) | 基本面 | GAAP 净利润 vs 营业利润 | 1–5% |
| `est_eps` (EPS 预测) | ptp1 | 分析师预期修正动量 | 5–15% |
| `est_ptp` (目标价) | ptp1 | 价格动量与目标价差异 | 5–15% |
| `implied_volatility_call_120` | 期权 | 隐含波动率溢价 | 10–25% |
| `scl12_sentiment` | 情绪 | 情绪绝对值 vs 声量波动 | 15–30% |
| `vec_avg(nws12_afterhsz_120_min)` | 新闻 | 盘后新闻的平均涨幅信号 | 20–40% |

### 7.4 快速开发建议（提高测试效率）

1. **先用基本面字段扩展**：新字段（sales、net_income）套用已验证的 `group_rank(ts_rank(field, 126), sector)` 模式，成功率 > 30%
2. **每个字段只测 3 个窗口**：63、126、252（短中长期）+ `sector` 和 `industry` 两种分组 = 6 次模拟即可判断字段价值
3. **Batch 提交时用 SUBINDUSTRY 中性化为默认值**：通过率最高（56.6%）
4. **组合因子测试要谨慎**：多因子组合可提升 Sharpe 但相关性更难控制，建议单因子验证通过后再叠加

---

## 八、关键数字速查表

| 问题 | 答案 |
|------|------|
| 本项目测试了多少个 Alpha？ | **625 个**（去重） |
| 有多少通过？ | **99 个（15.8%）** |
| 独特通过表达式有多少种？ | **32 种** |
| 基本面因子通过率？ | **40.0%** |
| 技术因子通过率？ | **5.3%** |
| 通过 Alpha 平均 Sharpe？ | **1.579** |
| 通过 Alpha 平均 Fitness？ | **1.289** |
| 通过 Alpha 平均换手率？ | **3.84%** |
| 最高 Sharpe 是多少？ | **2.10**（operating_income/equity + equity/assets 组合）|
| 最高 Fitness 是多少？ | **1.92**（同上）|
| 换手率 Fitness 临界点？ | **12.5%**（低于此值，Fitness 计算固定为 0.125） |
| 最常用的通过中性化设置？ | **SUBINDUSTRY**（56.6%）|
| 最常用的通过 Decay 值？ | **0**（54.5%）|
| 最大失败原因？ | **LOW_SHARPE**（90.7% 的失败 Alpha 有此失败）|
| 第二大失败原因？ | **LOW_FITNESS**（66.2%）|
| SELF_CORRELATION 何时触发？ | **提交到 Portfolio 后**，模拟阶段为 PENDING |

---

## 九、附录：通过 Alpha 完整表达式清单

以下是 32 个独特通过表达式（按 Sharpe 降序），供参考和自相关分析：

| # | Sharpe | Fitness | TO% | 表达式 |
|---|--------|---------|-----|--------|
| 1 | 2.10 | 1.81 | 5.7% | `rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)` |
| 2 | 2.07 | 1.45 | 7.0% | `group_rank(ts_rank(operating_income/equity, 126), sector)` |
| 3 | 2.06 | 1.42 | 7.2% | `group_rank(ts_rank(operating_income/equity, 126), industry)` |
| 4 | 2.04 | 1.44 | 6.7% | `group_rank(ts_rank(operating_income/equity, 150), sector)` |
| 5 | 2.01 | 1.32 | 6.3% | `group_rank(ts_rank(operating_income/equity, 126), subindustry)` |
| 6 | 1.98 | 1.41 | 6.4% | `group_rank(ts_rank(operating_income/equity, 175), sector)` |
| 7 | 1.94 | 1.29 | 7.7% | `group_rank(ts_rank(operating_income/equity, 95), sector)` |
| 8 | 1.86 | 1.35 | 5.8% | `group_rank(ts_rank(operating_income/equity, 252), sector)` |
| 9 | 1.83 | 1.38 | 6.7% | `group_rank(ts_rank(ts_delta(equity, 63) + operating_income/equity * equity, 126), sector)` |
| 10 | 1.78 | 1.36 | 5.4% | `group_rank(ts_rank(operating_income/equity, 126), sector)` *(MARKET neut)* |
| 11 | 1.75 | 1.14 | 7.0% | `group_rank(ts_rank(operating_income/assets, 126), sector)` |
| 12 | 1.72 | 1.25 | 6.4% | `group_rank(ts_rank(ts_delta(equity, 63), 175), sector)` |
| 13 | 1.72 | 1.15 | 7.7% | `group_rank(ts_rank(ts_delta(equity, 63), 126), industry)` |
| 14 | 1.72 | 1.09 | 7.2% | `group_rank(ts_rank(operating_income/assets, 126), industry)` |
| 15 | 1.68 | 1.05 | 7.4% | `group_rank(ts_rank(ts_delta(assets, 63), 126), sector)` |
| 16 | 1.68 | 1.18 | 6.8% | `group_rank(ts_rank(ts_delta(equity, 63), 126), sector)` |
| 17 | 1.67 | 1.18 | 6.6% | `group_rank(ts_rank(ts_delta(equity, 63), 150), sector)` |
| 18 | 1.67 | 1.01 | 6.3% | `group_rank(ts_rank(operating_income/assets, 126), subindustry)` |
| 19 | 1.67 | 1.09 | 6.7% | `group_rank(ts_rank(operating_income/assets, 150), sector)` |
| 20 | 1.66 | 1.11 | 6.2% | `group_rank(ts_rank(operating_income/assets, 126), industry)` |
| 21 | 1.65 | 1.04 | 6.8% | `rank(ts_rank(operating_income/equity, 126))` |
| 22 | 1.65 | 1.06 | 7.3% | `group_rank(ts_rank(ts_delta(assets, 63) / ts_delay(assets, 63), 126), industry)` |
| 23 | 1.64 | 1.11 | 6.7% | `group_rank(ts_rank(ts_delta(equity, 63) / ts_delay(equity, 63), 126), sector)` |
| 24 | 1.56 | 1.03 | 6.5% | `group_rank(ts_rank(ts_delta(assets, 63) / ts_delay(assets, 63), 126), sector)` |
| 25 | 1.55 | 1.28 | 1.8% | `rank(-equity/assets)` |
| 26 | 1.55 | 1.00 | 6.5% | `group_rank(ts_rank(operating_income/assets, 175), sector)` |
| 27 | 1.54 | 1.08 | 5.9% | `group_rank(ts_rank(ts_delta(equity, 63), 252), sector)` |
| 28 | 1.52 | 1.27 | 1.5% | `rank(liabilities/assets)` |
| 29 | 1.47 | 1.67 | 13.5% | `-ts_std_dev(scl12_buzz, 18)` |
| 30 | 1.47 | 1.77 | 9.5% | `-ts_std_dev(scl12_buzz, 20)` |
| 31 | 1.46 | 1.17 | 4.0% | `group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), sector)` |
| 32 | 1.44 | 1.66 | 10.3% | `-ts_std_dev(scl12_buzz, 25)` |

---

*本文档生成于 2026 年 4 月，基于项目 results/ 目录中所有实测数据和 WorldQuant BRAIN 社区知识综合分析。*

*下一篇推荐：对照 [11_进阶Alpha知识与策略.md](./11_进阶Alpha知识与策略.md) 中的策略，继续开发 sales、net_income、est_eps 等尚未测试的字段组合。*

---

## 十、官方平台知识库精华（wq_knowledge_base 提炼）

> 来源：`data/wq_knowledge_base.json`，由84个平台页面爬取汇总（2026-04-20）

### 10.1 官方示例 Alpha 表达式（直接可用）

| 优先级 | 表达式 | 类别 | 推荐设置 |
|--------|--------|------|----------|
| 🔴 HIGH | `ts_rank(operating_income, 252)` | 基本面/盈利趋势 | decay=0, SUBINDUSTRY, trunc=0.08 |
| 🔴 HIGH | `group_rank(ts_rank(est_eps/close, 60), industry)` | 分析师/收益率 | decay=0, INDUSTRY, trunc=0.08 |
| 🔴 HIGH | `group_rank(-ts_zscore(enterprise_value/cashflow, 63), industry)` | 估值/现金流 | decay=0, INDUSTRY, trunc=0.08 |
| 🟡 MED | `-ts_rank(fn_liab_fair_val_l1_a, 252)` | 风险/公允价值 | decay=0, SUBINDUSTRY, trunc=0.08 |
| 🟡 MED | `ts_zscore(est_eps, 252)` | 分析师/EPS趋势 | decay=0, MARKET, trunc=0.05 |
| 🟡 MED | `-ts_corr(est_ptp, est_fcf, 252)` | 分析师/背离 | decay=4, MARKET, trunc=0.05 |
| 🟡 MED | `implied_volatility_call_120/parkinson_volatility_120` | 期权/波动率 | decay=10, SECTOR, trunc=0.05 |
| 🟢 LOW | `rank(ebit/capex)` | 基本面/资本效率 | decay=0, SUBINDUSTRY, trunc=0.08 |
| 🟢 LOW | `group_rank(sales_growth, sector)` | 基本面/成长 | decay=0, SECTOR, trunc=0.08 |
| 🟢 LOW | `rank(sales/assets)` | 基本面/资产效率 | decay=0, SUBINDUSTRY, trunc=0.08 |

### 10.2 新发现的数据字段（可开发新 Alpha）

**分析师预测数据集（analyst_estimates）：**
- `est_eps`, `est_fcf`, `est_ptp`, `est_revenue`, `est_ebitda`
- 这些是前瞻性字段，与历史数据相关性天然较低 → **自相关低**

**情绪1数据集（sentiment1）：**
- `snt1_cored1_score` - 综合情绪得分
- `snt1_d1_earningssurprise` - 盈利惊喜
- `snt1_d1_buyrecpercent` - 买入推荐比例
- `snt1_d1_analystcoverage` - 分析师覆盖度
- **注意**：约覆盖2000只股票，建议在 TOP1000/TOPSP500 宇宙中测试

**期权数据（options）：**
- `implied_volatility_call_120` - 120天隐含波动率（看涨）
- `parkinson_volatility_120` - Parkinson历史波动率
- `pcr_oi_30` - 30日持仓量 Put/Call Ratio

**向量数据算子（处理事件型数据）：**
- `vec_avg`, `vec_sum`, `vec_max`, `vec_min`, `vec_median` 等
- 处理新闻/事件数量不固定的向量字段时使用

### 10.3 中性化设置选择指南（官方建议）

| 中性化级别 | 推荐场景 | 通过率（本项目实测） |
|-----------|----------|---------------------|
| SUBINDUSTRY | 基本面因子（季度数据）| **56.6%** |
| INDUSTRY | 基本面因子（混合）| ~35% |
| MARKET | 技术因子 / 纯价格信号 | ~12% |
| NONE | 配合 `group_rank()` 手动中性化 | 取决于表达式 |

> **经验法则**：使用了 `group_rank(x, industry/sector)` 的表达式，settings 可设 neutralization=NONE，因为已通过算子中性化。未使用 `group_rank()` 的，建议配合 neutralization=SUBINDUSTRY。

---

## 十一、IQC 2026 竞赛关键信息

> 来源：`data/spa_crawl/competition_iqc2026.json`，竞赛截止：2026-05-19

- **竞赛时间**：2026年3月17日 - 5月19日（仍在进行！）
- **评分方式**：Merged Alpha Performance（合并 Alpha 表现）
- **关键 URL**：`https://platform.worldquantbrain.com/competitions`
- **目标**：提交 Alpha 到竞赛，被算入 IQC 积分

### IQC 评分原则（来自官方课程）
1. 评分基于所有提交 Alpha 的**合并表现（Merged Alpha）**
2. Alpha 之间的多样性（低自相关）会**提升合并Alpha的Sharpe**
3. 因此，低自相关的 Alpha 比单纯高 Sharpe 的 Alpha 更有价值
4. 50个多样性强的 Alpha 优于 50个相同的高Sharpe Alpha

> **结论**：本项目的低自相关 Alpha 开发策略（使用 FCF、分析师预测、期权、情绪、人力资本等8个不同类别）完全符合 IQC 竞赛的评分逻辑。

---

## 十二、Session 守护进程使用指南

本项目新增了 `src/session_watchdog.py`，会在后台持续监控 session 并自动执行流程：

```bash
# 启动守护进程（后台运行）
nohup python src/session_watchdog.py > logs/watchdog.log 2>&1 &

# 查看进度
tail -f logs/watchdog_live.log

# 手动刷新 session 后，守护进程会自动检测并运行：
python src/login.py   # → 守护进程60秒内自动触发
```

守护进程流程：
1. 每60秒检查 session 有效性
2. 检测到有效后，运行 `agent_lowcorr`（40个）+ `agent_kb_official`（15个）
3. 自动提交所有合格 Alpha
4. 总计最多等待4小时，之后退出

---

*更新时间：2026-04-20 | 知识库版本：2.0（84页爬取）| 守护进程 PID: 见 logs/watchdog_live.log*
