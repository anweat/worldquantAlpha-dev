"""
charts.py — Reusable Plotly chart builders for the Alpha Studio UI.
"""
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

# Color palette
C = {
    "pass": "#00C853",
    "fail": "#FF1744",
    "warn": "#FFA726",
    "primary": "#5B9BD5",
    "purple": "#9B59B6",
    "bg": "#0E1117",
    "surface": "#1E1E2E",
}


def scatter_sharpe_fitness(df: pd.DataFrame, highlight_id: str = None) -> go.Figure:
    """Sharpe vs Fitness scatter colored by pass/fail, with submission thresholds."""
    df = df.copy()
    df["status"] = df["all_pass"].map({True: "✅ All Pass", False: "❌ Fail"})
    df["hover_text"] = df.apply(
        lambda r: (
            f"<b>{r['name'] or r['alpha_id']}</b><br>"
            f"Sharpe: {r['sharpe']:.3f} | Fitness: {r['fitness']:.3f}<br>"
            f"Turnover: {r['turnover']:.1%} | Returns: {r['returns']:.2%}<br>"
            f"<i>{str(r['expr'])[:80]}</i>"
        ),
        axis=1,
    )

    fig = px.scatter(
        df,
        x="sharpe",
        y="fitness",
        color="status",
        color_discrete_map={"✅ All Pass": C["pass"], "❌ Fail": C["fail"]},
        hover_name="name",
        custom_data=["hover_text"],
        title="Sharpe vs Fitness（全部历史 Alpha）",
        labels={"sharpe": "Sharpe Ratio", "fitness": "Fitness Score"},
        opacity=0.75,
    )
    fig.update_traces(
        hovertemplate="%{customdata[0]}<extra></extra>",
        marker_size=8,
    )

    # Submission threshold lines
    fig.add_hline(y=1.0, line_dash="dash", line_color=C["warn"],
                  annotation_text="Fitness ≥ 1.0", annotation_position="bottom right")
    fig.add_vline(x=1.25, line_dash="dash", line_color=C["warn"],
                  annotation_text="Sharpe ≥ 1.25", annotation_position="top left")

    # Highlight current alpha
    if highlight_id:
        rows = df[df["alpha_id"] == highlight_id]
        if not rows.empty:
            row = rows.iloc[0]
            fig.add_trace(go.Scatter(
                x=[row["sharpe"]], y=[row["fitness"]],
                mode="markers",
                marker=dict(size=18, symbol="star", color="gold",
                            line=dict(color="white", width=1)),
                name="⭐ 当前 Alpha",
                hovertemplate=f"<b>当前提交</b><br>Sharpe: {row['sharpe']:.3f}<br>Fitness: {row['fitness']:.3f}<extra></extra>",
            ))

    fig.update_layout(
        plot_bgcolor=C["bg"],
        paper_bgcolor=C["bg"],
        font_color="white",
        legend_title_text="",
        height=420,
    )
    return fig


def scatter_turnover_returns(df: pd.DataFrame) -> go.Figure:
    df = df.copy()
    df["status"] = df["all_pass"].map({True: "✅ All Pass", False: "❌ Fail"})

    fig = px.scatter(
        df,
        x="turnover",
        y="returns",
        color="status",
        color_discrete_map={"✅ All Pass": C["pass"], "❌ Fail": C["fail"]},
        hover_name="name",
        title="Turnover vs Annual Returns",
        labels={"turnover": "Turnover", "returns": "Annual Returns"},
        opacity=0.75,
    )
    fig.update_traces(marker_size=7)

    fig.add_vline(x=0.70, line_dash="dash", line_color="red",
                  annotation_text="HIGH_TURNOVER 上限 70%")
    fig.add_vline(x=0.01, line_dash="dash", line_color=C["warn"],
                  annotation_text="LOW_TURNOVER 下限 1%")

    fig.update_layout(
        xaxis_tickformat=".0%",
        yaxis_tickformat=".0%",
        plot_bgcolor=C["bg"],
        paper_bgcolor=C["bg"],
        font_color="white",
        height=420,
    )
    return fig


def scatter_sharpe_turnover(df: pd.DataFrame) -> go.Figure:
    df = df.copy()
    df["status"] = df["all_pass"].map({True: "✅ All Pass", False: "❌ Fail"})

    fig = px.scatter(
        df,
        x="turnover",
        y="sharpe",
        color="status",
        color_discrete_map={"✅ All Pass": C["pass"], "❌ Fail": C["fail"]},
        hover_name="name",
        title="Turnover vs Sharpe（换手-质量关系）",
        labels={"turnover": "Turnover", "sharpe": "Sharpe Ratio"},
        opacity=0.75,
    )
    fig.update_traces(marker_size=7)
    fig.add_hline(y=1.25, line_dash="dash", line_color=C["warn"],
                  annotation_text="Sharpe ≥ 1.25")
    fig.add_vline(x=0.70, line_dash="dash", line_color="red",
                  annotation_text="HIGH_TURNOVER 上限")

    fig.update_layout(
        xaxis_tickformat=".0%",
        plot_bgcolor=C["bg"],
        paper_bgcolor=C["bg"],
        font_color="white",
        height=380,
    )
    return fig


def histogram_metrics(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=df["sharpe"].dropna(), name="Sharpe",
        opacity=0.7, marker_color=C["primary"], nbinsx=30,
    ))
    fig.add_trace(go.Histogram(
        x=df["fitness"].dropna(), name="Fitness",
        opacity=0.7, marker_color=C["purple"], nbinsx=30,
    ))
    fig.update_layout(
        barmode="overlay",
        title="Sharpe & Fitness 分布",
        xaxis_title="Value", yaxis_title="Count",
        plot_bgcolor=C["bg"], paper_bgcolor=C["bg"], font_color="white",
        height=350,
    )
    return fig


