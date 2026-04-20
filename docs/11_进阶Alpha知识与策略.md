# 11 进阶 Alpha 知识与策略

> 本文档基于 WorldQuant BRAIN 平台官方爬取内容、社区帖子、实测批量结果综合整理，
> 聚焦于**超越入门示例、实际通过提交标准**的进阶知识。

---

## 一、Alpha 模式优先级矩阵（基于实测）

以下优先级来自对 30+ 批次、200+ Alpha 实际模拟结果的统计：

| 优先级 | 模式 | 典型 Fitness | 典型换手率 | 代表表达式 |
|--------|------|-------------|-----------|-----------|
| ⭐⭐⭐ | 基本面比率 rank | 1.3–3.0 | 1–5% | `rank(liabilities/assets)` |
| ⭐⭐⭐ | group_rank + ts_rank 组合 | 1.3–2.0 | 5–10% | `group_rank(ts_rank(oi/equity, 126), sector)` |
| ⭐⭐⭐ | 情绪波动反向 | 1.4–1.9 | 10–25% | `-ts_std_dev(scl12_buzz, 18)` |
| ⭐⭐ | 期权隐含/历史波动比 | 1.2–1.5 | 15–30% | `implied_volatility_call_120/parkinson_volatility_120` |
| ⭐⭐ | ts_zscore + group_rank | 1.0–1.5 | 10–20% | `group_rank(-ts_zscore(ev/cashflow, 63), industry)` |
| ⭐⭐ | 分析师 EPS + 行业中性化 | 1.0–1.5 | 15–25% | `group_rank(ts_rank(est_eps/close, 60), industry)` |
| ⭐ | 纯技术动量/反转 | <1.0 | 30–80% | `rank(-ts_delta(close, 5))` |
| ⭐ | ts_delta（单独使用）| <0.5 | 50–90% | `ts_delta(close, 5)` |

**核心结论**：基本面 + 截面/时序标准化 + 行业中性 = 胜率最高的组合。

---

## 二、深度解析：group_rank + ts_rank 黄金组合

### 2.1 原理

```
group_rank(ts_rank(field, lookback), group_level)
```

- `ts_rank(field, d)`：把当前基本面值与该股自身过去 d 天历史比较，输出 [0,1]
- `group_rank(..., group)`：再在行业/板块内横截面排名，输出 [0,1]

**效果**：
1. 消除了不同公司基本面绝对量级的差异（行业间财务指标差异极大）
2. 同时捕捉了"相对自身历史的改善"信号
3. 换手率保持低位（基本面季度更新）

### 2.2 实测最优参数组合

| 字段 | 最优 lookback | 最优 group | Sharpe | Fitness |
|------|--------------|-----------|--------|---------|
| `operating_income/equity` | 126（半年）| sector | 2.04 | 1.44 |
| `operating_income/equity` | 126 | industry | 2.06 | 1.42 |
| `operating_income/equity` | 150（6个月+）| sector | 1.99 | 1.41 |
| `operating_income/assets` | 126 | sector | 1.75 | 1.14 |
| `operating_income/assets` | 126 | industry | 1.72 | 1.09 |
| `free_cash_flow_reported_value/equity` | 126 | sector | 1.46 | 1.17 |

**关键发现**：
- **126天窗口**（半年）普遍优于 252天（1年），信号更新速度与噪声的最佳平衡
- **sector 级别**中性化略优于 industry（在盈利类因子上）
- `equity` 作为分母比 `assets` 好（股东权益更能反映经营杠杆）

### 2.3 扩展方向

```python
# 1. 加入增长趋势：把绝对值换成变化量
group_rank(ts_rank(ts_delta(equity, 63), 126), sector)
# → fitness 1.25, 换手6.4%

# 2. 收益质量：盈利 + 杠杆 双信号叠加
rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)
# → fitness 1.92 (实测最高！)

# 3. 跨窗口组合（多时间尺度）
group_rank(ts_rank(operating_income/equity, 126), sector) 
  + group_rank(ts_rank(operating_income/equity, 252), sector)
```

