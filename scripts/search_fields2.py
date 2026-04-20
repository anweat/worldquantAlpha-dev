"""Search data fields with minimal params."""
import sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\codeproject\worldquantAlpha-dev\src')
import brain_client as bc
BASE = bc.API_BASE
from brain_client import BrainClient

c = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')

queries = ['sentiment', 'analyst', 'buzz', 'implied', 'ebit', 'capex',
           'enterprise', 'earnings', 'news', 'short', 'estimate', 'volatility']
found_fields = []
for q in queries:
    r = c.session.get(f'{BASE}/search/datafields', params={'query': q, 'limit': 10})
    if r.status_code == 200:
        data = r.json()
        items = data if isinstance(data, list) else data.get('results', [])
        for x in items:
            fid = x.get('id') or x.get('name') or ''
            found_fields.append(fid)
        print(f'{q}: {[x.get("id","?") for x in items[:5]]}')
    else:
        print(f'{q}: {r.status_code} {r.text[:100]}')
    time.sleep(0.3)

print(f'\nAll found: {sorted(set(found_fields))}')
