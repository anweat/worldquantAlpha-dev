import json, os

base = 'data/spa_crawl'
files = os.listdir(base)
for f in sorted(files):
    path = os.path.join(base, f)
    with open(path, encoding='utf-8') as fp:
        d = json.load(fp)
    length = d.get('raw_text_length', 0)
    if length > 500:
        print('=== {} (len={}) ==='.format(f, length))
        preview = d.get('raw_text_preview','')
        print(preview[:3000])
        alphas = d.get('alpha_expressions_found',[])
        if alphas:
            print('ALPHAS:', alphas)
        insights = d.get('key_insights',[])
        if insights:
            print('INSIGHTS:', insights[:5])
        print()
