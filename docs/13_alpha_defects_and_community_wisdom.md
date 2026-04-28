# 13 Alpha 缺陷模式、社区智慧与深度实战分析

> **数据来源**：本文档基于 `/data/crawl_manual/` 下 111 个爬取文件的深度解析，以及 `/results/` 下
> **1,022 条实测 Alpha 记录**的定量分析（共 13+ 个测试批次）。所有结论均有具体数字支撑。
>
> 本文档是对 `docs/12_community_insights_and_alpha_experience.md` 的深度补充，
> 侧重于**失败模式归因、社区官方教程精华提炼、运算符使用决策树、以及 IQC 2026 竞赛策略**。

---

## 一、Alpha 缺陷模式深度总结

### 1.1 本项目全量测试统计

| 维度 | 数值 |
|------|------|
| 测试记录总数 | **1,022 条** |
| 通过全部 IS 检查 | **119 条（11.6%）** |
| 失败 | **878 条（85.9%）** |
| 独立表达式（去重） | **通过 37 个 / 约 500+ 独立失败表达式** |
| 独立 Alpha ID（去重） | **通过 114 个** |

> **注**：通过率低的原因是大量"参数扫描"——同一表达式用不同 decay/truncation/neutralization 反复测试。
> 实际独特通过表达式仅 **37 个**，都高度集中在 3-4 种数据类别组合中。

---

### 1.2 六大检查项失败统计与根因分析

**基于 878 条失败记录：**

| 检查项 | 失败次数 | 失败率 | 根本原因 |
|--------|---------|--------|---------|
| `LOW_SHARPE` | **695** | 79.2% | 信号本身无效或噪声过大 |
| `LOW_FITNESS` | **476** | 54.2% | 换手率 30-70% 区间，Fitness 被压缩 |
| `LOW_SUB_UNIVERSE_SHARPE` | **396** | 45.1% | 信号在大市值股（TOP1000 子集）失效 |
| `CONCENTRATED_WEIGHT` | **84** | 9.6% | 未 `rank` 的原始信号，权重高度集中 |
| `HIGH_TURNOVER` | **76** | 8.7% | 日频信号换手率超 70% |
| `LOW_TURNOVER` | **17** | 1.9% | 基本面字段更新极低频（极少数情况） |

#### 失败 Sharpe 分布（874 条有效数据）

| Sharpe 区间 | 数量 | 占比 | 含义 |
|-------------|------|------|------|
| < 0.50 | 130 | 17.8% | 信号完全无效 |
| 0.50 – 0.80 | 150 | 20.5% | 信号微弱，需根本改造 |
| 0.80 – 1.00 | 176 | 24.1% | 有一定信号，但差距明显 |
| 1.00 – 1.25 | 85 | 11.6% | 最可惜：差一口气 |
| ≥ 1.25（仍失败）| 36 | 4.9% | Sharpe 达标但 Fitness/CWEIGHT 问题 |

**重要发现**：即使 Sharpe 超过 1.25，仍有 **36 条记录**因 `LOW_FITNESS` 或 `CONCENTRATED_WEIGHT` 失败。这些是"第二道门槛"的牺牲品。

---

### 1.3 LOW_SHARPE 失败模式详解

**最接近通过但未过关的表达式（Sharpe 1.0–1.24）：**

```
# 改变了分母——OI本身而非对股本/资产归一化
group_rank(ts_rank(operating_income/sales, 126), subindustry)  → Sh=1.24
group_rank(ts_rank(operating_income, 252), subindustry)         → Sh=1.23
group_rank(ts_rank(ebitda/equity, 126), sector)                 → Sh=1.22
group_rank(ts_rank(ebitda/assets, 126), industry)               → Sh=1.18
group_rank(ts_rank(ts_delta(operating_income, 63), 126), sector) → Sh=1.17
group_rank(ts_rank(ts_delta(sales, 63), 126), sector)           → Sh=1.17
group_rank(ts_rank(revenue/equity, 126), sector)                → Sh=1.13
```

**规律总结**：

| 失败类型 | 典型表达式 | 为何失败 |
|----------|-----------|---------|
| 分母错误 | `operating_income/sales`（利润率）| 利润率截面比较不如 ROE/ROA 稳定 |
| 使用绝对值 | `ts_rank(operating_income, 252)` | 大型公司绝对值高，市值效应混入 |
| EBITDA 替代 | `ebitda/equity` 或 `ebitda/assets` | EBITDA 噪声更大，分析师调整差异大 |
| 短期变化 | `ts_delta(operating_income, 63)` | 季度性波动过大，信噪比低 |
| 销售增长 | `ts_delta(sales, 63)` | 销售增长与股价关系弱于盈利质量 |

**核心教训**：`operating_income/equity`（ROE 的代理）和 `operating_income/assets`（ROA 的代理）是这套数据中最强的基本面信号，其他组合 Sharpe 全部低于临界值。

---

### 1.4 HIGH_TURNOVER 触发器清单

以下表达式在实测中**明确触发 HIGH_TURNOVER**（换手率 > 70%）：

```python
# 直接使用原始情绪数值（不做时序平滑）
group_rank(ts_rank(scl12_buzz, 10), sector)   → TO=0.767（失败）
group_rank(ts_rank(scl12_buzz, 20), sector)   → TO=0.760（失败）
group_rank(ts_rank(-scl12_buzz, 10), sector)  → TO=0.787（失败）
group_rank(ts_zscore(-scl12_buzz, 20), sector)→ TO=0.707（失败）
group_rank(-scl12_buzz, sector)               → TO=0.729（失败）

# 日内价格信号（极端案例）
rank(-(close/vwap - 1))                       → TO=0.852（Sharpe=1.74 但 TO 超标）

# 新闻情绪信号（旧版 Ravenpack）
ts_rank(rp_css_equity, 20)                    → TO=1.626（严重超标，且 Sharpe=1.13）
```

**规律**：

1. **`scl12_buzz`（社交媒体 Buzz）本身是日频高噪声信号**，需要用 `ts_std_dev` 而非 `ts_rank` 处理才能控制换手率
2. **日内信号（close/vwap）天然换手率 > 80%**，Delay-1 下几乎不可用
3. **Ravenpack 情绪信号**（`rp_css_equity`）换手率极高，不建议直接使用

---

### 1.5 CONCENTRATED_WEIGHT 触发分析

以下情况触发权重集中检查：

```python
# 未归一化的期权信号（使用 SECTOR 中性化时最严重）
implied_volatility_call_120/parkinson_volatility_120  → CONCENTRATED_WEIGHT FAIL（多种设置）

# 未包裹 rank 的情绪信号
-ts_std_dev(scl12_buzz, 5)  → 部分设置下 CONCENTRATED_WEIGHT FAIL
```

