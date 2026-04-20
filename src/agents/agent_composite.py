"""
agent_composite.py - 复合多因子 Agent
策略方向：融合基本面与技术信号，降低因子间相关性，提升 Sharpe
核心逻辑：
  - 基本面因子（低换手）+ 技术因子（趋势确认）= 信号互补
  - 多因子权重组合降低单一因子方差
  - 行业内中性化消除行业 beta 干扰

预期效果：比单一因子更稳定，Sharpe 更高，Fitness 中高

运行方式：
    python src/agents/agent_composite.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.base import run_agent

_MKT = {"decay": 10, "neutralization": "MARKET", "truncation": 0.05, "nanHandling": "ON"}
_SUB = {"decay": 10, "neutralization": "SUBINDUSTRY", "truncation": 0.05, "nanHandling": "ON"}
_SUB_PURE = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}
_SUB_8 = {"decay": 5, "neutralization": "SUBINDUSTRY", "truncation": 0.08, "nanHandling": "ON"}

ALPHAS = [
    # ── 价值 + 动量 ──────────────────────────────────────────────────────────
    {
        "name": "CM01_价值动量_行业",
        "expr": "group_rank(rank(-liabilities/assets) + rank(ts_delta(close, 252)), industry)",
        "settings": _SUB,
        "hypothesis": "行业内低杠杆(价值安全)+年度价格动量，两类信号互补增加稳定性",
        "category": "复合/价值+动量",
    },
    {
        "name": "CM02_低杠杆动量组合",
        "expr": "0.5 * rank(-liabilities/assets) + 0.5 * rank(ts_rank(close, 252))",
        "settings": _MKT,
        "hypothesis": "低杠杆价值因子 + 52周相对强弱，市场级价值动量组合",
        "category": "复合/价值+动量",
    },
    {
        "name": "CM03_去杠杆趋势动量",
        "expr": "0.5 * group_rank(-ts_delta(liabilities/assets, 252), industry) + 0.5 * rank(ts_delta(close, 252))",
        "settings": _SUB,
        "hypothesis": "行业内去杠杆趋势+价格年度动量，基本面改善与技术信号共振",
        "category": "复合/价值+动量",
    },
    # ── 质量 + 动量 ──────────────────────────────────────────────────────────
    {
        "name": "CM04_运营利润率动量",
        "expr": "0.5 * group_rank(operating_income/sales, industry) + 0.5 * rank(ts_rank(close, 252))",
        "settings": _SUB,
        "hypothesis": "运营利润率(质量)+52周相对强弱(动量)，质量+趋势双维度选股",
        "category": "复合/质量+动量",
    },
    {
        "name": "CM05_ROA动量组合",
        "expr": "group_rank(rank(earnings/assets) + rank(ts_delta(close, 252)), industry)",
        "settings": _SUB,
        "hypothesis": "行业内ROA(质量)+年度价格动量，基本面质量验证技术趋势",
        "category": "复合/质量+动量",
    },
    {
        "name": "CM06_盈利排名动量",
        "expr": "0.5 * rank(ts_rank(earnings, 252)) + 0.5 * rank(ts_delta(close, 252))",
        "settings": _MKT,
        "hypothesis": "盈利历史高位(成长动量)+价格年度动量，基本面与技术双动量",
        "category": "复合/质量+动量",
    },
    # ── 质量 + 低波动 ────────────────────────────────────────────────────────
    {
        "name": "CM07_ROA低波复合",
        "expr": "0.5 * group_rank(earnings/assets, industry) + 0.5 * rank(-ts_std_dev(returns, 252))",
        "settings": _SUB,
        "hypothesis": "高ROA(质量)+低年度波动率(稳定)，高质量低风险复合选股",
        "category": "复合/质量+波动",
    },
    {
        "name": "CM08_利润率低波组合",
        "expr": "group_rank(rank(operating_income/sales) + rank(-ts_std_dev(returns, 252)), sector)",
        "settings": _SUB,
        "hypothesis": "板块内高运营利润率+低波动率，质量稳健型防御选股",
        "category": "复合/质量+波动",
    },
    # ── 价值 + 低波动 ────────────────────────────────────────────────────────
    {
        "name": "CM09_价值低波组合",
        "expr": "0.5 * group_rank(-liabilities/assets, industry) + 0.5 * rank(-ts_std_dev(returns, 252))",
        "settings": _SUB,
        "hypothesis": "低杠杆(价值)+低波动率(稳定)，防御型价值选股",
        "category": "复合/价值+波动",
    },
    {
        "name": "CM10_安全质量组合",
        "expr": "group_rank(rank(-liabilities/assets) + rank(-ts_std_dev(returns, 252)), sector)",
        "settings": _SUB,
        "hypothesis": "板块内低杠杆+低波动率，双重安全性约束下的最稳健公司",
        "category": "复合/价值+波动",
    },
    # ── 三因子组合 ───────────────────────────────────────────────────────────
    {
        "name": "CM11_三因子均等_板块",
        "expr": "group_rank(rank(-liabilities/assets) + rank(earnings/assets) + rank(-ts_std_dev(returns, 252)), sector)",
        "settings": _SUB,
        "hypothesis": "板块内低杠杆+高ROA+低波动率，三因子均等权重防御成长组合",
        "category": "复合/三因子",
    },
    {
        "name": "CM12_三因子_价值质量动量",
        "expr": "0.33 * rank(-liabilities/assets) + 0.33 * rank(earnings/assets) + 0.34 * rank(ts_delta(close, 252))",
        "settings": _MKT,
        "hypothesis": "价值(低杠杆)+质量(ROA)+动量(年度涨幅)均等三因子市场级组合",
        "category": "复合/三因子",
    },
    {
        "name": "CM13_杜邦三因子动量",
        "expr": "group_rank(rank(earnings/sales) + rank(sales/assets) + rank(ts_rank(close, 252)), sector)",
        "settings": _SUB,
        "hypothesis": "板块内净利率+资产周转率+股价52周排名，财务效率+趋势三因子",
        "category": "复合/三因子",
    },
    # ── 成长 + 技术 ──────────────────────────────────────────────────────────
    {
        "name": "CM14_盈利增速低波",
        "expr": "0.5 * rank(ts_delta(earnings, 252)) + 0.5 * rank(-ts_std_dev(returns, 252))",
        "settings": _SUB_8,
        "hypothesis": "盈利增速(成长)+低波动率(稳定)，成长型低波动选股",
        "category": "复合/成长+波动",
    },
    {
        "name": "CM15_收入增速低波_板块",
        "expr": "0.6 * group_rank(ts_delta(sales, 252), sector) + 0.4 * rank(-ts_std_dev(returns, 252))",
        "settings": _SUB,
        "hypothesis": "板块内60%收入增速+40%低波动率，成长稳健型因子",
        "category": "复合/成长+波动",
    },
    {
        "name": "CM16_盈利趋势动量",
        "expr": "group_rank(rank(ts_rank(earnings, 252)) + rank(ts_delta(close, 252)), industry)",
        "settings": _SUB,
        "hypothesis": "行业内盈利历史排名+价格年度动量，基本面趋势与技术趋势双重确认",
        "category": "复合/成长+动量",
    },
    # ── 多维财务健康 ─────────────────────────────────────────────────────────
    {
        "name": "CM17_财务健康指数",
        "expr": "group_rank(rank(-liabilities/assets) + rank(sales/assets) + rank(-ts_delta(liabilities, 252)), sector)",
        "settings": _SUB_PURE,
        "hypothesis": "板块内低杠杆+高资产周转+负债减少，综合财务健康指数",
        "category": "复合/财务健康",
    },
    {
        "name": "CM18_综合盈利质量",
        "expr": "group_rank(rank(ts_delta(earnings, 252)) + rank(earnings/sales) + rank(-ts_std_dev(returns, 252)), industry)",
        "settings": _SUB_8,
        "hypothesis": "行业内盈利增速+净利润率+低波动率，盈利质量综合评分",
        "category": "复合/盈利质量",
    },
    {
        "name": "CM19_五因子综合",
        "expr": "group_rank(rank(-liabilities/assets) + rank(earnings/assets) + rank(operating_income/sales) + rank(ts_delta(close, 252)) + rank(-ts_std_dev(returns, 252)), sector)",
        "settings": _SUB,
        "hypothesis": "板块内五因子均等：低杠杆+ROA+利润率+年度动量+低波动率",
        "category": "复合/五因子",
    },
    {
        "name": "CM20_质量成长价值三维",
        "expr": "rank(ts_delta(sales, 252)) * 0.33 + rank(-liabilities/assets) * 0.33 + rank(earnings/assets) * 0.34",
        "settings": _SUB_8,
        "hypothesis": "收入增速(成长)+低杠杆(价值)+ROA(质量)均等三因子，经典 QGV 组合",
        "category": "复合/三因子",
    },
]


if __name__ == "__main__":
    run_agent("agent_composite", ALPHAS)
