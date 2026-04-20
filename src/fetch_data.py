"""
fetch_data.py - 抓取示例数据集信息并分析可用字段
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from brain_client import BrainClient

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

FIELD_QUERIES = [
    ("close",             "价格"),
    ("volume",            "成交量"),
    ("returns",           "收益率"),
    ("earnings",          "盈利/EPS"),
    ("assets",            "资产"),
    ("liabilities",       "负债"),
    ("sales",             "营收"),
    ("operating_income",  "运营利润"),
    ("sentiment",         "情绪"),
    ("inventory",         "库存"),
    ("debt",              "负债/债务"),
    ("dividend",          "股息"),
    ("analyst",           "分析师"),
    ("cap",               "市值"),
    ("cashflow",          "现金流"),
]


def fetch_and_save():
    client = BrainClient()
    auth = client.check_auth()
    print(f"Auth: {auth['status']} | User: {auth['body'].get('user', {}).get('id', 'N/A')}")

    all_fields = {}

    for query, label in FIELD_QUERIES:
        print(f"  搜索 '{query}' ({label})...", end=" ")
        try:
            result = client.search_datafields(query, limit=10)
            fields = result if isinstance(result, list) else result.get("results", [])
            all_fields[query] = {
                "label": label,
                "count": len(fields),
                "fields": fields
            }
            print(f"找到 {len(fields)} 个字段")
        except Exception as e:
            print(f"失败: {e}")
            all_fields[query] = {"label": label, "count": 0, "fields": [], "error": str(e)}

    out = OUTPUT_DIR / "datafields_catalog.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_fields, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 数据字段目录已保存: {out}")

    # 生成摘要文本
    summary_lines = ["# 可用数据字段目录\n"]
    for query, info in all_fields.items():
        summary_lines.append(f"\n## {info['label']} (搜索: {query})")
        for f in info.get("fields", []):
            name = f.get("id") or f.get("name") or str(f)[:60]
            desc = f.get("description") or f.get("def") or ""
            dataset = f.get("datasetId") or f.get("dataset") or ""
            summary_lines.append(f"  - `{name}` [{dataset}] {desc[:80]}")
        if not info.get("fields"):
            summary_lines.append("  (无结果)")

    summary_out = OUTPUT_DIR / "datafields_summary.md"
    with open(summary_out, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
    print(f"✅ 摘要 Markdown 已保存: {summary_out}")
    return all_fields


if __name__ == "__main__":
    fetch_and_save()
