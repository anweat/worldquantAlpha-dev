"""
agent_fundamental.py - 基本面价值/质量因子 Agent
策略方向：低杠杆、高利润率、高ROA、资产效率
数据来源：财务报表字段（季度更新，天然低换手率 1-5%）
预期效果：Fitness 高（低换手 → max(TO,0.125) = 0.125），约 80% 合格率

运行方式：
    python src/agents/agent_fundamental.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.base import run_agent

# ─── Alpha 定义（20 个）─────────────────────────────────────────────────────
# 核心设置：decay=0（不做时序平滑），SUBINDUSTRY 中性化，truncation=0.08
# 财务字段按季度更新，换手率自然 1-5%，Fitness 公式中分母 = max(TO, 0.125) = 0.125
# Fitness = Sharpe × √(Returns / 0.125) → 需要 Returns > 8% 且 Sharpe > 1.25

_FUND_SETTINGS = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08}
_FUND_NAN = {**_FUND_SETTINGS, "nanHandling": "ON"}

ALPHAS = [
    # ── 价值因子：杠杆率 ─────────────────────────────────────────────────────
    {
        "name": "FV01_低杠杆_市场",
        "expr": "rank(-liabilities/assets)",
        "settings": _FUND_SETTINGS,
        "hypothesis": "低负债率公司财务稳健，系统性风险低，长期超额收益更稳定",
        "category": "基本面/价值",
    },
    {
        "name": "FV02_低杠杆_行业内",
        "expr": "group_rank(-liabilities/assets, industry)",
        "settings": _FUND_SETTINGS,
        "hypothesis": "行业内低负债率公司相对同行具有明显财务优势",
        "category": "基本面/价值",
    },
    {
        "name": "FV03_低DE比_行业",
        "expr": "group_rank(-liabilities/(assets - liabilities), industry)",
        "settings": _FUND_NAN,
        "hypothesis": "行业内低债务权益比(D/E)公司财务杠杆风险最小",
        "category": "基本面/价值",
    },
    {
        "name": "FV04_低债务收入比",
        "expr": "group_rank(-liabilities/sales, industry)",
        "settings": _FUND_NAN,
        "hypothesis": "行业内低债务/收入比公司偿债压力小，经营更健康",
        "category": "基本面/价值",
    },
    {
        "name": "FV05_净资产规模_板块",
        "expr": "group_rank(assets - liabilities, sector)",
        "settings": _FUND_SETTINGS,
        "hypothesis": "板块内净资产规模大的公司财务缓冲能力强（规模+价值因子）",
        "category": "基本面/价值",
    },
    # ── 质量因子：盈利能力 ───────────────────────────────────────────────────
    {
        "name": "FQ01_运营利润率_行业",
        "expr": "group_rank(operating_income/sales, industry)",
        "settings": _FUND_NAN,
        "hypothesis": "行业内高运营利润率公司经营效率最优，竞争优势最强",
        "category": "基本面/质量",
    },
    {
        "name": "FQ02_净利润率_行业",
        "expr": "group_rank(earnings/sales, industry)",
        "settings": _FUND_NAN,
        "hypothesis": "行业内高净利润率公司盈利能力持续更强，估值溢价更持久",
        "category": "基本面/质量",
    },
    {
        "name": "FQ03_ROA_行业",
        "expr": "group_rank(earnings/assets, industry)",
        "settings": _FUND_NAN,
        "hypothesis": "行业内高资产回报率(ROA)公司资本使用效率最高",
        "category": "基本面/质量",
    },
    {
        "name": "FQ04_运营ROA_行业",
        "expr": "group_rank(operating_income/assets, industry)",
        "settings": _FUND_NAN,
        "hypothesis": "行业内运营利润/总资产比率高，综合运营盈利能力最强",
        "category": "基本面/质量",
    },
    {
        "name": "FQ05_资产周转率_板块",
        "expr": "group_rank(sales/assets, sector)",
        "settings": _FUND_NAN,
        "hypothesis": "板块内高资产周转率公司运营效率最优，资产利用能力最强",
        "category": "基本面/质量",
    },
    # ── 复合因子：杜邦分解 ───────────────────────────────────────────────────
    {
        "name": "FC01_杜邦双因子_净利+周转",
        "expr": "group_rank(rank(earnings/sales) + rank(sales/assets), sector)",
        "settings": _FUND_NAN,
        "hypothesis": "净利润率×资产周转率 = ROE分子，板块内杜邦两因子均等评分",
        "category": "基本面/复合",
    },
    {
        "name": "FC02_杜邦三因子",
        "expr": "rank(earnings/sales) * 0.34 + rank(sales/assets) * 0.33 + rank(-liabilities/assets) * 0.33",
        "settings": _FUND_NAN,
        "hypothesis": "净利润率+资产周转率+低杠杆三因子均等权重，杜邦全因子模型",
        "category": "基本面/复合",
    },
    {
        "name": "FC03_价值质量综合_行业",
        "expr": "group_rank(rank(-liabilities/assets) + rank(earnings/assets), industry)",
        "settings": _FUND_NAN,
        "hypothesis": "低杠杆(安全)+ 高ROA(质量)双维度行业内综合评分",
        "category": "基本面/复合",
    },
    {
        "name": "FC04_运营效率综合_板块",
        "expr": "group_rank(rank(operating_income/sales) + rank(sales/assets), sector)",
        "settings": _FUND_NAN,
        "hypothesis": "高利润率+高资产周转率，板块内运营效率最优秀的公司",
        "category": "基本面/复合",
    },
    {
        "name": "FC05_财务健康三因子",
        "expr": "group_rank(rank(-liabilities/assets) + rank(operating_income/sales) + rank(sales/assets), sector)",
        "settings": _FUND_NAN,
        "hypothesis": "低杠杆+高利润率+高周转率，板块内财务健康综合最优评分",
        "category": "基本面/复合",
    },
    # ── 反向信号：高杠杆/困境价值 ────────────────────────────────────────────
    {
        "name": "FV06_高杠杆_行业",
        "expr": "group_rank(liabilities/assets, industry)",
        "settings": _FUND_SETTINGS,
        "hypothesis": "行业内高杠杆公司（困境价值），在牛市中杠杆效应放大超额收益",
        "category": "基本面/价值",
    },
    {
        "name": "FV07_低估值_资产收入比",
        "expr": "group_rank(-assets/sales, industry)",
        "settings": _FUND_NAN,
        "hypothesis": "行业内资产/收入比低的公司（类P/S低估值），具有更大上行空间",
        "category": "基本面/价值",
    },
    {
        "name": "FV08_收入规模_板块",
        "expr": "group_rank(sales, sector)",
        "settings": _FUND_SETTINGS,
        "hypothesis": "板块内收入规模领先公司定价权更强（规模效应），长期超额收益更稳健",
        "category": "基本面/规模",
    },
    # ── 趋势改善因子 ─────────────────────────────────────────────────────────
    {
        "name": "FT01_去杠杆趋势_行业",
        "expr": "group_rank(-ts_delta(liabilities/assets, 252), industry)",
        "settings": _FUND_SETTINGS,
        "hypothesis": "行业内过去一年杠杆率下降最快的公司，财务质量改善信号最强",
        "category": "基本面/趋势",
    },
    {
        "name": "FT02_负债减少_板块",
        "expr": "group_rank(-ts_delta(liabilities, 252), sector)",
        "settings": _FUND_SETTINGS,
        "hypothesis": "板块内绝对负债规模减少最多的公司，主动去杠杆意愿最强",
        "category": "基本面/趋势",
    },
]


if __name__ == "__main__":
    run_agent("agent_fundamental", ALPHAS)
