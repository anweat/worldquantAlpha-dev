"""
generate_learning_charts.py
生成《从零理解BRAIN平台》文档中用到的所有示意图表
运行: python scripts/generate_learning_charts.py
输出: docs/img/ 目录下的 PNG 文件
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import os, warnings
warnings.filterwarnings('ignore')

# 确保输出目录存在
os.makedirs('docs/img', exist_ok=True)

# 全局字体设置（避免中文乱码）
plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 120

np.random.seed(42)

# ──────────────────────────────────────────────
# 1. 数据矩阵概念图
# ──────────────────────────────────────────────
def chart_data_matrix():
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('BRAIN 数据结构：矩阵概念', fontsize=15, fontweight='bold')

    stocks = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM']
    dates = ['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08']

    # 左图：close 价格矩阵
    ax = axes[0]
    data = np.array([
        [185.2, 374.0, 139.8, 153.4,  248.4, 346.2, 495.2, 169.5],
        [184.4, 374.5, 140.1, 153.1,  240.4, 345.0, 481.7, 170.2],
        [186.2, 375.8, 141.2, 155.0,  241.4, 344.2, 522.8, 170.8],
        [185.9, 374.4, 139.9, 154.2,  245.0, 341.2, 535.3, 171.1],
        [187.1, 378.9, 142.5, 156.0,  218.9, 353.0, 613.5, 172.0],
    ])
    im = ax.imshow(data, cmap='RdYlGn', aspect='auto')
    ax.set_xticks(range(len(stocks)))
    ax.set_xticklabels(stocks, rotation=45, fontsize=9)
    ax.set_yticks(range(len(dates)))
    ax.set_yticklabels(dates, fontsize=8)
    ax.set_title('close（收盘价）矩阵\n行=日期，列=股票', fontsize=11)
    for i in range(len(dates)):
        for j in range(len(stocks)):
            ax.text(j, i, f'{data[i,j]:.0f}', ha='center', va='center', fontsize=7, color='black')
    plt.colorbar(im, ax=ax, label='价格 ($)')

    # 右图：returns 矩阵
    ax2 = axes[1]
    returns = np.diff(data, axis=0) / data[:-1] * 100
    im2 = ax2.imshow(returns, cmap='RdYlGn', aspect='auto', vmin=-3, vmax=3)
    ax2.set_xticks(range(len(stocks)))
    ax2.set_xticklabels(stocks, rotation=45, fontsize=9)
    ax2.set_yticks(range(len(dates)-1))
    ax2.set_yticklabels(dates[1:], fontsize=8)
    ax2.set_title('returns（日收益率）矩阵\n= (close[t] - close[t-1]) / close[t-1]', fontsize=11)
    for i in range(len(dates)-1):
        for j in range(len(stocks)):
            ax2.text(j, i, f'{returns[i,j]:.2f}%', ha='center', va='center', fontsize=7,
                     color='black')
    plt.colorbar(im2, ax=ax2, label='日收益率 (%)')

    plt.tight_layout()
    plt.savefig('docs/img/01_data_matrix.png', bbox_inches='tight')
    plt.close()
    print('✓ 01_data_matrix.png')


# ──────────────────────────────────────────────
# 2. 数据集分类总览
# ──────────────────────────────────────────────
def chart_dataset_overview():
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')
    ax.set_title('BRAIN 平台数据集全景图', fontsize=16, fontweight='bold', pad=20)

    datasets = [
        # (x, y, w, h, title, fields_list, color)
        (0.2, 6.5, 4.5, 3.2, '价格/成交量\n(Price-Volume)',
         ['close  开盘价/收盘价', 'open / high / low', 'volume  成交量',
          'returns  日收益率', 'vwap  量加权均价', 'adv20  20日均量'],
         '#AED6F1', '换手率: 30-80%\n更新: 每日'),
        (5.3, 6.5, 4.5, 3.2, '基本面\n(Fundamentals)',
         ['assets  总资产', 'liabilities  总负债', 'sales  营业收入',
          'operating_income  营业利润', 'equity  股东权益', 'free_cash_flow'],
         '#A9DFBF', '换手率: 1-5%\n更新: 每季度'),
        (0.2, 3.0, 4.5, 3.2, '分析师预测\n(Analyst Estimates)',
         ['est_eps  EPS预测', 'est_revenue  营收预测', 'est_fcf  FCF预测',
          'est_ptp  目标价预测', 'etz_eps  EPS修正量', 'est_ebitda'],
         '#F9E79F', '换手率: 10-30%\n更新: 每日'),
        (5.3, 3.0, 4.5, 3.2, '情绪/新闻\n(Sentiment/News)',
         ['scl12_buzz  相对声量', 'snt1_cored1_score  情绪分',
          'snt1_d1_earningssurprise', 'nws12_afterhsz_*  新闻后涨幅',
          'snt1_d1_buyrecpercent', 'snt1_d1_analystcoverage'],
         '#F1948A', '换手率: 15-40%\n更新: 每日'),
        (0.2, 0.5, 4.5, 2.2, '期权\n(Options)',
         ['implied_volatility_call_120', 'implied_volatility_put_120',
          'parkinson_volatility_120', '（需 TOP2000 以上）'],
         '#D7BDE2', '换手率: 15-30%\n更新: 每日'),
        (5.3, 0.5, 4.5, 2.2, '模型/技术\n(Model/Technical)',
         ['adv5/adv20/adv180', 'IndClass (行业分类)',
          '各种 Fundamental 数据集', '(fn_*, anl4_* 前缀字段)'],
         '#FDEBD0', '覆盖范围: TOP3000\n用于行业中性化'),
    ]

    for (x, y, w, h, title, fields, color, note) in datasets:
        rect = plt.Rectangle((x, y), w, h, linewidth=1.5, edgecolor='#555', facecolor=color, alpha=0.8)
        ax.add_patch(rect)
        ax.text(x + w/2, y + h - 0.35, title, ha='center', va='top',
                fontsize=10, fontweight='bold')
        for i, field in enumerate(fields):
            ax.text(x + 0.15, y + h - 0.75 - i * 0.35, '• ' + field,
                    ha='left', va='top', fontsize=7.5)
        ax.text(x + w - 0.1, y + 0.1, note, ha='right', va='bottom',
                fontsize=7, color='#555', style='italic')

    plt.tight_layout()
    plt.savefig('docs/img/02_dataset_overview.png', bbox_inches='tight')
    plt.close()
    print('✓ 02_dataset_overview.png')


# ──────────────────────────────────────────────
# 3. FE 表达式计算流程图
# ──────────────────────────────────────────────
def chart_fe_pipeline():
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.axis('off')
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 5)
    ax.set_title('Fast Expression 数据处理流水线\n以 group_rank(ts_rank(operating_income/equity, 126), sector) 为例',
                 fontsize=12, fontweight='bold')

    steps = [
        (0.5, 'Step 1\n原始数据',
         'operating_income[t]\n3000×1 向量\n（每股营业利润）\n\n季度更新，NaN较多',
         '#AED6F1'),
        (3.0, 'Step 2\n比率计算',
         'operating_income / equity\n\n消除公司规模差异\n→ 股权回报率代理',
         '#A9DFBF'),
        (5.5, 'Step 3\nts_rank(..., 126)',
         '与自身过去126天比较\n→ 今日值处于历史高位吗？\n\n输出: [0, 1]\n换手率大幅降低',
         '#F9E79F'),
        (8.0, 'Step 4\ngroup_rank(..., sector)',
         '在同行业内横截面排名\n→ 消除行业系统差异\n\n输出: 行业内 [0, 1]',
         '#F1948A'),
        (10.5, 'Step 5\n权重输出',
         'Alpha 持仓权重向量\n范围约 [-1, 1]\n\n正值=做多，负值=做空\n行业市场中性',
         '#D7BDE2'),
        (13.0, 'Step 6\n模拟回测',
         'BRAIN 执行5年回测\n→ 输出 Sharpe/Fitness\n/Turnover/Returns',
         '#FDEBD0'),
    ]

    colors_arrow = '#888'
    for i, (x, title, content, color) in enumerate(steps):
        rect = plt.Rectangle((x - 0.45, 0.5), 2.0, 4.0,
                              linewidth=1.5, edgecolor='#555', facecolor=color, alpha=0.85,
                              zorder=2)
        ax.add_patch(rect)
        ax.text(x + 0.55, 4.25, title, ha='center', va='top',
                fontsize=9, fontweight='bold', zorder=3)
        ax.text(x + 0.55, 3.75, content, ha='center', va='top',
                fontsize=7.5, zorder=3, linespacing=1.5)
        if i < len(steps) - 1:
            ax.annotate('', xy=(x + 1.6, 2.5), xytext=(x + 2.1, 2.5),
                        arrowprops=dict(arrowstyle='->', color=colors_arrow, lw=2), zorder=4)

    plt.tight_layout()
    plt.savefig('docs/img/03_fe_pipeline.png', bbox_inches='tight')
    plt.close()
    print('✓ 03_fe_pipeline.png')


# ──────────────────────────────────────────────
# 4. rank() 运算符演示
# ──────────────────────────────────────────────
def chart_rank_demo():
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle('rank() 运算符：将原始值转换为 [0,1] 均匀分布的截面排名', fontsize=13, fontweight='bold')

    stocks = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'WMT', 'PFE']
    
    # 原始 operating_income/equity（模拟真实分布，右偏）
    raw_values = np.array([0.28, 0.45, 0.22, 0.18, 0.12, 0.35, 0.85, 0.14, 0.19, 0.09])
    ranked = pd.Series(raw_values).rank(pct=True).values  # 0 to 1
    portfolio_weight = ranked - 0.5  # centered, ~[-0.5, 0.5]

    colors = ['#E74C3C' if w < 0 else '#27AE60' for w in portfolio_weight]

    ax1, ax2, ax3 = axes

    # 左：原始值
    ax1.bar(stocks, raw_values, color='#AED6F1', edgecolor='#555')
    ax1.set_title('原始值: operating_income / equity', fontsize=10)
    ax1.set_ylabel('数值')
    ax1.tick_params(axis='x', rotation=45)
    for i, v in enumerate(raw_values):
        ax1.text(i, v + 0.005, f'{v:.2f}', ha='center', fontsize=8)

    # 中：rank 后
    ax2.bar(stocks, ranked, color='#A9DFBF', edgecolor='#555')
    ax2.set_title('rank(operating_income/equity)\n→ 均匀分布于 [0, 1]', fontsize=10)
    ax2.set_ylabel('rank 值')
    ax2.set_ylim(0, 1.1)
    ax2.tick_params(axis='x', rotation=45)
    for i, v in enumerate(ranked):
        ax2.text(i, v + 0.01, f'{v:.2f}', ha='center', fontsize=8)

    # 右：持仓权重（rank - 0.5）
    ax3.bar(stocks, portfolio_weight, color=colors, edgecolor='#555')
    ax3.axhline(0, color='black', linewidth=1)
    ax3.set_title('持仓权重 = rank() 中性化后\n正值=做多  负值=做空', fontsize=10)
    ax3.set_ylabel('持仓权重')
    ax3.tick_params(axis='x', rotation=45)
    for i, v in enumerate(portfolio_weight):
        ax3.text(i, v + (0.01 if v >= 0 else -0.025), f'{v:.2f}', ha='center', fontsize=8)

    plt.tight_layout()
    plt.savefig('docs/img/04_rank_demo.png', bbox_inches='tight')
    plt.close()
    print('✓ 04_rank_demo.png')


# ──────────────────────────────────────────────
# 5. 时序运算符演示 (ts_rank, ts_delta, ts_std_dev)
# ──────────────────────────────────────────────
def chart_ts_operators():
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle('时序运算符（Time Series Operators）示意 — 以单只股票为例', fontsize=13, fontweight='bold')

    # 模拟一只股票的 operating_income 数据（季度更新）
    np.random.seed(10)
    t = np.arange(300)
    # 季度跳变的基本面数据
    quarterly = np.repeat(np.cumsum(np.random.randn(25) * 0.05 + 0.02) + 1.0, 12)[:300]
    noise = np.random.randn(300) * 0.005
    oi = quarterly + noise  # operating_income (约表示标准化后的值)

    # 模拟情绪声量（高频，每日）
    buzz = np.abs(np.random.randn(300)) * 0.5 + 0.5
    buzz[150:170] += 2.5  # 模拟新闻事件spike
    buzz[220:235] += 1.5

    ax_oi, ax_tsrank, ax_tsdelta, ax_buzz_std = axes.flatten()

    # 上左：原始 operating_income
    ax_oi.plot(t, oi, color='#3498DB', linewidth=1.5, label='operating_income/equity')
    ax_oi.fill_between(t, oi, alpha=0.15, color='#3498DB')
    ax_oi.set_title('原始基本面数据: operating_income/equity\n(季度更新，约每90天一个台阶)', fontsize=10)
    ax_oi.set_ylabel('值')
    ax_oi.set_xlabel('天数')
    ax_oi.legend(fontsize=8)
    ax_oi.grid(True, alpha=0.3)

    # 上右：ts_rank(oi, 126)
    ts_rank_result = pd.Series(oi).rolling(126).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    ax_tsrank.plot(t, ts_rank_result, color='#E74C3C', linewidth=1.5)
    ax_tsrank.axhline(0.5, color='gray', linestyle='--', alpha=0.5, label='中位线')
    ax_tsrank.fill_between(t, ts_rank_result, 0.5, where=ts_rank_result > 0.5,
                            alpha=0.3, color='#27AE60', label='做多信号')
    ax_tsrank.fill_between(t, ts_rank_result, 0.5, where=ts_rank_result < 0.5,
                            alpha=0.3, color='#E74C3C', label='做空信号')
    ax_tsrank.set_title('ts_rank(operating_income/equity, 126)\n当前值在过去126天中的百分位', fontsize=10)
    ax_tsrank.set_ylabel('[0, 1]')
    ax_tsrank.set_xlabel('天数')
    ax_tsrank.legend(fontsize=8)
    ax_tsrank.grid(True, alpha=0.3)
    ax_tsrank.set_ylim(-0.05, 1.05)

    # 下左：ts_delta
    ts_delta_5 = pd.Series(oi).diff(5)
    ts_delta_20 = pd.Series(oi).diff(20)
    ax_tsdelta.plot(t, ts_delta_5, color='#F39C12', linewidth=1, label='ts_delta(oi, 5)')
    ax_tsdelta.plot(t, ts_delta_20, color='#8E44AD', linewidth=1.5, label='ts_delta(oi, 20)')
    ax_tsdelta.axhline(0, color='black', linewidth=0.8)
    ax_tsdelta.fill_between(t, ts_delta_20, 0, where=ts_delta_20 > 0,
                             alpha=0.2, color='#27AE60')
    ax_tsdelta.fill_between(t, ts_delta_20, 0, where=ts_delta_20 < 0,
                             alpha=0.2, color='#E74C3C')
    ax_tsdelta.set_title('ts_delta(x, d) = x[t] - x[t-d]\n换手率高（信号变化快）', fontsize=10)
    ax_tsdelta.set_ylabel('变化量')
    ax_tsdelta.set_xlabel('天数')
    ax_tsdelta.legend(fontsize=8)
    ax_tsdelta.grid(True, alpha=0.3)

    # 下右：-ts_std_dev(buzz, 18) 情绪波动信号
    ax_buzz_std.plot(t, buzz, color='#AED6F1', linewidth=0.8, alpha=0.7, label='scl12_buzz 原始值')
    std_buzz = pd.Series(buzz).rolling(18).std()
    signal = -std_buzz
    ax_buzz_std.plot(t, std_buzz * 3, color='#E74C3C', linewidth=1.5, label='ts_std_dev(buzz, 18) ×3')
    ax2_twin = ax_buzz_std.twinx()
    ax2_twin.plot(t, signal, color='#27AE60', linewidth=2, linestyle='--',
                  label='-ts_std_dev (做多信号)')
    ax2_twin.set_ylabel('-ts_std_dev', color='#27AE60')
    ax_buzz_std.set_title('-ts_std_dev(scl12_buzz, 18)\n情绪声量波动大→做空（反向）', fontsize=10)
    ax_buzz_std.set_ylabel('buzz 值 / std×3')
    ax_buzz_std.set_xlabel('天数')
    ax_buzz_std.legend(fontsize=8, loc='upper left')
    ax2_twin.legend(fontsize=8, loc='upper right')
    ax_buzz_std.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('docs/img/05_ts_operators.png', bbox_inches='tight')
    plt.close()
    print('✓ 05_ts_operators.png')


# ──────────────────────────────────────────────
# 6. 中性化（Neutralization）演示
# ──────────────────────────────────────────────
def chart_neutralization():
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('中性化（Neutralization）的效果：消除市场/行业系统性暴露', fontsize=13, fontweight='bold')

    np.random.seed(7)
    n = 30
    sectors = ['科技'] * 10 + ['金融'] * 10 + ['能源'] * 10
    
    # 模拟原始信号（科技行业整体值偏高，能源偏低）
    raw = np.concatenate([
        np.random.randn(10) + 1.5,   # 科技
        np.random.randn(10) + 0.0,   # 金融
        np.random.randn(10) - 1.2,   # 能源
    ])
    
    # 市场中性化：减去全体均值
    market_neutral = raw - raw.mean()
    
    # 行业中性化：在每个行业内减去该行业均值
    sector_neutral = raw.copy()
    for i, s in enumerate(set(sectors)):
        mask = np.array(sectors) == s
        sector_neutral[mask] -= raw[mask].mean()

    colors_map = {'科技': '#AED6F1', '金融': '#A9DFBF', '能源': '#F1948A'}
    colors_list = [colors_map[s] for s in sectors]

    for ax, data, title in zip(
        axes,
        [raw, market_neutral, sector_neutral],
        ['原始信号 raw(operating_income/equity)',
         'MARKET 中性化后\n= raw - mean(raw)', 
         'SECTOR 中性化后\n= raw - mean_per_sector(raw)']
    ):
        x = np.arange(n)
        ax.bar(x, data, color=colors_list, edgecolor='white', linewidth=0.5)
        ax.axhline(0, color='black', linewidth=1)
        if ax != axes[0]:
            for s in set(sectors):
                mask = np.where(np.array(sectors) == s)[0]
                mean_val = data[mask].mean()
                ax.axhline(mean_val, color=colors_map[s], linewidth=1.5, linestyle='--',
                          alpha=0.6, xmin=mask[0]/n, xmax=(mask[-1]+1)/n)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel('股票编号')
        ax.set_ylabel('信号值')
        net = data.sum()
        ax.text(0.5, 0.02, f'净多头暴露: {net:.2f}', transform=ax.transAxes,
                ha='center', va='bottom', fontsize=9,
                bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    patches = [mpatches.Patch(color=v, label=k) for k, v in colors_map.items()]
    fig.legend(handles=patches, loc='lower center', ncol=3, fontsize=10,
               bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout()
    plt.savefig('docs/img/06_neutralization.png', bbox_inches='tight')
    plt.close()
    print('✓ 06_neutralization.png')


# ──────────────────────────────────────────────
# 7. Decay（衰减）效果演示
# ──────────────────────────────────────────────
def chart_decay():
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle('Decay（线性衰减）的作用：平滑信号、降低换手率', fontsize=13, fontweight='bold')

    np.random.seed(5)
    t = np.arange(60)
    raw_signal = np.sin(t * 0.2) + np.random.randn(60) * 0.4

    def decay_linear(series, d):
        weights = np.arange(1, d + 1, dtype=float)
        weights = weights / weights.sum()
        return pd.Series(series).rolling(d).apply(
            lambda x: np.dot(x, weights), raw=True)

    d4 = decay_linear(raw_signal, 4)
    d8 = decay_linear(raw_signal, 8)
    d16 = decay_linear(raw_signal, 16)

    ax1, ax2 = axes

    ax1.plot(t, raw_signal, 'o-', color='#AED6F1', linewidth=1, markersize=3,
             label='decay=0 (原始信号)', alpha=0.7)
    ax1.plot(t, d4, '-', color='#F39C12', linewidth=2, label='decay=4')
    ax1.plot(t, d8, '-', color='#E74C3C', linewidth=2, label='decay=8')
    ax1.plot(t, d16, '-', color='#8E44AD', linewidth=2, label='decay=16')
    ax1.set_title('信号平滑效果\n（decay越大越平滑，但信号滞后）', fontsize=11)
    ax1.legend(fontsize=9)
    ax1.set_xlabel('天数')
    ax1.set_ylabel('信号值')
    ax1.grid(True, alpha=0.3)

    # 右图：换手率变化示意
    turnover_raw = np.abs(np.diff(raw_signal)).mean() * 100
    turnover_d4 = np.abs(np.diff(d4.dropna())).mean() * 100
    turnover_d8 = np.abs(np.diff(d8.dropna())).mean() * 100
    turnover_d16 = np.abs(np.diff(d16.dropna())).mean() * 100

    labels = ['decay=0', 'decay=4', 'decay=8', 'decay=16']
    values = [turnover_raw, turnover_d4, turnover_d8, turnover_d16]
    bar_colors = ['#AED6F1', '#F39C12', '#E74C3C', '#8E44AD']
    
    bars = ax2.bar(labels, values, color=bar_colors, edgecolor='#555', width=0.5)
    ax2.axhline(70, color='red', linestyle='--', linewidth=1.5, label='70% 换手率上限')
    ax2.set_title('Decay 对换手率的降低效果\n（相对值，仅供示意）', fontsize=11)
    ax2.set_ylabel('日均换手率（相对）')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, values):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                 f'{val:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

    plt.tight_layout()
    plt.savefig('docs/img/07_decay.png', bbox_inches='tight')
    plt.close()
    print('✓ 07_decay.png')


# ──────────────────────────────────────────────
# 8. Sharpe / Fitness / Turnover 关系图
# ──────────────────────────────────────────────
def chart_fitness_formula():
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle('Fitness 公式解析：Sharpe × √(|Returns| / max(Turnover, 0.125))', fontsize=13, fontweight='bold')

    ax1, ax2 = axes

    # 左图：换手率 vs Fitness（固定 Sharpe=1.5, Returns=10%）
    turnover = np.linspace(0.01, 0.80, 200)
    returns_val = 0.10
    sharpe = 1.5
    fitness_vals = sharpe * np.sqrt(np.abs(returns_val) / np.maximum(turnover, 0.125))

    ax1.plot(turnover * 100, fitness_vals, color='#3498DB', linewidth=2.5)
    ax1.axhline(1.0, color='red', linestyle='--', linewidth=1.5, label='Fitness = 1.0 (提交门槛)')
    ax1.axvline(70, color='orange', linestyle='--', linewidth=1.5, label='70% 换手率上限')
    ax1.fill_between(turnover * 100, fitness_vals, 1.0,
                      where=fitness_vals >= 1.0, alpha=0.2, color='#27AE60', label='通过区域')
    ax1.fill_between(turnover * 100, fitness_vals, 1.0,
                      where=fitness_vals < 1.0, alpha=0.2, color='#E74C3C', label='不通过区域')
    ax1.set_title(f'换手率 vs Fitness\n(Sharpe={sharpe}, Returns={returns_val*100:.0f}%)', fontsize=11)
    ax1.set_xlabel('换手率 (%)')
    ax1.set_ylabel('Fitness')
    ax1.legend(fontsize=9)
    ax1.set_xlim(0, 85)
    ax1.grid(True, alpha=0.3)

    # 标注几个代表点
    for to, label, color in [(0.05, '5%换手\n基本面', '#27AE60'),
                               (0.25, '25%换手\n情绪类', '#F39C12'),
                               (0.60, '60%换手\n技术类', '#E74C3C')]:
        f = sharpe * np.sqrt(returns_val / max(to, 0.125))
        ax1.annotate(f'{label}\nFit={f:.2f}', xy=(to*100, f),
                      xytext=(to*100+3, f+0.1), fontsize=8,
                      arrowprops=dict(arrowstyle='->', color=color),
                      color=color, fontweight='bold')

    # 右图：实测通过 Alpha 的分布散点图
    # 来自真实结果数据
    real_alphas = [
        ('基本面', 1.92, 5.0, 2.09),
        ('基本面', 1.44, 6.7, 2.04),
        ('基本面', 1.42, 7.2, 2.06),
        ('基本面', 1.35, 1.5, 1.51),
        ('基本面', 1.28, 1.8, 1.55),
        ('基本面', 1.14, 7.0, 1.75),
        ('基本面', 1.09, 7.2, 1.72),
        ('情绪',   1.67, 13.5, 1.47),
        ('情绪',   1.66, 10.3, 1.44),
        ('情绪',   1.60, 23.5, 1.81),
        ('情绪',   1.46, 38.8, 1.99),
        ('情绪',   1.36, 15.6, 1.34),
        ('情绪',   1.23, 18.8, 1.32),
        ('期权',   1.35, 25.3, 1.53),
    ]
    
    cat_colors = {'基本面': '#27AE60', '情绪': '#F39C12', '期权': '#8E44AD'}
    for cat, fitness, turnover_pct, sharpe_val in real_alphas:
        ax2.scatter(turnover_pct, fitness, c=cat_colors[cat], s=sharpe_val*40,
                    alpha=0.8, edgecolors='#555', linewidth=0.5, zorder=3)

    ax2.axhline(1.0, color='red', linestyle='--', linewidth=1.5, label='Fitness门槛=1.0')
    ax2.axvline(70, color='orange', linestyle='--', linewidth=1.5, label='换手率上限70%')
    ax2.set_title('实测通过 Alpha 的分布\n（点大小 = Sharpe，颜色 = 数据类别）', fontsize=11)
    ax2.set_xlabel('换手率 (%)')
    ax2.set_ylabel('Fitness')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, 80)
    ax2.set_ylim(0.8, 2.2)

    patches = [mpatches.Patch(color=v, label=k) for k, v in cat_colors.items()]
    ax2.legend(handles=patches + [
        mpatches.Patch(color='red', label='Fitness门槛=1.0'),
        mpatches.Patch(color='orange', label='换手率上限70%'),
    ], fontsize=8)

    plt.tight_layout()
    plt.savefig('docs/img/08_fitness_formula.png', bbox_inches='tight')
    plt.close()
    print('✓ 08_fitness_formula.png')


# ──────────────────────────────────────────────
# 9. Alpha 模拟结果解读：PnL 图对比
# ──────────────────────────────────────────────
def chart_pnl_comparison():
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('Alpha 模拟结果对比：PnL 曲线（5年IS期间）', fontsize=13, fontweight='bold')

    np.random.seed(42)
    days = 1260  # 5年交易日

    def generate_pnl(sharpe, volatility, trend=None):
        daily_ret = np.random.randn(days) * volatility
        if trend is not None:
            daily_ret += trend
        else:
            daily_ret += sharpe * volatility / np.sqrt(252)
        return np.cumsum(daily_ret)

    # 低质量Alpha（Sharpe<1，高波动）
    bad_pnl = generate_pnl(0.6, 0.015)
    # 中等Alpha（Sharpe~1.2）
    ok_pnl = generate_pnl(1.2, 0.010)
    # 好Alpha（Sharpe~2.0，低波动）
    good_pnl = generate_pnl(2.0, 0.006)

    scenarios = [
        (bad_pnl, '❌ 差 Alpha\nSharpe=0.6, Fitness<1.0\n高波动，多次大幅回撤', '#E74C3C'),
        (ok_pnl, '⚠️ 勉强通过\nSharpe=1.2, Fitness~1.0\n走势有起伏但整体向上', '#F39C12'),
        (good_pnl, '✅ 优质 Alpha\nSharpe=2.0, Fitness>1.4\n稳定上升，回撤小', '#27AE60'),
    ]

    for ax, (pnl, title, color) in zip(axes, scenarios):
        ax.plot(pnl, color=color, linewidth=1.5)
        ax.fill_between(range(days), pnl, 0, where=pnl > 0, alpha=0.15, color=color)
        ax.fill_between(range(days), pnl, 0, where=pnl < 0, alpha=0.3, color='#E74C3C')
        ax.axhline(0, color='black', linewidth=0.8)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel('交易天数')
        ax.set_ylabel('累计 PnL')
        ax.grid(True, alpha=0.3)
        
        # 标注最大回撤
        running_max = np.maximum.accumulate(pnl)
        drawdown = pnl - running_max
        max_dd_idx = np.argmin(drawdown)
        peak_idx = np.argmax(pnl[:max_dd_idx+1])
        ax.annotate('', xy=(max_dd_idx, pnl[max_dd_idx]),
                    xytext=(peak_idx, pnl[peak_idx]),
                    arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(max_dd_idx, (pnl[max_dd_idx]+pnl[peak_idx])/2,
                f' MaxDD={drawdown.min():.3f}', fontsize=8, color='purple')

    plt.tight_layout()
    plt.savefig('docs/img/09_pnl_comparison.png', bbox_inches='tight')
    plt.close()
    print('✓ 09_pnl_comparison.png')


# ──────────────────────────────────────────────
# 10. group_rank + ts_rank 实测效果图
# ──────────────────────────────────────────────
def chart_grouprank_results():
    """基于真实批次结果展示参数调优效果"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('实测：group_rank(ts_rank(operating_income/equity, lookback), group_level) 参数调优',
                 fontsize=12, fontweight='bold')

    # 实测数据（来自 wave9 批次）
    results = [
        # (lookback, group, sharpe, fitness, turnover)
        (63,  'sector',      1.52, 0.89, 0.075),
        (95,  'sector',      1.94, 1.29, 0.077),
        (126, 'sector',      2.04, 1.44, 0.067),
        (150, 'sector',      1.99, 1.41, 0.064),
        (175, 'sector',      1.98, 1.41, 0.064),
        (252, 'sector',      1.86, 1.35, 0.058),
        (126, 'industry',    2.06, 1.42, 0.072),
        (126, 'subindustry', 2.01, 1.32, 0.063),
        (126, 'market',      1.45, 0.85, 0.081),
    ]

    df = pd.DataFrame(results, columns=['lookback', 'group', 'sharpe', 'fitness', 'turnover'])

    ax1, ax2 = axes

    # 左图：lookback vs 指标（固定 sector）
    sector_data = df[df['group'] == 'sector'].sort_values('lookback')
    x = sector_data['lookback'].values
    ax1.plot(x, sector_data['sharpe'], 'o-', color='#3498DB', linewidth=2, markersize=8,
             label='Sharpe')
    ax1.plot(x, sector_data['fitness'], 's-', color='#27AE60', linewidth=2, markersize=8,
             label='Fitness')
    ax1.plot(x, sector_data['turnover'] * 10, '^--', color='#E74C3C', linewidth=1.5, markersize=7,
             label='Turnover ×10')
    ax1.axhline(1.25, color='#3498DB', linestyle=':', alpha=0.5, label='Sharpe门槛=1.25')
    ax1.axhline(1.0, color='#27AE60', linestyle=':', alpha=0.5, label='Fitness门槛=1.0')
    ax1.set_title('group=sector 时，lookback 的影响\n（126天最优）', fontsize=11)
    ax1.set_xlabel('lookback 天数')
    ax1.set_ylabel('指标值')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    for xi, f in zip(x, sector_data['fitness']):
        ax1.annotate(f'{f:.2f}', xy=(xi, f), xytext=(0, 8), textcoords='offset points',
                     ha='center', fontsize=8, color='#27AE60')

    # 右图：不同 group 对比（固定 lookback=126）
    lb126 = df[df['lookback'] == 126].sort_values('fitness', ascending=False)
    groups = lb126['group'].values
    x2 = np.arange(len(groups))
    width = 0.3

    bars1 = ax2.bar(x2 - width, lb126['sharpe'], width, label='Sharpe', color='#3498DB', alpha=0.85)
    bars2 = ax2.bar(x2, lb126['fitness'], width, label='Fitness', color='#27AE60', alpha=0.85)
    bars3 = ax2.bar(x2 + width, lb126['turnover'] * 10, width, label='Turnover ×10',
                     color='#E74C3C', alpha=0.85)

    ax2.axhline(1.25, color='#3498DB', linestyle=':', alpha=0.5)
    ax2.axhline(1.0, color='#27AE60', linestyle=':', alpha=0.5)
    ax2.set_title('lookback=126 时，不同 group 级别的效果', fontsize=11)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(groups, fontsize=10)
    ax2.set_ylabel('指标值')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars2, lb126['fitness']):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                 f'{val:.2f}', ha='center', fontsize=9, fontweight='bold', color='#27AE60')

    plt.tight_layout()
    plt.savefig('docs/img/10_grouprank_results.png', bbox_inches='tight')
    plt.close()
    print('✓ 10_grouprank_results.png')


