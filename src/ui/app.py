"""
app.py — WorldQuant Alpha Studio 主入口
运行方式: streamlit run src/ui/app.py
"""
import streamlit as st

st.set_page_config(
    page_title="WorldQuant Alpha Studio",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize global session state
if "submission_history" not in st.session_state:
    st.session_state.submission_history = []
if "comparison_list" not in st.session_state:
    st.session_state.comparison_list = []

# ── Header ──────────────────────────────────────────────────────────────────
st.title("🧠 WorldQuant Alpha Studio")
st.caption("BRAIN Alpha 因子研究 · 实验 · 可视化工作台")
st.markdown("---")

# ── Feature Overview ────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown("""
    ### 🧪 Alpha Lab
    - 编写 Fast Expression 表达式
    - 实时语法验证 & 类别预测
    - 一键提交 BRAIN API 回测
    - Sharpe / Fitness / Turnover 仪表盘
    - Checks 通过状态可视化
    - 在历史 Alpha 中定位当前结果
    """)
with col2:
    st.markdown("""
    ### 📊 Explorer
    - 加载全部历史回测结果
    - Sharpe × Fitness 散点图
    - Turnover × Returns 散点图
    - Sharpe / Fitness / Turnover 分布直方图
    - 多维度筛选 & 搜索
    - 完整数据表格（可排序导出）
    """)
with col3:
    st.markdown("""
    ### 📚 Operators
    - 全部 66 个运算符参考手册
    - 按类别浏览 & 搜索
    - 定义、说明一览
    - 点击复制用法
    - 常用字段速查表
    """)
with col4:
    st.markdown("""
    ### ⚖️ Comparison
    - 多 Alpha 指标对比
    - 雷达图（5 维归一化）
    - Sharpe / Fitness / Turnover 柱状对比
    - 表达式与设置并排展示
    - 从 Lab 历史一键添加
    """)

st.markdown("---")
st.info("👈 **使用左侧导航栏**切换功能页面")

# ── Quick Stats ─────────────────────────────────────────────────────────────
st.markdown("### 📈 快速概览")
try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from utils.result_loader import load_all_results

    df = load_all_results()
    if not df.empty:
        pass_df = df[df["all_pass"]]
        col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
        col_s1.metric("历史 Alpha 总数", len(df))
        col_s2.metric("全部通过", len(pass_df), delta=f"{len(pass_df)/len(df):.0%}")
        col_s3.metric("最高 Sharpe", f"{df['sharpe'].max():.3f}")
        col_s4.metric("最高 Fitness", f"{df['fitness'].max():.3f}")
        col_s5.metric("本次提交", len(st.session_state.submission_history))
    else:
        st.info("暂无历史数据，先在 Explorer 页面刷新或在 Alpha Lab 提交新测试。")
except Exception as e:
    st.warning(f"加载历史数据失败: {e}")
