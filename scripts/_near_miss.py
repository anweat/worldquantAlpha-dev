from wq_bus.data._sqlite import open_knowledge
with open_knowledge() as c:
    rows = list(c.execute(
        "SELECT expression, sharpe, fitness, turnover FROM alphas "
        "WHERE sharpe IS NOT NULL AND sharpe >= 0.9 AND fitness >= 0.6 "
        "AND alpha_id NOT LIKE 'DRY%' ORDER BY sharpe DESC LIMIT 12"
    ))
    for r in rows:
        print(dict(r))
    print('count:', len(rows))
