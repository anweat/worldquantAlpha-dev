# 08 API 接口与自动化脚本

> 本文档介绍 WorldQuant BRAIN REST API 的完整使用方法，以及用 Python 实现自动化模拟、轮询结果、提交 Alpha 的脚本示例。

---

## 一、API 基础信息

| 项目 | 值 |
|------|-----|
| API Base URL | `https://api.worldquantbrain.com` |
| 认证方式 | HTTP Basic Auth → Cookie JWT |
| 内容类型 | `Accept: application/json;version=2.0` |
| 速率限制 | 1800 次/时间窗口 |

---

## 二、认证流程

### 步骤一：登录获取 Cookie

```python
import requests
import base64

EMAIL = "your_email@example.com"
PASSWORD = "your_password"

credentials = base64.b64encode(f"{EMAIL}:{PASSWORD}".encode()).decode()

session = requests.Session()
resp = session.post(
    "https://api.worldquantbrain.com/authentication",
    headers={
        "Authorization": f"Basic {credentials}",
        "Accept": "application/json;version=2.0",
        "Content-Type": "application/json"
    }
)

# 成功返回 204 No Content（不是 200！）
assert resp.status_code == 204, f"登录失败: {resp.status_code}"
print("登录成功！")
# session 中已自动保存 Cookie（JWT token "t"）
```

### 步骤二：验证认证状态

```python
check = session.get(
    "https://api.worldquantbrain.com/authentication",
    headers={"Accept": "application/json;version=2.0"}
)
# 204 = 已认证，401 = 未认证/过期
print("认证状态:", "有效" if check.status_code == 204 else "无效/过期")
```

### 注意事项

- Cookie `t` 是 JWT Token，**有效期约 12-16 小时**，每天需重新登录
- 登录会被 reCAPTCHA 保护，**自动化登录建议使用 Playwright**（有头浏览器模式）
- Cookie 存储在 `.state/session.json`（Playwright storage_state 格式）
- 用已有 Cookie 文件初始化：

```python
import json
import requests

with open(".state/session.json") as f:
    state = json.load(f)

session = requests.Session()
for cookie in state["cookies"]:
    domain = cookie["domain"].lstrip(".")
    session.cookies.set(cookie["name"], cookie["value"], domain=domain)
```

---

## 三、已确认的 API 端点

### 3.1 用户信息

```http
GET /users/self
```

**响应**：
```json
{
  "id": "JA60238",
  "username": "anweat@163.com",
  "firstName": "...",
  "lastName": "...",
  "status": "ACTIVE"
}
```

---

### 3.2 获取用户的 Alpha 列表

```http
GET /users/{userId}/alphas?limit=20&offset=0&stage=IS&status=ACTIVE
```

**参数**：
| 参数 | 说明 |
|------|------|
| `limit` | 每页数量（最大 100） |
| `offset` | 分页偏移 |
| `stage` | `IS`（样本内）/ `OS`（样本外） |
| `status` | `ACTIVE` / `UNSUBMITTED` / `DECOMMISSIONED` |

---

### 3.3 提交模拟

```http
POST /simulations
Content-Type: application/json
```

**请求体**：
```json
{
  "type": "REGULAR",
  "settings": {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 6,
    "neutralization": "MARKET",
    "truncation": 0.05,
    "pasteurize": "ON",
    "nanHandling": "OFF",
    "unitHandling": "VERIFY",
    "language": "FASTEXPR",
    "visualization": false
  },
  "regular": "rank(-ts_delta(close, 5))"
}
```

**响应**：
- 状态码：`201 Created`
- 响应头：`Location: /simulations/{simulationId}`
- 响应头：`Retry-After: 5.0`（建议等待秒数）

---

### 3.4 查询模拟状态

```http
GET /simulations/{simulationId}
```

**响应**（状态字段）：
| `status` | 含义 |
|----------|------|
| `UNKNOWN` | 刚提交，排队中 |
| `RUNNING` | 计算中 |
| `COMPLETE` | 完成，含 `alpha` 字段（Alpha ID） |
| `ERROR` | 失败 |

完成时响应体包含 `"alpha": "alphaId"`。

---

### 3.5 获取 Alpha 详情

```http
GET /alphas/{alphaId}
```

