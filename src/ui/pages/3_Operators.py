"""
3_Operators.py — 运算符参考手册：搜索、分类浏览、常用数据字段速查
"""
import sys
import json
import streamlit as st
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
UI_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(UI_DIR))

OPERATORS_FILE = ROOT / "operators_full.json"

st.set_page_config(page_title="Operators", page_icon="📚", layout="wide")
st.title("📚 Operators 参考手册")
st.caption("全部 66 个 WorldQuant BRAIN Fast Expression 运算符，搜索 · 分类 · 复制")


@st.cache_data
def load_operators() -> list:
    with open(OPERATORS_FILE, encoding="utf-8") as f:
        return json.load(f)


ops = load_operators()

# ── Sidebar: Search & Filter ──────────────────────────────────────────────────
with st.sidebar:
    st.header("🔍 筛选")
    search = st.text_input("搜索运算符名称或描述", placeholder="例: rank, ts_delta, corr")

    categories = sorted(set(op.get("category", "Other") for op in ops))
    sel_cats = st.multiselect("类别", categories, default=categories)

    levels = sorted(set(op.get("level", "ALL") for op in ops))
    sel_levels = st.multiselect("Level", levels, default=levels)

    st.markdown("---")
    st.metric("运算符总数", len(ops))
    st.metric("已选", len([
        op for op in ops
        if op.get("category", "Other") in sel_cats
        and op.get("level", "ALL") in sel_levels
        and (not search or search.lower() in op["name"].lower() or search.lower() in op.get("description", "").lower())
    ]))

# ── Filter operators ──────────────────────────────────────────────────────────
filtered = [
    op for op in ops
    if op.get("category", "Other") in sel_cats
    and op.get("level", "ALL") in sel_levels
    and (
        not search
        or search.lower() in op["name"].lower()
        or search.lower() in op.get("description", "").lower()
        or search.lower() in op.get("definition", "").lower()
    )
]

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_browse, tab_table, tab_fields = st.tabs(["🗂️ 分类浏览", "📋 表格视图", "🏷️ 数据字段速查"])

# ── Tab 1: Card-style browsing by category ────────────────────────────────────
with tab_browse:
    if not filtered:
        st.warning("没有匹配的运算符，请调整搜索条件。")
    else:
        # Group by category
        by_cat: dict[str, list] = {}
        for op in filtered:
            cat = op.get("category", "Other")
            by_cat.setdefault(cat, []).append(op)

        for cat, cat_ops in sorted(by_cat.items()):
            st.markdown(f"### {cat}  `{len(cat_ops)}`")
            # 2-column grid
            pairs = [cat_ops[i:i+2] for i in range(0, len(cat_ops), 2)]
            for pair in pairs:
                cols = st.columns(2)
                for col, op in zip(cols, pair):
                    with col:
                        with st.container(border=True):
                            st.markdown(f"#### `{op['name']}`")
                            st.code(op.get("definition", op["name"]), language="text")
                            st.caption(op.get("description", ""))
                            if op.get("documentation"):
                                doc_url = f"https://platform.worldquantbrain.com{op['documentation']}"
                                st.markdown(f"[📖 文档]({doc_url})")

# ── Tab 2: Table view ─────────────────────────────────────────────────────────
with tab_table:
    import pandas as pd
    table_data = [
        {
            "名称": op["name"],
            "类别": op.get("category", ""),
            "定义": op.get("definition", ""),
            "说明": op.get("description", ""),
            "Level": op.get("level", "ALL"),
        }
        for op in filtered
    ]
    st.dataframe(
        pd.DataFrame(table_data),
        use_container_width=True,
        hide_index=True,
        column_config={
            "名称":  st.column_config.TextColumn(width="small"),
            "类别":  st.column_config.TextColumn(width="small"),
            "定义":  st.column_config.TextColumn(width="medium"),
            "说明":  st.column_config.TextColumn(width="large"),
        },
    )