def histogram_turnover(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Histogram(
        x=df["turnover"].dropna(), nbinsx=30,
        marker_color=C["primary"], opacity=0.8,
    ))
    fig.add_vline(x=0.70, line_dash="dash", line_color="red",
                  annotation_text="HIGH_TURNOVER 上限")
    fig.add_vline(x=0.01, line_dash="dash", line_color=C["warn"],
                  annotation_text="LOW_TURNOVER 下限")
    fig.update_layout(
        title="Turnover 分布",
        xaxis_tickformat=".0%",
        xaxis_title="Turnover", yaxis_title="Count",
        plot_bgcolor=C["bg"], paper_bgcolor=C["bg"], font_color="white",
        height=350,
    )
    return fig


def gauge_chart(value: float, title: str, min_val: float, max_val: float,
                threshold: float, higher_is_better: bool = True) -> go.Figure:
    if higher_is_better:
        good = value >= threshold
    else:
        good = value <= threshold
    color = C["pass"] if good else C["fail"]

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": title, "font": {"size": 13, "color": "white"}},
        number={"font": {"size": 28, "color": color}},
        gauge={
            "axis": {"range": [min_val, max_val], "tickcolor": "white"},
            "bar": {"color": color},
            "bgcolor": C["surface"],
            "threshold": {
                "line": {"color": C["warn"], "width": 3},
                "thickness": 0.85,
                "value": threshold,
            },
            "steps": [
                {"range": [min_val, threshold], "color": "#2a2a3a" if higher_is_better else "#1a3a1a"},
                {"range": [threshold, max_val], "color": "#1a3a1a" if higher_is_better else "#3a1a1a"},
            ],
        },
    ))
    fig.update_layout(
        height=210,
        margin=dict(l=20, r=20, t=50, b=10),
        paper_bgcolor=C["bg"],
        font_color="white",
    )
    return fig


def radar_comparison(alphas: list[dict]) -> go.Figure:
    """Radar chart comparing multiple alphas on 5 normalized dimensions."""
    categories = ["Sharpe", "Fitness", "Returns", "Low Turnover", "Low Drawdown"]
    fig = go.Figure()

    for a in alphas:
        is_data = a.get("is", {})
        sharpe_n = min(max(is_data.get("sharpe", 0), 0) / 3.0, 1.0)
        fitness_n = min(max(is_data.get("fitness", 0), 0) / 2.0, 1.0)
        returns_n = min(max(is_data.get("returns", 0), 0) / 0.30, 1.0)
        turnover_raw = is_data.get("turnover", 1.0)
        low_turnover_n = max(1.0 - turnover_raw / 0.70, 0.0)
        drawdown_raw = is_data.get("drawdown", 0.3)
        low_drawdown_n = max(1.0 - drawdown_raw / 0.30, 0.0)

        vals = [sharpe_n, fitness_n, returns_n, low_turnover_n, low_drawdown_n]
        vals.append(vals[0])  # close polygon

        fig.add_trace(go.Scatterpolar(
            r=vals,
            theta=categories + [categories[0]],
            fill="toself",
            name=a.get("name") or a.get("id", "Alpha"),
            opacity=0.55,
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], tickfont=dict(size=9)),
            bgcolor=C["surface"],
            angularaxis=dict(color="white"),
        ),
        paper_bgcolor=C["bg"],
        font_color="white",
        title="多维度对比雷达图（归一化）",
        height=430,
        showlegend=True,
    )
    return fig


def bar_comparison(alphas: list[dict], metric: str,
                   label_map: dict = None, threshold: float = None,
                   higher_is_better: bool = True) -> go.Figure:
    names = [a.get("name") or a.get("id", "Alpha") for a in alphas]
    values = [a.get("is", {}).get(metric, 0) or 0 for a in alphas]

    colors = []
    for v in values:
        if threshold is None:
            colors.append(C["primary"])
        elif higher_is_better:
            colors.append(C["pass"] if v >= threshold else C["fail"])
        else:
            colors.append(C["pass"] if v <= threshold else C["fail"])

    fmt = label_map.get(metric, "{}") if label_map else "{:.3f}"
    text_vals = [f"{v:.3f}" for v in values]

    fig = go.Figure(go.Bar(
        x=names, y=values,
        marker_color=colors,
        text=text_vals,
        textposition="outside",
        textfont=dict(color="white"),
    ))
    if threshold is not None:
        fig.add_hline(y=threshold, line_dash="dash", line_color=C["warn"],
                      annotation_text=f"Threshold: {threshold}")
    fig.update_layout(
        title=metric.title(),
        plot_bgcolor=C["bg"],
        paper_bgcolor=C["bg"],
        font_color="white",
        yaxis_title=metric.title(),
        height=300,
    )
    return fig


def category_pie(df: pd.DataFrame) -> go.Figure:
    cat_counts = df["category"].value_counts()
    if cat_counts.empty:
        cat_counts = df["source_file"].apply(
            lambda x: x.split("_")[0] if "_" in x else x
        ).value_counts()

    fig = go.Figure(go.Pie(
        labels=cat_counts.index.tolist(),
        values=cat_counts.values.tolist(),
        hole=0.4,
    ))
    fig.update_layout(
        title="Alpha 分类分布",
        paper_bgcolor=C["bg"],
        font_color="white",
        height=320,
    )
    return fig
