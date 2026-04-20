# 09 学习路径与 Challenge 得分指南

> 本文档介绍 WorldQuant BRAIN 的系统学习路径，以及如何在 WorldQuant Challenge 中高效积累积分、晋升顾问。

---

## 一、官方推荐 10 步入门路径

官方文档提供了从零开始的 10 步学习计划：

| 步骤 | 内容 | 平台位置 |
|------|------|---------|
| 1 | 观看"Alpha 介绍"训练系列视频 | Events → Training Videos |
| 2 | 阅读新手包（Starter Pack）系列 | Learn → Documentation → Discover BRAIN |
| 3 | 用 `close` 和 `rank` 模拟 3 个简单公式 | Simulate 页面 |
| 4 | 理解模拟设置（重点：Delay 和 Neutralization） | Settings 面板 |
| 5 | 点击 Example 按钮，尝试改进示例 Alpha | Simulate → Example 按钮 |
| 6 | 阅读模拟结果和提交检查的含义 | Learn → Documentation → Interpret Results |
| 7 | 模拟"Create Alphas"章节的 Alpha | Learn → Documentation → Create Alphas |
| 8 | 参加 Events 页的培训 Webinar | Events 页面 |
| 9 | 阅读 BRAIN Tips 系列和 FAQ 中的 Beginner 帖子 | Learn → FAQ / Community |
| 10 | 尝试用价量数据和运算符创建自己的 Alpha | Simulate 页面 |

---

## 二、学习阶段划分

### 阶段一：入门（第 1~2 周）

**目标**：理解平台，成功模拟第一个 Alpha

**学习内容**：
- 量化交易基础（多空、PnL、Sharpe）
- Fast Expression 语言基础（rank、ts_delta、ts_mean）
- 模拟设置（Delay、Decay、Neutralization）
- 阅读结果（PnL 曲线、IS 年度表格）

**练习 Alpha**（从最简单开始）：
```
# 练习 1：最简单的价格排名
rank(close)

# 练习 2：成交量排名
rank(volume)

# 练习 3：5 日价格变化
rank(-ts_delta(close, 5))

# 练习 4：资产利用率
rank(sales/assets)
```

---

### 阶段二：初级（第 3~4 周）

**目标**：理解提交标准，提交第一个 ACTIVE Alpha

**学习内容**：
- 深入理解 Fitness/Sharpe/Turnover 三角关系
- 时间序列运算符（ts_rank、ts_zscore、ts_corr）
- 行业中性化（group_neutralize、group_rank）
- 数据字段探索（基本面数据）

**练习 Alpha**：
```
# 基本面因子（低换手率，易通过 Fitness）
rank(-liabilities/assets)
设置: Decay=4, Neutralization=Subindustry, Truncation=0.05

# 行业内盈利能力
group_rank(ts_rank(earnings/assets, 252), sector)
设置: Decay=0, Truncation=0.08

# 量价异动
rank(-ts_corr(rank(volume), rank(close), 10))
设置: Decay=6, Neutralization=Market
```

---

### 阶段三：进阶（第 2~3 个月）

**目标**：每天稳定提交 1~2 个有质量的 Alpha，进入积分快速增长期

**学习内容**：
- 复合因子设计（多因子加权合成）
- Sub-Universe 稳健性优化
- 自相关管理（探索新数据集）
- Alpha 变体系统测试（自动化脚本）

**关键策略**：
- 围绕一个核心想法，测试 5~10 个变体
- 记录每个 Alpha 的 Sharpe/Fitness/Turnover
- 选择相关性最低的最优版本提交
- 每周探索至少一个新数据集

---

### 阶段四：顾问冲刺（3 个月后）

**目标**：累积 10,000 分，申请成为 Research Consultant

**策略**：
- D1（Delay-1）Alpha 比 D0 得分更高
- 小 Universe（TOP500）得分系数更高
- 低自相关 Alpha 增加质量因子
- 每天 1~2 个提交（达到最高日分 2,000）

---

## 三、WorldQuant Challenge 详解

### 基本规则

