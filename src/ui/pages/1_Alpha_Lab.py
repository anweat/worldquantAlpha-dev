"""
1_Alpha_Lab.py — 表达式实验室：提交 Alpha、查看 IS 指标、在历史中定位
"""
import sys
import json
import streamlit as st
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent.parent
UI_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(UI_DIR))

from utils.expression_validator import validate_expression
from utils.charts import gauge_chart, scatter_sharpe_fitness
from utils.result_loader import load_all_results

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Alpha Lab", page_icon="🧪", layout="wide")
st.title("🧪 Alpha Lab")
st.caption("编写 Fast Expression → 实时验证 → 提交 BRAIN API → 查看回测结果")

# ── Session state init ────────────────────────────────────────────────────────
if "submission_history" not in st.session_state:
    st.session_state.submission_history = []
if "comparison_list" not in st.session_state:
    st.session_state.comparison_list = []
if "lab_expr" not in st.session_state:
    st.session_state.lab_expr = "rank(-ts_delta(close, 5))"
if "last_result" not in st.session_state:
    st.session_state.last_result = None

# ── Sidebar: Simulation Settings ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 模拟设置")

    universe = st.selectbox("Universe", ["TOP3000", "TOP2000", "TOP500"], index=0)
    region = st.selectbox("Region", ["USA"], index=0)
    delay = st.selectbox("Delay", [1, 0], index=0)
    decay = st.number_input("Decay", min_value=0, max_value=20, value=4, step=1)
    neutralization = st.selectbox(
        "Neutralization",
        ["MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY", "NONE"],
        index=0,
    )
    truncation = st.number_input(
        "Truncation", min_value=0.01, max_value=0.20, value=0.05, step=0.01
    )

    st.markdown("---")
    st.markdown("**📦 预设配置**")
    col_pa, col_pb = st.columns(2)
    if col_pa.button("基本面", use_container_width=True):
        st.session_state["_preset"] = "fundamental"
        st.rerun()
    if col_pb.button("技术面", use_container_width=True):
        st.session_state["_preset"] = "technical"
        st.rerun()

    # Apply preset values before widgets render (must set via query params hack or rerun)
    if st.session_state.get("_preset") == "fundamental":
        decay = 0
        neutralization = "SUBINDUSTRY"
        truncation = 0.08
        st.session_state.pop("_preset", None)
    elif st.session_state.get("_preset") == "technical":
        decay = 4
        neutralization = "MARKET"
        truncation = 0.05
        st.session_state.pop("_preset", None)

    st.markdown("---")
    st.markdown("**📋 表达式模板**")
    EXAMPLES = [
        ("动量反转", "rank(-ts_delta(close, 5))"),
        ("杠杆率", "rank(liabilities/assets)"),
        ("收益波动率反向", "rank(-ts_std_dev(returns, 20))"),
        ("TS-Rank 营收", "rank(ts_rank(operating_income, 252))"),
        ("行业内动量", "group_rank(-ts_corr(returns, adv20, 10), sector)"),
        ("价量背离", "rank(-ts_corr(close, volume, 10))"),
        ("ROA", "rank(operating_income/assets)"),
        ("均值回归", "rank(-ts_zscore(close, 20))"),
    ]
    for label, ex in EXAMPLES:
        if st.button(f"{label}", key=f"ex_{label}", use_container_width=True):
            st.session_state.lab_expr = ex
            st.rerun()

# ── Main: Expression Input ────────────────────────────────────────────────────
col_left, col_right = st.columns([3, 2])

with col_left:
    expr_input = st.text_area(
        "📝 Fast Expression",
        value=st.session_state.lab_expr,
        height=90,
        key="lab_expr",
        help="WorldQuant BRAIN Fast Expression 语法",
        placeholder="例: rank(-ts_delta(close, 5))",
    )