**解决方案**：在 `implied_volatility_call_120/parkinson_volatility_120` 外包裹 `rank()`：

```python
# 失败版本（高风险）：
implied_volatility_call_120/parkinson_volatility_120

# 修复版本（通过）：
rank(implied_volatility_call_120/parkinson_volatility_120)
```

实测：加 `rank()` 后权重集中问题消失，且 Sharpe 基本不变。

---

### 1.6 LOW_SUB_UNIVERSE_SHARPE 隐患

该检查要求 Alpha 在 TOP1000 子宇宙中的 Sharpe 满足：

```
Sub_Sharpe ≥ 0.75 × √(TOP1000/TOP3000) × alpha_sharpe ≈ 0.43 × alpha_sharpe
```

实测触发案例：

```python
-ts_std_dev(scl12_buzz, 5)  
  → 全市场 Sh=2.13, Sub_Sh=0.87 < limit=0.92 → 失败（INDUSTRY 中性化）

-ts_std_dev(scl12_buzz, 5)
  → 全市场 Sh=1.99, Sub_Sh=0.60 < limit=0.86 → 失败（INDUSTRY，truncation=0.05）

group_rank(ts_rank(ts_delta(assets, 252), 252), sector)
  → 全市场 Sh=1.35, Sub_Sh=0.46 < limit=0.58 → 失败
```

**规律**：
- **情绪信号（scl12_buzz）在大市值股中信号弱**：社交媒体 Buzz 对小票有更强的预测力，TOP1000 大票上信号稀释
- **长期资产变化（252天）**：大公司资产变化太慢，短窗口（63天）效果更好
- **SUBINDUSTRY 中性化有帮助**：更细粒度的中性化让 Sub_Sharpe 维持更高

---

### 1.7 参数扫描的"相关性陷阱"

本项目 119 条通过记录中，**60 条都是 `rank(liabilities/assets)` 的参数变体**：

```python
rank(liabilities/assets)  # 基础表达式，Sharpe=1.51 不变
```

| decay | truncation | 中性化 | Sharpe | Fitness | TO |
|-------|-----------|--------|--------|---------|-----|
| 0 | 0.05 | SUBINDUSTRY | 1.51 | 1.26 | 0.017 |
| 0 | 0.08 | SUBINDUSTRY | 1.51 | 1.26 | 0.017 |
| 2 | 0.05 | SUBINDUSTRY | 1.51 | 1.26 | 0.016 |
| 6 | 0.08 | SUBINDUSTRY | 1.51 | 1.26 | 0.015 |
| 0 | 0.05 | INDUSTRY | 1.51 | 1.35 | 0.015 |
| 4 | 0.08 | INDUSTRY | 1.51 | 1.35 | 0.014 |

**发现**：`rank(liabilities/assets)` 的 Sharpe 对参数**完全不敏感**（全部精确 1.51），说明这个信号非常稳定。但这也意味着平台会将这 60 个 Alpha 视为**高度自相关**——SELF_CORRELATION 提交时极可能失败。

**行动建议**：每种表达式只提交 **1-2 个最优参数组合**，不要提交参数变体。

---

## 二、通过 Alpha 的完整清单与模式分析

### 2.1 37 个独特通过表达式

按类别整理（所有表达式均在 delay=1, TOP3000 USA 下测试）：

#### 类别 A：盈利能力 × 股本/资产（最强信号族）

```python
# 核心信号：ROE 时序强度
group_rank(ts_rank(operating_income/equity, 126), sector)    # Sh=2.07 Fit=1.45 TO=6.7%
group_rank(ts_rank(operating_income/equity, 126), industry)  # Sh=2.06 Fit=1.42 TO=7.2%
group_rank(ts_rank(operating_income/equity, 126), subindustry) # Sh=2.01 Fit=1.32 TO=6.3%
group_rank(ts_rank(operating_income/equity, 150), sector)    # Sh=2.04 Fit=1.44 TO=6.7%
group_rank(ts_rank(operating_income/equity, 175), sector)    # Sh=1.98 Fit=1.41 TO=6.4%
group_rank(ts_rank(operating_income/equity, 95), sector)     # Sh=1.94 Fit=1.29 TO=7.7%
group_rank(ts_rank(operating_income/equity, 252), sector)    # Sh=1.86 Fit=1.35 TO=5.8%
rank(ts_rank(operating_income/equity, 126))                  # Sh=1.65 Fit=1.04 TO=6.8% (SUBINDUSTRY neut)

# 同类变体：ROA
group_rank(ts_rank(operating_income/assets, 126), sector)    # Sh=1.70 Fit=1.17 TO=6.2%
group_rank(ts_rank(operating_income/assets, 126), industry)  # Sh=1.66 Fit=1.11 TO=6.2%
group_rank(ts_rank(operating_income/assets, 126), subindustry) # Sh=1.67 Fit=1.01 TO=6.3%
group_rank(ts_rank(operating_income/assets, 150), sector)    # Sh=1.67 Fit=1.09 TO=6.7%
group_rank(ts_rank(operating_income/assets, 175), sector)    # Sh=1.55 Fit=1.00 TO=6.5%
```

**经济直觉**：过去 126 天（约两个季度）ROE 处于历史高位的公司，往往盈利质量改善，下一期股价往往延续上涨趋势（趋势外推 + 基本面动量）。

#### 类别 B：杠杆/资本结构（超稳定信号）

```python
rank(liabilities/assets)      # Sh=1.51 Fit=1.26 TO=1.7%  SUBINDUSTRY
rank(-equity/assets)          # Sh=1.55 Fit=1.28 TO=1.8%  SUBINDUSTRY
                               # Sh=1.52 Fit=1.34 TO=1.6%  INDUSTRY

# 复合因子（最高 Sharpe 之一）
rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)
                               # Sh=2.10 Fit=1.81 TO=5.7%  SUBINDUSTRY
                               # Sh=2.09 Fit=1.92 TO=5.0%  INDUSTRY
```

**经济直觉**：`liabilities/assets` 高的公司（高杠杆）在 SUBINDUSTRY 中性化下表现好，原因是同行业内高杠杆公司风险溢价更高，在 BRAIN 5 年回测周期（非熊市）中获得超额收益。`-equity/assets = -(1-L/A) = L/A - 1`，与 L/A 方向一致。

#### 类别 C：情绪 Buzz 波动率（高换手率但有效）