**响应结构**（关键字段）：
```json
{
  "id": "npOz2ZN8",
  "status": "UNSUBMITTED",
  "grade": "INFERIOR",
  "is": {
    "sharpe": 1.74,
    "fitness": 0.82,
    "returns": 0.1358,
    "turnover": 0.6165,
    "drawdown": 0.0654,
    "margin": 0.00044,
    "pnl": 6717571,
    "longCount": 1539,
    "shortCount": 1532,
    "checks": [
      {"name": "LOW_SHARPE",   "result": "PASS", "limit": 1.25, "value": 1.74},
      {"name": "LOW_FITNESS",  "result": "FAIL", "limit": 1.0,  "value": 0.82},
      {"name": "LOW_TURNOVER", "result": "PASS", "limit": 0.01, "value": 0.6165},
      {"name": "HIGH_TURNOVER","result": "PASS", "limit": 0.7,  "value": 0.6165},
      {"name": "CONCENTRATED_WEIGHT", "result": "PASS"},
      {"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "PASS", "limit": 0.75, "value": 1.41},
      {"name": "SELF_CORRELATION", "result": "PENDING"}
    ]
  }
}
```

---

### 3.6 提交 Alpha

```http
POST /alphas/{alphaId}/submit
```

**响应**：
- `201 Created`：提交成功，Alpha 变为 ACTIVE
- `403 Forbidden`：检查未通过，响应体包含失败原因

**403 响应示例**：
```json
{
  "detail": [
    {"name": "LOW_FITNESS", "result": "FAIL", "limit": 1.0, "value": 0.82}
  ]
}
```

---

### 3.7 运算符列表

```http
GET /operators?limit=200
```

---

### 3.8 数据字段搜索

```http
GET /search/datafields?query=earnings&limit=10&instrumentType=EQUITY&region=USA&delay=1&universe=TOP3000
```

---

### 3.9 比赛列表

```http
GET /competitions
```

---

## 四、完整自动化脚本

以下是一个完整的 Python 脚本，实现：登录 → 模拟 → 轮询 → 查看结果 → 尝试提交。