---

## 三、情绪数据（Sentiment）进阶应用

### 3.1 scl12_buzz：相对情绪声量

`scl12_buzz` 是 SCL12 数据集的"相对情绪/新闻声量"字段，值越高表示该股当前被市场讨论越多。

**核心洞察（实测验证）**：

> 短期情绪声量的**标准差高**（波动剧烈）→ 投资者注意力不稳定 → **股价往往随后跑输**

```python
# 基础版（官方示例，已验证通过）
-ts_std_dev(scl12_buzz, 10)
# Sharpe=1.81, Fitness=1.60, Turnover=23.5%

# 更优版（实测 Fitness 最高）
-ts_std_dev(scl12_buzz, 18)  
# Sharpe=1.47, Fitness=1.67, Turnover=13.5%  ← Fitness 更高因为换手率更低

-ts_std_dev(scl12_buzz, 25)
# Sharpe=1.44, Fitness=1.66, Turnover=10.3%
```

**参数规律**：
- 窗口从 5 增加到 18：Sharpe 略降但换手率从 39% 降到 13%，Fitness 反升
- 最优窗口约 **15–20天**，在 Sharpe 与换手率间取得最佳 Fitness

**推荐设置**：
```
decay=0, neutralization=SUBINDUSTRY, truncation=0.08, universe=TOP3000
```

### 3.2 snt1 情绪数据集字段

| 字段 | 含义 | 典型用法 |
|------|------|---------|
| `snt1_cored1_score` | 核心情绪分（>5 看涨，<-5 看跌）| `rank(snt1_cored1_score)` |
| `snt1_d1_earningssurprise` | 盈利惊喜指数 | `rank(snt1_d1_earningssurprise)` |
| `snt1_d1_buyrecpercent` | 买入评级占比 | `group_rank(snt1_d1_buyrecpercent, industry)` |
| `snt1_d1_analystcoverage` | 分析师覆盖数量 | 常用于过滤器（低覆盖 = 高不确定性）|

**注意**：
- snt1 数据集覆盖约 2000 支股票（TOP3000 中有空缺），建议用 `pasteurize()` 处理
- 情绪字段换手率天然较高，建议搭配 decay=2~4 降低换手
- 对 TOP1000 或 TOPSP500 测试可提升覆盖率，避免稀疏导致 Weight 检查失败

### 3.3 News Vector 字段（nws12）

新闻数据是**向量字段**，每天每支股票可有多条新闻记录，必须先用 `vec_` 运算符聚合：

```python
# 统计一支股票过去每天的新闻数量 → 新闻密度
vec_count(nws12_afterhsz_120_min)
# 新闻密度高的股票往往在新闻高峰后跟随动量或反转

# 高密度新闻 → 动量/反转效应
rank(vec_count(nws12_afterhsz_120_min))

# 新闻后120分钟平均涨幅 → 信号强度
rank(vec_avg(nws12_afterhsz_120_min))
```

**可用 vec_ 运算符汇总**：

| 运算符 | 描述 |
|--------|------|
| `vec_avg(x)` | 向量均值 |
| `vec_count(x)` | 向量元素数（新闻条数）|
| `vec_sum(x)` | 向量总和 |
| `vec_std_dev(x)` | 向量标准差（分歧度）|
| `vec_max(x)` / `vec_min(x)` | 最大/最小值 |
| `vec_ir(x)` | 信息比率（均值/标准差）|
| `vec_skewness(x)` | 偏度（新闻情绪分布是否偏斜）|
| `vec_kurtosis(x)` | 峰度 |
| `vec_percentage(x, 0.9)` | 第90百分位数 |

---

## 四、期权数据（Options）Alpha 策略

### 4.1 核心数据字段