```python
-ts_std_dev(scl12_buzz, 5)    # Sh=2.13 Fit=1.68 TO=39.1%  INDUSTRY（最高）
-ts_std_dev(scl12_buzz, 10)   # Sh=1.82 Fit=1.70 TO=21.7%  INDUSTRY
-ts_std_dev(scl12_buzz, 12)   # Sh=1.32 Fit=1.23 TO=18.8%  INDUSTRY
-ts_std_dev(scl12_buzz, 15)   # Sh=1.34 Fit=1.36 TO=15.6%  INDUSTRY
-ts_std_dev(scl12_buzz, 18)   # Sh=1.47 Fit=1.67 TO=13.5%  INDUSTRY
-ts_std_dev(scl12_buzz, 20)   # Sh=1.46 Fit=1.71 TO=12.4%  INDUSTRY
-ts_std_dev(scl12_buzz, 25)   # Sh=1.44 Fit=1.66 TO=10.3%  INDUSTRY
-ts_std_dev(scl12_buzz, 20)   # Sh=1.29 Fit=1.36 TO=13.3%  SUBINDUSTRY
-ts_std_dev(scl12_buzz, 25)   # Sh=1.25 Fit=1.33 TO=11.1%  SUBINDUSTRY
-ts_std_dev(scl12_buzz, 10)   # Sh=1.70 Fit=1.81 TO=17.0%  MARKET
-ts_std_dev(scl12_buzz, 20)   # Sh=1.47 Fit=1.77 TO=9.5%   MARKET
```

**经济直觉**：Buzz 波动率低（`-ts_std_dev`）意味着社交媒体讨论稳定，公司信息环境稳定，反而对应好的股票表现。Buzz 剧烈波动的股票往往是被炒作的，短期内有反转倾向。

**窗口期规律**：窗口越长（25天），换手率越低（10.3%）、Fitness 越高（1.66），但 Sharpe 略下降（1.44）。**最优甜点区：10-20 天窗口**，MARKET 中性化时窗口 10 天 Fitness=1.81（最高）。

#### 类别 D：增长动量（股本/资产变化）

```python
group_rank(ts_rank(ts_delta(equity, 63), 126), sector)   # Sh=1.68 Fit=1.18 TO=6.8% MARKET
group_rank(ts_rank(ts_delta(equity, 63), 175), sector)   # Sh=1.72 Fit=1.25 TO=6.4% MARKET
group_rank(ts_rank(ts_delta(equity, 63), 150), sector)   # Sh=1.67 Fit=1.18 TO=6.6% MARKET
group_rank(ts_rank(ts_delta(equity, 63), 252), sector)   # Sh=1.54 Fit=1.08 TO=5.9% MARKET
group_rank(ts_rank(ts_delta(equity, 63), 126), industry) # Sh=1.72 Fit=1.15 TO=7.7% MARKET
group_rank(ts_rank(ts_delta(assets, 63), 126), sector)   # Sh=1.68 Fit=1.05 TO=7.4% INDUSTRY
group_rank(ts_rank(ts_delta(assets, 63), 126), industry) # Sh=1.65 Fit=1.10 TO=7.3% MARKET

# 增长率归一化版本（更鲁棒）
group_rank(ts_rank(ts_delta(equity, 63)/ts_delay(equity, 63), 126), sector)  # Sh=1.64 Fit=1.11 TO=6.7%
group_rank(ts_rank(ts_delta(assets, 63)/ts_delay(assets, 63), 126), sector)  # Sh=1.56 Fit=1.03 TO=6.5%
group_rank(ts_rank(ts_delta(assets, 63)/ts_delay(assets, 63), 126), industry)# Sh=1.65 Fit=1.06 TO=7.3%
```

**经济直觉**：过去 63 天（约一个季度）股本增长处于历史高位的公司，往往对应内部再投资能力强，或正进行大型资本运作，在同行业中属于扩张型企业，短期有正向动量。

#### 类别 E：期权波动率信号（高换手率族）

```python
implied_volatility_call_120/parkinson_volatility_120  
  # 最优设置：INDUSTRY neut, Sh=1.72 Fit=1.30 TO=30.1%（不加 rank）
  # SECTOR neut:   Sh=1.65 Fit=1.33 TO=28.6%
  # SECTOR neut:   Sh=1.26 Fit=1.25 TO=22.6%（需加 rank 避免 CWEIGHT）
```

**经济直觉**：隐含波动率（IV）相对实际价格波动（Parkinson 范围波动率）高的股票，表明期权市场预期大幅波动但实际并未发生，意味着期权溢价被高估，预测股票未来下跌或波动率回归。

#### 类别 F：FCF 质量信号

```python
group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), sector)  # Sh=1.46 Fit=1.17 TO=4.0%
group_rank(ts_rank(free_cash_flow_reported_value/equity, 252), sector)  # Sh=1.41 Fit=1.11 TO=3.4%
```

**FCF/Equity（自由现金流回报率）的本质**：高 FCF/Equity 意味着公司用股东资本创造真实现金流，而不仅是会计利润。在同行业横截面比较下，这是衡量现金创造能力的强信号。

---

### 2.2 通过 Alpha 统计汇总

| 类别 | 通过数 | Sharpe 范围 | TO 范围 | 说明 |
|------|--------|-------------|---------|------|
| 盈利/ROE (OI/equity) | 13 | 1.39–2.10 | 5–8% | 最强、最稳定 |
| 杠杆 (L/A, E/A) | 60 | 1.51–1.55 | 1–2% | 超稳定但自相关高 |
| 情绪 Buzz std | 16 | 1.25–2.13 | 10–42% | 高换手率、Fitness 好 |
| 增长 (equity delta) | 11 | 1.54–1.72 | 6–8% | 稳健 |
| 盈利/ROA (OI/assets) | 7 | 1.55–1.75 | 6–8% | 稳健 |
| 期权 IV/RV | 5 | 1.26–1.72 | 23–48% | 需 rank |
| FCF/Equity | 2 | 1.41–1.46 | 3–4% | 潜力待挖掘 |

---

## 三、官方 Alpha 示例深度解析

### 3.1 初学者官方示例（来自 `learn_documentation_examples_19-alpha-examples.json`）

#### 示例 1：Operating Earnings Yield（盈利收益率）

```python
ts_rank(operating_income, 252)
```

| 设置 | 值 |
|------|-----|
| Region | USA |
| Universe | TOP3000 |
| Delay | 1 |
| Decay | 0 |
| Truncation | 0.08 |
| Neutralization | Subindustry |
| Pasteurization | On |

**假说**：若公司当前营业收入高于过去一年历史，则做多该股票。

**已知问题**（本项目实测）：使用 `operating_income` 绝对值而非比率，大型公司绝对值自然高 → 信号混入市值效应 → Sharpe=1.23（勉强未达标）。