- **永久在线竞赛**：没有截止日期，持续进行
- **无负分**：得分只增不减
- **每日计算**：每天 3 AM EST 刷新分数
- **每日上限**：最高 2,000 分
- **最优策略**：每天提交 1~2 个高质量 Alpha

### 评分公式

```
日分 = f(数量因子, 质量因子) ，上限 2,000

数量因子 = 当天提交 Alpha 数量的相对排名

质量因子 = 当天所有提交 Alpha 质量均值，取决于：
  - Universe（更小 → 更高分）
  - Self-Correlation（越低 → 越高分）
  - Fitness（越高 → 越高分）
  - Delay（D1 > D0）
```

### 等级与福利

| 等级 | 所需分数 | 额外福利 |
|------|---------|---------|
| Bronze | > 1,000 | 进入排行榜 |
| Silver | > 5,000 | 特别培训视频/Webinar |
| Gold | > 10,000 | 顾问申请资格 |

### 顾问（Consultant）权益

顾问拥有超越普通用户的权限：

| 权益 | 说明 |
|------|------|
| 活动奖励 | 每日最高 $120（活动性奖励） |
| 季度绩效 | 每季度最高 $25,000 |
| 欧洲/亚洲区域 | 访问 EUR、ASI 市场数据 |
| 85,000+ 字段 | 全量数据访问（含特殊数据集） |
| 10 年 IS 期间 | 普通用户只有 5 年 |
| Python API | 官方 API 文档和高级功能 |
| 高级 Webinar | 进阶培训内容 |
| 内推机会 | 实习/全职考虑资格 |

---

## 四、分数优化策略

### 策略一：Universe 优先选 TOP500

```
TOP500 得分系数 > TOP1000 > TOP2000 > TOP3000

但注意：小 Universe 通过 Sub-Universe Test 更难
建议：先在 TOP3000 开发，再缩小至 TOP1000/TOP500
```

### 策略二：维持低自相关

```
每个新 Alpha 与已有 Alpha 的 PnL 相关系数应 < 0.5
（提交门槛是 < 0.7，但 0.5 以下得分更高）

方法：
- 探索不同数据集（基本面 + 情绪 + 价量交替使用）
- 探索不同时间窗口（5日 vs 20日 vs 60日）
- 探索不同 Universe 或 Region
```

### 策略三：每天规律提交

```
每日最高 2,000 分，通常提交 1~2 个即可达到
不需要一天提交 10 个（数量因子递减边际效益）
保持高质量比堆量更有效
```

---

## 五、常用学习资源

| 资源 | 位置 | 内容 |
|------|------|------|
| 官方文档 | Learn → Documentation | 平台全面文档 |
| 运算符手册 | Learn → Operators | 所有运算符详解 |
| 视频课程 | Learn → Courses | 系统性培训视频 |
| 培训 Webinar | Events | 定期直播，深度主题 |
| FAQ / 社区 | support.worldquantbrain.com | 问答、讨论、Tips |
| 比赛 | Competition → IQC/Challenge | 排行榜、竞赛信息 |
| 示例 Alpha | Simulate → Example 按钮 | 5 个官方示例 |

---

## 六、常见误区

### ❌ 误区一：Sharpe 高就可以提交

实测反例：`rank(-ts_delta(close, 5))` 的 Sharpe = 1.74（通过），但 Fitness = 0.82（失败）。  
**正确**：Fitness ≥ 1.0 才是提交的核心门槛。

### ❌ 误区二：大量优化提升 IS 表现

过度拟合（Overfitting）是量化研究的最大风险。IS 很好但 OS 糟糕 = 无价值的 Alpha。  
**正确**：每次修改要有经济直觉支撑，而非仅凭回测结果调参。

### ❌ 误区三：相关性高但 Sharpe 更好可以一直提交

自相关池会越来越大，后续找低相关 Alpha 越来越难。  
**正确**：从一开始就注重探索不同数据集和策略类型。

### ❌ 误区四：等 Alpha 完美再提交

平台鼓励持续探索和多次提交，不应花过多时间打磨单个 Alpha。  
**正确**：有"Average"评级（Fitness > 1.0）就可以提交，然后探索新想法。

---

*下一篇：[10_实战Alpha测试报告.md](./10_实战Alpha测试报告.md)*
