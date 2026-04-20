# WorldQuant BRAIN Alpha 开发学习项目

> 系统学习 WorldQuant BRAIN 平台的 Alpha 开发流程，包含完整文档体系、API自动化工具和10个实战Alpha测试。

---

## 📁 项目结构

```
worldquantAlpha-dev/
├── docs/                          # 学习文档（10篇）
│   ├── 01_量化交易与BRAIN平台概述.md
│   ├── 02_Fast_Expression_语言指南.md
│   ├── 03_运算符完整参考手册.md
│   ├── 04_模拟设置详解.md
│   ├── 05_性能指标与提交标准.md
│   ├── 06_数据字段与数据集.md
│   ├── 07_Alpha开发实战指南.md
│   ├── 08_API接口与自动化脚本.md
│   ├── 09_学习路径与Challenge得分指南.md
│   └── 10_实战Alpha测试报告.md    ← 10个Alpha测试结果与分析
├── src/                           # 自动化工具脚本
│   ├── login.py                   # 登录并保存 session（首次必须运行）
│   ├── brain_client.py            # BRAIN API 统一客户端
│   ├── session_guard.py           # Session 有效性检查与自动刷新
│   ├── run_10_alphas.py           # 10个Alpha测试主脚本
│   └── fetch_data.py              # 数据字段探索脚本
├── .state/                        # Session 存储（自动创建，已加入 .gitignore）
│   └── session.json               # 登录 cookie（不提交到 Git）
├── data/                          # 数据文件（已加入 .gitignore）
├── results/                       # 模拟结果（已加入 .gitignore）
├── operators_full.json            # 全部66个运算符定义（来自API）
├── test_alpha_result.json         # 首个真实模拟结果示例
├── .env.example                   # 环境变量示例（复制为 .env 填入凭据）
└── .gitignore
```

---

## 📚 文档指南

### 推荐阅读顺序（新手）

| 序号 | 文档 | 内容要点 |
|------|------|---------|
| 1 | `01_量化交易与BRAIN平台概述` | 平台介绍、Alpha生命周期、Challenge评分规则 |
| 2 | `05_性能指标与提交标准` | Sharpe/Fitness/Turnover公式，8项提交检查 |
| 3 | `02_Fast_Expression_语言指南` | FE语法、运算符分类、常见模式 |
| 4 | `04_模拟设置详解` | region/universe/delay/decay等参数含义 |
| 5 | `07_Alpha开发实战指南` | 7步开发流程、19个官方示例 |
| 6 | `10_实战Alpha测试报告` | 真实测试结果、规律总结、优化方向 |
| 7 | `03_运算符完整参考手册` | 66个运算符签名和用法（参考查阅） |
| 8 | `06_数据字段与数据集` | 可用数据字段、NaN处理、数据类型 |
| 9 | `08_API接口与自动化脚本` | REST API端点、自动化Python脚本 |
| 10 | `09_学习路径与Challenge得分指南` | 4阶段学习路径、得分提升策略 |

---

## 🔑 核心结论（来自10个Alpha测试）

### 1. Fitness公式决定成败

```
Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))
```

- **换手率 < 10%**：Fitness ≈ Sharpe，几乎无损失
- **换手率 30-50%**：Fitness 仅为 Sharpe 的 40-60%
- **换手率 > 70%**：直接触发 HIGH_TURNOVER 拒绝

### 2. 基本面 Alpha 是初学者最佳选择

| 策略类型 | 换手率 | 能否通过 |
|---------|--------|---------|
| 基本面（季报数据） | 1-5% | 通常能通过 ✅ |
| 技术指标（中长周期）| 10-30% | 需要高Sharpe ⚠️ |
| 技术指标（短周期） | 40-90% | 基本不通过 ❌ |

### 3. 本次唯一通过的Alpha

```python
rank(liabilities/assets)    # Sharpe=1.51, Fitness=1.26, Turnover=1.66%
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install requests
```

### 2. 登录

```bash
python src/login.py
# 输入你的 WorldQuant BRAIN 邮箱和密码
# Session 自动保存至 .state/session.json（已加入 .gitignore）
```

也可使用环境变量（适合 CI / 脚本化）：

```bash
WQBRAIN_EMAIL=your@email.com WQBRAIN_PASSWORD=yourpass python src/login.py
```

> **注意：** Session 有效期约 12 小时，过期后重新运行 `python src/login.py` 即可。

### 3. 验证登录状态

```python
from src.brain_client import BrainClient

client = BrainClient()
print(client.check_auth())  # {"status": 200, "body": {...}}
```

### 4. 运行单个 Alpha 测试

```python
from src.brain_client import BrainClient

client = BrainClient()
result = client.simulate_and_get_alpha("rank(liabilities/assets)")
print(result['is']['sharpe'], result['is']['fitness'])
```

### 5. 运行全部 10 个 Alpha

```bash
python src/run_10_alphas.py
```

结果保存至 `results/alphas_final_TIMESTAMP.json`

---

## 🔧 API 快速参考

```
POST /simulations            提交模拟（201 + Location header）
GET  /simulations/{id}       轮询状态（UNKNOWN → COMPLETE）
GET  /alphas/{id}            获取完整IS指标和检查结果
POST /alphas/{id}/submit     提交Alpha（需通过所有检查）
GET  /operators?limit=200    获取全部66个运算符
GET  /authentication         验证登录状态
```

**认证方式：** Cookie `t`（JWT），通过 `POST /authentication` 获取

**提交门槛（Delay-1）：** Sharpe ≥ 1.25 且 Fitness ≥ 1.0 且 1% ≤ Turnover ≤ 70%

---

## 📊 测试结果摘要

| Alpha | 表达式 | Sharpe | Fitness | 状态 |
|-------|--------|--------|---------|------|
| A04_财务杠杆 | `rank(liabilities/assets)` | 1.51 | 1.26 | ✅ 可提交 |
| A08_VWAP偏离 | `rank(-(close/vwap-1))` | 1.74 | 0.87 | ❌ 高换手 |
| A06_放量反转 | `rank(-ts_delta(close,5))*rank(vol/avg_vol)` | 1.33 | 0.78 | ❌ 低Fitness |
| A09_运营收益率 | `group_rank(ts_rank(operating_income,252),industry)` | 1.21 | 0.79 | ❌ 接近通过 |
| A01_短期反转 | `rank(-ts_delta(close,5))` | 1.05 | 0.64 | ❌ 双低 |

> 完整分析见 `docs/10_实战Alpha测试报告.md`

---

## 📝 注意事项

1. **Session 有效期约 12 小时**，过期后重新运行 `python src/login.py`
2. **系统代理问题**：`brain_client.py` 已配置 `proxies=None` 绕过本地代理（如 Clash）
3. **TUTORIAL 权限限制**：无法访问原始数据字段列表，使用平台 Data Explorer 浏览
4. **模拟频率限制**：每次模拟约 60-120 秒，建议不同 Alpha 之间等待 5 秒
5. **Alpha ID 复用**：相同表达式 + 设置的 Alpha 会返回相同 ID（平台去重）
