"""
2_Explorer.py — 历史 Alpha 结果浏览器：筛选、散点图、分布分析、数据表
"""
import sys
import json
import streamlit as st
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
UI_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(UI_DIR))

from utils.result_loader import load_all_results, _load_results_cached
from utils.charts import (
    scatter_sharpe_fitness,
    scatter_turnover_returns,
    scatter_sharpe_turnover,
    histogram_metrics,
    histogram_turnover,
    category_pie,
)

st.set_page_config(page_title="Explorer", page_icon="📊", layout="wide")
st.title("📊 Alpha Explorer")
st.caption("浏览全部历史回测结果，多维度筛选与可视化分析")

if "comparison_list" not in st.session_state:
    st.session_state.comparison_list = []

# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner("加载历史数据…"):
    df_raw = load_all_results()

if df_raw.empty:
    st.error("没有找到历史数据。请确保 results/ 目录中有 JSON 文件。")
    st.stop()

st.success(f"已加载 **{len(df_raw)}** 条唯一 Alpha 记录（去重后）")

# ── Sidebar: Filters ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔍 筛选条件")

    search_text = st.text_input("表达式关键词", placeholder="例: ts_delta, liabilities")

    sharpe_min, sharpe_max = float(df_raw["sharpe"].min()), float(df_raw["sharpe"].max())
    sharpe_range = st.slider(
        "Sharpe 范围",
        min_value=round(sharpe_min, 2),
        max_value=round(sharpe_max, 2) + 0.01,
        value=(round(sharpe_min, 2), round(sharpe_max, 2) + 0.01),
        step=0.05,
    )

    fitness_min, fitness_max = float(df_raw["fitness"].min()), float(df_raw["fitness"].max())
    fitness_range = st.slider(
        "Fitness 范围",
        min_value=round(fitness_min, 2),
        max_value=round(fitness_max, 2) + 0.01,
        value=(round(fitness_min, 2), round(fitness_max, 2) + 0.01),
        step=0.05,
    )

    turnover_range = st.slider(
        "Turnover 范围",
        min_value=0.0, max_value=1.0,
        value=(0.0, 1.0), step=0.01,
        format="%.2f",
    )

    categories = sorted([c for c in df_raw["category"].unique() if c])
    if categories:
        sel_cats = st.multiselect("类别", categories, default=categories)
    else:
        sel_cats = []

    pass_filter = st.radio(
        "通过状态",
        ["全部", "仅全部通过 ✅", "仅有失败项 ❌"],
        index=0,
    )

    neutralization_opts = sorted(df_raw["neutralization"].unique().tolist())
    sel_neutral = st.multiselect("Neutralization", neutralization_opts, default=neutralization_opts)

    st.markdown("---")
    if st.button("🔄 重新加载数据", use_container_width=True):
        _load_results_cached.clear()
        st.rerun()

# ── Apply filters ─────────────────────────────────────────────────────────────
df = df_raw.copy()

if search_text:
    mask = df["expr"].str.contains(search_text, case=False, na=False)
    mask |= df["name"].str.contains(search_text, case=False, na=False)
    mask |= df["hypothesis"].str.contains(search_text, case=False, na=False)
    df = df[mask]

df = df[
    (df["sharpe"] >= sharpe_range[0]) & (df["sharpe"] <= sharpe_range[1]) &
    (df["fitness"] >= fitness_range[0]) & (df["fitness"] <= fitness_range[1]) &
    (df["turnover"] >= turnover_range[0]) & (df["turnover"] <= turnover_range[1])
]

if sel_cats:
    df = df[df["category"].isin(sel_cats) | ~df_raw["category"].isin(
        [c for c in df_raw["category"].unique() if c]
    )]

if sel_neutral:
    df = df[df["neutralization"].isin(sel_neutral)]

if pass_filter == "仅全部通过 ✅":
    df = df[df["all_pass"]]
elif pass_filter == "仅有失败项 ❌":
    df = df[~df["all_pass"]]

n_pass = df["all_pass"].sum()
st.markdown(
    f"**筛选结果：{len(df)} 条**　（✅ 全部通过: {n_pass}　❌ 有失败: {len(df)-n_pass}）"
)

if df.empty:
    st.warning("当前筛选条件下没有结果，请调整筛选范围。")
    st.stop()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_scatter, tab_dist, tab_table, tab_detail = st.tabs([
    "📈 散点图分析", "📊 分布分析", "📋 数据表格", "🔬 详情查看"
])

# ── Tab 1: Scatter plots ──────────────────────────────────────────────────────
with tab_scatter:
    sc1, sc2 = st.columns(2)
    with sc1:
        st.plotly_chart(scatter_sharpe_fitness(df), use_container_width=True)
    with sc2:
        st.plotly_chart(scatter_turnover_returns(df), use_container_width=True)

    st.plotly_chart(scatter_sharpe_turnover(df), use_container_width=True)

    # Summary stats
    st.markdown("### 📐 关键统计")
    stat_cols = ["sharpe", "fitness", "turnover", "returns", "drawdown"]
    stat_df = df[stat_cols].describe().round(4)
    st.dataframe(stat_df, use_container_width=True)

