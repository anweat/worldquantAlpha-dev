"""
analyze_results.py - Alpha 测试结果分析与报告
功能：
  1. 扫描所有结果文件，统计各项指标
  2. 可视化（ASCII图表）Sharpe/Fitness/Turnover 分布
  3. 分析各策略类别合格率
  4. 输出合格 Alpha 详细列表
  5. 生成改进建议

运行方式：
    python src/analyze_results.py
    python src/analyze_results.py --category "基本面/价值"
    python src/analyze_results.py --show-fails     # 额外显示失败原因
    python src/analyze_results.py --export         # 导出 CSV 报告
"""
import argparse
import csv
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

# Windows 终端 UTF-8 兼容处理
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

RESULTS_DIR = Path(__file__).parent.parent / "results"
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def all_checks_pass(alpha_result: dict) -> bool:
    checks = alpha_result.get("is", {}).get("checks", [])
    if not checks:
        return False
    return all(c["result"] in ("PASS", "PENDING") for c in checks)


def get_fail_reasons(alpha_result: dict) -> list:
    checks = alpha_result.get("is", {}).get("checks", [])
    return [c["name"] for c in checks if c["result"] == "FAIL"]


def load_all_results() -> list:
    """加载所有结果文件，去重"""
    result_files = sorted(RESULTS_DIR.glob("*.json"))
    seen = set()
    all_items = []

    for f in result_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for item in data:
                alpha_id = item.get("alpha", {}).get("id")
                if alpha_id and alpha_id not in seen:
                    seen.add(alpha_id)
                    item["_source"] = f.name
                    all_items.append(item)
        except Exception as e:
            print(f"  ⚠️  读取 {f.name}: {e}")

    return all_items


def ascii_histogram(values: list, title: str, bins: int = 10, width: int = 40):
    """绘制 ASCII 直方图"""
    if not values:
        return
    min_v, max_v = min(values), max(values)
    if max_v == min_v:
        return
    step = (max_v - min_v) / bins
    counts = [0] * bins
    for v in values:
        bucket = min(int((v - min_v) / step), bins - 1)
        counts[bucket] += 1
    max_count = max(counts) if counts else 1

    print(f"\n  {title}")
    for i, count in enumerate(counts):
        lo = min_v + i * step
        hi = lo + step
        bar = "█" * int(count / max_count * width)
        print(f"  {lo:6.3f}-{hi:6.3f} │{bar:<{width}} {count}")