# ──────────────────────────────────────────────
# 11. 数据类型 vs Alpha 策略成功率热图
# ──────────────────────────────────────────────
def chart_strategy_heatmap():
    fig, ax = plt.subplots(figsize=(11, 7))
    fig.suptitle('不同数据类型 × Alpha 模式的实测 Fitness 热图', fontsize=13, fontweight='bold')

    patterns = ['rank(ratio)', 'group_rank(ratio)', 'ts_rank(field, 126)',
                 'group_rank(ts_rank)', '-ts_std_dev', 'ts_corr', 'ts_delta']
    data_types = ['基本面\n(fundamental)', '分析师预测\n(analyst)', '情绪/新闻\n(sentiment)',
                  '期权\n(options)', '价格/量\n(price-vol)']

    fitness_matrix = np.array([
        # rank  gr_rank  ts_rank  gr+ts  std_dev  corr  delta
        [1.35,   1.44,    1.40,   1.92,    0.30,  0.60,  0.20],  # 基本面
        [0.80,   1.00,    1.10,   1.30,    0.40,  1.00,  0.30],  # 分析师
        [0.50,   0.70,    0.80,   0.90,    1.67,  0.80,  0.60],  # 情绪
        [0.60,   0.70,    0.70,   0.80,    0.60,  0.70,  0.40],  # 期权
        [0.50,   0.60,    0.60,   0.70,    0.50,  0.50,  0.20],  # 价格量
    ])

    im = ax.imshow(fitness_matrix, cmap='RdYlGn', vmin=0.0, vmax=2.0, aspect='auto')
    ax.set_xticks(range(len(patterns)))
    ax.set_xticklabels(patterns, fontsize=9, rotation=20, ha='right')
    ax.set_yticks(range(len(data_types)))
    ax.set_yticklabels(data_types, fontsize=10)

    for i in range(len(data_types)):
        for j in range(len(patterns)):
            val = fitness_matrix[i, j]
            color = 'white' if val > 1.5 or val < 0.4 else 'black'
            ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                    fontsize=11, color=color, fontweight='bold')

    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('预期 Fitness', fontsize=10)
    cbar.ax.axhline(1.0, color='red', linewidth=2)
    cbar.ax.text(2.5, 1.0, '← 提交门槛', va='center', color='red', fontsize=8)

    ax.set_xlabel('Alpha 表达式模式', fontsize=11, labelpad=10)
    ax.set_ylabel('数据类型', fontsize=11)

    plt.tight_layout()
    plt.savefig('docs/img/11_strategy_heatmap.png', bbox_inches='tight')
    plt.close()
    print('✓ 11_strategy_heatmap.png')


