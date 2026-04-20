"""
4_Comparison.py — 多 Alpha 对比分析：雷达图、指标柱状图、表达式并排对比
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

from utils.result_loader import load_all_results
from utils.charts import radar_comparison, bar_comparison

st.set_page_config(page_title="Comparison", page_icon="⚖️", layout="wide")
st.title("⚖️ Alpha Comparison")
st.caption("多 Alpha 雷达图对比 · 指标横向分析 · 表达式 & 设置并排展示")

if "comparison_list" not in st.session_state:
    st.session_state.comparison_list = []

# ── Add from history results ──────────────────────────────────────────────────
with st.sidebar:
    st.header("➕ 添加 Alpha")

    with st.expander("从历史结果中选择", expanded=True):
        df_hist = load_all_results()
        if not df_hist.empty:
            opts = [
                f"{row['alpha_id']}  Sharpe:{row['sharpe']:.2f}  {row['expr'][:40]}"
                for _, row in df_hist.head(200).iterrows()
            ]
            row_map = {opt: row for opt, (_, row) in zip(opts, df_hist.head(200).iterrows())}

            sel_from_hist = st.selectbox("选择 Alpha", ["(不选择)"] + opts)
            if sel_from_hist != "(不选择)" and st.button("加入对比", use_container_width=True):
                row = row_map[sel_from_hist]
                existing_ids = [x["id"] for x in st.session_state.comparison_list]
                if row["alpha_id"] not in existing_ids:
                    st.session_state.comparison_list.append({
                        "id": row["alpha_id"],
                        "name": row["name"] or row["alpha_id"],
                        "expr": row["expr"],
                        "is": {
                            "sharpe": row["sharpe"],
                            "fitness": row["fitness"],
                            "turnover": row["turnover"],
                            "returns": row["returns"],
                            "drawdown": row.get("drawdown", 0),
                        },
                        "settings": {
                            "neutralization": row["neutralization"],
                            "decay": row["decay"],
                            "truncation": row["truncation"],
                            "universe": row["universe"],
                        },
                    })
                    st.success("已添加")
                else:
                    st.info("已在列表中")
        else:
            st.info("没有历史数据")

    st.markdown("---")
    if st.button("🗑️ 清空对比列表", use_container_width=True):
        st.session_state.comparison_list = []
        st.rerun()

# ── Current comparison list ───────────────────────────────────────────────────
comp_list = st.session_state.comparison_list

if not comp_list:
    st.info(
        "对比列表为空。\n\n"
        "请在 **🧪 Alpha Lab** 提交结果后点击「加入对比列表」，"
        "或在 **📊 Explorer** 的详情 Tab 中添加，"
        "或在左侧边栏从历史记录选择。"
    )
    st.stop()

st.markdown(f"**当前对比列表：{len(comp_list)} 个 Alpha**")

# ── List management ───────────────────────────────────────────────────────────
with st.expander("📝 管理对比列表", expanded=False):
    for i, rec in enumerate(comp_list):
        is_d = rec.get("is", {})
        col_a, col_b = st.columns([5, 1])
        col_a.markdown(
            f"**[{i+1}]** `{rec['expr'][:70]}{'...' if len(rec['expr'])>70 else ''}`  "
            f"　Sharpe: `{is_d.get('sharpe', 0):.3f}`  "
            f"Fitness: `{is_d.get('fitness', 0):.3f}`"
        )
        if col_b.button("移除", key=f"rm_{i}"):
            st.session_state.comparison_list.pop(i)
            st.rerun()

st.markdown("---")

# ── Radar chart ───────────────────────────────────────────────────────────────
st.markdown("### 🕸️ 多维度雷达图")
st.caption("所有维度归一化到 [0, 1]：Sharpe÷3，Fitness÷2，Returns÷0.3，Low Turnover = 1 - Turnover/0.7，Low Drawdown = 1 - Drawdown/0.3")
st.plotly_chart(radar_comparison(comp_list), use_container_width=True)

# ── Bar charts ────────────────────────────────────────────────────────────────
st.markdown("### 📊 指标柱状对比")
bc1, bc2 = st.columns(2)
with bc1:
    st.plotly_chart(
        bar_comparison(comp_list, "sharpe", threshold=1.25, higher_is_better=True),
        use_container_width=True,
    )
    st.plotly_chart(
        bar_comparison(comp_list, "returns", higher_is_better=True),
        use_container_width=True,
    )
with bc2:
    st.plotly_chart(
        bar_comparison(comp_list, "fitness", threshold=1.0, higher_is_better=True),
        use_container_width=True,
    )
    st.plotly_chart(
        bar_comparison(comp_list, "turnover", threshold=0.70, higher_is_better=False),
        use_container_width=True,
    )

# ── Side-by-side table ────────────────────────────────────────────────────────
st.markdown("### 📋 指标汇总表")
rows = []
for rec in comp_list:
    is_d = rec.get("is", {})
    settings = rec.get("settings", {})
    sharpe = is_d.get("sharpe", 0) or 0
    fitness = is_d.get("fitness", 0) or 0
    turnover = is_d.get("turnover", 0) or 0
    returns = is_d.get("returns", 0) or 0
    drawdown = is_d.get("drawdown", 0) or 0
    ok = sharpe >= 1.25 and fitness >= 1.0 and 0.01 <= turnover <= 0.70
    rows.append({
        "Status":        "✅" if ok else "❌",
        "Name / ID":     rec.get("name") or rec.get("id", ""),
        "Sharpe":        round(sharpe, 3),
        "Fitness":       round(fitness, 3),
        "Turnover":      f"{turnover:.1%}",
        "Returns":       f"{returns:.2%}",
        "Drawdown":      f"{drawdown:.2%}",
        "Neutral":       settings.get("neutralization", ""),
        "Decay":         settings.get("decay", ""),
        "Expression":    rec.get("expr", ""),
    })
st.dataframe(
    pd.DataFrame(rows),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Expression": st.column_config.TextColumn(width="large"),
        "Sharpe":     st.column_config.NumberColumn(format="%.3f"),
        "Fitness":    st.column_config.NumberColumn(format="%.3f"),
    },
)

# ── Expression diff ───────────────────────────────────────────────────────────
st.markdown("### 🔤 表达式并排展示")
expr_cols = st.columns(min(len(comp_list), 4))
for col, rec in zip(expr_cols, comp_list):
    is_d = rec.get("is", {})
    with col:
        st.markdown(f"**{rec.get('name') or rec.get('id', 'Alpha')}**")
        st.code(rec.get("expr", ""), language="text")
        settings = rec.get("settings", {})
        st.caption(
            f"neutral: {settings.get('neutralization', 'N/A')}  "
            f"decay: {settings.get('decay', 'N/A')}  "
            f"trunc: {settings.get('truncation', 'N/A')}"
        )
        sh = is_d.get("sharpe", 0) or 0
        fi = is_d.get("fitness", 0) or 0
        to = is_d.get("turnover", 0) or 0
        ok_icon = "✅" if sh >= 1.25 and fi >= 1.0 else "❌"
        st.markdown(
            f"{ok_icon} Sharpe `{sh:.3f}` · Fitness `{fi:.3f}` · Turnover `{to:.1%}`"
        )
