# 03 运算符完整参考手册

> 数据来源：WorldQuant BRAIN API `/operators?limit=200`，共 66 个运算符，分 7 大类别。

## 一、算术运算符（Arithmetic）— 15 个

这些运算符对数值进行基本数学运算，适用于价格、成交量等所有数值字段。

| 运算符 | 语法 | 说明 |
|--------|------|------|
| `add` | `add(x, y, filter=false)` 或 `x + y` | 逐元素加法。`filter=true` 时将 NaN 视为 0 |
| `subtract` | `subtract(x, y, filter=false)` 或 `x - y` | 逐元素减法。`filter=true` 时将 NaN 视为 0 |
| `multiply` | `multiply(x, y, ..., filter=false)` 或 `x * y` | 逐元素乘法。支持多个输入 |
| `divide` | `divide(x, y)` 或 `x / y` | 逐元素除法 |
| `abs` | `abs(x)` | 绝对值 |
| `log` | `log(x)` | 自然对数（常用于正值数据压缩） |
| `sqrt` | `sqrt(x)` | 非负平方根，等价于 `power(x, 0.5)` |
| `power` | `power(x, y)` | x 的 y 次方 |
| `signed_power` | `signed_power(x, y)` | 保留 x 符号的幂运算（适用于有正负值的数据） |
| `sign` | `sign(x)` | 符号函数：正→+1，负→-1，零→0，NaN→NaN |
| `reverse` | `reverse(x)` | 取负，等价于 `-x` |
| `inverse` | `inverse(x)` | 取倒数，等价于 `1/x` |
| `min` | `min(x, y, ...)` | 逐元素最小值 |
| `max` | `max(x, y, ...)` | 逐元素最大值 |
| `densify` | `densify(x)` | 移除稀疏结构，将稀疏数据转为密集表示 |

### 示例

```
# 价格变化率
(close - ts_delay(close, 1)) / ts_delay(close, 1)

# 用 returns 代替（等价）
returns

# 量价指数
log(volume) * sign(returns)

# 真实波动幅度（近似）
max(high - low, abs(high - ts_delay(close, 1)), abs(low - ts_delay(close, 1)))
```

---

## 二、逻辑运算符（Logical）— 11 个

用于条件判断，返回值为 0 或 1（或 NaN）。

| 运算符 | 语法 | 说明 |
|--------|------|------|
| `and` | `and(x, y)` | 逻辑与：两者均非零且非 NaN 时返回 1 |
| `or` | `or(x, y)` | 逻辑或：任一非零且非 NaN 时返回 1 |
| `not` | `not(x)` | 逻辑非：x=0 或 NaN 时返回 1，否则返回 0 |
| `if_else` | `if_else(cond, x, y)` | 条件选择：cond 非零时取 x，否则取 y |
| `equal` | `x == y` | 等于：相等返回 1，否则返回 0 |
| `not_equal` | `x != y` | 不等于 |
| `greater` | `x > y` | 大于 |
| `greater_equal` | `x >= y` | 大于等于 |
| `less` | `x < y` | 小于 |
| `less_equal` | `x <= y` | 小于等于 |
| `is_nan` | `is_nan(x)` | 检查是否为 NaN：是则返回 1，否则返回 0 |

### 示例

```
# 阳线（收盘 > 开盘）时做多，阴线做空
if_else(close > open, 1, -1)

# 成交量放大时做多
if_else(volume > ts_mean(volume, 20), rank(-returns), 0)

# 过滤掉 NaN 数据
if_else(is_nan(earnings), 0, rank(-earnings))

# 组合条件：价格上涨且成交量放大
and(returns > 0, volume > ts_mean(volume, 20))
```

---

## 三、时间序列运算符（Time Series）— 24 个

对**单只股票的历史时间窗口**进行计算。参数 `d` 为回望天数（lookback window）。

