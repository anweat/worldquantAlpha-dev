# 02 Fast Expression 语言完全指南

## 一、什么是 Fast Expression

**Fast Expression（FE）** 是 WorldQuant BRAIN 平台独有的**向量化表达式语言**，专为股票 Alpha 开发设计。它的核心思想是：

> 将"一组股票在一段时间内的数据矩阵"，通过数学运算，转化为"每只股票的持仓权重向量"。

Fast Expression 类似电子表格公式，但它操作的是**二维矩阵**（行=日期，列=股票），而非单个单元格。

---

## 二、基础概念：标量、向量与矩阵

| 概念 | 说明 | 示例 |
|------|------|------|
| **标量（Scalar）** | 单个数值 | `5`, `0.5`, `252` |
| **向量（Vector）** | 某一天所有股票的数值 | `close`（今日收盘价列） |
| **时间序列** | 某只股票历史上所有天的数据 | `close`（某股票的历史收盘价行） |
| **矩阵** | 所有股票所有天的数据 | `close`（完整收盘价矩阵） |

FE 表达式最终输出的是**向量**——每只股票当天的一个数值，代表其持仓权重。

---

## 三、数据字段（Data Fields）

数据字段是 FE 表达式的输入原料，命名格式类似变量名。

### 常用价格/量价字段

| 字段 | 含义 |
|------|------|
| `close` | 收盘价（最常用） |
| `open` | 开盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `vwap` | 成交量加权平均价格（Volume Weighted Average Price） |
| `volume` | 成交量（股数） |
| `adv5` / `adv20` | 最近 5/20 天平均成交金额（Amount） |
| `returns` | 当日收益率 `= (close - prev_close) / prev_close` |
| `cap` | 市值（Market Capitalization） |

### 基本面字段示例

| 字段 | 含义 |
|------|------|
| `assets` | 总资产 |
| `liabilities` | 总负债 |
| `sales` | 营业收入 |
| `earnings` | 净利润 |
| `dividends` | 股息 |
| `inventory` | 存货 |
| `debt` | 负债 |

> **提示**：平台提供 85,000+ 数据字段，使用 Data Explorer 页面搜索。

---

## 四、表达式基础语法

### 算术运算

```
close + open           # 加
close - open           # 减
close * volume         # 乘
close / open           # 除
close ^ 2              # 幂运算（Python 里是 ** ，FE 里用 ^）
abs(returns)           # 绝对值
log(close)             # 自然对数
sqrt(volume)           # 平方根
sign(returns)          # 符号函数：正→1，负→-1，零→0
```

### 比较运算

```
close > open           # 收盘 > 开盘 → 1，否则 0
returns >= 0           # 今日上涨？
close == vwap          # 等于
close != vwap          # 不等于
```

### 条件运算

```
if_else(close > open, 1, -1)          # 阳线做多，阴线做空
if_else(returns > 0, volume, -volume) # 上涨时做多量能，下跌做空
```

---

## 五、核心运算符详解

### 5.1 横截面运算符（Cross-Sectional）

在**同一天**对**所有股票**计算排名/标准化。

```
rank(close)              # 收盘价的截面排名，结果 ∈ (0,1)
rank(-returns)           # 按收益率降序排名（跌幅大的 rank 高）
zscore(close)            # 截面 Z-score 标准化：(x - mean) / std
normalize(x)             # 截面归一化：使绝对权重之和 = 1
scale(x, scale=1)        # 使截面绝对值之和 = scale
winsorize(x, std=4)      # 截尾：将极值截断到 ±4σ
quantile(x, driver="close", nbins=5)  # 分位分桶
```

**rank 是最常用的 Alpha 构建工具**，输出 0-1 之间的均匀分布：
- `rank(x) ≈ 0`：该指标在同期所有股票中最低
- `rank(x) ≈ 1`：该指标在同期所有股票中最高

### 5.2 时间序列运算符（Time Series）

对**单只股票**的**历史数据**做时间维度的计算。

```
ts_delta(close, 5)       # 今日收盘 - 5天前收盘（5日价格变化）
ts_mean(close, 10)       # 最近 10 日收盘价均值（10日均线）
ts_std_dev(returns, 20)  # 最近 20 日收益率标准差（20日波动率）
ts_rank(volume, 30)      # 成交量在最近 30 天中的排名 ∈ (0,1)
ts_zscore(close, 20)     # 最近 20 日的 Z-score
ts_delay(close, 1)       # 1日前的收盘价（昨收盘）
ts_corr(close, volume, 20)   # 最近 20 日收盘价与成交量的相关系数
ts_regression(returns, benchmark_returns, 60)  # 60日 β 回归
ts_sum(volume, 5)        # 最近 5 日成交量总和
ts_product(returns+1, 5) # 最近 5 日收益率的乘积（复利）
ts_decay_linear(x, 10)   # 线性衰减：近期权重大，远期权重小
ts_arg_max(close, 20)    # 最近 20 日最高价在哪天（时间位置）
ts_arg_min(close, 20)    # 最近 20 日最低价在哪天（时间位置）
ts_scale(x, 1)           # 使时间序列最大绝对值为 1
ts_covariance(x, y, 20)  # 最近 20 日协方差
ts_quantile(x, 0.9, 20)  # 最近 20 日的 90% 分位数
ts_backfill(x, 5)        # 向前填充 NaN（最多追溯 5 天）
ts_count_nans(x, 10)     # 最近 10 天中 NaN 的数量
```