# ──────────────────────────────────────────────
# 12. Alpha 开发完整工作流图
# ──────────────────────────────────────────────
def chart_workflow():
    fig, ax = plt.subplots(figsize=(14, 8))
    ax.axis('off')
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8)
    ax.set_title('WorldQuant BRAIN Alpha 开发完整工作流', fontsize=15, fontweight='bold')

    steps = [
        # (x, y, w, h, emoji, title, desc, color)
        (0.3, 5.5, 2.8, 2.2, '💡', '1. 想法生成\n(Hypothesis)',
         '• 选择数据类别\n• 构建市场假设\n• 参考学术论文', '#AED6F1'),
        (3.3, 5.5, 2.8, 2.2, '✍️', '2. 编写表达式\n(Expression)',
         '• 用 FE 语法写公式\n• rank/ts_rank等算子\n• 选择中性化方式', '#A9DFBF'),
        (6.3, 5.5, 2.8, 2.2, '⚙️', '3. 配置设置\n(Settings)',
         '• decay / truncation\n• neutralization\n• universe / delay', '#F9E79F'),
        (9.3, 5.5, 2.8, 2.2, '🚀', '4. 提交模拟\n(Simulate)',
         '• POST /simulations\n• 等待 COMPLETE\n• 轮询状态', '#F1948A'),
        (11.8, 4.0, 2.0, 1.5, '⏳', '轮询等待', 'UNKNOWN\n→ COMPLETE\n(约1-3分钟)', '#FDEBD0'),
        (9.3, 2.5, 2.8, 2.2, '📊', '5. 查看结果\n(IS Metrics)',
         '• Sharpe/Fitness\n• Turnover/Returns\n• Check 通过列表', '#D7BDE2'),
        (6.3, 2.5, 2.8, 2.2, '🔧', '6. 优化迭代\n(Optimize)',
         '• 调窗口/中性化\n• 换字段组合\n• 多因子叠加', '#FAD7A0'),
        (3.3, 2.5, 2.8, 2.2, '✅', '7. 提交 Alpha\n(Submit)',
         '• 全 Checks 通过\n• POST /submit\n• 进入OS评分', '#A9DFBF'),
        (0.3, 2.5, 2.8, 2.2, '🏆', '8. 参加竞赛\n(Compete)',
         '• IQC/OC 积分\n• 多样化 Alpha 池\n• 提升排名', '#AED6F1'),
    ]

    for (x, y, w, h, emoji, title, desc, color) in steps:
        rect = plt.Rectangle((x, y), w, h, linewidth=1.5, edgecolor='#555',
                              facecolor=color, alpha=0.85, zorder=2)
        ax.add_patch(rect)
        ax.text(x + w/2, y + h - 0.2, f'{emoji} {title}', ha='center', va='top',
                fontsize=9, fontweight='bold', zorder=3)
        ax.text(x + w/2, y + h - 0.75, desc, ha='center', va='top',
                fontsize=7.5, zorder=3, linespacing=1.5)

    # 箭头：主流程
    arrow_style = dict(arrowstyle='->', color='#555', lw=2)
    # 上排 (右)
    for x_start in [3.1, 6.1, 9.1]:
        ax.annotate('', xy=(x_start, 6.6), xytext=(x_start - 0.2, 6.6),
                    arrowprops=arrow_style, zorder=4)
    # 4→轮询→5
    ax.annotate('', xy=(12.8, 5.5), xytext=(12.8, 5.7),
                arrowprops=arrow_style, zorder=4)
    ax.annotate('', xy=(12.0, 3.5), xytext=(12.8, 3.5),
                arrowprops=arrow_style, zorder=4)
    ax.annotate('', xy=(9.3+1.4, 4.7), xytext=(11.8, 4.7),
                arrowprops=dict(arrowstyle='->', color='#555', lw=2), zorder=4)
    # 下排 (左)
    for x_start in [9.1, 6.1, 3.1]:
        ax.annotate('', xy=(x_start, 3.6), xytext=(x_start + 0.2, 3.6),
                    arrowprops=arrow_style, zorder=4)
    # 6 → 优化回环
    ax.annotate('迭代\n优化', xy=(7.7, 5.5), xytext=(7.7, 4.7),
                arrowprops=dict(arrowstyle='->', color='#E74C3C', lw=2),
                fontsize=8, ha='center', color='#E74C3C', zorder=4)

    # 说明注释
    ax.text(7.0, 0.5, '通过标准：Sharpe ≥ 1.25  AND  Fitness ≥ 1.0  AND  1% ≤ Turnover ≤ 70%',
            ha='center', va='bottom', fontsize=10, color='#C0392B',
            bbox=dict(boxstyle='round', facecolor='#FDEBD0', alpha=0.9))

    plt.tight_layout()
    plt.savefig('docs/img/12_workflow.png', bbox_inches='tight')
    plt.close()
    print('✓ 12_workflow.png')


# ──────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────
if __name__ == '__main__':
    print('正在生成学习文档图表...')
    chart_data_matrix()
    chart_dataset_overview()
    chart_fe_pipeline()
    chart_rank_demo()
    chart_ts_operators()
    chart_neutralization()
    chart_decay()
    chart_fitness_formula()
    chart_pnl_comparison()
    chart_grouprank_results()
    chart_strategy_heatmap()
    chart_workflow()
    print('\n全部图表生成完毕！保存在 docs/img/ 目录')