| 字段 | 含义 |
|------|------|
| `implied_volatility_call_120` | 看涨期权隐含波动率（120日）|
| `implied_volatility_put_120` | 看跌期权隐含波动率（120日）|
| `parkinson_volatility_120` | 历史实际波动率（Parkinson，120日）|

### 4.2 波动率套利策略

**假设**：看涨期权隐含波动率 > 历史波动率 → 市场预期未来更大上行，看涨情绪强

```python
# 已验证通过（Sharpe=1.53, Fitness=1.35）
implied_volatility_call_120 / parkinson_volatility_120

# 推荐设置
settings = {
    "universe": "TOP2000",  # 期权数据流动性要求更高
    "neutralization": "SECTOR",
    "decay": 0,
    "truncation": 0.08
}
```

**扩展变体**：
```python
# 看跌/看涨期权隐含波动率之差（恐慌偏斜）
implied_volatility_put_120 - implied_volatility_call_120
# 值越大 → 保护性需求越高 → 可能看空

# Z-score标准化：消除绝对量级差异
ts_zscore(implied_volatility_call_120 / parkinson_volatility_120, 63)
```

**注意事项**：
- 期权数据覆盖约 TOP2000，用 TOP200 可提升质量但样本量减少
- SECTOR 中性化优于 MARKET（波动率在不同行业差异大）

---

## 五、分析师预测数据（Analyst Estimates）

### 5.1 关键字段

| 字段 | 含义 | 更新频率 |
|------|------|---------|
| `est_eps` | 每股盈利预测 | 每日更新 |
| `est_revenue` | 营收预测 | 每日更新 |
| `est_ebitda` | EBITDA 预测 | 每日更新 |
| `est_fcf` | 自由现金流预测 | 每日更新 |
| `est_ptp` | 分析师目标价 | 每日更新 |
| `etz_eps` | EPS 预测修正量 | 每日更新 |

### 5.2 经典策略：盈利收益率动量

```python
# 官方示例（高优先级）
# 假设：盈利收益率相对历史更高 → 可能被低估
group_rank(ts_rank(est_eps / close, 60), industry)

# 推荐设置
settings = {"decay": 0, "neutralization": "INDUSTRY", "truncation": 0.08}
```

**原理分解**：
1. `est_eps / close`：实时估算盈利收益率（P/E的倒数，基于预测EPS）
2. `ts_rank(..., 60)`：过去60天内今天的收益率排名 → 收益率是否处于历史高位
3. `group_rank(..., industry)`：在行业内再排名 → 消除行业估值差异

### 5.3 目标价与FCF预测相关性策略

```python
# 假设：价格目标与FCF预测高度正相关 → 市场已完全定价 → 做空
-ts_corr(est_ptp, est_fcf, 252)

# 逻辑：当二者同步程度高时，市场已充分预期，未来难超预期
```

### 5.4 分析师修正动量

```python
# EPS 预测修正的时序标准化（分析师上调 → 做多）
ts_zscore(etz_eps, 252)

# 行业内归一化版本
group_rank(ts_zscore(etz_eps, 63), industry)
```

---

## 六、中性化深度指南

中性化决定了 Alpha 在哪个维度上"市场中立"，选择错误会大幅影响 Sharpe。

### 6.1 各层级含义

```
MARKET（市场）
  └── SECTOR（11个GICS板块，如科技、医疗）
        └── INDUSTRY（约24个行业，如半导体、银行）
              └── SUBINDUSTRY（约68个子行业，最细粒度）
```

### 6.2 按数据类型选择中性化

| 数据类型 | 推荐中性化 | 原因 |
|---------|-----------|------|
| 基本面比率（ROE、ROA、P/B等）| SUBINDUSTRY | 行业间财务指标差异极大 |
| 分析师预测（est_eps、est_ptp）| INDUSTRY | 预测在行业内可比 |
| 价格/成交量 | MARKET | 技术信号跨行业通用 |
| 情绪/新闻 | SUBINDUSTRY | 新闻影响在子行业内差异大 |
| 期权波动率 | SECTOR | 波动率在板块间有系统差异 |