with col_right:
    # Live validation
    if expr_input and expr_input.strip():
        v = validate_expression(expr_input)

        if v["issues"]:
            for issue in v["issues"]:
                st.error(f"❌ {issue}")
        elif v["warnings"]:
            for w in v["warnings"]:
                st.warning(f"⚠️ {w}")
        else:
            st.success("✅ 语法正确")

        with st.container():
            st.markdown(
                f"**预估类别** `{v['estimated_category']}`　"
                f"**预估换手** {v['estimated_turnover']}"
            )
            if v["used_operators"]:
                ops_str = " · ".join(f"`{o}`" for o in v["used_operators"])
                st.markdown(f"**运算符** {ops_str}")

# ── Submit ────────────────────────────────────────────────────────────────────
st.markdown("---")
col_btn, col_hint = st.columns([1, 4])
with col_btn:
    submit = st.button("🚀 提交回测", type="primary", use_container_width=True)
with col_hint:
    st.caption("提交后等待约 1–5 分钟轮询完成，请勿关闭页面。")

if submit:
    if not expr_input or not expr_input.strip():
        st.error("请先输入表达式")
    else:
        v = validate_expression(expr_input)
        if v["issues"]:
            st.error("表达式有语法错误，请先修正后再提交。")
        else:
            settings = {
                "universe": universe,
                "region": region,
                "delay": delay,
                "decay": decay,
                "neutralization": neutralization,
                "truncation": truncation,
            }
            with st.spinner("⏳ 提交中… 等待模拟完成（约 1–5 分钟）"):
                try:
                    from brain_client import BrainClient
                    client = BrainClient()
                    auth = client.check_auth()
                    if auth["status"] != 200:
                        st.error(
                            "❌ Session 已过期，请运行 `python src/login.py` 重新登录。"
                        )
                    else:
                        result = client.simulate_and_get_alpha(expr_input, settings)
                        if "error" in result:
                            st.error(f"❌ 模拟失败：{result}")
                        else:
                            record = {
                                "expr": expr_input,
                                "settings": settings,
                                "id": result.get("id", ""),
                                "name": result.get("id", "Alpha"),
                                "is": result.get("is", {}),
                            }
                            st.session_state.submission_history.insert(0, record)
                            st.session_state.last_result = result
                            st.success("✅ 模拟完成！")
                            st.rerun()
                except FileNotFoundError as e:
                    st.error(f"❌ Session 文件不存在: {e}")
                except Exception as e:
                    st.error(f"❌ 错误: {e}")

