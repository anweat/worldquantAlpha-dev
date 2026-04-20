"""
fetch_historical.py - 历史数据抓取与分析工具
功能：
  1. 抓取 BRAIN 平台可用数据字段目录（分类搜索）
  2. 分析 results/ 目录中已有的测试结果（找出哪类 Alpha 效果最好）
  3. 获取用户历史 Alpha 提交记录
  4. 生成推荐报告

运行方式：
    python src/fetch_historical.py
"""
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

sys.path.insert(0, str(Path(__file__).parent))
from brain_client import BrainClient

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
DATA_DIR.mkdir(exist_ok=True)

# 搜索关键词分类（按数据类型）
FIELD_QUERIES = [
    # 价格 / 市场
    ("close",             "收盘价"),
    ("open",              "开盘价"),
    ("volume",            "成交量"),
    ("vwap",              "成交量加权均价"),
    ("returns",           "日收益率"),
    ("turnover_ratio",    "换手率"),
    # 基本面 - 盈利
    ("earnings",          "净利润/EPS"),
    ("operating_income",  "运营利润/EBIT"),
    ("revenue",           "营业收入"),
    ("sales",             "销售额"),
    ("ebitda",            "EBITDA"),
    # 基本面 - 资产负债
    ("assets",            "总资产"),
    ("liabilities",       "总负债"),
    ("equity",            "股东权益"),
    ("debt",              "有息债务"),
    ("cash",              "现金及等价物"),
    ("inventory",         "存货"),
    # 基本面 - 现金流
    ("cashflow",          "现金流"),
    ("capex",             "资本支出"),
    # 市场估值
    ("market_cap",        "市值"),
    ("book_value",        "账面价值"),
    ("dividend",          "股息"),
    # 分析师/情绪
    ("analyst",           "分析师评级"),
    ("sentiment",         "情绪/舆情"),
    ("short",             "做空数据"),
    # 宏观/行业
    ("beta",              "Beta系数"),
    ("sector",            "行业分类"),
]


def fetch_data_catalog(client: BrainClient) -> dict:
    """抓取数据字段目录"""
    print("\n" + "=" * 60)
    print("📦 抓取 BRAIN 数据字段目录")
    print("=" * 60)

    all_fields = {}

    for query, label in FIELD_QUERIES:
        print(f"  搜索 '{query}' ({label})...", end=" ", flush=True)
        try:
            result = client.search_datafields(query, limit=10)
            fields = result if isinstance(result, list) else result.get("results", [])
            all_fields[query] = {"label": label, "count": len(fields), "fields": fields}
            print(f"找到 {len(fields)} 个字段")
        except Exception as e:
            print(f"失败: {e}")
            all_fields[query] = {"label": label, "count": 0, "fields": [], "error": str(e)}

    out = DATA_DIR / "datafields_catalog_full.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_fields, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 数据字段目录保存至: {out}")
    return all_fields