### 6.3 group_rank 与 neutralization 的关系

> **重要**：当表达式最外层使用 `group_rank()` 时，设置中的 `neutralization` 应设为 `NONE`，避免双重中性化。

```python
# 正确：表达式内中性化 + 设置中性化=NONE
group_rank(operating_income/assets, industry)
# settings: neutralization=NONE

# 双重中性化（不推荐，会过度处理）
group_rank(operating_income/assets, industry)  
# settings: neutralization=INDUSTRY  ← 避免这样
```

### 6.4 group_neutralize 与 neutralization 的等价性

```python
# 两种等价写法：
# 写法1：operator 中性化
group_neutralize(rank(operating_income/assets), industry)
# settings: neutralization=NONE

# 写法2：settings 中性化
rank(operating_income/assets)
# settings: neutralization=INDUSTRY
```

---

## 七、多因子 Alpha 组合策略

### 7.1 简单加法组合

不同信号维度叠加可提升稳健性：

```python
# 盈利能力 + 杠杆保守性（实测 Fitness=1.92）
rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)

# 解读：
# - ts_rank(oi/equity, 126): 当前盈利能力相对半年历史的排名
# - rank(-equity/assets): 杠杆率低（资本结构保守）的股票
# 两个信号方向不同 → 低相关 → 组合更稳健
```

### 7.2 多数据集组合

```python
# 基本面 + 情绪（不同信号源）
rank(operating_income/assets) + rank(-ts_std_dev(scl12_buzz, 15))

# 分析师 + 基本面
group_rank(ts_rank(est_eps/close, 60), industry) + rank(liabilities/assets)
```

### 7.3 加权组合（scale 操作）

```python
# 用 scale 把多个信号归一化后加权
scale(rank(operating_income/equity)) * 0.6 + scale(-ts_std_dev(scl12_buzz, 15)) * 0.4
```

### 7.4 信号过滤（条件逻辑）

```python
# 仅在低波动率环境下做多高盈利
# （间接实现：用波动率做权重）
rank(operating_income/equity) * rank(-ts_std_dev(returns, 20))
```

---

## 八、如何提升 Sharpe

基于 BRAIN 社区帖"How do you get a higher Sharpe?"的核心建议：

### 8.1 改变截面中性化维度

```
当前: MARKET  →  尝试: SECTOR 或 INDUSTRY
理由: 更精细的中性化去除更多噪声，信号纯度更高
```

### 8.2 调整时间窗口

| 数据类型 | 常见窗口 | 建议方向 |
|---------|---------|---------|
| 基本面 | 252天（1年）| 尝试 126天（半年），信号更新更快 |
| 情绪 | 10天 | 尝试 15–20天，降低换手同时保持信号 |
| 技术 | 20天 | 尝试 5天（短线）或 60天（中线）|

### 8.3 用 ts_rank 代替原始值

```python
# 原始值：受量级影响，跨股票可比性差
rank(operating_income)

# 更好：与自身历史比较后再截面排名
ts_rank(operating_income, 252)
# 或：行业内标准化
group_rank(ts_rank(operating_income, 252), industry)
```

### 8.4 使用 log 变换处理偏态

```python
# 基本面字段通常右偏分布
rank(log(market_cap / book_value))    # P/B ratio，log变换稳定分布

# signed_power 保留符号的幂次变换
signed_power(operating_income / assets, 0.5)  # 接近平方根变换
```

### 8.5 Subinverse Sharpe 不过关时

BRAIN 要求 Alpha 在 TOP1000 子宇宙中也具有足够 Sharpe：

```python
# 策略1：直接用 TOP1000 模拟
settings["universe"] = "TOP1000"

# 策略2：保证信号在大盘股中也有效（避免小票驱动）
# 检查：去掉低流动性股票后 Alpha 是否仍然有信号
```

