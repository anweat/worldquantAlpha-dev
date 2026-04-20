# 07 Alpha 开发实战指南

> 本文档从实际开发流程出发，讲解如何系统地构建、优化和提交高质量的 Alpha。

---

## 一、Alpha 开发思路框架

### 第一步：产生想法（Hypothesis）

每个 Alpha 都应基于清晰的市场假设：

```
假设（Hypothesis）：
  描述为什么某个信号能预测股票的相对涨跌

实现（Implementation）：
  用 Fast Expression 表达这个想法

验证（Validation）：
  通过 IS 模拟验证假设

优化（Optimization）：
  提升 Sharpe/Fitness，降低换手率/相关性
```

### 想法来源

| 来源 | 典型 Alpha 类型 |
|------|----------------|
| 技术分析 | 动量、均值回归、量价关系 |
| 基本面分析 | 价值因子、质量因子、成长因子 |
| 行为金融 | 投资者过度反应、注意力效应 |
| 替代数据 | 情绪、搜索量、社交媒体声量 |
| 学术论文 | 经典因子（Fama-French 五因子等） |

---

## 二、19 个官方 Alpha 示例精解

以下是 BRAIN 平台官方提供的 Alpha 示例，涵盖多种策略类型：

### 2.1 技术分析类

#### 动量策略（Momentum）

```
# Alpha：过去 5 日价格下跌越多，预期反弹越多（短期反转）
rank(-ts_delta(close, 5))

设置: Universe=TOP3000, Delay=1, Decay=0, Neutralization=Market
思路: 5日跌幅最大 → rank最高 → 做多（短期均值回归）
改进: 可将 5 改为 20（中期动量）；
      也可换为 -rank(...)（做动量而非反转）
```

#### 量价反转

```
# 成交量与价格负相关 = 异常信号
rank(-ts_corr(rank(volume), rank(close), 10))

思路: 量价负相关（涨价缩量/跌价放量）= 可能反转
```

### 2.2 基本面类

#### 运营收益率（Operating Earnings Yield）

```
ts_rank(operating_income, 252)

设置: Universe=TOP3000, Delay=1, Neutralization=Subindustry
      Truncation=0.08, NaN Handling=On
思路: 公司运营收益高于历史 → 买入
改进: 加入市场估值（如 operating_income/cap）
```

#### 负债增值（Appreciation of Liabilities）

```
-ts_rank(fn_liab_fair_val_l1_a, 252)

思路: 公允价值负债增加 = 公司财务恶化信号 → 做空
改进: 观察更短周期以提升时效性
```

#### 财务杠杆（Power of Leverage）

```
liabilities / assets

设置: Universe=TOP3000, Delay=1, Neutralization=Market
思路: 高负债率公司利用杠杆实现高增长（激进成长股）
改进: 尝试行业中性化（subindustry）效果更稳定
```

#### 盈利收益率动量（Earnings Yield Momentum）

```
group_rank(ts_rank(est_eps/close, 60), industry)

设置: Neutralization=Industry, NaN Handling=On
思路: 行业内，预期盈利收益率在过去3个月更高 = 低估 → 买入
改进: 用 NaN Handling=On 补全分析师覆盖不足的问题
```

### 2.3 情绪/替代数据类

#### 短期情绪量稳定性（Short-Term Sentiment Volume Stability）

```
-ts_std_dev(scl12_buzz, 10)

设置: Neutralization=Industry, NaN Handling=On
思路: 情绪声量波动大 = 关注度不稳定 = 短期噪音 → 做空
改进: 对更流动的股票使用更短的观察窗口
```

### 2.4 财务比率类（来自初学者包）

```
# 存货周转率（Inventory Turnover）
inventory_turnover
思路: 周转率高 = 运营效率高 → 买入

# 资产利用率（Sales/Assets）
rank(sales/assets)
思路: 资产周转率高 = 经营高效 → 买入

# 负债率（Liabilities/Assets）
liabilities/assets
思路: 高杠杆 = 高成长（也高风险）
```

---

## 三、Alpha 开发流程（7 步法）

```
Step 1: 提出假设
  "成交量相对历史均值放大时，股票会有更大价格动量"

Step 2: 找到对应数据字段
  volume, adv20, returns

Step 3: 写出初版表达式
  rank(volume / adv20) * rank(-ts_delta(close, 5))

Step 4: 首次模拟（默认设置）
  Region=USA, Universe=TOP3000, Delay=1, Decay=4, Neutralization=Market

Step 5: 分析结果
  - 查看 PnL 曲线：是否稳定向上？
  - 检查 Sharpe/Fitness：是否达标？
  - 检查年度分布：哪些年份表现差？

Step 6: 迭代优化（见下节）

Step 7: 通过所有 IS 检查 → 提交
```

---

## 四、常见问题与优化策略

### 问题一：Fitness 太低（最常见）

**根本原因**：换手率过高（Turnover > 50%）

```
诊断：Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))
      Sharpe=1.74, Returns=13.58%, Turnover=61.65%
      → Fitness = 1.74 × √(0.1358/0.6165) = 0.82（低于1.0）

修复方案：
1. 增加 Decay（4 → 8 → 12）
   rank(-ts_delta(close, 5)) with Decay=8  → 换手率降低约30%

2. 使用 trade_when 限制交易时机
   trade_when(rank(-ts_delta(close, 5)), volume > ts_mean(volume, 5), 1)

3. 改用低频数据（基本面数据换手率天然低）
   rank(-liabilities/assets)  → 换手率通常 < 5%

4. 使用 hump 忽略小变化
   rank(hump(-returns, 0.005))
```

