"""
login.py - WorldQuant BRAIN 登录脚本
将 session cookie 保存到项目内 .state/session.json

用法:
  python src/login.py                              # 交互式输入凭据
  python src/login.py --email x --password y      # 参数传入
  WQBRAIN_EMAIL=x WQBRAIN_PASSWORD=y python src/login.py  # 环境变量
"""
import os
import sys
import json
import getpass
import argparse
import requests
from pathlib import Path

API_BASE = "https://api.worldquantbrain.com"
PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE = PROJECT_ROOT / ".state" / "session.json"


def login(email: str, password: str) -> bool:
    """向 BRAIN API 提交凭据，将返回的 cookie 保存到 .state/session.json"""
    session = requests.Session()
    # 绕过本地代理（Clash 等会破坏到 WorldQuant API 的 SSL 握手）
    session.proxies.update({"http": None, "https": None})

    resp = session.post(
        f"{API_BASE}/authentication",
        json={"username": email, "password": password},
        headers={"Content-Type": "application/json", "Accept": "application/json;version=2.0"},
    )

    if resp.status_code not in (200, 201):
        print(f"❌ 登录失败: HTTP {resp.status_code}")
        try:
            print(resp.json())
        except Exception:
            print(resp.text[:300])
        return False

    # 将 cookie 保存为 Playwright storage_state 兼容格式（brain_client._load_session 读取相同结构）
    cookies = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain or "api.worldquantbrain.com",
            "path": c.path or "/",
            "expires": c.expires if c.expires else -1,
            "httpOnly": False,
            "secure": bool(c.secure),
            "sameSite": "None",
        }
        for c in session.cookies
    ]

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "origins": []}, f, indent=2)

    print(f"✅ 登录成功！Session 已保存至 {STATE_FILE.relative_to(PROJECT_ROOT)}")
    return True


def main():
    parser = argparse.ArgumentParser(description="登录 WorldQuant BRAIN 并保存 session")
    parser.add_argument("--email", default=os.environ.get("WQBRAIN_EMAIL", ""),
                        help="登录邮箱（或设置环境变量 WQBRAIN_EMAIL）")
    parser.add_argument("--password", default=os.environ.get("WQBRAIN_PASSWORD", ""),
                        help="登录密码（或设置环境变量 WQBRAIN_PASSWORD）")
    args = parser.parse_args()

    email = args.email or input("Email: ").strip()
    password = args.password or getpass.getpass("Password: ")

    if not email or not password:
        print("错误: 必须提供邮箱和密码")
        sys.exit(1)

    if not login(email, password):
        sys.exit(1)


if __name__ == "__main__":
    main()
