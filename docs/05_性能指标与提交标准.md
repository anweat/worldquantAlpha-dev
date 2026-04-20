# 05 性能指标解读与提交标准

> 本文档详解 Alpha 模拟结果中的每个性能指标含义，以及提交 Alpha 必须通过的所有检查项。

---

## 一、核心性能指标

### 1.1 Sharpe Ratio（夏普比率）

Sharpe 是衡量 Alpha **风险调整后收益一致性**的最核心指标。

**公式**：
```
IR = mean(daily_PnL) / std_dev(daily_PnL)   # 信息比率（日维度）
Sharpe = IR × √252 ≈ 15.87 × IR              # 年化版本（252 = 年交易日数）
```

| Sharpe | 含义 |
|--------|------|
| < 1.0 | 较差，不足以提交 |
| 1.25~1.5 | Delay-1 最低提交线以上 |
| 1.5~2.0 | Good |
| 2.0~2.5 | Excellent |
| > 2.5 | Spectacular |

**理解 Sharpe**：
- 高 Sharpe 不代表高收益，代表**收益稳定**（每日盈亏波动小）
- Sharpe = 2 意味着年化收益约是年化波动率的 2 倍
- BRAIN 中的 Sharpe 基于**日收益率序列**计算，与某些市场定义略有不同

---

### 1.2 Fitness（综合评分）

Fitness 是 BRAIN 平台的**综合质量分**，综合了收益率、换手率和 Sharpe。

**公式**：
```
Fitness = Sharpe × √( |Returns| / max(Turnover, 0.125) )
```

| Fitness | 评级 | 含义（Delay-1） |
|---------|------|----------------|
| > 2.5 | **Spectacular** | 极优秀 |
| > 2.0 | **Excellent** | 优秀 |
| > 1.5 | **Good** | 良好 |
| > 1.0 | **Average** | 一般（最低提交线） |
| ≤ 1.0 | **Needs Improvement** | 不足，无法提交 |

**Delay-0 对应 Fitness 标准（更高）**：
- > 3.25 Spectacular / > 2.6 Excellent / > 1.95 Good / > 1.3 Average

**优化 Fitness 的方法**：
- 提升 Sharpe（改善信号质量）
- 提升 Returns（增加绝对收益）
- 降低 Turnover（减少交易频率）
- ⚠️ 三者通常互相制约，需要平衡优化

---

### 1.3 Returns（年化收益率）

```
Returns = 年化 PnL / (Book Size / 2) × 100%
        = 年化 PnL / $10,000,000 × 100%
```

- Book Size 固定 $20M，但计算基准为 **$10M**（假设 1:1 杠杆）
- 利润不再投资，亏损由现金注入补足
- 通常期望 Returns ≥ 10% 的 Alpha 具有一定价值

---

### 1.4 Turnover（换手率）

```
Daily Turnover = 当日交易金额 / Book Size
```

| Turnover | 评估 |
|----------|------|
| < 1% | 太低，信号无效（LOW_TURNOVER 检查失败） |
| 1%~20% | 低换手，适合基本面 Alpha |
| 20%~50% | 中等换手，大多数技术型 Alpha |
| 50%~70% | 高换手，接近上限 |
| > 70% | 太高（HIGH_TURNOVER 检查失败） |

**降低换手率的方法**：
- 增大 Decay 值（平滑持仓变化）
- 使用 `trade_when()` 限制交易时机
- 使用 `hump()` 忽略小变化
- 使用更慢的信号（季度数据 vs 日频数据）

---

### 1.5 Margin（利润率）

```
Margin = PnL / 总交易额
       = 每交易 1 美元获得的利润
```

Margin 衡量交易效率，高 Margin + 高 Turnover 理论上获得更高收益，但实际中需要在两者间取得平衡。

---

### 1.6 Drawdown（最大回撤）

```
Drawdown = 从峰值到谷值的最大 PnL 下跌 / ($10M 基准)
```

好的 Alpha 应具备**最小化 Drawdown**（保持 PnL 曲线平稳上升），Drawdown 大意味着策略存在较大风险敞口或过拟合。

---

### 1.7 Long/Short Count（多/空股票数量）

- `longCount`：每日做多的股票数量
- `shortCount`：每日做空的股票数量

理想情况：多空数量接近，且均在几百只以上（对于 TOP3000 Universe 而言）。

---

## 二、提交前检查项（IS Checks）

提交 Alpha 前，系统对以下 8 项进行自动检查，**全部通过才能提交**：

### Check 1：LOW_SHARPE（夏普过低）

| 参数 | Delay-1 | Delay-0 |
|------|---------|---------|
| 最低 Sharpe | **≥ 1.25** | **≥ 2.0** |

提升 Sharpe 方法：
- 改善信号质量（更强的预测能力）
- 增加 IS 期间数据覆盖（覆盖更多股票）
- 降低换手率（减少噪声交易）

---

### Check 2：LOW_FITNESS（适应度过低）

| 参数 | Delay-1 | Delay-0 |
|------|---------|---------|
| 最低 Fitness | **≥ 1.0（Average）** | **≥ 1.3** |

Fitness 是最常见的卡点。`rank(-ts_delta(close, 5))` 实测 Sharpe=1.74 但 Fitness=0.82（因换手率 61.65% 过高）。

---

### Check 3：LOW_TURNOVER（换手率过低）

- 最低：**≥ 1%**
- 信号太弱/持仓太稳定则失败