### 问题二：Sharpe 太低

```
修复方案：
1. 改善信号：组合多个因子
   0.5*rank(-ts_delta(close,20)) + 0.5*rank(-liabilities/assets)

2. 行业中性化：去除行业系统风险
   group_neutralize(rank(-ts_delta(close,20)), sector)

3. 去极值：减少极端权重造成的噪声
   rank(winsorize(ts_std_dev(returns,20), std=3))

4. 更大的 Universe（TOP3000 vs TOP500）
   更多股票 → 更多样本 → 更稳定的 Sharpe

5. 调整 Decay（通常 4~8 范围）
```

### 问题三：权重集中（CONCENTRATED_WEIGHT 失败）

```
修复方案：
1. 设置 Truncation = 0.05（每股最多5%）
2. 使用 rank() 而非原始值（rank 输出均匀分布）
3. 使用 normalize() 归一化权重
4. 增加股票覆盖（ts_backfill 填充 NaN）
```

### 问题四：Sub-Universe Sharpe 不足

```
修复方案：
1. 避免大市值/小市值倾斜
   ❌ rank(-assets)   # 偏向小市值
   ✅ group_rank(-assets, sector)  # 行业内排名，无市值倾斜

2. 对流动性分层处理
   ts_decay_linear(signal, 5) * rank(volume*close) +
   ts_decay_linear(signal, 10) * (1 - rank(volume*close))

3. 提升整体 Sharpe（子 Universe 阈值与总 Sharpe 成比例）
```

### 问题五：自相关过高（SELF_CORRELATION 失败）

```
修复方案：
1. 探索新数据集（替代数据、情绪数据）
2. 使用不同时间窗口（5日动量 vs 20日动量 相关性较低）
3. 加入过滤条件（如仅在特定市场条件下交易）
4. 换 Universe 或 Region（不同池子的 Alpha 相关性低）
```

---

## 五、Alpha 进阶技巧

### 5.1 多因子合成

```
# 等权合并（最简单）
vec_avg(rank(-ts_delta(close,20)), rank(-liabilities/assets))

# 加权合并（根据信号强度）
0.6 * rank(-ts_delta(close, 20)) + 0.4 * rank(-liabilities/assets)

# 动态加权（根据数据可用性）
if_else(is_nan(earnings), rank(-ts_delta(close,20)),
        0.5*rank(-ts_delta(close,20)) + 0.5*rank(-earnings/assets))
```

### 5.2 行业 + 时序组合

```
# 行业内时序排名（双层中性化）
group_rank(ts_rank(operating_income, 252), industry)

# 先行业排名，再截面排名
rank(group_rank(-liabilities/assets, sector))
```

### 5.3 量价关系 Alpha

```
# 量价背离（上涨放量 = 可持续；上涨缩量 = 可能反转）
rank(-ts_corr(rank(volume), rank(close), 20))

# 资金流向
rank(ts_mean(returns * volume, 5))    # 近5日资金净流入

# VWAP 偏离
rank(-(close/vwap - 1))              # 收盘偏离 VWAP 越多 = 回归概率越大
```

### 5.4 时序结合基本面

```
# 营收增速（季度同比）
rank(ts_delta(sales, 63))   # 约63个交易日 ≈ 一个季度

# 资产收益率变化
rank(ts_delta(earnings/assets, 252))  # 一年 ROA 变化

# 动量 + 价值
0.5 * rank(-ts_delta(close, 20)) + 0.5 * rank(earnings/cap)
```

---

## 六、Alpha 质量自检清单

在提交前，检查以下每一项：

```
□ PnL 曲线：整体向上，无长期下跌趋势
□ Sharpe ≥ 1.25（Delay-1）
□ Fitness ≥ 1.0（Delay-1）
□ Turnover：1% ~ 70% 之间
□ 年度 Sharpe：每年正收益（不一定年年高，但应多数年份为正）
□ Drawdown：< 30%（越小越好）
□ Long/Short Count：多空股数接近，各自 > 100 只
□ CONCENTRATED_WEIGHT：通过
□ LOW_SUB_UNIVERSE_SHARPE：通过
□ 假设是否有经济直觉支撑（非随机过拟合）
□ 与已有 Alpha 相关性 < 0.7（SELF_CORRELATION）
```

---

## 七、典型 Alpha 参考设置

| Alpha 类型 | Decay | Neutralization | Truncation | 预期 Turnover |
|-----------|-------|---------------|-----------|--------------|
| 技术/价量 | 6~10 | Market | 0.05~0.08 | 20%~60% |
| 基本面（季度） | 0~4 | Subindustry | 0.05~0.08 | 2%~10% |
| 情绪/分析师 | 4~8 | Industry | 0.05 | 10%~30% |
| 复合因子 | 4~6 | Market/Industry | 0.05 | 15%~40% |

---

*下一篇：[08_API接口与自动化脚本.md](./08_API接口与自动化脚本.md)*