# ── Results Display ───────────────────────────────────────────────────────────
result = st.session_state.get("last_result")
if result:
    is_data = result.get("is", {})
    sharpe   = is_data.get("sharpe", 0) or 0
    fitness  = is_data.get("fitness", 0) or 0
    turnover = is_data.get("turnover", 0) or 0
    returns  = is_data.get("returns", 0) or 0
    drawdown = is_data.get("drawdown", 0) or 0
    margin   = is_data.get("margin", 0) or 0

    st.markdown("## 📊 回测结果")

    # ── Metric cards ──────────────────────────────────────────────────────────
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    mc1.metric("Sharpe",   f"{sharpe:.3f}",   delta="✅ PASS" if sharpe >= 1.25 else "❌ FAIL")
    mc2.metric("Fitness",  f"{fitness:.3f}",  delta="✅ PASS" if fitness >= 1.0  else "❌ FAIL")
    mc3.metric("Turnover", f"{turnover:.1%}",
               delta="✅ OK" if 0.01 <= turnover <= 0.70 else "❌ Out of range")
    mc4.metric("Returns",  f"{returns:.2%}")
    mc5.metric("Drawdown", f"{drawdown:.2%}")
    mc6.metric("Margin",   f"{margin:.5f}")

    # ── Gauge charts ──────────────────────────────────────────────────────────
    g1, g2, g3 = st.columns(3)
    g1.plotly_chart(
        gauge_chart(sharpe, "Sharpe Ratio", 0, 4, 1.25), use_container_width=True
    )
    g2.plotly_chart(
        gauge_chart(fitness, "Fitness Score", 0, 3, 1.0), use_container_width=True
    )
    g3.plotly_chart(
        gauge_chart(turnover * 100, "Turnover %", 0, 100, 70, higher_is_better=False),
        use_container_width=True,
    )

    # ── Checks ────────────────────────────────────────────────────────────────
    st.markdown("### ✅ Submission Checks")
    checks = is_data.get("checks", [])
    check_rows = []
    for c in checks:
        status = c.get("result", "PENDING")
        icon = "✅" if status == "PASS" else ("⏳" if status == "PENDING" else "❌")
        row = {"Check": c["name"], "Result": f"{icon} {status}"}
        if "value" in c:
            row["Value"] = f"{c['value']:.4f}"
        if "limit" in c:
            row["Limit"] = str(c["limit"])
        check_rows.append(row)
    st.dataframe(check_rows, use_container_width=True, hide_index=True)

    # ── Fitness formula breakdown ─────────────────────────────────────────────
    with st.expander("📐 Fitness 公式分解"):
        if turnover > 0:
            denom = max(turnover, 0.125)
            inner = abs(returns) / denom
            st.latex(
                r"\text{Fitness} = \text{Sharpe} \times \sqrt{\frac{|\text{Returns}|}{\max(\text{Turnover},\,0.125)}}"
            )
            st.code(
                f"= {sharpe:.3f} × √({abs(returns):.4f} / {denom:.4f})\n"
                f"= {sharpe:.3f} × {inner**0.5:.4f}\n"
                f"= {sharpe * inner**0.5:.4f}   (API returned: {fitness:.4f})"
            )

    # ── Position in landscape ─────────────────────────────────────────────────
    st.markdown("### 🗺️ 在历史 Alpha 中的位置")
    df_all = load_all_results()
    if not df_all.empty:
        fig = scatter_sharpe_fitness(df_all, result.get("id"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无历史数据可比较。")

    # ── Add to comparison ─────────────────────────────────────────────────────
    col_add, col_info = st.columns([1, 3])
    with col_add:
        if st.button("➕ 加入对比列表", use_container_width=True):
            alpha_id = result.get("id", "")
            existing_ids = [x["id"] for x in st.session_state.comparison_list]
            if alpha_id not in existing_ids:
                st.session_state.comparison_list.append({
                    "id": alpha_id,
                    "name": alpha_id,
                    "expr": expr_input,
                    "is": is_data,
                })
                st.success(f"已加入，当前对比列表共 {len(st.session_state.comparison_list)} 个")
            else:
                st.info("已在对比列表中")

    # ── Clear result ──────────────────────────────────────────────────────────
    if st.button("🗑️ 清除结果"):
        st.session_state.last_result = None
        st.rerun()

# ── Session History ───────────────────────────────────────────────────────────
history = st.session_state.get("submission_history", [])
if history:
    st.markdown("---")
    st.markdown(f"## 📜 本次会话历史（{len(history)} 条）")
    for i, rec in enumerate(history[:15]):
        is_d = rec.get("is", {})
        sh = is_d.get("sharpe", 0) or 0
        fi = is_d.get("fitness", 0) or 0
        to = is_d.get("turnover", 0) or 0
        ok = sh >= 1.25 and fi >= 1.0
        icon = "✅" if ok else "❌"
        label = f"{icon} [{i+1}]  `{rec['expr'][:55]}{'...' if len(rec['expr'])>55 else ''}`"
        label += f"  —  Sharpe: **{sh:.2f}**  Fitness: **{fi:.2f}**  Turnover: **{to:.1%}**"
        with st.expander(label):
            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric("Sharpe", f"{sh:.3f}")
            hc2.metric("Fitness", f"{fi:.3f}")
            hc3.metric("Turnover", f"{to:.1%}")
            hc4.metric("Returns", f"{is_d.get('returns', 0):.2%}")
            st.code(rec["expr"], language="text")
            s = rec.get("settings", {})
            st.caption(
                f"decay={s.get('decay')}  neutral={s.get('neutralization')}  "
                f"trunc={s.get('truncation')}  universe={s.get('universe')}"
            )
            if st.button("➕ 加入对比", key=f"add_hist_{i}"):
                existing_ids = [x["id"] for x in st.session_state.comparison_list]
                if rec["id"] not in existing_ids:
                    st.session_state.comparison_list.append(rec)
