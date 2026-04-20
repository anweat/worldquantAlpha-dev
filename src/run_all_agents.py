"""
run_all_agents.py - 多 Agent 主控脚本
按顺序运行 4 个策略方向的 Alpha Agent，目标是获取 60 个合格 Alpha

Agent 运行顺序（按合格率预期从高到低）：
  1. agent_fundamental  - 基本面价值/质量（预期合格率 ~80%）
  2. agent_growth       - 基本面成长/动量（预期合格率 ~75%）
  3. agent_composite    - 复合多因子（预期合格率 ~65%）
  4. agent_technical    - 技术因子低换手（预期合格率 ~50%）

用法：
    # 运行全部 4 个 Agent（约 2-4 小时）
    python src/run_all_agents.py

    # 只运行指定 Agent
    python src/run_all_agents.py --agents fundamental growth

    # 达到 N 个合格后自动停止
    python src/run_all_agents.py --target 60

    # 运行后自动提交所有合格 Alpha
    python src/run_all_agents.py --auto-submit
"""
import argparse
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows 终端 UTF-8 兼容处理
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
from brain_client import BrainClient
from agents.base import run_agent, all_checks_pass, print_summary, RESULTS_DIR

# Agent 注册表（按顺序）
AGENT_REGISTRY = {
    "fundamental": ("agents.agent_fundamental", "ALPHAS", "agent_fundamental"),
    "growth":       ("agents.agent_growth",       "ALPHAS", "agent_growth"),
    "composite":    ("agents.agent_composite",    "ALPHAS", "agent_composite"),
    "technical":    ("agents.agent_technical",    "ALPHAS", "agent_technical"),
}


def load_agent_alphas(module_path: str, alphas_var: str) -> list:
    """动态导入 agent 模块并获取 ALPHAS 列表"""
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, alphas_var)


def count_qualifying(all_results: list) -> int:
    return sum(
        1 for r in all_results
        if all_checks_pass(r.get("alpha", {}))
    )


def print_grand_summary(all_results: list, target: int):
    qualifying = [
        r for r in all_results
        if all_checks_pass(r.get("alpha", {}))
    ]
    total = len(all_results)
    q = len(qualifying)

    print(f"\n\n{'#'*68}")
    print(f"# 🏆 总体结果汇总")
    print(f"{'#'*68}")
    print(f"  总测试 Alpha:  {total}")
    print(f"  合格 Alpha:    {q}  ({'✅ 达标' if q >= target else '⚠️  未达标, 需继续'})")
    print(f"  目标:          {target}")

    if qualifying:
        print(f"\n  {'名称':<28} {'类别':<20} {'Sharpe':>7} {'Fitness':>8} {'Turnover':>9}")
        print("-" * 80)
        for r in sorted(qualifying, key=lambda x: x.get("alpha", {}).get("is", {}).get("fitness", 0),
                        reverse=True):
            is_d = r["alpha"]["is"]
            print(f"  {r['name']:<28} {r.get('category', ''):<20} "
                  f"{is_d.get('sharpe', 0):>7.3f} {is_d.get('fitness', 0):>8.3f} "
                  f"{(is_d.get('turnover', 0))*100:>8.1f}%")

    if q < target:
        print(f"\n  ⚠️  还需 {target - q} 个合格 Alpha")
        print("  建议：增加 agent_fundamental 或 agent_growth 中的 Alpha 数量")
    else:
        print(f"\n  🎉 恭喜！已达到 {target} 个合格 Alpha！")
        print("  下一步：运行 python src/auto_submit.py 提交所有合格 Alpha")


def main():
    parser = argparse.ArgumentParser(description="运行全部 Alpha Agents")
    parser.add_argument("--agents", nargs="+", choices=list(AGENT_REGISTRY.keys()),
                        default=list(AGENT_REGISTRY.keys()),
                        help="指定运行的 Agent（默认全部）")
    parser.add_argument("--target", type=int, default=60,
                        help="目标合格 Alpha 数量（默认 60）")
    parser.add_argument("--auto-submit", action="store_true",
                        help="运行结束后自动提交合格 Alpha")
    parser.add_argument("--delay", type=int, default=10,
                        help="每个 Agent 间的等待秒数（默认 10）")
    args = parser.parse_args()

    print("=" * 68)
    print(f"🚀 WorldQuant BRAIN Multi-Agent Alpha 系统")
    print(f"   目标: {args.target} 个合格 Alpha")
    print(f"   运行 Agent: {', '.join(args.agents)}")
    print(f"   启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 68)

    # 认证
    client = BrainClient()
    auth = client.check_auth()
    print(f"\n✅ 认证成功 | 用户: {auth['body'].get('user', {}).get('id', 'N/A')}")
    if auth["status"] != 200:
        print("❌ 认证失败，请刷新 session")
        sys.exit(1)

    # 运行各 Agent
    grand_results = []
    start_time = time.time()

    for agent_key in args.agents:
        module_path, alphas_var, agent_name = AGENT_REGISTRY[agent_key]

        # 检查是否已达目标
        current_qualifying = count_qualifying(grand_results)
        if current_qualifying >= args.target:
            print(f"\n🎯 已达到目标 {args.target} 个合格 Alpha，跳过后续 Agent")
            break

        print(f"\n\n{'─'*68}")
        print(f"  启动 Agent: {agent_key.upper()}  "
              f"(当前合格: {current_qualifying}/{args.target})")
        print(f"{'─'*68}")

        alphas = load_agent_alphas(module_path, alphas_var)
        results = run_agent(agent_name, alphas, client=client)
        grand_results.extend(results)

        elapsed = (time.time() - start_time) / 60
        print(f"\n  ⏱  已运行 {elapsed:.1f} 分钟  |  "
              f"当前合格: {count_qualifying(grand_results)}/{args.target}")

        # Agent 间等待
        if agent_key != args.agents[-1]:
            print(f"\n  ⏸  等待 {args.delay}s 后启动下一个 Agent...")
            time.sleep(args.delay)

    # 保存综合结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_file = RESULTS_DIR / f"grand_results_{timestamp}.json"
    with open(final_file, "w", encoding="utf-8") as f:
        json.dump(grand_results, f, ensure_ascii=False, indent=2, default=str)

    # 打印总体汇总
    print_grand_summary(grand_results, args.target)

    elapsed_total = (time.time() - start_time) / 60
    print(f"\n⏱  总运行时间: {elapsed_total:.1f} 分钟")
    print(f"📁 综合结果: {final_file}")

    # 自动提交
    if args.auto_submit:
        qualifying_count = count_qualifying(grand_results)
        if qualifying_count > 0:
            print(f"\n🔄 --auto-submit: 开始提交 {qualifying_count} 个合格 Alpha...")
            import subprocess
            subprocess.run([sys.executable,
                            str(Path(__file__).parent / "auto_submit.py"), "--yes"])
        else:
            print("\n⚠️  无合格 Alpha，跳过提交")


if __name__ == "__main__":
    main()

