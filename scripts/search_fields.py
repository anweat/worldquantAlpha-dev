"""Search BRAIN API for available data fields by category."""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\codeproject\worldquantAlpha-dev\src')
from brain_client import BrainClient

c = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')
auth = c.check_auth()
print(f'Auth: {auth["status"]}')
if auth['status'] != 200:
    print('Session expired!')
    sys.exit(1)

queries = [
    'sentiment', 'analyst', 'options', 'news', 'estimate',
    'earnings', 'implied', 'volatility', 'enterprise', 'capex',
    'ebit', 'buzz', 'short', 'sector', 'industry', 'fair',
    'retained', 'cash', 'debt', 'total'
]

all_fields = {}
for q in queries:
    try:
        result = c.search_datafields(q, limit=10)
        items = result if isinstance(result, list) else result.get('results', result.get('items', []))
        if items:
            ids = []
            for x in items[:8]:
                fid = x.get('id') or x.get('name') or x.get('dataFieldId', '')
                ftype = x.get('type', x.get('category', ''))
                ids.append(f"{fid}({ftype})" if ftype else str(fid))
            print(f'  {q:12s}: {", ".join(ids[:6])}')
            for x in items:
                fid = x.get('id') or x.get('name') or x.get('dataFieldId', '')
                if fid:
                    all_fields[str(fid)] = x.get('description', x.get('type', ''))[:80]
        else:
            print(f'  {q:12s}: no results ({type(result).__name__})')
    except Exception as e:
        print(f'  {q:12s}: ERROR {e}')
    time.sleep(0.5)

print(f'\nTotal unique fields found: {len(all_fields)}')
print('\nAll discovered fields:')
for k, v in sorted(all_fields.items()):
    print(f'  {k}: {v}')