---

## 九、Fitness 优化系统方法

$$\text{Fitness} = \text{Sharpe} \times \sqrt{\frac{|\text{Returns}|}{\max(\text{Turnover}, 0.125)}}$$

**最大化 Fitness 的两条路径**：

| 路径 | 方法 | 适合数据类型 |
|------|------|-------------|
| 降换手率 | 用基本面数据（季度更新）、增大 decay、延长时序窗口 | 基本面、analyst |
| 提高 Sharpe | 更精细中性化、行业内比较、多因子叠加 | 所有类型 |

**实测 Fitness 对比**：

```
换手率 5% + Sharpe 2.0 → Fitness = 2.0 * sqrt(0.1/0.125) = 1.79  ✅
换手率 40% + Sharpe 2.0 → Fitness = 2.0 * sqrt(0.1/0.40) = 1.00  ⚠️ 边界
换手率 70% + Sharpe 2.0 → Fitness = 2.0 * sqrt(0.1/0.70) = 0.76  ❌ + HIGH_TURNOVER
```

---

## 十、Alpha 多样化与相关性管理

### 10.1 为什么多样化重要

- 平台要求新 Alpha 与现有 Alpha 的**自相关 < 0.7**，或新 Sharpe 比相关 Alpha 高 ≥10%
- 提交大量高度相关的 Alpha 会被拒绝（自相关检查）
- 竞赛中多样化的 Alpha 池可提升组合IR，胜过单个高Sharpe Alpha

### 10.2 实现多样化的方法

**数据维度多样化**：
```python
# 类别一：基本面价值
rank(liabilities/assets)
group_rank(ts_rank(operating_income/equity, 126), sector)

# 类别二：情绪/声量
-ts_std_dev(scl12_buzz, 18)

# 类别三：期权信号
implied_volatility_call_120 / parkinson_volatility_120

# 类别四：分析师
group_rank(ts_rank(est_eps/close, 60), industry)
```

**持仓频率多样化**：

| 类型 | 换手率范围 | 持仓天数（估算）|
|------|-----------|----------------|
| 低频（基本面）| 1–10% | 10–100天 |
| 中频（情绪、分析师）| 10–30% | 3–10天 |
| 高频（技术）| 30–70% | 1–3天 |

### 10.3 因子风险暴露管理

BRAIN 中的主要**因子风险**（来自 Quantcepts 课程）：

| 风险因子 | 来源 | 处理方法 |
|---------|------|---------|
| 市场风险（Beta）| 整体市场涨跌 | MARKET 中性化 |
| 行业风险 | 行业轮动 | SECTOR/INDUSTRY 中性化 |
| 规模因子 | 大盘/小盘效应 | 用 cap 加权或过滤 |
| 价值因子 | 成长/价值轮动 | 确保非单纯 P/B、P/E |
| 动量因子 | 短/中/长期动量 | 避免纯动量信号 |

---

## 十一、有限差分（Finite Differences）技巧

来自 BRAIN 社区 TIPS 帖：使用有限差分可以有效捕捉"变化"信号。

### 11.1 一阶差分（变化量）

```python
# 直接差分（高换手）
ts_delta(operating_income, 63)     # 一个季度内盈利的绝对变化

# 相对差分（增长率）
ts_delta(operating_income, 63) / ts_delay(operating_income, 63)

# 标准化差分（z-score + 差分）
ts_zscore(ts_delta(operating_income, 63), 252)
```

### 11.2 二阶差分（加速度）

```python
# 盈利加速度：连续两期增长率的变化
ts_delta(ts_delta(operating_income, 63), 63)

# 动量加速度：价格动量是否在加速
ts_delta(ts_mean(returns, 20), 5)
```

### 11.3 有限差分 + 行业中性化

