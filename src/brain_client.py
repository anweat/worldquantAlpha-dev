"""
brain_client.py - WorldQuant BRAIN API 客户端
统一管理认证、模拟提交、轮询、数据获取
"""
import json
import time
import requests
from pathlib import Path
from typing import Optional

API_BASE = "https://api.worldquantbrain.com"
HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json"
}

# 项目根目录下的 session 文件路径（由 src/login.py 生成）
_DEFAULT_STATE_FILE = Path(__file__).parent.parent / ".state" / "session.json"


class BrainClient:
    def __init__(self, state_file: str = None):
        self.session = requests.Session()
        # Bypass system proxy (local proxy breaks SSL to WorldQuant API)
        self.session.proxies.update({"http": None, "https": None})
        self.state_file = state_file or str(_DEFAULT_STATE_FILE)
        self._load_session()

    def _load_session(self):
        path = Path(self.state_file)
        if not path.exists():
            raise FileNotFoundError(
                f"Session file not found: {self.state_file}\n"
                "请先运行 `python src/login.py` 登录并保存 session。"
            )
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        for c in state.get("cookies", []):
            self.session.cookies.set(
                c["name"], c["value"],
                domain=c["domain"].lstrip(".")
            )

    def _get(self, path: str, params: dict = None) -> dict:
        r = self.session.get(f"{API_BASE}{path}", headers=HEADERS, params=params)
        r.raise_for_status()
        return r.json() if r.content else {}

    def _post(self, path: str, payload: dict) -> requests.Response:
        return self.session.post(f"{API_BASE}{path}", headers=HEADERS, json=payload)

    def check_auth(self) -> dict:
        """Returns status 200 with user info if authenticated, 401 if session expired."""
        r = self.session.get(f"{API_BASE}/users/self", headers=HEADERS)
        return {"status": r.status_code, "body": r.json() if r.content else {}}

    def get_user(self) -> dict:
        return self._get("/users/self")

    def get_operators(self) -> list:
        return self._get("/operators?limit=200")

    def search_datafields(self, query: str, limit: int = 20,
                          region: str = "USA", universe: str = "TOP3000",
                          delay: int = 1) -> dict:
        params = {
            "query": query,
            "limit": limit,
            "instrumentType": "EQUITY",
            "region": region,
            "universe": universe,
            "delay": delay
        }
        return self._get("/search/datafields", params)

    def simulate(self, expression: str, settings: dict = None,
                 wait_complete: bool = True, poll_interval: int = 8,
                 max_wait: int = 600) -> dict:
        """提交模拟并（可选）等待结果"""
        base = {
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
            "language": "FASTEXPR",
            "visualization": False
        }
        if settings:
            base.update(settings)

        payload = {"type": "REGULAR", "settings": base, "regular": expression}

        # Retry on 429 CONCURRENT_SIMULATION_LIMIT_EXCEEDED with backoff
        for attempt in range(12):
            resp = self._post("/simulations", payload)
            if resp.status_code == 201:
                break
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 30)) + 10
                print(f"  [429] Concurrent limit — waiting {wait:.0f}s before retry {attempt+1}/12...")
                time.sleep(wait)
                continue
            return {"error": resp.status_code, "body": resp.text}
        else:
            return {"error": 429, "body": "Exceeded max retries for concurrent simulation limit"}

        if resp.status_code != 201:
            return {"error": resp.status_code, "body": resp.text}

        sim_url = resp.headers.get("Location", "")
        sim_id = sim_url.split("/")[-1]
        retry_after = float(resp.headers.get("Retry-After", 5))

        if not wait_complete:
            return {"sim_id": sim_id}

        time.sleep(retry_after)
        return self._poll(sim_id, poll_interval, max_wait)

    def _poll(self, sim_id: str, interval: int, max_wait: int) -> dict:
        start = time.time()
        while time.time() - start < max_wait:
            try:
                data = self._get(f"/simulations/{sim_id}")
                status = data.get("status", "UNKNOWN")
                if status == "COMPLETE":
                    return data
                elif status == "ERROR":
                    return {"error": "simulation_error", "data": data}
            except Exception:
                pass
            time.sleep(interval)
        return {"error": "timeout"}

    def get_alpha(self, alpha_id: str) -> dict:
        return self._get(f"/alphas/{alpha_id}")

    def get_user_alphas(self, user_id: str, limit: int = 50,
                        status: str = None) -> dict:
        params = {"limit": limit}
        if status:
            params["status"] = status
        return self._get(f"/users/{user_id}/alphas", params)

    def submit_alpha(self, alpha_id: str) -> dict:
        resp = self._post(f"/alphas/{alpha_id}/submit", {})
        return {"status": resp.status_code, "body": resp.json() if resp.content else {}}

    def simulate_and_get_alpha(self, expression: str, settings: dict = None) -> dict:
        """一步完成：模拟 → 轮询 → 获取 Alpha 详情"""
        sim = self.simulate(expression, settings)
        if "error" in sim:
            return sim
        alpha_id = sim.get("alpha")
        if not alpha_id:
            return {"error": "no_alpha_id", "sim": sim}
        return self.get_alpha(alpha_id)
