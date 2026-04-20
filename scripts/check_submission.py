"""Check submission eligibility for passing alphas and trigger submission checks."""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from brain_client import BrainClient

c = BrainClient(state_file=r'D:\codeproject\auth-reptile\.state\session.json')

# Load passing alphas
with open(Path(__file__).parent.parent / 'data/unsubmitted_analysis.json', encoding='utf-8') as f:
    analysis = json.load(f)

passing = analysis['passing_alphas']
print(f"Checking {len(passing)} passing alphas...")

# Check one in detail
aid = passing[0]['id']
data = c.get_alpha(aid)
print(f"\nAlpha {aid}:")
print(f"  Status: {data.get('status')}")
print(f"  Grade: {data.get('grade')}")
is_data = data.get('is', {})
for chk in is_data.get('checks', []):
    name = chk['name']
    result = chk['result']
    value = chk.get('value')
    limit = chk.get('limit')
    print(f"  {name}: {result} (value={value}, limit={limit})")

# Try submit check (POST /alphas/{id}/submit but dry run?)
# Actually let's try check-submission endpoint
import requests
r = c.session.get(
    f'https://api.worldquantbrain.com/alphas/{aid}/check-submission',
    headers={'Accept': 'application/json;version=2.0'}
)
print(f"\nCheck-submission status: {r.status_code}")
if r.content:
    try:
        print(json.dumps(r.json(), indent=2)[:500])
    except:
        print(r.text[:300])
