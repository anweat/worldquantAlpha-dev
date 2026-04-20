"""
auto_submit.py - 自动提交合格 Alpha
功能：
  1. 扫描 results/ 目录中所有结果文件
  2. 找出全部检查通过（PASS 或 PENDING）的 Alpha
  3. 展示汇总列表供确认
  4. 支持批量自动提交
  5. 记录提交结果

运行方式：
    # 只显示合格列表，不提交
    python src/auto_submit.py --dry-run

    # 交互式确认后提交
    python src/auto_submit.py

    # 直接提交所有合格 Alpha（无确认）
    python src/auto_submit.py --yes
"""
import argparse
import io
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# Windows 终端 UTF-8 兼容处理
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

sys.path.insert(0, str(Path(__file__).parent))
from brain_client import BrainClient

RESULTS_DIR = Path(__file__).parent.parent / "results"
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def all_checks_pass(alpha_result: dict) -> bool:
    checks = alpha_result.get("is", {}).get("checks", [])
    if not checks:
        return False
    return all(c["result"] in ("PASS", "PENDING") for c in checks)


def load_qualifying_alphas() -> list:
    """从所有结果文件中加载合格 Alpha（按 alpha id 去重）"""
    result_files = sorted(RESULTS_DIR.glob("*.json"))
    seen_ids = set()
    qualifying = []

    for f in result_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for item in data:
                alpha_result = item.get("alpha", {})
                alpha_id = alpha_result.get("id")
                if not alpha_id or alpha_id in seen_ids:
                    continue
                seen_ids.add(alpha_id)

                if all_checks_pass(alpha_result):
                    is_data = alpha_result.get("is", {})
                    qualifying.append({
                        "id": alpha_id,
                        "name": item.get("name", ""),
                        "expr": item.get("expr", ""),
                        "category": item.get("category", ""),
                        "sharpe": is_data.get("sharpe", 0) or 0,
                        "fitness": is_data.get("fitness", 0) or 0,
                        "turnover": (is_data.get("turnover", 0) or 0) * 100,
                        "returns": (is_data.get("returns", 0) or 0) * 100,
                        "status": alpha_result.get("status", "UNSUBMITTED"),
                        "source_file": f.name,
                    })
        except Exception as e:
            print(f"  ⚠️  读取 {f.name} 出错: {e}")

    # 按 Fitness 降序排列
    qualifying.sort(key=lambda x: x["fitness"], reverse=True)
    return qualifying


def print_qualifying_table(qualifying: list):
    print(f"\n{'#'*68}")
    print(f"# 🎯 合格 Alpha 列表  (共 {len(qualifying)} 个)")
    print(f"{'#'*68}")
    print(f"\n  {'#':>3}  {'ID':<12} {'名称':<28} {'Sharpe':>7} {'Fitness':>8} "
          f"{'TO%':>6} {'Ret%':>7} {'状态':<15}")
    print("-" * 100)
    for i, a in enumerate(qualifying, 1):
        status_icon = "✅ UNSUBMITTED" if a["status"] == "UNSUBMITTED" else f"📤 {a['status']}"
        print(f"  {i:>3}. {a['id']:<12} {a['name']:<28} {a['sharpe']:>7.3f} "
              f"{a['fitness']:>8.3f} {a['turnover']:>5.1f}% {a['returns']:>6.1f}% {status_icon}")


def submit_alphas(client: BrainClient, qualifying: list, dry_run: bool = False) -> list:
    """提交尚未提交的合格 Alpha"""
    to_submit = [a for a in qualifying if a["status"] == "UNSUBMITTED"]
    results = []

    print(f"\n{'='*60}")
    print(f"📤 准备提交 {len(to_submit)} 个未提交的合格 Alpha")
    if dry_run:
        print("  （--dry-run 模式：仅展示，不实际提交）")
    print("=" * 60)

    for i, alpha in enumerate(to_submit, 1):
        print(f"\n[{i}/{len(to_submit)}] 提交: {alpha['name']}  [{alpha['id']}]")
        print(f"       Sharpe={alpha['sharpe']:.3f}  Fitness={alpha['fitness']:.3f}  "
              f"Turnover={alpha['turnover']:.1f}%")

        if dry_run:
            print("  ⏭️  跳过（dry-run 模式）")
            results.append({**alpha, "submit_result": "DRY_RUN"})
            continue

        try:
            resp = client.submit_alpha(alpha["id"])
            status = resp.get("status", 0)
            body = resp.get("body", {})

            if status in (200, 201, 202):
                print(f"  ✅ 提交成功！状态码: {status}")
                results.append({**alpha, "submit_result": "SUCCESS", "submit_response": resp})
            elif status == 409:
                print(f"  ℹ️  已提交过（409 Conflict）")
                results.append({**alpha, "submit_result": "ALREADY_SUBMITTED"})
            else:
                print(f"  ❌ 提交失败！状态码: {status}  响应: {body}")
                results.append({**alpha, "submit_result": f"FAILED_{status}", "submit_response": resp})

        except Exception as e:
            print(f"  ❌ 提交异常: {e}")
            results.append({**alpha, "submit_result": f"ERROR: {e}"})

        if i < len(to_submit):
            time.sleep(12)  # Increased from 2s to avoid 429 THROTTLED

    return results


def save_submission_log(results: list):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DATA_DIR / f"submission_log_{timestamp}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 提交记录保存至: {out}")
    return out


def main():
    parser = argparse.ArgumentParser(description="自动提交合格 Alpha")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示合格 Alpha 列表，不实际提交")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="跳过确认，直接提交所有合格 Alpha")
    parser.add_argument("--top", type=int, default=None,
                        help="只提交 Fitness 最高的 N 个")
    args = parser.parse_args()

    # 1. 加载合格 Alpha
    qualifying = load_qualifying_alphas()

    if not qualifying:
        print("❌ 未找到任何合格 Alpha")
        print(f"   请先运行: python src/run_all_agents.py")
        sys.exit(0)

    if args.top:
        qualifying = qualifying[:args.top]
        print(f"ℹ️  --top {args.top}: 只处理 Fitness 最高的 {args.top} 个")

    # 2. 展示列表
    print_qualifying_table(qualifying)

    unsubmitted = [a for a in qualifying if a["status"] == "UNSUBMITTED"]
    print(f"\n  未提交: {len(unsubmitted)}  |  已提交: {len(qualifying) - len(unsubmitted)}")

    if args.dry_run:
        print("\n✅ dry-run 完成，使用 --yes 参数执行实际提交")
        return

    if not unsubmitted:
        print("\n✅ 所有合格 Alpha 均已提交")
        return

    # 3. 确认提交
    if not args.yes:
        print(f"\n❓ 确认提交 {len(unsubmitted)} 个 Alpha? [y/N] ", end="", flush=True)
        ans = input().strip().lower()
        if ans not in ("y", "yes"):
            print("❎ 取消提交")
            return

    # 4. 连接 API 并提交
    client = BrainClient()
    auth = client.check_auth()
    if auth["status"] != 200:
        print("❌ 认证失败，请刷新 session")
        sys.exit(1)

    results = submit_alphas(client, qualifying, dry_run=False)
    save_submission_log(results)

    # 5. 最终统计
    success = sum(1 for r in results if r.get("submit_result") == "SUCCESS")
    print(f"\n\n{'='*60}")
    print(f"🎉 提交完成！成功: {success}/{len(results)}")


if __name__ == "__main__":
    main()