```python
# 盈利增长的行业内排名（最实用版）
group_rank(ts_rank(ts_delta(equity, 63), 126), sector)
# Sharpe=1.72, Fitness=1.25（实测通过）

# 盈利增长率的行业内排名
group_rank(ts_rank(ts_delta(equity, 63) / ts_delay(equity, 63), 126), sector)
# Sharpe=1.64, Fitness=1.11
```

---

## 十二、技术指标类 Alpha 的正确打开方式

纯技术 Alpha（`ts_delta(close, 5)`等）几乎必然无法通过 Fitness，需要改造：

### 12.1 高换手率的解决方案

```python
# 问题：ts_delta(close, 5) → 换手率 70%+ → Fitness 崩溃
# 方案一：延长窗口（5→20→60）
rank(ts_mean(returns, 60) - ts_mean(returns, 252))  # 动量减长期均值

# 方案二：增加 decay（至少 decay=8）
settings["decay"] = 8  # 大幅降低换手率

# 方案三：改用 ts_rank 代替 ts_delta
ts_rank(close, 252)   # 当前价位在52周内的历史分位 → 换手率约5-15%

# 方案四：结合基本面过滤
rank(ts_rank(close, 252)) * rank(operating_income/assets)  # 技术 × 质量
```

### 12.2 有效技术信号模板

| 策略思路 | 表达式 | 预期 Turnover |
|---------|--------|--------------|
| 52周价格分位 | `ts_rank(close, 252)` | 5–15% |
| 相对强度（RSI-like）| `ts_rank(returns, 20)` | 15–30% |
| 量价关系 | `ts_corr(volume, close, 20)` | 20–40% |
| 波动率聚类 | `-ts_std_dev(returns, 20)` | 20–40% |
| 低波动率异常 | `rank(-ts_std_dev(returns, 252))` | 3–8% |

---

## 十三、统计学方法在 Alpha 研究中的应用

来自 BRAIN TIPS "Statistics in Alpha Research"：

### 13.1 Z-score 标准化

```python
# 基础 z-score：消除量级差异，但不跨股票比较
ts_zscore(field, lookback)   # = (x - mean(x, d)) / std(x, d)

# 应用场景：标准化后使不同指标可以合理加总
ts_zscore(operating_income, 252) + ts_zscore(free_cash_flow, 252)
```

### 13.2 相关性信号

```python
# 两个时序变量的滚动相关（提取关系变化）
ts_corr(volume, returns, 20)   # 量价相关：量涨价涨 vs 量涨价跌

# 负相关：当两个信号背离时交易
-ts_corr(est_ptp, est_fcf, 252)   # 目标价与FCF预测背离
```

### 13.3 截面统计

```python
# 在截面（同一天，所有股票间）标准化
rank(field)                     # 均匀分布在 [0,1]
group_rank(field, industry)     # 行业内均匀分布

# 截面 z-score（可用 indneutralize 近似）
indneutralize(field, market)    # 减去截面均值（非精确 z-score）
```

---

## 十四、IQC 2026 竞赛策略建议

当前竞赛（IQC 2026 Stage 1，至 2026-05-19）评分规则：
- IS Score（Delay-1）：覆盖大部分分数
- D0 Score + D1 Score 两个组件
- 团队排名 7702（用户 JA60238）

### 14.1 竞赛提升优先级

1. **扩大通过的 Alpha 数量**（每额外通过一个提升分数）
2. **避免高度相关**（提交的 Alpha 池内自相关要 <0.7）
3. **覆盖多数据类别**（基本面、情绪、期权、分析师各有代表）

### 14.2 快速扩充 Alpha 池的系统方法

```python
# 框架：固定有效模式，遍历字段组合
base_pattern = "group_rank(ts_rank({numerator}/{denominator}, {lookback}), {group})"

# 可替换的基本面 numerator
numerators = [
    "operating_income", "net_income", "ebitda", "free_cash_flow_reported_value",
    "gross_profit", "sales", "cash_and_equivalents"
]

# 可替换的 denominator（规模化）
denominators = ["assets", "equity", "revenue", "market_cap"]

# 可替换的 lookback
lookbacks = [63, 95, 126, 150, 175, 252]

# 可替换的 group
groups = ["sector", "industry", "subindustry"]
```

