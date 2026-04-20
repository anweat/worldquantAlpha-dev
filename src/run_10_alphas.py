"""
run_10_alphas.py
运行 10 个不同策略类型的 Alpha，收集结果并分析趋势
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from brain_client import BrainClient

RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────
#  10 个 Alpha 定义  （表达式, 设置, 策略名, 思路说明）
# ─────────────────────────────────────────────────────────
ALPHAS = [
    # ── 1. 短期价格反转（5日）──────────────────────────────
    {
        "name": "A01_短期价格反转",
        "expr": "rank(-ts_delta(close, 5))",
        "settings": {"decay": 4, "neutralization": "MARKET", "truncation": 0.05},
        "hypothesis": "过去5日跌幅最大的股票，短期内容易反弹（均值回归）",
        "category": "技术分析 / 均值回归",
    },
    # ── 2. 20日价格动量 ─────────────────────────────────────
    {
        "name": "A02_20日价格动量",
        "expr": "rank(ts_delta(close, 20))",
        "settings": {"decay": 6, "neutralization": "MARKET", "truncation": 0.05},
        "hypothesis": "过去20日涨幅最大的股票，中期趋势延续（动量效应）",
        "category": "技术分析 / 动量",
    },
    # ── 3. 量价背离 ────────────────────────────────────────
    {
        "name": "A03_量价背离",
        "expr": "rank(-ts_corr(rank(volume), rank(close), 10))",
        "settings": {"decay": 4, "neutralization": "MARKET", "truncation": 0.05},
        "hypothesis": "量价负相关（涨价缩量/跌价放量）是价格反转的信号",
        "category": "技术分析 / 量价关系",
    },
    # ── 4. 基本面：负债率 ──────────────────────────────────
    {
        "name": "A04_财务杠杆",
        "expr": "rank(liabilities/assets)",
        "settings": {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08},
        "hypothesis": "高杠杆公司通过债务融资实现激进扩张，潜在超额收益更高",
        "category": "基本面 / 价值",
    },
    # ── 5. 基本面：资产利用率 ─────────────────────────────
    {
        "name": "A05_资产利用率",
        "expr": "group_rank(ts_rank(sales/assets, 252), sector)",
        "settings": {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08},
        "hypothesis": "行业内资产周转率历史排名高的公司，经营效率更优，未来表现更好",
        "category": "基本面 / 质量",
    },
    # ── 6. 成交量放大 + 价格反转 ──────────────────────────
    {
        "name": "A06_放量反转",
        "expr": "rank(-ts_delta(close, 5)) * rank(volume / ts_mean(volume, 20))",
        "settings": {"decay": 4, "neutralization": "MARKET", "truncation": 0.05},
        "hypothesis": "放量下跌的股票，后续反弹力度更大（资金底部承接信号）",
        "category": "技术分析 / 量价",
    },
    # ── 7. 波动率低选股 ──────────────────────────────────
    {
        "name": "A07_低波动率",
        "expr": "rank(-ts_std_dev(returns, 20))",
        "settings": {"decay": 4, "neutralization": "MARKET", "truncation": 0.05},
        "hypothesis": "低波动率股票具有更稳健的风险调整后收益（低波动异象）",
        "category": "技术分析 / 波动率",
    },
    # ── 8. VWAP 价格偏离 ─────────────────────────────────
    {
        "name": "A08_VWAP偏离回归",
        "expr": "rank(-(close/vwap - 1))",
        "settings": {"decay": 4, "neutralization": "MARKET", "truncation": 0.05},
        "hypothesis": "收盘价高于VWAP说明尾盘追涨，次日可能回落；反之亦然",
        "category": "技术分析 / 均值回归",
    },
    # ── 9. 行业内运营收益排名 ─────────────────────────────
    {
        "name": "A09_运营收益率",
        "expr": "group_rank(ts_rank(operating_income, 252), industry)",
        "settings": {
            "decay": 0, "neutralization": "SUBINDUSTRY",
            "truncation": 0.08, "nanHandling": "ON"
        },
        "hypothesis": "行业内运营利润历史排名高的公司，相对盈利能力改善，预期估值提升",
        "category": "基本面 / 盈利能力",
    },
    # ── 10. 多因子复合：动量 + 价值 ──────────────────────
    {
        "name": "A10_动量价值复合",
        "expr": "0.5 * rank(-ts_delta(close, 20)) + 0.5 * rank(-liabilities/assets)",
        "settings": {
            "decay": 4, "neutralization": "MARKET",
            "truncation": 0.05, "nanHandling": "ON"
        },
        "hypothesis": "结合中期反转（均值回归）和低负债率（价值因子），两个信号互补降低相关性",
        "category": "复合因子",
    },
]


def format_check(check: dict) -> str:
    icon = {"PASS": "✅", "FAIL": "❌", "PENDING": "⏳"}.get(check["result"], "❓")
    limit = f"  limit={check.get('limit', '')}" if "limit" in check else ""
    value = f"  value={check.get('value', ''):.4f}" if isinstance(check.get("value"), float) else ""
    return f"    {icon} {check['name']:<32}{value}{limit}"


def print_alpha(idx: int, alpha_def: dict, alpha_result: dict):
    is_data = alpha_result.get("is", {})
    print(f"\n{'='*60}")
    print(f"[{idx}] {alpha_def['name']}")
    print(f"  类型: {alpha_def['category']}")
    print(f"  思路: {alpha_def['hypothesis']}")
    print(f"  表达式: {alpha_def['expr']}")
    print(f"  Alpha ID: {alpha_result.get('id', 'N/A')}")
    print(f"\n  📊 IS 指标:")
    print(f"    Sharpe:   {is_data.get('sharpe', 'N/A')}")
    print(f"    Fitness:  {is_data.get('fitness', 'N/A')}")
    print(f"    Returns:  {is_data.get('returns', 0) * 100:.2f}%  (年化)")
    print(f"    Turnover: {is_data.get('turnover', 0) * 100:.2f}%")
    print(f"    Drawdown: {is_data.get('drawdown', 0) * 100:.2f}%")
    print(f"    PnL:      ${is_data.get('pnl', 0):,.0f}")
    print(f"    L/S Count:{is_data.get('longCount','?')}/{is_data.get('shortCount','?')}")
    print(f"\n  🔍 提交检查:")
    for chk in is_data.get("checks", []):
        print(format_check(chk))
    all_passed = all(
        c["result"] in ("PASS", "PENDING")
        for c in is_data.get("checks", [])
    )
    print(f"\n  {'🎉 可以提交！' if all_passed else '⚠️ 尚未满足提交标准'}")


def run_all():
    client = BrainClient()
    auth = client.check_auth()
    user_id = auth["body"].get("user", {}).get("id", "unknown")
    print(f"✅ 已认证 | 用户: {user_id}")
    print(f"⏱  开始测试 {len(ALPHAS)} 个 Alpha...\n")

    all_results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for idx, alpha_def in enumerate(ALPHAS, 1):
        print(f"\n[{idx}/{len(ALPHAS)}] 提交: {alpha_def['name']}")
        print(f"       {alpha_def['expr']}")

        try:
            result = client.simulate_and_get_alpha(
                alpha_def["expr"], alpha_def["settings"]
            )

            if "error" in result:
                print(f"  ❌ 失败: {result}")
                all_results.append({**alpha_def, "error": str(result), "alpha": {}})
            else:
                print_alpha(idx, alpha_def, result)
                all_results.append({**alpha_def, "alpha": result})

        except Exception as e:
            print(f"  ❌ 异常: {e}")
            all_results.append({**alpha_def, "error": str(e), "alpha": {}})

        # 保存中间结果（防止中途失败丢失数据）
        out_file = RESULTS_DIR / f"alphas_{timestamp}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

        if idx < len(ALPHAS):
            print(f"\n  ⏸  等待 5s 后继续...")
            time.sleep(5)

    # 汇总报告
    print_summary(all_results)

    # 保存最终结果
    final_file = RESULTS_DIR / f"alphas_final_{timestamp}.json"
    with open(final_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ 完整结果保存至: {final_file}")
    return all_results


def print_summary(results: list):
    print(f"\n\n{'#'*60}")
    print(f"# 📊 汇总报告：{len(results)} 个 Alpha")
    print(f"{'#'*60}")
    print(f"\n{'名称':<25} {'Sharpe':>8} {'Fitness':>8} {'Turnover':>10} {'Returns':>9} {'状态'}")
    print("-" * 75)

    submittable = []
    for r in results:
        if "error" in r and not r.get("alpha"):
            print(f"  {r['name']:<23} {'ERROR':>8}")
            continue
        is_data = r.get("alpha", {}).get("is", {})
        sh = is_data.get("sharpe", 0) or 0
        fi = is_data.get("fitness", 0) or 0
        to = (is_data.get("turnover", 0) or 0) * 100
        ret = (is_data.get("returns", 0) or 0) * 100
        checks = is_data.get("checks", [])
        passed = all(c["result"] in ("PASS", "PENDING") for c in checks)
        status = "✅可提交" if passed else "❌待优化"
        if passed:
            submittable.append(r["name"])
        print(f"  {r['name']:<23} {sh:>8.3f} {fi:>8.3f} {to:>9.1f}% {ret:>8.1f}% {status}")

    print(f"\n{'─'*75}")
    print(f"可提交的 Alpha ({len(submittable)}/{len(results)}):")
    for name in submittable:
        print(f"  ✅ {name}")

    if not submittable:
        print("  暂无可直接提交的 Alpha，请参考优化建议")


if __name__ == "__main__":
    run_all()
