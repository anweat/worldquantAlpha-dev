# WorldQuant BRAIN Alpha 开发项目 — Copilot 指令

## 项目定位

这是一个 **WorldQuant BRAIN 平台 Alpha 因子研究与自动化测试**项目。核心工作是：用 Python 调用 BRAIN REST API，提交 Fast Expression (FE) 因子表达式进行回测模拟，分析 IS（样本内）指标，筛选满足提交标准的 Alpha。

---

## 运行命令

```bash
# 测试单个 Alpha 表达式（交互式）
python -c "
from src.brain_client import BrainClient
c = BrainClient()
print(c.check_auth())
r = c.simulate_and_get_alpha('rank(liabilities/assets)')
print(r['is']['sharpe'], r['is']['fitness'])
"

# 运行全部 10 个 Alpha 批量测试（约 15-20 分钟）
python src/run_10_alphas.py

# 抓取数据字段信息
python src/fetch_data.py
```

所有脚本均从项目根目录运行（`D:\codeproject\studitile\worldquantAlpha-dev`）。无测试框架、无构建步骤、无 lint。

---

## 架构

### 核心流程

```
Fast Expression 表达式
  → BrainClient.simulate()          POST /simulations  → 201 + Location
  → BrainClient._poll()             GET /simulations/{id} 直到 status=COMPLETE
  → BrainClient.get_alpha()         GET /alphas/{id}   → IS 指标 + checks
  → (可选) submit_alpha()           POST /alphas/{id}/submit
```

### 关键文件

- **`src/brain_client.py`** — 唯一的 API 封装层。所有 HTTP 请求都通过 `BrainClient`。其 `simulate()` 方法内置了默认模拟设置（可被参数 `settings` 覆盖）。
- **`src/run_10_alphas.py`** — 批量测试脚本。Alpha 定义列表 `ALPHAS` 包含表达式、设置、策略名和假说说明。每次运行结果增量保存到 `results/`。
- **`operators_full.json`** — 从 API 获取的全部 66 个 FE 运算符权威定义，是编写表达式的参考来源。
- **`test_alpha_result.json`** — 真实 API 响应结构的示例，展示 `is` 对象的完整字段布局。

### 认证机制

- 登录凭据不在此项目中；Session cookie 存放于**外部项目** `D:\codeproject\auth-reptile\.state\session.json`（Playwright storage_state 格式）
- `BrainClient._load_session()` 读取该文件并将 cookie `t`（JWT）注入 `requests.Session`
- Cookie 有效期约 **12 小时**，过期后需用 `auth-reptile` 项目的 Playwright headless=False 浏览器重新登录
- 验证是否过期：调用 `client.check_auth()`，返回 200 则有效；401/403 则需刷新

---

## 关键约定

### API 设置字段命名

模拟设置中用 **`pasteurization`**（不是 `pasteurize`，旧版字段已废弃）。`brain_client.py` 的 `simulate()` 默认值已使用正确字段名。

### 代理绕过

`BrainClient.__init__` 中设置了 `self.session.proxies.update({"http": None, "https": None})`。这是**必须的**——本机系统代理（如 Clash，`127.0.0.1:7897`）会破坏到 BRAIN API 的 SSL 握手。不要删除此行。

### Alpha ID 去重

相同表达式 + 相同设置的模拟会返回**相同的 Alpha ID**（平台去重）。需要得到新 Alpha 时，必须修改表达式或任意一项设置。

### FE 表达式规范

- 所有截面操作需用 `rank()` 包裹以归一化到 [-1, 1]
- 基本面字段（`liabilities`、`assets`、`sales`、`operating_income` 等）按季度更新，自然换手率 1-5%
- 技术指标（`ts_delta`、`ts_corr`、`ts_std_dev` 等）按日更新，换手率通常 20-90%
- 用 `group_rank(expr, sector/industry)` 代替 `rank()` 可做行业内中性化

### Fitness 是真正的提交门槛

```
Fitness = Sharpe × √(|Returns| / max(Turnover, 0.125))
```

- **Delay-1 提交标准**：Sharpe ≥ 1.25 **且** Fitness ≥ 1.0 且 1% ≤ Turnover ≤ 70%
- 换手率超过 30% 时，Fitness 约为 Sharpe 的 40-60%；超过 70% 直接触发 HIGH_TURNOVER 拒绝
- 实测：基本面 Alpha（换手 <5%）天然满足 Fitness；纯技术 Alpha（换手 >40%）几乎不通过

### 默认模拟设置

```python
{
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 4,
    "neutralization": "MARKET",
    "truncation": 0.05,
    "pasteurization": "ON",
    "nanHandling": "OFF",
    "unitHandling": "VERIFY",
    "language": "FASTEXPR"
}
```

基本面因子推荐覆盖：`decay=0, neutralization="SUBINDUSTRY", truncation=0.08`

### 结果文件结构

`results/alphas_final_{timestamp}.json` 的每条记录结构：
```json
{
  "name": "...", "expr": "...", "settings": {...}, "hypothesis": "...", "category": "...",
  "alpha": {
    "id": "alphaId",
    "is": { "sharpe": 1.51, "fitness": 1.26, "turnover": 0.0166, "returns": 0.087,
            "checks": [{"name": "LOW_SHARPE", "result": "PASS", "limit": 1.25, "value": 1.51}, ...] }
  }
}
```

---

## API 端点速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/authentication` | 验证 session（200=有效） |
| POST | `/simulations` | 提交模拟，201 + `Location` + `Retry-After` |
| GET | `/simulations/{id}` | 轮询状态（UNKNOWN→COMPLETE/ERROR） |
| GET | `/alphas/{id}` | 获取完整 IS 指标和 checks |
| POST | `/alphas/{id}/submit` | 提交 Alpha（需通过全部 checks） |
| GET | `/operators?limit=200` | 获取全部 66 个运算符 |
| GET | `/users/self` | 当前用户信息 |
| GET | `/users/{id}/alphas` | 用户历史 Alpha 列表 |

`/search/datafields` 仅接受 `query` 和 `limit` 参数（其他过滤参数返回 400），且返回的是文档引用而非原始字段列表（TUTORIAL 权限限制）。
