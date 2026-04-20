"""
agent_growth.py - 基本面成长/动量因子 Agent
策略方向：财务指标的时序排名与加速趋势
核心逻辑：ts_rank(fundamental, 252) 捕捉"当前基本面处于历史高位"信号
数据来源：财务报表字段（季度更新，天然低换手率 2-5%）
预期效果：Fitness 高，成长动量强的公司具有持续超额收益

运行方式：
    python src/agents/agent_growth.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.base import run_agent

_BASE = {"decay": 0, "neutralization": "SUBINDUSTRY", "truncation": 0.08}
_NAN = {**_BASE, "nanHandling": "ON"}

ALPHAS = [
    # ── 52 周历史排名（当前处于历史高位 = 趋势最强）──────────────────────────
    {
        "name": "GR01_盈利52周排名",
        "expr": "rank(ts_rank(earnings, 252))",
        "settings": _NAN,
        "hypothesis": "过去252天盈利水平处于历史高位的公司，当前基本面最强",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR02_运营利润52周排名",
        "expr": "rank(ts_rank(operating_income, 252))",
        "settings": _NAN,
        "hypothesis": "运营利润在过去一年处于历史最高位，基本面趋势向好",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR03_收入52周排名_板块内",
        "expr": "group_rank(ts_rank(sales, 252), sector)",
        "settings": _BASE,
        "hypothesis": "板块内收入在历史上处于高位的公司，业务扩张势头最强",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR04_运营利润率趋势_行业",
        "expr": "group_rank(ts_rank(operating_income/sales, 252), industry)",
        "settings": _NAN,
        "hypothesis": "行业内运营利润率处于历史高位，盈利质量持续改善",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR05_ROA趋势_行业",
        "expr": "group_rank(ts_rank(earnings/assets, 252), industry)",
        "settings": _NAN,
        "hypothesis": "行业内ROA历史排名高，近期资本使用效率处于最佳状态",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR06_资产周转趋势_板块",
        "expr": "group_rank(ts_rank(sales/assets, 252), sector)",
        "settings": _NAN,
        "hypothesis": "板块内资产周转率处于历史高位，近期运营效率达到顶峰",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR07_净利率趋势_行业",
        "expr": "group_rank(ts_rank(earnings/sales, 252), industry)",
        "settings": _NAN,
        "hypothesis": "行业内净利润率历史排名高，当前盈利能力处于最优状态",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR08_运营ROA历史排名_板块",
        "expr": "group_rank(ts_rank(operating_income/assets, 252), sector)",
        "settings": _NAN,
        "hypothesis": "板块内运营ROA处于历史高位，综合运营效率和盈利性最优",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR09_负债率历史低位_行业",
        "expr": "group_rank(ts_rank(-liabilities/assets, 252), industry)",
        "settings": _BASE,
        "hypothesis": "行业内当前杠杆率处于历史低位，近期去杠杆最彻底",
        "category": "基本面/成长动量",
    },
    {
        "name": "GR10_长期盈利排名2年",
        "expr": "rank(ts_rank(earnings, 504))",
        "settings": _NAN,
        "hypothesis": "过去2年盈利水平处于历史最高位，显示持续强劲的基本面",
        "category": "基本面/成长动量",
    },
    # ── 年度增速（绝对变化量）────────────────────────────────────────────────
    {
        "name": "GA01_盈利年度增速",
        "expr": "rank(ts_delta(earnings, 252))",
        "settings": _NAN,
        "hypothesis": "年度盈利绝对增量最大的公司，业绩改善幅度最强",
        "category": "基本面/成长加速",
    },
    {
        "name": "GA02_运营利润年度增速",
        "expr": "rank(ts_delta(operating_income, 252))",
        "settings": _NAN,
        "hypothesis": "年度运营利润增幅最大，运营业绩持续改善信号最强",
        "category": "基本面/成长加速",
    },
    {
        "name": "GA03_收入年度增速_板块",
        "expr": "group_rank(ts_delta(sales, 252), sector)",
        "settings": _BASE,
        "hypothesis": "板块内年度收入增速最快的公司，业务扩张动力最强",
        "category": "基本面/成长加速",
    },
    {
        "name": "GA04_盈利增速_行业内",
        "expr": "group_rank(ts_delta(earnings, 252), industry)",
        "settings": _NAN,
        "hypothesis": "行业内年度盈利提升最多，相对盈利改善最明显",
        "category": "基本面/成长加速",
    },
    {
        "name": "GA05_净资产增速_板块",
        "expr": "group_rank(ts_delta(assets - liabilities, 252), sector)",
        "settings": _BASE,
        "hypothesis": "板块内净资产增速最快，账面价值积累最快（成长潜力最强）",
        "category": "基本面/成长加速",
    },
    # ── 稳定性/可预期性因子 ──────────────────────────────────────────────────
    {
        "name": "GS01_盈利稳定性_行业",
        "expr": "group_rank(ts_mean(earnings, 252) / ts_std_dev(earnings, 252), industry)",
        "settings": _NAN,
        "hypothesis": "行业内盈利稳定性（均值/标准差）高的公司，财务更可预期",
        "category": "基本面/稳定性",
    },
    {
        "name": "GS02_收入稳定性_行业",
        "expr": "group_rank(ts_mean(sales, 252) / ts_std_dev(sales, 252), industry)",
        "settings": _BASE,
        "hypothesis": "行业内收入稳定性高的公司（低波动高均值），经营预期最可靠",
        "category": "基本面/稳定性",
    },
    {
        "name": "GS03_运营利润稳定性_行业",
        "expr": "group_rank(ts_mean(operating_income, 252) / ts_std_dev(operating_income, 252), industry)",
        "settings": _NAN,
        "hypothesis": "行业内运营利润稳定性高的公司，盈利可持续性最强",
        "category": "基本面/稳定性",
    },
    # ── 复合成长评分 ─────────────────────────────────────────────────────────
    {
        "name": "GC01_成长质量双因子",
        "expr": "group_rank(rank(ts_delta(earnings, 252)) + rank(earnings/assets), industry)",
        "settings": _NAN,
        "hypothesis": "行业内盈利增速+盈利能力(ROA)双维度评分，GARP(合理成长价格)选股",
        "category": "基本面/成长复合",
    },
    {
        "name": "GC02_质量成长综合_板块",
        "expr": "group_rank(rank(operating_income/sales) + rank(ts_delta(sales, 252)), sector)",
        "settings": _NAN,
        "hypothesis": "板块内高利润率+高收入增速，质量与成长兼具的最优公司",
        "category": "基本面/成长复合",
    },
]


if __name__ == "__main__":
    run_agent("agent_growth", ALPHAS)