def print_full_report(items: list, show_fails: bool = False, filter_category: str = None):
    if filter_category:
        items = [i for i in items if filter_category in i.get("category", "")]

    total = len(items)
    if total == 0:
        print("❌ 未找到任何结果")
        return

    qualifying = [i for i in items if all_checks_pass(i.get("alpha", {}))]
    failing = [i for i in items if not all_checks_pass(i.get("alpha", {})) and i.get("alpha", {}).get("is")]
    errors = [i for i in items if "error" in i and not i.get("alpha", {}).get("is")]

    sharpes = [i["alpha"]["is"].get("sharpe", 0) or 0 for i in items if i.get("alpha", {}).get("is")]
    fitnesses = [i["alpha"]["is"].get("fitness", 0) or 0 for i in items if i.get("alpha", {}).get("is")]
    turnovers = [(i["alpha"]["is"].get("turnover", 0) or 0) * 100 for i in items if i.get("alpha", {}).get("is")]

    print("\n" + "=" * 70)
    print(f"  📊 Alpha 测试结果分析报告")
    if filter_category:
        print(f"  筛选类别: {filter_category}")
    print("=" * 70)
    print(f"\n  总 Alpha 数:    {total}")
    print(f"  合格 Alpha:     {len(qualifying)}  ({len(qualifying)/total*100:.1f}%)")
    print(f"  不合格 Alpha:   {len(failing)}")
    print(f"  错误 Alpha:     {len(errors)}")

    if sharpes:
        print(f"\n  指标统计:")
        print(f"  {'指标':<12} {'均值':>8} {'中位':>8} {'最小':>8} {'最大':>8}")
        print("  " + "-" * 48)
        for name, vals in [("Sharpe", sharpes), ("Fitness", fitnesses), ("换手率%", turnovers)]:
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            mean = sum(vals_sorted) / n
            median = vals_sorted[n // 2]
            print(f"  {name:<12} {mean:>8.3f} {median:>8.3f} {min(vals_sorted):>8.3f} {max(vals_sorted):>8.3f}")

    # 失败原因分析
    fail_reasons = defaultdict(int)
    for item in failing:
        for reason in get_fail_reasons(item.get("alpha", {})):
            fail_reasons[reason] += 1

    if fail_reasons:
        print(f"\n  失败原因分布:")
        for reason, count in sorted(fail_reasons.items(), key=lambda x: -x[1]):
            pct = count / len(failing) * 100 if failing else 0
            print(f"    {reason:<32} {count:>4}  ({pct:.0f}%)")

    # 类别统计
    cat_stats = defaultdict(lambda: {"total": 0, "qualifying": 0, "fitness": []})
    for item in items:
        cat = item.get("category", "未分类")
        is_d = item.get("alpha", {}).get("is", {})
        cat_stats[cat]["total"] += 1
        if all_checks_pass(item.get("alpha", {})):
            cat_stats[cat]["qualifying"] += 1
        fi = is_d.get("fitness", 0) or 0
        if fi > 0:
            cat_stats[cat]["fitness"].append(fi)

    print(f"\n  各类别合格率:")
    print(f"  {'类别':<30} {'合格':>5} {'总计':>5} {'率':>6} {'平均Fitness':>12}")
    print("  " + "-" * 60)
    for cat, cs in sorted(cat_stats.items(), key=lambda x: x[1]["qualifying"], reverse=True):
        rate = cs["qualifying"] / cs["total"] * 100 if cs["total"] > 0 else 0
        avg_fi = sum(cs["fitness"]) / len(cs["fitness"]) if cs["fitness"] else 0
        print(f"  {cat:<30} {cs['qualifying']:>5} {cs['total']:>5} {rate:>5.0f}%  {avg_fi:>12.3f}")

    # 分布图
    ascii_histogram(fitnesses, "Fitness 分布:")
    ascii_histogram(turnovers, "换手率(%) 分布:", bins=8)

    # 合格 Alpha 完整列表
    print(f"\n\n{'='*70}")
    print(f"  🏆 合格 Alpha 完整列表 ({len(qualifying)} 个，按 Fitness 排序)")
    print(f"{'='*70}")
    print(f"\n  {'#':>3}  {'ID':<10} {'名称':<28} {'Sharpe':>7} {'Fitness':>8} "
          f"{'TO%':>6} {'Ret%':>7} {'类别'}")
    print("  " + "-" * 90)

    for i, item in enumerate(sorted(qualifying,
                                    key=lambda x: x.get("alpha", {}).get("is", {}).get("fitness", 0),
                                    reverse=True), 1):
        is_d = item["alpha"]["is"]
        print(f"  {i:>3}. {item['alpha'].get('id', ''):<10} {item.get('name', ''):<28} "
              f"{is_d.get('sharpe', 0):>7.3f} {is_d.get('fitness', 0):>8.3f} "
              f"{(is_d.get('turnover', 0))*100:>5.1f}% {(is_d.get('returns', 0))*100:>6.1f}% "
              f"{item.get('category', '')}")

    # 不合格详情（可选）
    if show_fails and failing:
        print(f"\n\n{'='*70}")
        print(f"  ⚠️  不合格 Alpha 详情 ({len(failing)} 个)")
        print(f"{'='*70}")
        for item in sorted(failing, key=lambda x: x.get("alpha", {}).get("is", {}).get("fitness", 0), reverse=True):
            is_d = item["alpha"]["is"]
            reasons = ", ".join(get_fail_reasons(item["alpha"]))
            print(f"    {item.get('name', ''):<30} Sharpe={is_d.get('sharpe', 0):.3f} "
                  f"Fitness={is_d.get('fitness', 0):.3f} "
                  f"TO={is_d.get('turnover', 0)*100:.1f}%  ❌ {reasons}")

    # 改进建议
    print(f"\n\n  💡 改进建议:")
    if fail_reasons.get("LOW_FITNESS", 0) > fail_reasons.get("LOW_SHARPE", 0):
        print("    - 主要失败原因是 LOW_FITNESS，建议：")
        print("      · 优先使用基本面 Alpha（换手率 1-5%）")
        print("      · 对技术 Alpha 增加 decay（≥15）以降低换手率")
        print("      · 目标换手率 ≤ 15%")
    if fail_reasons.get("LOW_SHARPE", 0) > 0:
        print("    - 部分 Alpha LOW_SHARPE（Sharpe < 1.25），建议：")
        print("      · 增加行业内中性化（SUBINDUSTRY）")
        print("      · 尝试多因子组合（降低单因子噪声）")
    if fail_reasons.get("HIGH_TURNOVER", 0) > 0:
        print("    - 部分 Alpha HIGH_TURNOVER（>70%），建议：")
        print("      · 删除短窗口技术因子（<20 天）")
        print("      · 大幅增加 decay（≥20）")

    return qualifying


def export_csv(items: list):
    """导出 CSV 报告"""
    out = DATA_DIR / "results_analysis.csv"
    fieldnames = ["id", "name", "expr", "category", "sharpe", "fitness",
                  "turnover_pct", "returns_pct", "drawdown_pct", "status",
                  "fail_reasons", "source"]
    rows = []
    for item in items:
        is_d = item.get("alpha", {}).get("is", {})
        if not is_d:
            continue
        rows.append({
            "id": item.get("alpha", {}).get("id", ""),
            "name": item.get("name", ""),
            "expr": item.get("expr", ""),
            "category": item.get("category", ""),
            "sharpe": is_d.get("sharpe", 0) or 0,
            "fitness": is_d.get("fitness", 0) or 0,
            "turnover_pct": (is_d.get("turnover", 0) or 0) * 100,
            "returns_pct": (is_d.get("returns", 0) or 0) * 100,
            "drawdown_pct": (is_d.get("drawdown", 0) or 0) * 100,
            "status": "QUALIFYING" if all_checks_pass(item.get("alpha", {})) else "FAILING",
            "fail_reasons": "|".join(get_fail_reasons(item.get("alpha", {}))),
            "source": item.get("_source", ""),
        })
    rows.sort(key=lambda x: x["fitness"], reverse=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n📄 CSV 报告导出至: {out}")


def main():
    parser = argparse.ArgumentParser(description="Alpha 结果分析与报告")
    parser.add_argument("--category", type=str, default=None,
                        help="只显示指定类别的 Alpha")
    parser.add_argument("--show-fails", action="store_true",
                        help="显示不合格 Alpha 详情")
    parser.add_argument("--export", action="store_true",
                        help="导出 CSV 报告")
    args = parser.parse_args()

    items = load_all_results()
    if not items:
        print("❌ 未找到任何结果文件")
        print(f"   请先运行: python src/run_all_agents.py")
        sys.exit(0)

    print(f"  已加载 {len(items)} 个 Alpha 结果（来自 {RESULTS_DIR}）")

    qualifying = print_full_report(items,
                                   show_fails=args.show_fails,
                                   filter_category=args.category)

    if args.export:
        export_csv(items)

    qualifying_count = len(qualifying)
    target = 60
    if qualifying_count >= target:
        print(f"\n\n🎉 已有 {qualifying_count} 个合格 Alpha（目标 {target}）！")
        print("  运行以下命令提交：")
        print("    python src/auto_submit.py")
    else:
        print(f"\n\n⚠️  当前 {qualifying_count} 个合格，还需 {target - qualifying_count} 个")
        print("  运行以下命令继续测试：")
        print("    python src/run_all_agents.py")


if __name__ == "__main__":
    main()