```python
#!/usr/bin/env python3
"""
WorldQuant BRAIN Alpha 自动化脚本
功能：加载 session → 提交模拟 → 轮询结果 → 查看指标 → 提交 Alpha
"""

import json
import time
import requests
from pathlib import Path

API_BASE = "https://api.worldquantbrain.com"
HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json"
}

# ────────────────────────────────────────────────
# 1. 加载 Session
# ────────────────────────────────────────────────
def load_session(state_file: str = ".state/session.json") -> requests.Session:
    """从 Playwright session 文件加载 Cookie"""
    session = requests.Session()
    if Path(state_file).exists():
        with open(state_file) as f:
            state = json.load(f)
        for c in state.get("cookies", []):
            session.cookies.set(c["name"], c["value"],
                                domain=c["domain"].lstrip("."))
        print(f"✅ 从 {state_file} 加载 Cookie")
    return session

# ────────────────────────────────────────────────
# 2. 检查认证状态
# ────────────────────────────────────────────────
def check_auth(session: requests.Session) -> bool:
    resp = session.get(f"{API_BASE}/authentication", headers=HEADERS)
    return resp.status_code == 204

# ────────────────────────────────────────────────
# 3. 提交模拟
# ────────────────────────────────────────────────
def submit_simulation(session: requests.Session, expression: str,
                       settings: dict = None) -> str:
    """返回 simulation ID"""
    default_settings = {
        "instrumentType": "EQUITY",
        "region": "USA",
        "universe": "TOP3000",
        "delay": 1,
        "decay": 6,
        "neutralization": "MARKET",
        "truncation": 0.05,
        "pasteurize": "ON",
        "nanHandling": "OFF",
        "unitHandling": "VERIFY",
        "language": "FASTEXPR",
        "visualization": False
    }
    if settings:
        default_settings.update(settings)

    payload = {
        "type": "REGULAR",
        "settings": default_settings,
        "regular": expression
    }

    resp = session.post(f"{API_BASE}/simulations",
                        headers=HEADERS, json=payload)
    assert resp.status_code == 201, f"模拟提交失败: {resp.status_code} {resp.text}"

    sim_url = resp.headers.get("Location")  # 如 /simulations/abc123
    sim_id = sim_url.split("/")[-1]
    retry_after = float(resp.headers.get("Retry-After", 5))

    print(f"✅ 模拟已提交: {sim_id}，等待 {retry_after:.0f}s...")
    return sim_id, retry_after

# ────────────────────────────────────────────────
# 4. 轮询模拟结果
# ────────────────────────────────────────────────
def poll_simulation(session: requests.Session, sim_id: str,
                    max_wait: int = 600, interval: int = 10) -> dict:
    """轮询直到 COMPLETE，返回 simulation 结果"""
    start = time.time()
    while time.time() - start < max_wait:
        resp = session.get(f"{API_BASE}/simulations/{sim_id}", headers=HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "UNKNOWN")
            print(f"  状态: {status}")
            if status == "COMPLETE":
                return data
            elif status == "ERROR":
                raise RuntimeError(f"模拟失败: {data}")
        time.sleep(interval)
    raise TimeoutError(f"模拟超时（{max_wait}s）")

# ────────────────────────────────────────────────
# 5. 获取 Alpha 详情
# ────────────────────────────────────────────────
def get_alpha(session: requests.Session, alpha_id: str) -> dict:
    resp = session.get(f"{API_BASE}/alphas/{alpha_id}", headers=HEADERS)
    assert resp.status_code == 200
    return resp.json()

def print_alpha_summary(alpha: dict):
    """打印 Alpha 关键指标"""
    is_data = alpha.get("is", {})
    print(f"\n{'='*50}")
    print(f"Alpha ID:  {alpha['id']}")
    print(f"表达式:    {alpha.get('regular', {}).get('code', 'N/A')}")
    print(f"状态:      {alpha['status']}")
    print(f"评级:      {alpha.get('grade', 'N/A')}")
    print(f"\n📊 IS 指标:")
    print(f"  Sharpe:   {is_data.get('sharpe', 'N/A'):.3f}")
    print(f"  Fitness:  {is_data.get('fitness', 'N/A'):.3f}")
    print(f"  Returns:  {is_data.get('returns', 0)*100:.2f}%")
    print(f"  Turnover: {is_data.get('turnover', 0)*100:.2f}%")
    print(f"  Drawdown: {is_data.get('drawdown', 0)*100:.2f}%")
    print(f"  PnL:      ${is_data.get('pnl', 0):,.0f}")
    print(f"\n🔍 提交检查:")
    for chk in is_data.get("checks", []):
        icon = "✅" if chk["result"] == "PASS" else ("⏳" if chk["result"] == "PENDING" else "❌")
        limit = f"(limit={chk['limit']})" if "limit" in chk else ""
        value = f"value={chk.get('value', 'N/A')}" if "value" in chk else ""
        print(f"  {icon} {chk['name']:30s} {value} {limit}")

# ────────────────────────────────────────────────
# 6. 提交 Alpha
# ────────────────────────────────────────────────
def submit_alpha(session: requests.Session, alpha_id: str) -> bool:
    """提交 Alpha，返回是否成功"""
    resp = session.post(f"{API_BASE}/alphas/{alpha_id}/submit", headers=HEADERS)
    if resp.status_code == 201:
        print(f"🎉 Alpha {alpha_id} 提交成功！状态变为 ACTIVE")
        return True
    else:
        print(f"❌ 提交失败 ({resp.status_code}): {resp.text}")
        return False

# ────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────
def run_alpha(expression: str, settings: dict = None,
              auto_submit: bool = False,
              state_file: str = ".state/session.json"):
    session = load_session(state_file)

    if not check_auth(session):
        print("❌ Session 已过期，请重新登录")
        return

    print(f"\n🚀 提交 Alpha: {expression}")
    sim_id, retry_after = submit_simulation(session, expression, settings)
    time.sleep(retry_after)

    sim_result = poll_simulation(session, sim_id)
    alpha_id = sim_result.get("alpha")
    print(f"\n✅ 模拟完成，Alpha ID: {alpha_id}")

    alpha = get_alpha(session, alpha_id)
    print_alpha_summary(alpha)

    if auto_submit:
        all_pass = all(
            c["result"] in ("PASS", "PENDING")
            for c in alpha.get("is", {}).get("checks", [])
        )
        if all_pass:
            submit_alpha(session, alpha_id)
        else:
            print("\n⚠️ 有检查项失败，跳过自动提交")

    return alpha

# ────────────────────────────────────────────────
# 示例：运行多个 Alpha
# ────────────────────────────────────────────────
if __name__ == "__main__":
    ALPHAS_TO_TEST = [
        # (表达式, 自定义设置)
        ("rank(-liabilities/assets)", {"decay": 4, "neutralization": "SUBINDUSTRY"}),
        ("group_rank(ts_rank(earnings/assets, 252), sector)", {"decay": 0, "truncation": 0.08}),
        ("rank(-ts_corr(rank(volume), rank(close), 10))", {"decay": 6}),
    ]

    for expr, settings in ALPHAS_TO_TEST:
        result = run_alpha(expr, settings=settings, auto_submit=False)
        print("\n" + "─"*60 + "\n")
        time.sleep(3)  # 避免速率限制
```