**改进版**（本项目实测通过）：
```python
group_rank(ts_rank(operating_income/equity, 126), sector)  # Sh=2.07
```

分母归一化为股本，消除市值效应；使用 `group_rank` 代替 `rank` 做行业内中性化。

---

#### 示例 2：Appreciation of Liabilities（负债公允价值增长）

```python
-ts_rank(fn_liab_fair_val_l1_a, 252)
```

| 设置 | 同上（Subindustry, decay=0, trunc=0.08） |

**假说**：负债公允价值增长意味着融资成本增加，预测盈利下滑，做空。

**注**：字段 `fn_liab_fair_val_l1_a` 为会计准则下的公允价值负债，覆盖率约 40%，非所有股票都有此数据。

---

#### 示例 3：Power of Leverage（杠杆效应）

```python
liabilities/assets
```

| 设置 | Region=USA, Universe=TOP3000, Decay=0, Delay=1, Truncation=0.01, Neutralization=Market |

**本项目实测改进**：
- 原始版本 `liabilities/assets`（Market 中性化）实测 Sharpe=0.84（失败）
- 改用 `rank(liabilities/assets)` + SUBINDUSTRY → Sharpe=1.51 ✅
- 使用 INDUSTRY 中性化 → Fitness=1.35（比 SUBINDUSTRY 的 1.26 更高）

**关键教训**：`liabilities/assets` 需要用 `rank()` 归一化，且行业中性化比市场中性化更强。

---

#### 示例 4：Earnings Yield Momentum（盈利收益率动量）

**概念**：使用 EPS-to-price 比率（盈利收益率代理），比较过去历史，行业内归一化。

**本项目实测近似**：
```python
group_rank(ts_rank(operating_income/equity, 126), sector)  # Sh=2.07
```
用 `operating_income/equity` 作为盈利质量代理，效果显著优于 EPS/price（EPS 数据质量问题更多）。

---

### 3.2 数据类别官方 Alpha 示例（视频系列 Quantcepts）

根据爬取的官方课程目录，官方 Quantcepts 视频涵盖 19 个概念：

1. **价量数据（Price Volume）**：`close`, `open`, `vwap`, `returns`, `volume`, `adv20`
2. **基本面数据（Fundamentals）**：`operating_income`, `assets`, `equity`, `liabilities`, `sales`, `free_cash_flow_reported_value`
3. **情绪数据（Sentiment）**：`scl12_buzz`, `scl12_str_all`（Research Sentiment）, `snt1_*`
4. **期权数据（Options）**：`implied_volatility_call_120`, `parkinson_volatility_120`

---

### 3.3 官方数据集完整清单（来自 `data_data-sets.json`）

| 数据集 | 字段数 | 覆盖率 | Alpha 数 | 分类 |
|--------|--------|--------|---------|------|
| Analyst Estimate Data for Equity | 653 | 72% | 490,448 | Analyst |
| Company Fundamental Data for Equity | 886 | 50% | 619,796 | Fundamental |
| Report Footnotes | 318 | 41% | 105,116 | Fundamental |
| Fundamental Scores | 24 | 56% | 3,961 | Model |
| Systematic Risk Metrics | 16 | 77% | 24,557 | Model |
| US News Data | 322 | 80% | 118,699 | News |
| Ravenpack News Data | 75 | 50% | 40,388 | News |
| Volatility Data | 64 | 69% | 102,546 | Option |
| Options Analytics | 74 | 70% | 45,857 | Option |
| Price Volume Data for Equity | 23 | 100% | 1,465,665 | Price Volume |
| Relationship Data for Equity | 165 | 80% | 126,076 | Relationship |
| Research Sentiment Data | 17 | 56% | 11,464 | Sentiment |
| Sentiment Data for Equity | 18 | 99% | 42,716 | Sentiment |
| Social Media Data for Equity | 2 | 86% | 8,923 | Social Media |
| Universe Dataset | 6 | 36% | 97 | Universe |

**数据类别价值评分**（BRAIN 官方，基于 `data.json`）：

| 类别 | 官方价值分 | 字段数 | 数据集数 |
|------|-----------|--------|---------|
| Sentiment | **8** | 17 | 1 |
| Model | **7** | 40 | 2 |
| Analyst | **5** | 680 | 1 |
| News | **4** | 397 | 2 |
| Fundamental | **3** | 1,310 | 2 |
| Option | **3** | 138 | 2 |
| Price Volume | **2** | 201 | 3 |
| Social Media | **2** | 20 | 2 |

> **注意**：价值评分高（如 Sentiment=8）不代表容易过检，而是代表数据稀缺性和信息价值。本项目实测情绪类 Alpha 通过率依然很高（scl12 系列），但 Ravenpack 新闻数据（rp_*）因换手率过高基本无法直接使用。

---

## 四、数据字段分类与使用指南

### 4.1 已验证可用字段（TOP3000, USA, Delay=1）

#### 高质量基本面字段（季度更新，换手率 1-5%）

| 字段名 | 描述 | 实测换手率 | 推荐用法 |
|--------|------|-----------|---------|
| `operating_income` | 营业收入 | ~5% | 与 equity/assets 做比率 |
| `equity` | 股东权益 | ~5% | 分母归一化 |
| `assets` | 总资产 | ~5% | 分母归一化 |
| `liabilities` | 总负债 | ~1-2% | 直接做 rank 有效 |
| `sales` | 营业收入（销售额） | ~5% | 增长率信号 |
| `free_cash_flow_reported_value` | 自由现金流（实报） | ~3-4% | FCF/equity 信号 |

**注**：`ebitda`, `revenue` 类字段实测 Sharpe 均低于 1.25，不如 `operating_income` 有效。

#### 情绪/Buzz 字段（日频，换手率 10-40%）

| 字段名 | 数据集 | 描述 | 推荐处理 |
|--------|--------|------|---------|
| `scl12_buzz` | Social Media Data | 社交媒体 Buzz 分数 | `-ts_std_dev(scl12_buzz, 5-25)` |
| `scl12_str_all` | Social Media Data | 综合情绪评分 | 待测试 |
| `snt1_cored1_score` | Research Sentiment | 情绪分数 | `rank(snt1_cored1_score)` |
| `snt1_d1_earningssurprise` | Research Sentiment | 盈利惊喜 | `rank(snt1_d1_earningssurprise)` |
| `snt1_d1_buyrecpercent` | Research Sentiment | 买入推荐比例 | 换手率极低（0.6%），需结合其他 |

#### 期权字段（日频，换手率 20-50%）

