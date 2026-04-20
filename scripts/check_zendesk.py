"""Check session cookies and try Zendesk community access."""
import sys, json, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

state = json.loads(Path(r'D:\codeproject\auth-reptile\.state\session.json').read_text(encoding='utf-8'))
cookies = state.get('cookies', [])
domains = set(c.get('domain','') for c in cookies)
print('Cookie domains:', sorted(domains))

wq_cookies = [c for c in cookies if 'worldquant' in c.get('domain','')]
print(f'\nWQ cookies ({len(wq_cookies)}):')
for c in wq_cookies[:15]:
    d = c.get('domain','')
    n = c.get('name','')
    print(f"  domain={d} name={n}")

# Try to access Zendesk community with platform cookies
session = requests.Session()
session.proxies.update({"http": None, "https": None})

jar = requests.cookies.RequestsCookieJar()
for c in cookies:
    jar.set(c.get('name',''), c.get('value',''), 
            domain=c.get('domain','').lstrip('.'),
            path=c.get('path','/'))

session.cookies = jar

print('\nTrying support.worldquantbrain.com community...')
test_urls = [
    'https://support.worldquantbrain.com/hc/en-us/community/posts',
    'https://support.worldquantbrain.com/hc/en-us/community/topics',
    'https://support.worldquantbrain.com/api/v2/community/posts.json',
    'https://support.worldquantbrain.com/hc/en-us',
]
for url in test_urls:
    try:
        r = session.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        print(f"  {r.status_code} {len(r.text):6d}chars  {url}")
        if r.status_code == 200 and len(r.text) > 5000:
            print("    ACCESSIBLE!")
    except Exception as e:
        print(f"  ERROR: {e}  {url}")