---

## 五、端点错误排查

| 状态码 | 说明 |
|--------|------|
| `204` | 成功（无内容，如认证检查/登录） |
| `201` | 创建成功（模拟提交/Alpha 提交） |
| `200` | 正常响应 |
| `401` | 未认证或 Token 过期 |
| `403` | Alpha 检查未通过或权限不足 |
| `404` | 资源不存在 |
| `405` | 方法不允许（如 GET /alphas 应改为 GET /users/{id}/alphas） |
| `429` | 速率限制（超过 1800 次/窗口） |

### 已知不可用端点

```
GET  /alphas         → 405（改用 GET /users/{id}/alphas）
POST /alphas         → 405
GET  /datasets       → 404
GET  /datafields     → 404（改用 GET /search/datafields?query=...）
GET  /simulations    → 405
```

---

## 六、会话管理脚本（自动刷新 Cookie）

当 Cookie 过期时，使用 Playwright 可见浏览器重新登录：

```python
"""
refresh_session.py - 用 Playwright 刷新 BRAIN 登录 Session
"""
import asyncio
from playwright.async_api import async_playwright

EMAIL = "your_email@example.com"
PASSWORD = "your_password"
STATE_FILE = ".state/session.json"
LOGIN_URL = "https://platform.worldquantbrain.com/sign-in"

async def refresh():
    async with async_playwright() as p:
        # headless=False：可见浏览器，绕过 reCAPTCHA
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("打开登录页...")
        await page.goto(LOGIN_URL)

        # 填写邮箱和密码
        await page.fill('input[type="email"]', EMAIL)
        await page.fill('input[type="password"]', PASSWORD)

        # 手动完成 reCAPTCHA，然后点击登录
        print("请手动完成 reCAPTCHA 验证，然后等待自动继续...")
        await page.click('button[type="submit"]')

        # 等待跳转到主页（登录成功标志）
        await page.wait_for_url("**/simulate", timeout=60000)
        print("登录成功！")

        # 保存 Session
        await context.storage_state(path=STATE_FILE)
        print(f"Session 已保存到 {STATE_FILE}")
        await browser.close()

asyncio.run(refresh())
```

---

## 七、批量测试 Alpha 变体

```python
"""
批量测试一个 Alpha 思路的多种变体，找出最优参数组合
"""
import itertools

BASE_EXPR = "rank(-ts_delta(close, {window}))"
WINDOWS = [5, 10, 20]
DECAYS = [4, 6, 8]
NEUTRALIZATIONS = ["MARKET", "INDUSTRY"]

variants = []
for window, decay, neutral in itertools.product(WINDOWS, DECAYS, NEUTRALIZATIONS):
    expr = BASE_EXPR.format(window=window)
    settings = {"decay": decay, "neutralization": neutral}
    variants.append((expr, settings, f"w{window}_d{decay}_{neutral[:3]}"))

print(f"共 {len(variants)} 个变体待测试")

results = []
for expr, settings, label in variants:
    try:
        alpha = run_alpha(expr, settings=settings)
        is_data = alpha.get("is", {})
        results.append({
            "label": label,
            "expr": expr,
            "sharpe": is_data.get("sharpe"),
            "fitness": is_data.get("fitness"),
            "turnover": is_data.get("turnover"),
        })
        time.sleep(2)
    except Exception as e:
        print(f"  ❌ {label}: {e}")

# 按 Fitness 排序
results.sort(key=lambda x: x["fitness"] or 0, reverse=True)
print("\n📊 结果排名（按 Fitness）:")
for r in results:
    print(f"  {r['label']:20s} Sharpe={r['sharpe']:.2f}  Fitness={r['fitness']:.2f}  TO={r['turnover']*100:.1f}%")
```

---

*相关文档：[04_模拟设置详解.md](./04_模拟设置详解.md) | [05_性能指标与提交标准.md](./05_性能指标与提交标准.md)*