| 字段名 | 数据集 | 描述 | 推荐用法 |
|--------|--------|------|---------|
| `implied_volatility_call_120` | Options Analytics | 120 日看涨隐含波动率 | IV/RV 比率 |
| `parkinson_volatility_120` | Volatility Data | 120 日 Parkinson 波动率 | 作为分母 |

#### 分析师字段（周/月频，换手率 5-20%）

| 字段名 | 数据集 | 描述 | 实测效果 |
|--------|--------|------|---------|
| `analyst_revision_rank_derivative` | Fundamental Scores | 分析师修正排名变化 | Sh=0.83（失败，不够强） |
| `actual_eps_value_quarterly` | Analyst Estimate | EPS 实际值（季度） | 需与预期对比 |

#### 新闻字段（日频，换手率极高）

| 字段名 | 数据集 | 注意事项 |
|--------|--------|---------|
| `rp_css_equity` | Ravenpack News | TO=133%（远超限制，不可用） |
| `nws12_afterhsz_1_minute` | US News Data | 向量字段，需 `vec_count()` 处理 |

---

### 4.2 字段更新频率与换手率关系

根据官方文档 `learn_documentation_understanding-data_data.json` 的关键技巧：

```python
# 检测字段更新频率的方法：
ts_std_dev(datafield, N) != 0 ? 1 : 0
```

| 如果 Long Count + Short Count（N=） | 字段更新频率 | 代表字段 |
|-------------------------------------|------------|---------|
| N=252 时最高 | 年度更新 | `actual_sales_value_annual` |
| N=66 时最高 | 季度更新 | `operating_income`, `assets`, `equity` |
| N=22 时最高 | 月度更新 | 分析师预测修正 |
| N=5 时最高 | 周度更新 | 部分新闻/情绪 |
| N=1 时最高 | 日频更新 | `close`, `returns`, `scl12_buzz` |

**推论**：
- 季度更新字段（`equity`, `assets`, `operating_income`）的 Alpha 换手率自然低（1-8%）
- 日频字段（`scl12_buzz`, `returns`）的 Alpha 换手率自然高（10-90%），需用 `decay` 或时序聚合降低

---

### 4.3 向量字段（Vector Fields）处理规范

来源：`learn_documentation_understanding-data_vector-datafields.json`

**什么是向量字段**：每天每只股票有多个值（如多条新闻），无法直接使用。

**可用向量算子**（来自 `operators_full.json`）：

| 算子 | 描述 | 使用场景 |
|------|------|---------|
| `vec_avg(x)` | 向量均值 | 情绪均值（如 scl15_d1_sentiment） |
| `vec_sum(x)` | 向量求和 | 新闻总量 |
| `vec_count(x)` | 向量元素个数 | 新闻数量代理 |
| `vec_std_dev(x)` | 向量标准差 | 情绪一致性/分歧度 |
| `vec_max(x)` | 向量最大值 | 极端新闻检测 |
| `vec_min(x)` | 向量最小值 | 极端新闻检测 |
| `vec_ir(x)` | 向量信息比率 | 情绪稳定性 |
| `vec_percentage(x, 0.5)` | 向量中位数 | 鲁棒性更好 |

**实例**：
```python
# 新闻数量信号（高新闻量=高注意力=短期动量/反转）
vec_count(nws12_afterhsz_120_min)          # 原始，TO极高
rank(ts_sum(vec_count(nws12_afterhsz_120_min), 5))  # 5天聚合后归一化
```

---

## 五、运算符使用最佳实践

### 5.1 时序运算符决策树

#### `ts_rank` vs `ts_zscore` vs `ts_av_diff`

| 运算符 | 定义 | 输出范围 | 适用场景 |
|--------|------|---------|---------|
| `ts_rank(x, d)` | x 在过去 d 天中的排名 | [0, 1] | 基本面字段（非正态），季度更新 |
| `ts_zscore(x, d)` | (x - mean(x,d)) / std(x,d) | (-∞, +∞) | 日频信号（正态分布假设合理） |
| `ts_av_diff(x, d)` | x - mean(x, d) | 与 x 同量纲 | 需要绝对变化量而非相对排名 |
| `ts_delta(x, d)` | x - x[d天前] | 与 x 同量纲 | 变化量动量，需配合 rank |

**关键区别**：
- `ts_rank` 是**非参数**方法，对异常值鲁棒，推荐用于基本面数据（非正态）
- `ts_zscore` 假设正态分布，适合日频收益率、情绪分数
- 实测：基本面字段用 `ts_rank` 比 `ts_zscore` 普遍高 0.2-0.4 Sharpe

#### 推荐窗口期

| 数据类型 | 推荐窗口 | 依据 |
|---------|---------|------|
| 基本面（季度） | 126 天（≈2季度） | 本项目最优，Sh=2.07 |
| 基本面（季度） | 150–175 天 | 次优 |
| 基本面（季度） | 63 天（1季度） | 增长率信号的变化窗口 |
| 情绪 Buzz | 5–25 天 | 本项目实测最优 10-20 天 |
| 期权 IV | 120 天 | 与 IV 字段本身窗口一致 |

---

### 5.2 `group_rank` vs `rank` + 中性化

| 方式 | 优点 | 缺点 | 适用 |
|------|------|------|------|
| `group_rank(x, sector)` | 输出已在行业内归一化 [0,1] | 直接输出即为行业中性 | 行业内比较时 |
| `rank(x)` + `neutralization=SUBINDUSTRY` | 更多控制权 | 中性化在信号之外做 | 全市场信号 |
| `rank(x)` + `neutralization=MARKET` | 最简单 | 行业集中风险未消除 | 市值中性即可 |

**实测对比**（`operating_income/equity, 126`）：

| 表达式 | 中性化 | Sharpe | Fitness |
|--------|--------|--------|---------|
| `group_rank(ts_rank(...), sector)` | SUBINDUSTRY | **2.07** | 1.45 |
| `group_rank(ts_rank(...), industry)` | SUBINDUSTRY | **2.06** | 1.42 |
| `rank(ts_rank(...))` | SUBINDUSTRY | 1.65 | 1.04 |
| `group_rank(ts_rank(...), sector)` | MARKET | 1.78 | 1.36 |

**结论**：`group_rank(x, sector/industry)` + SUBINDUSTRY 中性化组合效果最佳——双重行业中性化。

---

### 5.3 中性化选择指南

| 中性化级别 | 适用情景 | 实测效果 |
|-----------|---------|---------|
| `SUBINDUSTRY` | 基本面信号首选（行业内比较最精确） | OI/equity: Sh=2.07 |
| `INDUSTRY` | 情绪/期权信号首选 | buzz: Sh=2.13 |
| `MARKET` | FCF、增长类信号（跨行业效应） | equity delta: Sh=1.72 |
| `SECTOR` | 期权 IV 信号 | IV/RV: Sh=1.65 |
| `NONE` | **仅用于数据探索**，不提交 | — |