def analyze_local_results() -> dict:
    """分析 results/ 目录中已有的测试结果"""
    print("\n" + "=" * 60)
    print("📊 分析历史 Alpha 测试结果")
    print("=" * 60)

    result_files = sorted(RESULTS_DIR.glob("*.json"))
    if not result_files:
        print("  未找到任何结果文件")
        return {}

    # 合并所有结果（按 alpha id 去重）
    all_alphas = {}
    for f in result_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    alpha_id = item.get("alpha", {}).get("id")
                    if alpha_id:
                        all_alphas[alpha_id] = item
        except Exception as e:
            print(f"  读取 {f.name} 失败: {e}")

    print(f"  总计去重 Alpha 数: {len(all_alphas)}")

    # 统计分析
    stats = {
        "total": len(all_alphas),
        "qualifying": 0,
        "fail_sharpe": 0,
        "fail_fitness": 0,
        "fail_turnover_high": 0,
        "fail_turnover_low": 0,
        "category_stats": defaultdict(lambda: {"total": 0, "qualifying": 0}),
        "sharpe_dist": [],
        "fitness_dist": [],
        "turnover_dist": [],
        "qualifying_alphas": [],
        "top_by_fitness": [],
    }

    for alpha_id, item in all_alphas.items():
        is_data = item.get("alpha", {}).get("is", {})
        if not is_data:
            continue

        sharpe = is_data.get("sharpe", 0) or 0
        fitness = is_data.get("fitness", 0) or 0
        turnover = is_data.get("turnover", 0) or 0
        category = item.get("category", "未分类")

        stats["sharpe_dist"].append(sharpe)
        stats["fitness_dist"].append(fitness)
        stats["turnover_dist"].append(turnover)

        checks = is_data.get("checks", [])
        passed = all(c["result"] in ("PASS", "PENDING") for c in checks) and bool(checks)

        stats["category_stats"][category]["total"] += 1
        if passed:
            stats["qualifying"] += 1
            stats["category_stats"][category]["qualifying"] += 1
            stats["qualifying_alphas"].append({
                "id": alpha_id,
                "name": item.get("name", ""),
                "expr": item.get("expr", ""),
                "category": category,
                "sharpe": sharpe,
                "fitness": fitness,
                "turnover": turnover,
            })

        for chk in checks:
            if chk["result"] == "FAIL":
                if chk["name"] == "LOW_SHARPE":
                    stats["fail_sharpe"] += 1
                elif chk["name"] == "LOW_FITNESS":
                    stats["fail_fitness"] += 1
                elif chk["name"] == "HIGH_TURNOVER":
                    stats["fail_turnover_high"] += 1
                elif chk["name"] == "LOW_TURNOVER":
                    stats["fail_turnover_low"] += 1

    # 按 fitness 排序
    stats["top_by_fitness"] = sorted(
        stats["qualifying_alphas"], key=lambda x: x["fitness"], reverse=True
    )[:20]

    # 打印报告
    _print_analysis_report(stats)

    # 保存报告
    report_out = DATA_DIR / "historical_analysis.json"
    report_stats = {k: v for k, v in stats.items()
                    if k not in ("sharpe_dist", "fitness_dist", "turnover_dist")}
    report_stats["category_stats"] = dict(stats["category_stats"])
    with open(report_out, "w", encoding="utf-8") as f:
        json.dump(report_stats, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ 历史分析报告保存至: {report_out}")
    return stats


def _print_analysis_report(stats: dict):
    total = stats["total"]
    qualifying = stats["qualifying"]
    q_rate = qualifying / total * 100 if total > 0 else 0

    print(f"\n  总测试 Alpha: {total}")
    print(f"  合格 Alpha:   {qualifying}  ({q_rate:.1f}%)")
    print(f"\n  失败原因分布:")
    print(f"    LOW_SHARPE   : {stats['fail_sharpe']}")
    print(f"    LOW_FITNESS  : {stats['fail_fitness']}")
    print(f"    HIGH_TURNOVER: {stats['fail_turnover_high']}")
    print(f"    LOW_TURNOVER : {stats['fail_turnover_low']}")

    if stats["sharpe_dist"]:
        import statistics
        print(f"\n  Sharpe  均值={statistics.mean(stats['sharpe_dist']):.3f}  "
              f"中位={statistics.median(stats['sharpe_dist']):.3f}  "
              f"最高={max(stats['sharpe_dist']):.3f}")
        print(f"  Fitness 均值={statistics.mean(stats['fitness_dist']):.3f}  "
              f"中位={statistics.median(stats['fitness_dist']):.3f}  "
              f"最高={max(stats['fitness_dist']):.3f}")
        tv_pct = [t * 100 for t in stats["turnover_dist"]]
        print(f"  换手率  均值={statistics.mean(tv_pct):.1f}%  "
              f"中位={statistics.median(tv_pct):.1f}%")

    print(f"\n  各类别合格率:")
    for cat, cs in sorted(stats["category_stats"].items(),
                          key=lambda x: x[1]["qualifying"], reverse=True):
        rate = cs["qualifying"] / cs["total"] * 100 if cs["total"] > 0 else 0
        print(f"    {cat:<30} {cs['qualifying']:>3}/{cs['total']:<3} ({rate:.0f}%)")

    print(f"\n  🏆 Fitness 最高的合格 Alpha:")
    for i, a in enumerate(stats["top_by_fitness"][:10], 1):
        print(f"    {i:>2}. [{a['id']}] {a['name']:<28} "
              f"Sharpe={a['sharpe']:.3f} Fitness={a['fitness']:.3f} "
              f"TO={a['turnover']*100:.1f}%")


def fetch_user_history(client: BrainClient) -> dict:
    """获取用户历史 Alpha 提交记录"""
    print("\n" + "=" * 60)
    print("👤 获取用户历史 Alpha 记录")
    print("=" * 60)

    try:
        auth = client.check_auth()
        user_id = auth["body"].get("user", {}).get("id", "")
        if not user_id:
            print("  ⚠️  无法获取用户 ID")
            return {}

        print(f"  用户 ID: {user_id}")
        history = client.get_user_alphas(user_id, limit=100)
        alphas = history if isinstance(history, list) else history.get("results", [])
        print(f"  历史 Alpha 数: {len(alphas)}")

        # 统计状态
        by_status = defaultdict(int)
        by_grade = defaultdict(int)
        for a in alphas:
            by_status[a.get("status", "UNKNOWN")] += 1
            by_grade[a.get("grade", "UNKNOWN")] += 1

        print(f"\n  状态分布: {dict(by_status)}")
        print(f"  评级分布: {dict(by_grade)}")

        out = DATA_DIR / "user_alpha_history.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"user_id": user_id, "alphas": alphas}, f,
                      ensure_ascii=False, indent=2, default=str)
        print(f"\n  ✅ 用户历史保存至: {out}")
        return {"user_id": user_id, "alphas": alphas}

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return {}


def main():
    client = BrainClient()
    auth = client.check_auth()
    print(f"✅ 认证状态: {auth['status']}")
    if auth["status"] != 200:
        print("❌ 认证失败，请刷新 session")
        return

    # 1. 抓取数据字段目录
    fetch_data_catalog(client)

    # 2. 分析本地历史结果
    analyze_local_results()

    # 3. 获取用户历史提交
    fetch_user_history(client)

    print("\n\n🎉 历史数据抓取与分析完成！")
    print(f"   输出目录: {DATA_DIR}")


if __name__ == "__main__":
    main()