---

### Check 4：HIGH_TURNOVER（换手率过高）

- 最高：**≤ 70%**
- 换手过高意味着交易成本极大，实际不可操作

---

### Check 5：CONCENTRATED_WEIGHT（权重集中）

两种失败情形：
1. 单只股票权重 **> 10%**
2. 每年中有显著天数，持仓股票数量过少（太集中）

解决方法：
- 设置 `Truncation = 0.05~0.08`
- 确保 Alpha 覆盖足够多的股票

---

### Check 6：LOW_SUB_UNIVERSE_SHARPE（子 Universe Sharpe 不足）

验证 Alpha 在**更流动的子 Universe** 中也有效，防止策略仅在非流动性小股票上盈利。

**公式**：
```
sub_sharpe ≥ 0.75 × √(sub_size / alpha_size) × alpha_sharpe
```

**示例（TOP3000 Alpha，Sharpe=2.73）**：
```
cutoff = 0.75 × √(1000/3000) × 2.73 = 1.18
实际 TOP1000 Sharpe = 1.17 → FAIL（仅差 0.01！）
```

**提升 Sub-Universe Sharpe 的技巧**：
- 避免使用公司规模类乘数（如 `rank(-assets)`，小公司敏感）
- 对流动/非流动部分分别设置不同衰减：
  ```
  ts_decay_linear(signal, 5) * rank(volume*close) +
  ts_decay_linear(signal, 10) * (1 - rank(volume*close))
  ```
- 确保信号在各流动性档位均有效

---

### Check 7：SELF_CORRELATION（自相关过高）

防止提交太多相似 Alpha，确保新 Alpha 贡献不同信号。

**规则**：
- 与已提交 Alpha 的 PnL 相关系数 **< 0.7**
- 例外：如果新 Alpha 的 Sharpe **高于**相关 Alpha 的 10% 以上，也可提交

```
举例：已有 Alpha X 的 Sharpe = 3.18
      新 Alpha Y 与 X 相关系数 = 0.85（> 0.7 cutoff）
      则 Y 需要 Sharpe ≥ 3.18 × 1.1 = 3.50 才可提交
```

---

### Check 8：MATCHES_COMPETITION（比赛匹配）

纯信息性提示，显示该 Alpha 符合哪些比赛要求（Challenge、IQC 等），不影响提交。

---

## 三、完整提交检查顺序

系统按以下顺序检查，**一旦失败立即停止**：

```
1. CONCENTRATED_WEIGHT → 权重集中检查
2. SELF_CORRELATION    → 自相关检查
3. LOW_FITNESS         → Fitness 检查
4. checkDelay1Sharpe   → Delay-0 Alpha 是否更适合 Delay-1 运行
5. LOW_SUB_UNIVERSE_SHARPE → 子 Universe 检查
```

---

## 四、特殊 Alpha 类型的额外规则

### ATOM Alpha

- 仅使用**单一数据集**的 Alpha
- 可以跳过 IS Ladder Sharpe 测试
- 仍需通过常规 IS 测试和 2Y Sharpe 测试

### Pyramid Alpha

- 最多贡献 2 个 Pyramid（Region × Delay × Dataset 三元组）
- 分组字段（sector、industry 等）不计入 Pyramid 数量

### Power Pool Alpha

- Sharpe ≥ 1.0
- 唯一运算符数量 ≤ 8
- 唯一数据字段数量 ≤ 3（不含分组字段）
- 仅限 USA Delay-1
- Power Pool 内自相关 ≤ 0.5

---

## 五、IS 统计年度表格解读

模拟结果中的年度表格（IS Summary）：

| 字段 | 说明 |
|------|------|
| `Year` | 年份（最后行为全 IS 期间汇总） |
| `Long Count` | 平均做多股票数 |
| `Short Count` | 平均做空股票数 |
| `Sharpe` | 当年夏普比率 |
| `Fitness` | 当年 Fitness 评分 |
| `Returns` | 当年年化收益率 |
| `Turnover` | 当年平均换手率 |
| `Margin` | 当年利润率 |
| `PnL` | 当年总盈亏（美元） |

⚠️ **注意**：年度 Sharpe 波动较大属正常现象。关注**全期汇总行**，以及 PnL 曲线是否整体向上。

---

## 六、实测示例解读

以下是实际 API 测试获取的 Alpha 结果（`rank(-ts_delta(close, 5))`）：

```json
{
  "sharpe": 1.74,         ✅ > 1.25 (PASS)
  "fitness": 0.82,        ❌ < 1.0  (FAIL - 无法提交)
  "returns": 0.1358,      ✅ 13.58% 年化
  "turnover": 0.6165,     ⚠️ 61.65% 接近上限
  "drawdown": 0.0654,     ✅ 回撤 6.54%
  "pnl": 6717571,         ✅ 5年 IS 期间盈利 $6.7M
  "longCount": 1539,      ✅ 多/空各约 1500 只
  "shortCount": 1532
}
```

**问题诊断**：
- Fitness = 0.82 原因：换手率 61.65% 过高
- `Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))`
- `= 1.74 × √(0.1358 / 0.6165) ≈ 1.74 × 0.469 ≈ 0.82`

**改进方向**：
- 增加 Decay（降低换手率）
- 寻找更低换手率的信号（基本面数据）
- 增加 `trade_when()` 过滤条件

---

*下一篇：[06_数据字段与数据集.md](./06_数据字段与数据集.md)*