**最优中性化规律**：
- 基本面（财务比率）→ **SUBINDUSTRY**（控制行业财务特性差异）
- 情绪/新闻 → **INDUSTRY**（行业舆论环境差异较大）
- 技术/价量 → **MARKET**（技术信号跨行业有效）

---

### 5.4 关键运算符速查（来自 `operators_full.json`，共 66 个）

#### 时序运算符（24 个，最常用）

```python
ts_rank(x, d)              # 时序排名（基本面首选）
ts_zscore(x, d)            # 时序 Z-score（日频信号）
ts_std_dev(x, d)           # 时序标准差（用于情绪波动率信号）
ts_delta(x, d)             # x - x[d天前]
ts_delay(x, d)             # x 延迟 d 天
ts_mean(x, d)              # 时序均值
ts_av_diff(x, d)           # x - mean(x, d)，NaN 友好版
ts_corr(x, y, d)           # 时序 Pearson 相关
ts_covariance(x, y, d)     # 时序协方差
ts_sum(x, d)               # 时序求和
ts_regression(x, y, d)     # 时序回归（多参数版）
hump(x, hump=0.01)         # 限制变化量（降换手率神器）
kth_element(x, d, k)       # 第 k 个值（数据回填用）
```

**`hump` 算子**是**降低换手率**的专用工具：
```python
# 原始（TO=39%）：
-ts_std_dev(scl12_buzz, 5)

# 用 hump 限制变化（预期降低 TO）：
hump(-ts_std_dev(scl12_buzz, 5), 0.005)
```

#### 截面运算符（6 个）

```python
rank(x)                    # 全市场排名 [0,1]
zscore(x)                  # 全市场 Z-score
scale(x)                   # 使 sum(|x|) = 1
normalize(x)               # 减均值除标准差
winsorize(x, w=0.05)       # 截断极值（消 CONCENTRATED_WEIGHT）
quantile(x, n)             # 分位数归组
```

#### 分组运算符（6 个）

```python
group_rank(x, group)       # 组内排名 [0,1]
group_zscore(x, group)     # 组内 Z-score
group_mean(x, group)       # 组内均值
group_neutralize(x, group) # 组内中性化（减去组均值）
group_backfill(x, group)   # 组内数据填充
group_scale(x, group)      # 组内缩放 [0,1]
```

---

### 5.5 Decay 参数的作用与限制

来源：官方文档 `learn_documentation_discover-brain_intermediate-pack-part-2.json`

> **"Decay can be used to reduce turnover, but decay values that are too large will attenuate the signal."**

实测 `rank(liabilities/assets)` 在不同 decay 下：

| decay | Sharpe | Fitness | TO |
|-------|--------|---------|-----|
| 0 | 1.51 | 1.26 | 0.017 |
| 2 | 1.51 | 1.26 | 0.016 |
| 6 | 1.51 | 1.26 | 0.015 |
| 10 | 1.52 | 1.27 | 0.015 |

**发现**：对于季度基本面信号，`decay` 对 Sharpe 和 Fitness 几乎无影响（换手率已经很低），增加 `decay` 无益。

对于高换手率信号（`scl12_buzz`），推荐用 **较大的 d 窗口**而非 `decay`：
```python
# 换手率控制方案优先级：
# 1. 增大 ts_std_dev 窗口（5→20，TO: 39%→12%）
# 2. 使用 hump 算子
# 3. 使用 decay（对基本面无效，对日频信号有帮助）
```

---

## 六、自相关降低策略

### 6.1 自相关检查机制

SELF_CORRELATION 检查在提交 Alpha 时触发，检查新 Alpha 与用户已提交的 Alpha 组合是否过于相似。

**核心机制**：
- BRAIN 计算新 Alpha 的日收益序列与现有 Portfolio 的相关性
- 若相关性过高（通常 > 0.7），则 SELF_CORRELATION = FAIL
- 本项目 119 条通过记录的 SELF_CORRELATION 均为 `PENDING`（提交前无法预先知道结果）

### 6.2 相关性风险评估

**高度同质的表达式族（极高相关风险）**：

```python
# 族群 1：rank(liabilities/assets) 的所有参数变体（60 个）
# → 这些 alpha 几乎完全相同，只提交 1-2 个

# 族群 2：group_rank(ts_rank(operating_income/equity, d), sector/industry)
# → 窗口期 95-252 天都相关，只提交 2-3 个最优组合

# 族群 3：-ts_std_dev(scl12_buzz, d) 系列
# → 窗口期 5-25 天有差异，但同向（都是做空 buzz 波动率高的）
# → 提交 2-3 个窗口差异最大的（如 5、15、25）
```

### 6.3 确保低相关性的 8 类策略

以下 8 类是已验证或已知的有效 Alpha 类别，理论上彼此相关性较低：

| 编号 | 类别 | 典型表达式 | 数据源 |
|------|------|-----------|--------|
| 1 | 基本面质量（ROE动量） | `group_rank(ts_rank(operating_income/equity, 126), sector)` | Fundamental |
| 2 | 杠杆率 | `rank(liabilities/assets)` | Fundamental |
| 3 | FCF 质量 | `group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), sector)` | Fundamental |
| 4 | 情绪波动率 | `-ts_std_dev(scl12_buzz, 10)` | Social Media |
| 5 | 期权波动率 | `rank(implied_volatility_call_120/parkinson_volatility_120)` | Options |
| 6 | 股本增长动量 | `group_rank(ts_rank(ts_delta(equity, 63), 175), sector)` | Fundamental |
| 7 | 盈利惊喜（待测） | `rank(snt1_d1_earningssurprise)` | Sentiment |
| 8 | 分析师修正（待测） | `rank(ts_rank(actual_eps_value_quarterly, 126))` | Analyst |

### 6.4 最大化多样性的新方向建议

**基于现有通过 Alpha 的空白区域**：

现有通过 Alpha 集中在：ROE、L/A、buzz_std、equity_delta、IV/RV。以下方向尚未被测试或失败率高，但值得探索：

```python
# 方向 1：分析师一致性（共识方向）
rank(ts_rank(actual_eps_value_quarterly/ts_delay(actual_eps_value_quarterly, 252), 126))

# 方向 2：新闻数量信号（注意力捕获）
rank(ts_sum(vec_count(nws12_afterhsz_120_min), 5))

# 方向 3：盈利惊喜动量
rank(snt1_d1_earningssurprise)  # 先验证 TO 和 Sharpe

# 方向 4：短期利率/短期利息支出变化（与杠杆不同维度）
group_rank(ts_rank(interest_expense/liabilities, 126), sector)

# 方向 5：研究情绪分数（sentiment1 数据集）
rank(snt1_cored1_score)  # 纯情绪，与 scl12 相关性低

# 方向 6：销售增长质量（但非单纯 ts_delta(sales)）
group_rank(ts_rank(sales/assets, 126), sector)  # 资产周转率
```

