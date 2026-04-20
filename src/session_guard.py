"""
session_guard.py - Session 有效性检查与自动刷新
在批量运行前调用 ensure_session()，如 session 已过期则自动触发重新登录。
"""
import os
import sys
import getpass
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


def ensure_session(verbose=True) -> bool:
    """
    检查 session 有效性。
    - 有效：直接返回 True
    - 过期或缺失：尝试用环境变量 WQBRAIN_EMAIL / WQBRAIN_PASSWORD 自动刷新；
                  若未设置则提示用户运行 `python src/login.py` 后退出。
    """
    from brain_client import BrainClient
    from login import login

    # 若 session 文件不存在，直接尝试登录
    try:
        c = BrainClient()
        r = c.check_auth()
    except FileNotFoundError:
        r = {"status": 0, "body": {}}

    if r["status"] == 200:
        if verbose:
            body = r["body"]
            user = body.get("user", body)
            print(f"✅ Session OK: {user.get('id','?')} / {user.get('email','?')}")
        return True

    if verbose:
        print(f"⚠️  Session 过期或无效 (HTTP {r['status']})，尝试自动刷新...")

    email = os.environ.get("WQBRAIN_EMAIL", "")
    password = os.environ.get("WQBRAIN_PASSWORD", "")

    if not email:
        email = input("Email: ").strip()
    if not password:
        password = getpass.getpass("Password: ")

    if not email or not password:
        print("❌ 未提供凭据，无法刷新 session。请运行 `python src/login.py`")
        sys.exit(1)

    if not login(email, password):
        print("❌ 登录失败，请检查凭据后重试：`python src/login.py`")
        sys.exit(1)

    # 验证刷新后的 session
    c2 = BrainClient()
    r2 = c2.check_auth()
    if r2["status"] == 200:
        body = r2["body"]
        user = body.get("user", body)
        if verbose:
            print(f"✅ Session 刷新成功: {user.get('id','?')} / {user.get('email','?')}")
        return True

    print(f"❌ Session 刷新后仍无效 (HTTP {r2['status']})")
    sys.exit(1)


if __name__ == "__main__":
    ensure_session()