| 运算符 | 语法 | 说明 |
|--------|------|------|
| `ts_delay` | `ts_delay(x, d)` | d 天前的值（时间延迟） |
| `ts_delta` | `ts_delta(x, d)` | 今日值 - d 天前的值（差分） |
| `ts_mean` | `ts_mean(x, d)` | 最近 d 天均值（移动平均） |
| `ts_sum` | `ts_sum(x, d)` | 最近 d 天求和 |
| `ts_std_dev` | `ts_std_dev(x, d)` | 最近 d 天标准差（波动率） |
| `ts_zscore` | `ts_zscore(x, d)` | 最近 d 天 Z-score 标准化 |
| `ts_rank` | `ts_rank(x, d, constant=0)` | 当前值在最近 d 天中的排名 ∈ (0,1) |
| `ts_corr` | `ts_corr(x, y, d)` | 最近 d 天 x 与 y 的相关系数 |
| `ts_covariance` | `ts_covariance(y, x, d)` | 最近 d 天协方差 |
| `ts_regression` | `ts_regression(y, x, d, lag=0, rettype=0)` | 线性回归（rettype: 0=β, 1=α, 2=残差, 3=预测, 4=R²） |
| `ts_decay_linear` | `ts_decay_linear(x, d, dense=false)` | 线性衰减加权均值（近期权重大） |
| `ts_product` | `ts_product(x, d)` | 最近 d 天乘积（适用于复利计算） |
| `ts_scale` | `ts_scale(x, d, constant=0)` | 时间序列缩放，使最大绝对值为指定值 |
| `ts_quantile` | `ts_quantile(x, d, driver="gaussian")` | 最近 d 天的分位数排名 |
| `ts_arg_max` | `ts_arg_max(x, d)` | 最近 d 天最大值所在的时间位置（天数） |
| `ts_arg_min` | `ts_arg_min(x, d)` | 最近 d 天最小值所在的时间位置（天数） |
| `ts_av_diff` | `ts_av_diff(x, d)` | 当前值与最近 d 天均值的差 |
| `ts_backfill` | `ts_backfill(x, lookback=d, k=1)` | 向前回溯填充 NaN（最多 d 天） |
| `ts_count_nans` | `ts_count_nans(x, d)` | 最近 d 天中 NaN 的数量 |
| `ts_step` | `ts_step(1)` | 生成时间步序列（第 1 天→1，第 2 天→2，...） |
| `hump` | `hump(x, hump=0.01)` | 忽略小于阈值的变化（防止过度交易） |
| `kth_element` | `kth_element(x, d, k, ignore="NaN")` | 最近 d 天中第 k 小的值 |
| `last_diff_value` | `last_diff_value(x, d)` | 最近 d 天内最后一次与当前值不同的值 |
| `days_from_last_change` | `days_from_last_change(x)` | 距最近一次变化的天数 |

### ts_regression 的 rettype 参数

```
rettype = 0  →  回归系数 β（斜率）
rettype = 1  →  截距 α
rettype = 2  →  残差（实际值 - 预测值）
rettype = 3  →  预测值
rettype = 4  →  R²（决定系数）
```

### 时间序列运算符示例

```
# 20 日移动平均线偏离度
(close - ts_mean(close, 20)) / ts_mean(close, 20)

# 20 日历史波动率（年化）
ts_std_dev(returns, 20) * sqrt(252)

# 5 日动量
ts_delta(close, 5)

# 量价相关系数（负相关 = 异常）
rank(-ts_corr(rank(volume), rank(close), 10))

# 与市场的 Beta（60日）
ts_regression(returns, benchmark_returns, 60, rettype=0)

# 线性衰减动量（近期更重要）
ts_decay_linear(returns, 20)
```

---

## 四、截面运算符（Cross Sectional）— 6 个

在**同一天**对**所有股票**做截面计算，输出相对排名或归一化值。

| 运算符 | 语法 | 说明 |
|--------|------|------|
| `rank` | `rank(x, rate=2)` | 截面排名，结果均匀分布在 (0, 1)。rate 控制 NaN 处理 |
| `zscore` | `zscore(x)` | 截面 Z-score：`(x - mean) / std` |
| `normalize` | `normalize(x, useStd=false, limit=0.0)` | 截面归一化：绝对值之和 = 1 |
| `scale` | `scale(x, scale=1, longscale=1, shortscale=1)` | 截面缩放：绝对值之和 = scale |
| `winsorize` | `winsorize(x, std=4)` | 截尾：将极端值截断至 ±std 倍标准差 |
| `quantile` | `quantile(x, driver="gaussian", sigma=1.0)` | 截面分位数排名，输出满足指定分布 |

### rank 详解

`rank(x)` 是 Alpha 开发中**最核心**的运算符：

- 输出 0~1 之间均匀分布的值
- **最小值** → rank ≈ 0（做空候选）
- **最大值** → rank ≈ 1（做多候选）
- 自动处理跨股票的比较，无需关心绝对值尺度

```
# 收盘价排名（贵的股票持仓高）
rank(close)

# 反转：价格低的 rank 高（价值投资风格）
rank(-close)

# 先做时序处理，再做截面排名
rank(ts_zscore(close, 20))
```

### 截面运算符示例

```
# 标准化权重（用 normalize）
normalize(-ts_delta(close, 5))

# 去极值（先 winsorize 再 rank）
rank(winsorize(ts_std_dev(returns, 20), std=3))

# 使多空资金对称（scale）
scale(rank(returns) - 0.5)
```