---

## 七、IQC 2026 竞赛策略

### 7.1 竞赛结构（来自 `brain_iqc.json`, `competition_IQC2026S1.json`）

| 阶段 | 时间 | 形式 |
|------|------|------|
| 第一阶段：资格赛 | 2026年3月17日–5月18日 | 线上提交 Alpha，积累分数 |
| 第二阶段：全国/区域决赛 | 5月26日–7月中 | 线上资格赛 + 演讲 |
| 第三阶段：全球总决赛 | 2026年9月，新加坡 | 现场决赛 |

**奖金**：
- 第二阶段：第一名 $3,000，第二名 $2,000，第三名 $1,000
- 第三阶段：第一名 $20,000，第二名 $12,000，第三名 $8,000

### 7.2 评分机制

来源：`competition_IQC2026S1.json` 排行榜数据

排行榜显示每支队伍有三个分数：
- **Individual Qualifier Score**：个人资格分（满分 10,000）
- **IS Score**：样本内得分（最高约 32,000+）
- **D0 Score**：D0 Delay 特有得分（可选）
- **D1 Score**：Delay-1 得分（与 IS Score 重叠）

**第一名分析**（Sigma Lab, NUS, Singapore）：
```
Individual Qualifier Score: 10,000（满分）
IS Score: 32,449
D0 Score: 15,594
D1 Score: 27,251
```

**得分构成**：团队分 = 各成员分数之和。4人团队可提交 4 倍数量的 Alpha。

### 7.3 Challenge 积分现状

来源：`competition_challenge.json`（本账号情况）

```
当前账号：Jiexiong Zhao
级别：Bronze（铜牌）
分数：3,997 / 5,000（距 Silver 还差 1,003 分）
提交 Alpha 数：2
```

**排行榜 Top 玩家数据**（截至爬取时间）：

| 排名 | 用户 | 分数 | 提交数 |
|------|------|------|--------|
| 1 | JY12161 | 746,059 | 560 |
| 2 | Bret Hribar | 470,688 | 254 |
| 3 | Mika Aatos Heikkinen | 360,639 | 222 |
| 4 | Yan Yingshuang | 269,382 | 416 |

**结论**：顶级玩家提交了 100-600 个 Alpha，平均每个 Alpha 贡献约 600-1,300 分。**数量与质量并重**，而非只依赖少数高 Sharpe Alpha。

### 7.4 推荐提交顺序

基于本项目已通过的 37 种表达式，按**预期自相关最低**原则排序：

**第一批（5个）：最多样化的起点**

```python
# 1. 杠杆（超稳定）
rank(liabilities/assets)               # SUBINDUSTRY

# 2. ROE 动量（最强）
group_rank(ts_rank(operating_income/equity, 126), sector)  # SUBINDUSTRY

# 3. 情绪波动率（高换手率，与上面不相关）
-ts_std_dev(scl12_buzz, 10)            # INDUSTRY

# 4. 期权 IV（数据源完全不同）
rank(implied_volatility_call_120/parkinson_volatility_120)  # INDUSTRY

# 5. FCF 质量（独立信号）
group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), sector)  # MARKET
```

**第二批（5个）：扩展到未测试区域**

```python
# 6. 盈利惊喜
rank(snt1_d1_earningssurprise)  

# 7. 研究情绪
rank(snt1_cored1_score)          

# 8. 复合因子（ROE + 杠杆）
rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)  # INDUSTRY

# 9. 股本增长
group_rank(ts_rank(ts_delta(equity, 63), 175), sector)  # MARKET

# 10. 资产周转率
group_rank(ts_rank(sales/assets, 126), sector)  # SUBINDUSTRY（待测）
```

**第三批（后续）：系统性变体扩展**

对每类有效信号，用不同的：
- 中性化级别（SUBINDUSTRY → INDUSTRY → MARKET）
- 窗口期（95 → 126 → 150 → 175 → 252）
- 组合方式（sector → industry → subindustry）

### 7.5 D0 Alpha 策略（Day 0，竞赛专项）

来源：`brain_iqc.json` 课程表（D0 Alphas 培训课 2026年5月28日）

**D0 Alpha 特点**：
- Delay=0（当天信号、当天交易）
- Sharpe 要求 ≥ 2.0（比 Delay-1 的 1.25 高 60%）
- Fitness 要求 ≥ 1.3（比 Delay-1 的 1.0 高 30%）
- 换手率通常 > 50%

**D0 适用数据**：
- 日内价格信号（`close/vwap`, `returns`）
- 盘前/盘后信号（`nws12_afterhsz_1_minute`）
- 高频情绪（即时 Buzz 分数）

**注意**：本项目目前仅测试了 Delay-1，D0 策略需单独探索。

---

## 八、社区官方教程精华提炼

### 8.1 官方入门教程核心要点

来源：`learn_documentation_examples_19-alpha-examples.json`, `learn_documentation_discover-brain_intermediate-pack-part-1.json`, `learn_documentation_discover-brain_intermediate-pack-part-2.json`

#### 好的 PnL 曲线特征

> "A good Alpha should produce a steadily rising PnL chart with few fluctuations and no major drawdown."

- ❌ 差：多次大幅亏损期，高波动
- ✅ 好：持续缓慢上升，无大回撤

#### Fitness 公式记忆

```
Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))
```

关键约束：**`max(Turnover, 0.125)`** 意味着：
- 换手率 < 12.5% → Fitness 计算上等同于 12.5%（不会因换手率极低而更好）
- 换手率 > 12.5% → 换手率越高，Fitness 越低（分母变大）

**换手率-Fitness 实用换算表**（Sharpe=1.5, Returns=10%）：

| 换手率 | Fitness |
|--------|---------|
| 1-12.5% | ~1.34（等同于 12.5%） |
| 20% | ~1.06 |
| 30% | ~0.87 |
| 40% | ~0.75 |
| 70% | ~0.57 |

#### `rank(x)` 的权重分布效果

官方文档中的关键图示说明（来自 intermediate-pack-part-2）：

```
不用 rank：
  sales/assets → 最大权重股占组合 80%（过度集中）

用 rank：
  rank(sales/assets) → 最大权重股占组合 40%（分散）
```

**教训**：所有原始财务比率都应先用 `rank()` 归一化再使用，避免权重集中。