# ── Tab 2: Distributions ─────────────────────────────────────────────────────
with tab_dist:
    d1, d2 = st.columns(2)
    with d1:
        st.plotly_chart(histogram_metrics(df), use_container_width=True)
        # Pass rate by Sharpe quartile
        df_q = df.copy()
        df_q["sharpe_bin"] = pd.cut(df_q["sharpe"], bins=5).astype(str)
        pass_by_bin = df_q.groupby("sharpe_bin")["all_pass"].mean().reset_index()
        pass_by_bin.columns = ["Sharpe 区间", "通过率"]
        st.markdown("**Sharpe 分段通过率**")
        st.dataframe(pass_by_bin, use_container_width=True, hide_index=True)
    with d2:
        st.plotly_chart(histogram_turnover(df), use_container_width=True)
        # Category pie
        if "category" in df.columns:
            st.plotly_chart(category_pie(df), use_container_width=True)

    # Neutralization breakdown
    st.markdown("### ⚖️ 按 Neutralization 分析")
    neutral_stats = (
        df.groupby("neutralization")[["sharpe", "fitness", "turnover"]]
        .mean()
        .round(3)
    )
    neutral_stats["count"] = df.groupby("neutralization").size()
    neutral_stats["pass_rate"] = df.groupby("neutralization")["all_pass"].mean().round(3)
    st.dataframe(neutral_stats, use_container_width=True)

# ── Tab 3: Data Table ─────────────────────────────────────────────────────────
with tab_table:
    display_cols = [
        "name", "expr", "category", "sharpe", "fitness", "turnover",
        "returns", "drawdown", "all_pass", "neutralization", "decay", "alpha_id",
    ]
    display_df = df[display_cols].copy()
    display_df["all_pass"] = display_df["all_pass"].map({True: "✅", False: "❌"})
    display_df["turnover"] = (display_df["turnover"] * 100).round(2).astype(str) + "%"
    display_df["returns"]  = (display_df["returns"] * 100).round(2).astype(str) + "%"

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "expr":     st.column_config.TextColumn("Expression", width="large"),
            "sharpe":   st.column_config.NumberColumn("Sharpe",  format="%.3f"),
            "fitness":  st.column_config.NumberColumn("Fitness", format="%.3f"),
            "alpha_id": st.column_config.TextColumn("ID", width="small"),
        },
    )

    # Export
    csv = df[display_cols].to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ 下载 CSV",
        data=csv,
        file_name="alpha_results.csv",
        mime="text/csv",
    )

# ── Tab 4: Detail View ────────────────────────────────────────────────────────
with tab_detail:
    st.markdown("### 选择 Alpha 查看详情 & 加入对比")

    # Pick by name or alpha_id
    options = [
        f"{row['name'] or row['alpha_id']}  |  Sharpe:{row['sharpe']:.2f}  Fitness:{row['fitness']:.2f}  {row['expr'][:50]}"
        for _, row in df.head(100).iterrows()
    ]
    id_map = {opt: row["alpha_id"] for opt, (_, row) in zip(options, df.head(100).iterrows())}
    name_map = {opt: row for opt, (_, row) in zip(options, df.head(100).iterrows())}

    selected = st.selectbox("选择 Alpha", options)

    if selected:
        row = name_map[selected]
        dc1, dc2, dc3, dc4 = st.columns(4)
        dc1.metric("Sharpe",   f"{row['sharpe']:.3f}")
        dc2.metric("Fitness",  f"{row['fitness']:.3f}")
        dc3.metric("Turnover", f"{row['turnover']:.1%}")
        dc4.metric("Returns",  f"{row['returns']:.2%}")

        st.markdown(f"**表达式：** `{row['expr']}`")
        st.markdown(
            f"**设置：** delay={row.get('decay', 'N/A')}  "
            f"neutral={row['neutralization']}  "
            f"universe={row['universe']}"
        )

        if row.get("hypothesis"):
            st.info(f"💡 假说：{row['hypothesis']}")

        # Checks
        if row.get("checks_json"):
            checks = json.loads(row["checks_json"])
            check_rows = [
                {"Check": k, "Result": ("✅ PASS" if v == "PASS" else ("⏳ PENDING" if v == "PENDING" else "❌ " + v))}
                for k, v in checks.items()
            ]
            st.dataframe(check_rows, use_container_width=True, hide_index=True)

        if st.button("➕ 加入对比列表", key="detail_add"):
            rec = {
                "id": row["alpha_id"],
                "name": row["name"] or row["alpha_id"],
                "expr": row["expr"],
                "is": {
                    "sharpe": row["sharpe"], "fitness": row["fitness"],
                    "turnover": row["turnover"], "returns": row["returns"],
                    "drawdown": row.get("drawdown", 0),
                },
            }
            existing_ids = [x["id"] for x in st.session_state.comparison_list]
            if row["alpha_id"] not in existing_ids:
                st.session_state.comparison_list.append(rec)
                st.success(f"✅ 已添加，对比列表共 {len(st.session_state.comparison_list)} 个")
            else:
                st.info("已在对比列表中")