---

## 五、组别运算符（Group）— 6 个

在**同一天**的**特定组别内**（如行业 `sector`）做运算，实现**行业中性化**或**组内排名**。

| 运算符 | 语法 | 说明 |
|--------|------|------|
| `group_rank` | `group_rank(x, group)` | 组内排名 |
| `group_neutralize` | `group_neutralize(x, group)` | 减去组内均值（行业中性化） |
| `group_zscore` | `group_zscore(x, group)` | 组内 Z-score |
| `group_scale` | `group_scale(x, group)` | 组内缩放 |
| `group_mean` | `group_mean(x, weight, group)` | 组内加权均值（`weight` 可为 1） |
| `group_backfill` | `group_backfill(x, group, d, std=4.0)` | 用组内值填充 NaN（最多回溯 d 天） |

### 常用 group 字段

| 字段 | 含义 |
|------|------|
| `sector` | 行业板块（GICS 一级，11 个） |
| `industry` | 行业（GICS 二级） |
| `subindustry` | 子行业（GICS 三级） |
| `market` | 交易所（NYSE、NASDAQ 等） |

### 组别运算符示例

```
# 行业中性化的价格动量
group_neutralize(rank(-ts_delta(close, 20)), sector)

# 行业内低负债率选股
group_rank(-liabilities/assets, sector)

# 行业内 Z-score 标准化
group_zscore(ts_std_dev(returns, 20), sector)

# 填充财务数据空值（用行业均值）
group_backfill(earnings, sector, 5)
```

---

## 六、变换运算符（Transformational）— 2 个

### bucket

```
bucket(rank(x), range="0,1,0.1", skipBoth=False, NaNGroup=False)
bucket(rank(x), buckets="2,5,6,7,10", skipBoth=False, NaNGroup=False)
```

将排名值分入离散化的桶（bins）：
- `range="0,1,0.1"` → 从 0 到 1，步长 0.1（创建 10 个桶）
- `buckets="2,5,6,7,10"` → 按指定边界分桶
- `skipBoth=True` → 跳过最高和最低桶（只用中间的）
- `NaNGroup=True` → 将 NaN 单独归为一个桶

```
# 将动量信号分为 5 档
bucket(rank(-ts_delta(close, 20)), range="0,1,0.2")
```

### trade_when

```
trade_when(x, cond, delay=1)
```

只有当 `cond` 为 True 时，才用 `x` 更新持仓。条件为 False 时保持上一个持仓不变。

```
# 只在成交量放大时交易（减少无效交易）
trade_when(rank(-returns), volume > ts_mean(volume, 20), 1)

# 只在月末交易（换手率极低）
trade_when(rank(earnings/assets), ts_step(1) % 21 == 0, 1)
```

---

## 七、向量运算符（Vector）— 2 个

对**多个字段**进行逐元素合并。

| 运算符 | 语法 | 说明 |
|--------|------|------|
| `vec_sum` | `vec_sum(x)` | 将多字段逐元素求和 |
| `vec_avg` | `vec_avg(x)` | 将多字段逐元素求平均 |

```
# 多因子等权合并
vec_avg(rank(-ts_delta(close, 5)), rank(-liabilities/assets), rank(earnings/sales))
```

---

## 八、运算符适用范围

| 适用范围 | 说明 |
|----------|------|
| `REGULAR` | 适用于普通 Alpha（所有运算符均支持） |

部分高级运算符（如 `ts_regression` 的 `rettype=4`）仅在高权限账户可用。

---

## 九、运算符选择速查

| 我想做什么 | 推荐运算符 |
|-----------|-----------|
| 截面排名 | `rank(x)` |
| 移动平均 | `ts_mean(x, d)` |
| 价格变化 | `ts_delta(x, d)` |
| 历史波动率 | `ts_std_dev(returns, d)` |
| 时间序列排名 | `ts_rank(x, d)` |
| 行业中性化 | `group_neutralize(x, sector)` |
| 行业内排名 | `group_rank(x, sector)` |
| 条件筛选 | `if_else(cond, x, y)` |
| 去极值 | `winsorize(x, std=4)` |
| 填充空值 | `ts_backfill(x, d)` / `group_backfill(x, g, d)` |
| 多因子合并 | `vec_avg(x, y, z)` 或加权求和 |
| 量价相关 | `ts_corr(rank(volume), rank(close), d)` |
| 控制换手率 | `trade_when(x, cond)` / `hump(x)` |

---

*下一篇：[04_模拟设置详解.md](./04_模拟设置详解.md)*
