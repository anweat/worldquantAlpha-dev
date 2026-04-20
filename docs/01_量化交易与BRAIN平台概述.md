# 01 量化交易与 WorldQuant BRAIN 平台概述

## 一、什么是量化交易

量化交易（Quantitative Trading）是一种依赖数学模型、统计分析和计算机程序来识别和执行交易机会的方法。与依靠主观判断的传统交易不同，量化交易通过历史数据建模，寻找可统计重复的市场规律。

### 核心概念

| 概念 | 说明 |
|------|------|
| **Long（做多）** | 买入股票，预期价格上涨获利 |
| **Short（做空）** | 借入股票卖出，预期价格下跌后低价买回 |
| **Returns（收益率）** | 持有期间的资产增减百分比 |
| **Volume（成交量）** | 某段时间内的成交股数/金额 |
| **Open / Close** | 开盘价 / 收盘价，技术分析基础数据 |
| **PnL（盈亏）** | Profit and Loss，每日/累计盈亏金额 |
| **Book Size（资金规模）** | 模拟中使用的总资金量，BRAIN 默认 $20M |

### 量化分析的两大流派

**技术分析（Technical Analysis）**  
基于价格和成交量的历史数据，寻找可重复的价格模式。  
例：移动平均线、动量指标、成交量变化。

**基本面分析（Fundamental Analysis）**  
分析公司财务数据（盈利、资产、负债等）来评估内在价值。  
例：市盈率、库存周转率、营收增长。

---

## 二、WorldQuant BRAIN 平台介绍

### 平台定位

WorldQuant BRAIN 是 WorldQuant 公司推出的**网页端量化回测平台**，允许用户以"Fast Expression"语言编写 Alpha 表达式，并对全球股票市场进行历史回测。

- 官网：https://platform.worldquantbrain.com
- API：https://api.worldquantbrain.com

WorldQuant 成立于 2007 年，是全球顶尖量化资管公司，拥有 850+ 员工，管理资产横跨全球多个资产类别。

### 平台功能概览

| 功能模块 | 说明 |
|----------|------|
| **Simulate** | Alpha 表达式编辑与回测主界面 |
| **My Alphas** | 管理已创建/提交的 Alpha |
| **Data Explorer** | 搜索和探索 85,000+ 数据字段 |
| **Learn** | 文档、课程、运算符手册 |
| **Events** | 培训 Webinar、比赛活动 |
| **Competition** | 挑战赛（Challenge / IQC）排行榜 |
| **Community** | support.worldquantbrain.com 社区论坛 |

---

## 三、什么是 Alpha

在 BRAIN 中，**Alpha** 是一个用表达式语言编写的数学模型，它将数据（价格、成交量、财务数据等）转化为一个向量，向量中每个值对应一只股票的持仓权重（weight）。

### Alpha 的本质

> Alpha = 将市场数据矩阵转化为持仓权重向量的函数

```
输入: 市场数据矩阵 (日期 × 股票)
  ↓ Alpha 表达式
输出: 权重向量 (每只股票的持仓比例)
  ↓ × Book Size
投资组合 → 计算每日 PnL → 累积 PnL 曲线
```

### 权重的含义

- **正权重** → 做多该股票（预期上涨）
- **负权重** → 做空该股票（预期下跌）
- **零/NaN** → 不持有该股票

**示例**（书本规模 $100）：
```
weight_A = +0.2  → 做多 $20
weight_B = -0.5  → 做空 $50
weight_C = +0.3  → 做多 $30
```

---

## 四、Alpha 的生命周期

```
想法产生
  → 编写 Alpha 表达式（Fast Expression）
  → 配置模拟设置（Region/Universe/Delay等）
  → 提交模拟（Simulate）
  → 查看 IS（In-Sample）结果
  → 是否满足提交标准？
      ├─ 否 → 优化修改，重新模拟
      └─ 是 → 提交 Alpha
            → OS（Out-of-Sample）测试
            → ACTIVE（计入评分）
            → 或 DECOMMISSIONED（数据下架/长期表现差）
```

### Alpha 状态说明

| 状态 | 含义 |
|------|------|
| **UNSUBMITTED** | 模拟完成，尚未提交 |
| **ACTIVE** | 已提交并通过 OS 测试，正在计分 |
| **DECOMMISSIONED** | 已停用（数据下架或长期表现差） |

---

## 五、WorldQuant 顾问计划

通过 WorldQuant Challenge 积累 10,000 分后，可申请成为**研究顾问（Research Consultant）**。

### 顾问特权

- 每日最高 $120 活动奖励，每季度最高 $25,000 绩效奖励
- 访问欧洲、亚洲区域数据（普通用户仅有美国）
- 访问 85,000+ 数据字段（普通用户更少）
- Python API 访问权限、高级训练 Webinar
- 可考虑实习/全职机会

### Challenge 积分规则

- 每日最高得 2,000 分，总分累加（无负分）
- 得分由**数量因子**（提交数量）× **质量因子**（Fitness/Sharpe/低相关性）决定
- D1（Delay-1）Alpha 比 D0 贡献更多分数
- 小 Universe（如 TOP500）比大 Universe 得分更高

### 等级

| 等级 | 所需分数 |
|------|---------|
| Bronze | > 1,000 |
| Silver | > 5,000 |
| Gold | > 10,000 |

---

## 六、BRAIN 模拟流程（后台 7 步）

当你点击"Simulate"后，BRAIN 平台在后台执行以下 7 步：

1. **计算 Alpha 向量**：对 Universe 中每只股票，按表达式计算当日权重值
2. **中性化（Neutralization）**：减去组内均值，使组内净头寸为零
3. **归一化（Normalization）**：绝对值之和缩放为 1
4. **资金分配**：权重 × Book Size = 每只股票投资金额
5. **计算当日 PnL**：持仓 × 实际收益率 = 当日盈亏
6. **滚动所有历史日期**：对 IS 期间每天重复 1-5 步
7. **累积 PnL 图**：将每日 PnL 累加形成最终收益曲线

### Decay（衰减）的作用

若 Decay = 3，最终权重为：

```
weight_final = (w[t]*3 + w[t-1]*2 + w[t-2]*1) / (3+2+1)
```

衰减可降低换手率，减少交易成本，但过大会稀释信号。

---

## 七、市场中性策略

BRAIN 鼓励**股票多空市场中性（Equity Long-Short Market Neutral）**策略：

- 多头敞口 = 空头敞口（金额相等）
- 不依赖市场整体涨跌获利
- 降低系统性风险，提高风险调整后收益
- 对冲基金常用的策略框架

**优势**：在市场上涨或下跌时均可盈利，关键在于识别相对强弱关系。

---

*下一篇：[02_Fast_Expression_语言指南.md](./02_Fast_Expression_语言指南.md)*