### 14.3 单 Alpha 最大化 Fitness 的调优流程

```
1. 确定基础表达式（来自已知有效模式）
2. 模拟默认设置 → 记录 baseline
3. 调 neutralization：SECTOR / INDUSTRY / SUBINDUSTRY
4. 调 lookback：63 / 95 / 126 / 150 / 175 / 252
5. 调 truncation：0.05 / 0.08
6. 取 Fitness 最高的组合提交
```

---

## 十五、AI 辅助量化研究

来自 Quantcepts 第 19 集"How Quants Can Partner with AI"：

### 15.1 AI 的合理使用场景

| 用途 | 具体操作 |
|------|---------|
| 扩展 Alpha 想法 | 基于一个已通过的 Alpha，让 AI 生成变体 |
| 理解数据字段 | 输入字段描述，让 AI 解释经济含义 |
| 调试表达式 | 粘贴报错信息，让 AI 修复语法 |
| 生成假设 | 描述市场现象，让 AI 提出可测试的量化假设 |

### 15.2 人机协作工作流

```
研究员：提供领域知识 + 验证经济逻辑
   ↓
AI：快速生成 Alpha 变体 + 代码调试 + 文档总结
   ↓  
BRAIN：实际模拟验证
   ↓
研究员：解读结果，选择有效 Alpha，提交
```

**重要提示**：AI 不能替代对数据字段含义的理解和对模拟结果的解读，需要结合量化领域知识判断 Alpha 是否存在**过拟合**或**逻辑漏洞**。

---

## 附：高优先级 Alpha 速查表

### 基于实测通过的 Alpha（Fitness ≥ 1.0）

| 排名 | 表达式 | Fitness | Sharpe | 换手率 | 类别 |
|------|--------|---------|--------|--------|------|
| 1 | `rank(ts_rank(operating_income/equity, 126)) + rank(-equity/assets)` | 1.92 | 2.09 | 5.0% | 基本面组合 |
| 2 | `-ts_std_dev(scl12_buzz, 18)` | 1.67 | 1.47 | 13.5% | 情绪 |
| 3 | `-ts_std_dev(scl12_buzz, 25)` | 1.66 | 1.44 | 10.3% | 情绪 |
| 4 | `-ts_std_dev(scl12_buzz, 10)` | 1.60 | 1.81 | 23.5% | 情绪 |
| 5 | `group_rank(ts_rank(operating_income/equity, 150), sector)` | 1.44 | 2.04 | 6.7% | 基本面 |
| 6 | `group_rank(ts_rank(operating_income/equity, 126), industry)` | 1.42 | 2.06 | 7.2% | 基本面 |
| 7 | `group_rank(ts_rank(operating_income/equity, 175), sector)` | 1.41 | 1.98 | 6.4% | 基本面 |
| 8 | `group_rank(ts_rank(...ts_delta(equity,63)..., 126), sector)` | 1.38 | 1.83 | 6.7% | 成长 |
| 9 | `implied_volatility_call_120/parkinson_volatility_120` | 1.35 | 1.53 | 25.3% | 期权 |
| 10 | `rank(liabilities/assets)` | 1.35 | 1.51 | 1.5% | 基本面 |

### 推荐设置

| Alpha 类型 | decay | neutralization | truncation |
|-----------|-------|----------------|-----------|
| 基本面比率 | 0 | SUBINDUSTRY | 0.08 |
| group_rank 基本面 | 0 | NONE | 0.08 |
| 情绪（scl12）| 0 | SUBINDUSTRY | 0.08 |
| 期权波动率 | 0 | SECTOR | 0.08 |
| 分析师预测 | 0 | INDUSTRY | 0.08 |
| 技术/价格 | 4–8 | MARKET | 0.05 |
