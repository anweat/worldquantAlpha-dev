"""
agent_technical.py - 技术因子 Agent（低换手率优化版）
策略方向：长周期价格/量价信号 + 高 decay 抑制换手率
核心原则：
  - 使用 60-252 天长窗口（避免短期高频换仓）
  - decay=15-25 进一步平滑信号（换手率降至 15-35%）
  - 目标换手率 ≤ 30%，确保 Fitness 可达标
  
换手率 ≈ 30% 时：Fitness = Sharpe × √(Returns/0.30)
若 Sharpe=1.5，Returns=15%：Fitness = 1.5 × √(0.15/0.30) = 1.5 × 0.707 = 1.06 ✓

运行方式：
    python src/agents/agent_technical.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.base import run_agent

# 高 decay 压低换手率
_MKT_20 = {"decay": 20, "neutralization": "MARKET", "truncation": 0.05}
_MKT_15 = {"decay": 15, "neutralization": "MARKET", "truncation": 0.05}
_MKT_25 = {"decay": 25, "neutralization": "MARKET", "truncation": 0.05}
_SUB_20 = {"decay": 20, "neutralization": "SUBINDUSTRY", "truncation": 0.05}
_SUB_15 = {"decay": 15, "neutralization": "SUBINDUSTRY", "truncation": 0.05}

ALPHAS = [
    # ── 年度价格动量（252天）──────────────────────────────────────────────────
    {
        "name": "TM01_年度价格动量",
        "expr": "rank(ts_delta(close, 252))",
        "settings": _MKT_20,
        "hypothesis": "52周价格涨幅最大，中长期趋势延续（1年动量效应）",
        "category": "技术/动量",
    },
    {
        "name": "TM02_半年价格动量",
        "expr": "rank(ts_delta(close, 126))",
        "settings": _MKT_15,
        "hypothesis": "过去半年价格动量，中期趋势延续信号",
        "category": "技术/动量",
    },
    {
        "name": "TM03_季度价格动量_行业内",
        "expr": "group_rank(ts_delta(close, 63), industry)",
        "settings": _SUB_15,
        "hypothesis": "行业内过去一季度涨幅最大，行业内动量最强",
        "category": "技术/动量",
    },
    {
        "name": "TM04_52周价格排名",
        "expr": "rank(ts_rank(close, 252))",
        "settings": _MKT_20,
        "hypothesis": "股价处于52周高位的股票相对强势明显",
        "category": "技术/相对强弱",
    },
    {
        "name": "TM05_年度风险调整动量",
        "expr": "rank(ts_delta(close, 252) / ts_std_dev(returns, 252))",
        "settings": _MKT_20,
        "hypothesis": "年度风险调整动量（类Sharpe动量），比纯价格动量更稳健",
        "category": "技术/动量",
    },
    {
        "name": "TM06_半年风险调整动量",
        "expr": "rank(ts_delta(close, 126) / ts_std_dev(returns, 126))",
        "settings": _MKT_15,
        "hypothesis": "半年风险调整动量，平衡趋势强度和稳定性",
        "category": "技术/动量",
    },
    {
        "name": "TM07_动量加速度",
        "expr": "rank(ts_delta(close, 126) - ts_delay(ts_delta(close, 126), 126))",
        "settings": _MKT_20,
        "hypothesis": "近半年动量减去前半年动量 = 动量加速度，正值代表趋势增强",
        "category": "技术/动量",
    },
    {
        "name": "TM08_年度平均日收益",
        "expr": "rank(ts_mean(returns, 252))",
        "settings": _MKT_20,
        "hypothesis": "过去一年平均日收益率最高的股票，趋势延续概率更高",
        "category": "技术/动量",
    },
    {
        "name": "TM09_行业内年度动量",
        "expr": "group_rank(ts_delta(close, 252) / ts_std_dev(returns, 252), industry)",
        "settings": _SUB_20,
        "hypothesis": "行业内风险调整年度动量最高，趋势强度与稳定性双优",
        "category": "技术/动量",
    },
    # ── 低波动率因子 ─────────────────────────────────────────────────────────
    {
        "name": "TV01_年度低波动率",
        "expr": "rank(-ts_std_dev(returns, 252))",
        "settings": _MKT_25,
        "hypothesis": "年度低波动率股票长期风险调整后收益更优（低波动异象）",
        "category": "技术/波动率",
    },
    {
        "name": "TV02_半年低波动率",
        "expr": "rank(-ts_std_dev(returns, 126))",
        "settings": _MKT_20,
        "hypothesis": "半年低波动率股票稳定性更强，机构投资者偏好",
        "category": "技术/波动率",
    },
    {
        "name": "TV03_收益质量_Sharpe型",
        "expr": "rank(ts_mean(returns, 252) / ts_std_dev(returns, 252))",
        "settings": _MKT_25,
        "hypothesis": "年均日收益/年度波动率 = 类 Sharpe 比，长期风险调整收益最优",
        "category": "技术/波动率",
    },
    {
        "name": "TV04_半年收益质量",
        "expr": "rank(ts_mean(returns, 126) / ts_std_dev(returns, 252))",
        "settings": _MKT_20,
        "hypothesis": "半年平均日收益 / 年度波动率 = 风险调整收益质量最高",
        "category": "技术/波动率",
    },
    # ── 价格位置因子 ─────────────────────────────────────────────────────────
    {
        "name": "TP01_52周接近高点",
        "expr": "rank(close / ts_max(close, 252))",
        "settings": _MKT_20,
        "hypothesis": "接近52周高点的股票相对强度最高，趋势延续性最强",
        "category": "技术/相对强弱",
    },
    {
        "name": "TP02_半年均线上方偏离",
        "expr": "rank(close / ts_mean(close, 126))",
        "settings": _MKT_15,
        "hypothesis": "股价高于半年均线越多，中期上升趋势越强（均线动量）",
        "category": "技术/趋势",
    },
    {
        "name": "TP03_年度均线偏离_反转",
        "expr": "rank(-(close / ts_mean(close, 252) - 1))",
        "settings": _MKT_20,
        "hypothesis": "股价高于年度均线幅度大时容易回落（长期均值回归）",
        "category": "技术/反转",
    },
    # ── 量价关系因子 ─────────────────────────────────────────────────────────
    {
        "name": "TQ01_年度量价相关_反向",
        "expr": "rank(-ts_corr(rank(close), rank(volume), 252))",
        "settings": _MKT_20,
        "hypothesis": "年度量价负相关（涨价缩量/跌价放量）是价格可持续的信号",
        "category": "技术/量价",
    },
    {
        "name": "TQ02_年度成交量动量",
        "expr": "rank(ts_delta(volume, 252))",
        "settings": _MKT_20,
        "hypothesis": "年度成交量持续增长的股票，资金关注度持续提升",
        "category": "技术/成交量",
    },
    {
        "name": "TQ03_成交量稳定性",
        "expr": "rank(-ts_std_dev(volume, 252) / ts_mean(volume, 252))",
        "settings": _MKT_25,
        "hypothesis": "年度成交量变异系数低（稳定量价）的股票，资金流入更持续",
        "category": "技术/成交量",
    },
    {
        "name": "TQ04_长期量价协同",
        "expr": "rank(ts_corr(close, volume, 252))",
        "settings": _SUB_20,
        "hypothesis": "量价正相关强（涨量/跌缩量）的股票，中期趋势最健康",
        "category": "技术/量价",
    },
]


if __name__ == "__main__":
    run_agent("agent_technical", ALPHAS)
