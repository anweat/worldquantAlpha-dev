"""
base.py - 所有 Alpha Agent 共用的基础工具函数
提供统一的运行框架、打印格式、结果保存逻辑
"""
import json
import io
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows 终端 UTF-8 兼容处理
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

# 确保能找到 brain_client
sys.path.insert(0, str(Path(__file__).parent.parent))
from brain_client import BrainClient

RESULTS_DIR = Path(__file__).parent.parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ─── 判断是否通过全部检查 ───────────────────────────────────────────────────────
def all_checks_pass(alpha_result: dict) -> bool:
    """所有检查 PASS 或 PENDING 时返回 True"""
    checks = alpha_result.get("is", {}).get("checks", [])
    if not checks:
        return False
    return all(c["result"] in ("PASS", "PENDING") for c in checks)


# ─── 格式化单条 check ──────────────────────────────────────────────────────────
def format_check(check: dict) -> str:
    icon = {"PASS": "✅", "FAIL": "❌", "PENDING": "⏳"}.get(check["result"], "❓")
    value = ""
    if isinstance(check.get("value"), (int, float)):
        value = f"  value={check['value']:.4f}"
    limit = f"  limit={check['limit']}" if "limit" in check else ""
    return f"    {icon} {check['name']:<32}{value}{limit}"


# ─── 打印单个 Alpha 结果 ───────────────────────────────────────────────────────
def print_alpha_result(idx: int, alpha_def: dict, alpha_result: dict):
    is_data = alpha_result.get("is", {})
    sharpe = is_data.get("sharpe", 0) or 0
    fitness = is_data.get("fitness", 0) or 0
    turnover = (is_data.get("turnover", 0) or 0) * 100
    returns = (is_data.get("returns", 0) or 0) * 100

    print(f"\n{'='*62}")
    print(f"[{idx}] {alpha_def['name']}  [{alpha_def.get('category', '')}]")
    print(f"  expr:  {alpha_def['expr']}")
    print(f"  id:    {alpha_result.get('id', 'N/A')}")
    print(f"\n  📊 Sharpe={sharpe:.3f}  Fitness={fitness:.3f}  "
          f"Turnover={turnover:.1f}%  Returns={returns:.1f}%  "
          f"Drawdown={(is_data.get('drawdown',0) or 0)*100:.1f}%")
    print(f"\n  🔍 Checks:")
    for chk in is_data.get("checks", []):
        print(format_check(chk))
    passed = all_checks_pass(alpha_result)
    print(f"\n  {'🎉 合格可提交！' if passed else '⚠️  未达标'}")
    return passed


# ─── 打印汇总表格 ──────────────────────────────────────────────────────────────
def print_summary(agent_name: str, results: list):
    print(f"\n\n{'#'*62}")
    print(f"# 📊 {agent_name} 汇总 ({len(results)} 个 Alpha)")
    print(f"{'#'*62}")
    print(f"\n{'名称':<28} {'Sharpe':>7} {'Fitness':>8} {'Turnover':>10} {'Returns':>8} {'状态'}")
    print("-" * 78)

    qualifying = []
    for r in results:
        if "error" in r and not r.get("alpha"):
            print(f"  {r['name']:<26} {'ERROR':>7}")
            continue
        is_data = r.get("alpha", {}).get("is", {})
        sh = is_data.get("sharpe", 0) or 0
        fi = is_data.get("fitness", 0) or 0
        to = (is_data.get("turnover", 0) or 0) * 100
        ret = (is_data.get("returns", 0) or 0) * 100
        checks = is_data.get("checks", [])
        passed = all(c["result"] in ("PASS", "PENDING") for c in checks) and bool(checks)
        status = "✅" if passed else "❌"
        if passed:
            qualifying.append(r["name"])
        print(f"  {r['name']:<26} {sh:>7.3f} {fi:>8.3f} {to:>9.1f}% {ret:>7.1f}% {status}")

    print(f"\n合格: {len(qualifying)}/{len(results)}")
    for name in qualifying:
        print(f"  ✅ {name}")
    return qualifying


# ─── 主运行函数 ────────────────────────────────────────────────────────────────
def run_agent(agent_name: str, alphas: list, client: BrainClient = None,
              stop_at: int = None) -> list:
    """
    运行一个 Agent 的全部 Alpha 表达式。
    
    Parameters
    ----------
    agent_name : str
        Agent 名称，用于文件命名和日志
    alphas : list
        Alpha 定义列表，每项包含 name/expr/settings/hypothesis/category
    client : BrainClient, optional
        复用已有的认证 client；为 None 时自动创建
    stop_at : int, optional
        当全局合格数达到此值时提前停止（用于跨 agent 的限制）
    
    Returns
    -------
    list
        结果列表，每项含原始定义 + "alpha" 字段（API 返回）
    """
    if client is None:
        client = BrainClient()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"{agent_name}_{timestamp}.json"
    results = []
    qualifying_count = 0

    print(f"\n{'#'*62}")
    print(f"# 🤖 Agent: {agent_name}")
    print(f"# 准备测试 {len(alphas)} 个 Alpha")
    print(f"{'#'*62}")

    for idx, alpha_def in enumerate(alphas, 1):
        print(f"\n[{idx}/{len(alphas)}] 提交: {alpha_def['name']}")
        print(f"       {alpha_def['expr']}")

        try:
            result = client.simulate_and_get_alpha(
                alpha_def["expr"], alpha_def.get("settings")
            )

            if "error" in result:
                print(f"  ❌ 错误: {result}")
                results.append({**alpha_def, "error": str(result), "alpha": {}})
            else:
                passed = print_alpha_result(idx, alpha_def, result)
                results.append({**alpha_def, "alpha": result})
                if passed:
                    qualifying_count += 1
                    print(f"  ✨ 本 agent 已合格: {qualifying_count} 个")

        except Exception as e:
            print(f"  ❌ 异常: {e}")
            results.append({**alpha_def, "error": str(e), "alpha": {}})

        # 增量保存（防止中途失败丢失数据）
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)

        if stop_at and qualifying_count >= stop_at:
            print(f"\n🎯 已达到目标合格数 {stop_at}，提前停止！")
            break

        if idx < len(alphas):
            time.sleep(3)

    # 最终汇总
    print_summary(agent_name, results)
    print(f"\n📁 结果保存至: {out_file}")
    return results