# ── Tab 3: Data Fields Quick Reference ───────────────────────────────────────
with tab_fields:
    st.markdown("""
## 📊 常用数据字段速查

以下字段可直接在 Fast Expression 中使用（大小写敏感，全部小写）。

---

### 💰 价格 & 市场数据（日频更新，换手率高）
""")
    price_fields = [
        ("close",    "收盘价",       "最常用，动量/反转因子基础"),
        ("open",     "开盘价",       "隔夜跳空分析"),
        ("high",     "最高价",       "价格区间分析"),
        ("low",      "最低价",       "价格区间分析"),
        ("vwap",     "成交量加权均价", "机构交易基准价"),
        ("volume",   "成交量",       "流动性代理，价量分析"),
        ("returns",  "日收益率",     "= (close-close[-1])/close[-1]"),
        ("cap",      "市值",         "市值加权 / 规模因子"),
        ("adv5",     "5日均成交量",   "短期流动性"),
        ("adv10",    "10日均成交量",  "中期流动性"),
        ("adv20",    "20日均成交量",  "最常用流动性代理"),
        ("adv60",    "60日均成交量",  "长期流动性"),
    ]
    import pandas as pd
    st.dataframe(
        pd.DataFrame(price_fields, columns=["字段", "含义", "说明"]),
        use_container_width=True, hide_index=True,
    )

    st.markdown("""
---
### 📑 基本面数据（季度更新，换手率极低 1-5%）
""")
    fundamental_fields = [
        ("assets",              "总资产",      "资产负债表"),
        ("liabilities",         "总负债",      "资产负债表，杠杆因子常用"),
        ("equity",              "股东权益",    "assets - liabilities"),
        ("sales",               "营业收入",    "利润表，增长因子常用"),
        ("revenue",             "营收",        "同 sales，部分数据集"),
        ("operating_income",    "营业利润",    "利润表，盈利能力"),
        ("net_income",          "净利润",      "利润表"),
        ("ebitda",              "息税折旧摊销前利润", "盈利能力"),
        ("gross_profit",        "毛利润",      "sales - COGS"),
        ("capex",               "资本支出",    "投资活动"),
        ("cash",                "现金及现金等价物", "流动性"),
        ("debt",                "总债务",      "有息负债"),
        ("current_assets",      "流动资产",    "短期资产"),
        ("current_liabilities", "流动负债",    "短期负债，流动比率"),
        ("book_value",          "账面价值",    "股东权益账面值"),
        ("shares_outstanding",  "流通股数",    "EPS 计算"),
        ("dividends",           "股息",        "股息收益率因子"),
        ("ppe",                 "物业厂房设备净值", "固定资产"),
        ("goodwill",            "商誉",        "并购溢价资产"),
        ("retained_earnings",   "留存收益",    "盈利积累"),
    ]
    st.dataframe(
        pd.DataFrame(fundamental_fields, columns=["字段", "含义", "说明"]),
        use_container_width=True, hide_index=True,
    )

    st.markdown("""
---
### 🧮 常用表达式模式

| 模式 | 表达式 | 说明 |
|------|--------|------|
| 杠杆率 | `rank(liabilities/assets)` | 高杠杆 → 高风险溢价 |
| ROA | `rank(operating_income/assets)` | 资产回报率 |
| P/B 倒数 | `rank(book_value/cap)` | 价值因子 |
| 动量 5日 | `rank(-ts_delta(close, 5))` | 短期反转 |
| 动量 20日 | `rank(ts_delta(close, 20))` | 中期动量 |
| 波动率 | `rank(-ts_std_dev(returns, 20))` | 低波动溢价 |
| 价量背离 | `rank(-ts_corr(close, volume, 10))` | 价量相关性 |
| 行业内动量 | `group_rank(-ts_corr(returns, adv20, 10), sector)` | 行业中性 |
| TS-Rank 基本面 | `rank(ts_rank(operating_income, 252))` | 盈利改善趋势 |
| 复合因子 | `rank(0.5*rank(liabilities/assets) + 0.5*rank(-ts_std_dev(returns,20)))` | 组合因子 |
""")

    st.markdown("""
---
### ⚙️ 分组变量（用于 group_rank / group_neutralize）

| 变量 | 说明 |
|------|------|
| `sector` | GICS 行业（11 个一级） |
| `industry` | GICS 行业组（约 25 个） |
| `subindustry` | GICS 子行业（约 160 个） |
| `country` | 国家（多区域时使用） |
""")