### 5.3 组别运算符（Group）

在**同一天**的**特定组内**（如行业、市场）做运算，实现**行业中性化**。

```
group_rank(x, sector)         # 在同行业内排名
group_neutralize(x, sector)   # 减去同行业均值 → 行业中性化
group_zscore(x, sector)       # 同行业内 Z-score 标准化
group_mean(x, sector)         # 同行业均值
group_scale(x, sector)        # 同行业内缩放
group_backfill(x, sector, 5)  # 用同行业值填充 NaN
```

**常用分组字段**：`sector`（行业板块）、`market`（交易所）、`subindustry`

### 5.4 变换运算符（Transformational）

```
bucket(x, range="0,1,10")     # 将 x 的值分成 10 个桶（分位分桶）
trade_when(x, cond, delay=1)  # 只在 cond 为 True 时更新持仓
```

### 5.5 向量运算符（Vector）

```
vec_sum(a, b, c)      # 多个字段逐元素求和
vec_avg(a, b, c)      # 多个字段逐元素求平均
```

---

## 六、常见 Alpha 模式

### 6.1 动量（Momentum）

价格趋势延续。

```
# 5日价格动量
rank(-ts_delta(close, 5))

# 20日收益率动量
rank(ts_mean(returns, 20))

# 多时间周期动量
rank(-ts_delta(close, 20)) + rank(-ts_delta(close, 5))
```

### 6.2 均值回归（Mean Reversion）

偏离均值后回归。

```
# 短期 Z-score 回归
rank(-ts_zscore(close, 20))

# VWAP 偏离回归
rank(-(close/vwap - 1))

# 量价背离回归
rank(-ts_corr(close, volume, 10))
```

### 6.3 基本面因子（Fundamental）

用财务数据选股。

```
# 低负债率（价值因子）
rank(-liabilities/assets)

# 高营收增长
rank(ts_delta(sales, 4))  # 季度营收变化

# 高利润率
rank(earnings/sales)
```

### 6.4 行业中性

```
# 行业内低负债率
group_neutralize(rank(-liabilities/assets), sector)

# 行业内动量
group_rank(rank(-ts_delta(close, 20)), sector)
```

### 6.5 复合因子

```
# 价值 + 动量复合
0.5 * rank(-liabilities/assets) + 0.5 * rank(-ts_delta(close, 20))

# 量价异动
rank(-ts_corr(rank(volume), rank(close), 10))
```

---

## 七、Alpha 表达式注意事项

### ① 避免超前偏差（Look-ahead Bias）

超前偏差是回测中最危险的错误：使用了当时无法获得的未来数据。

- **Delay=1**（推荐）：用 T-1 日数据决定 T 日持仓，T 日收盘时结算
- **Delay=0**（高风险）：用 T 日数据决定 T 日持仓，仅适合日内策略

```
# 安全（Delay=1）：用昨天的信号今天交易
rank(-ts_delta(close, 5))    # close 是 T-1 的数据

# 危险：如果基本面数据发布时间不确定，应加 delay
ts_delay(earnings, 1)        # 确保用的是上个报告期数据
```

### ② NaN 处理

```
ts_backfill(x, 5)           # 用最近有效值填充，最多向前 5 天
group_backfill(x, sector)   # 用同行业均值填充 NaN
is_nan(x)                   # 检查是否为 NaN，返回 0/1
```

### ③ 标量与向量兼容

FE 自动广播标量到向量尺寸：
```
close * 2           # OK：2 自动扩展到所有股票
close + 1.5         # OK
```

### ④ 链式运算

```
# 正确：先计算内层，再排名
rank(-ts_delta(close, 5))

# 分步理解：
step1 = ts_delta(close, 5)    # 每只股票 5 日价格变化
step2 = -step1                 # 取负（价格下跌 → 高值）
step3 = rank(step2)            # 截面排名 → 最终权重
```

---

## 八、字段类型与频率

| 类型 | 更新频率 | 字段示例 |
|------|----------|---------|
| Price/Volume | 日频 | `close`, `volume`, `vwap` |
| Fundamental | 季度/年度 | `assets`, `earnings`, `sales` |
| Analyst | 不定期 | 预测数据 |
| Technical | 日频衍生 | `adv5`, `cap` |
| Alternative | 日频/月频 | 新闻情绪、搜索量等 |

---

*下一篇：[03_运算符完整参考.md](./03_运算符完整参考.md)*