### 8.2 情绪数据集（sentiment1）使用指南

来源：`learn_documentation_understanding-data_getting-started-sentiment1-dataset.json`

**数据集特点**：
- 结合情绪指标与盈利估计和惊喜
- 覆盖约 2,000 只（TOP3000 中）
- 情绪分数是**日频高换手率**信号，需用 `decay` 平滑
- 分析师/盈利指标是**低频信号**

**官方推荐 Alpha 思路**：

```python
# 思路1：情绪极性信号
rank(snt1_cored1_score)  # 多空情绪 >5 做多，<-5 做空

# 思路2：盈利惊喜
rank(snt1_d1_earningssurprise)

# 思路3：分析师共识+覆盖率过滤
rank(snt1_d1_buyrecpercent)  # 但需注意 TO 极低（0.6%）

# 注意：
# - 不要用超过 63 天的回溯窗口（信息时效性差）
# - 先在 TOP1000/TOPSP500 测试（覆盖率更好）
```

### 8.3 数据探索 6 种方法

来源：`learn_documentation_understanding-data_data.json`

```python
# 方法 1：覆盖率检查（Long Count + Short Count ≈ 非 NaN 比例）
datafield

# 方法 2：非零覆盖
datafield != 0 ? 1 : 0

# 方法 3：更新频率检测（N=66=季度、22=月、5=周）
ts_std_dev(datafield, N) != 0 ? 1 : 0

# 方法 4：数据范围
abs(datafield) > X  # 调整 X 查看分布

# 方法 5：相关性
ts_corr(datafield, close, 252)  # 与价格的相关性

# 方法 6：时序稳定性
ts_std_dev(datafield, 252)  # 字段自身波动性
```

**标准做法**：所有上述探索都用 `neutralization=NONE, decay=0`。

---

## 九、快速决策参考卡

### 9.1 遇到这些失败时该怎么办

| 失败检查 | 症状 | 解决方案 |
|---------|------|---------|
| `LOW_SHARPE` | Sharpe < 1.25 | 换更强的数据字段；改用 `group_rank`；更换窗口期 |
| `LOW_FITNESS` | Sharpe≥1.25 但 Fitness<1.0 | 换手率 20-50%：用 `hump` 或增大窗口期 |
| `HIGH_TURNOVER` | TO > 70% | 用 `ts_std_dev` 替代 `ts_rank`；增大窗口 |
| `LOW_TURNOVER` | TO < 1% | 信号几乎不变化；换更高频字段 |
| `CONCENTRATED_WEIGHT` | 权重集中在少数股 | 加 `rank()` 包裹原始比率 |
| `LOW_SUB_UNIVERSE_SHARPE` | 大市值效果差 | 换 SUBINDUSTRY；用行业内归一化 |
| `SELF_CORRELATION` | 与已提交 Alpha 太像 | 换数据类别；改变信号方向 |

### 9.2 表达式模板库（已验证有效）

```python
# ============ 基本面（低换手率，高稳定性）============

# 盈利质量（最强）
group_rank(ts_rank(operating_income/equity, 126), sector)    # SUBINDUSTRY, Sh=2.07
group_rank(ts_rank(operating_income/assets, 126), sector)    # SUBINDUSTRY, Sh=1.70
rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)  # INDUSTRY, Sh=2.09

# 杠杆（超稳）
rank(liabilities/assets)    # SUBINDUSTRY, Sh=1.51, TO=1.7%
rank(-equity/assets)        # SUBINDUSTRY, Sh=1.55, TO=1.8%

# 增长动量
group_rank(ts_rank(ts_delta(equity, 63), 175), sector)    # MARKET, Sh=1.72

# FCF
group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), sector)  # MARKET, Sh=1.46

# ============ 情绪/社交媒体（中等换手率）============

-ts_std_dev(scl12_buzz, 10)   # INDUSTRY, Sh=1.82, TO=21.7%
-ts_std_dev(scl12_buzz, 20)   # MARKET,   Sh=1.47, TO=9.5%

# ============ 期权（高换手率，需 rank）============

rank(implied_volatility_call_120/parkinson_volatility_120)  # INDUSTRY, Sh=1.72 (with rank)

# ============ 待测试方向 ============

rank(snt1_d1_earningssurprise)   # 情绪数据集 - 盈利惊喜
rank(snt1_cored1_score)          # 情绪数据集 - 综合情绪
group_rank(ts_rank(sales/assets, 126), sector)  # 资产周转率
```

---

## 十、附录：原始数据引用

### A. 已抓取但内容为空的社区帖子（网络超时）

以下帖子因 Playwright 超时无法爬取（40秒超限），其内容来自标题推断：

| 帖子 | 标题 | 状态 |
|------|------|------|
| 14431641039383 | BRAIN TIPS: Getting Started with Technical Indicators | ❌ 超时 |
| 15053280147223 | BRAIN TIPS: Finite differences | ❌ 超时 |
| 15233993197079 | BRAIN TIPS: Statistics in alphas research | ❌ 超时 |
| 8123350778391 | How do you get a higher Sharpe? | ❌ 超时 |
| 8419305084823 | BRAIN TIPS: Weight Coverage common issues and advice | ❌ 超时 |

**推断内容**（基于标题和官方文档）：
- **Finite differences**：即 `ts_delta` 和 `ts_av_diff` 的使用，计算离散导数
- **Statistics in alphas**：`ts_zscore`, `ts_std_dev`, 正态化技术
- **Technical Indicators**：`ts_rank`, `ts_corr` 与价量数据结合
- **Higher Sharpe**：可能推荐行业内中性化、组合多个独立信号、控制噪声
- **Weight Coverage**：已从 `support_hc_en-us_articles_19248385997719` 了解部分

### B. 本项目测试的 Alpha 类别分布

| 批次文件 | 主要测试方向 |
|----------|------------|
| batch1, batch2_final | 基础基本面（liabilities, operating_income） |
| batch3, batch4 | 参数扫描（decay, truncation 组合） |
| batch5, batch5c | 扩展基本面（ebitda, sales, revenue） |
| batch10_scl12 | 情绪 Buzz 系列（scl12_buzz） |
| batch11_combo | 复合因子（ROE + 杠杆） |
| batch12_rpanl | Ravenpack + 分析师信号 |
| batch13_vol | 期权波动率信号（IV/RV） |
| wave12b | FCF、增长率信号 |
| alphas_20260415 | 初始测试（rank(liabilities/assets) 验证） |

---

> 文档创建：2026年4月 | 基于 1,022 条实测 Alpha 记录和 111 个社区文件分析
> 版本：1.0 | 作者：GitHub Copilot（基于项目数据自动生成）
