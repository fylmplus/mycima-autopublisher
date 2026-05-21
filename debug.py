import requests
from bs4 import BeautifulSoup
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
}

# Use one of the URLs already in your database
url = "https://wecima.cx/watch/%D9%85%D8%B3%D9%84%D8%B3%D9%84-%D8%A7%D9%84%D9%84%D8%B9%D8%A8%D8%A9-%D9%85%D9%88%D8%B3%D9%85-5-%D8%AD%D9%84%D9%82%D8%A9-30"

res = requests.get(url, headers=headers, timeout=15)
soup = BeautifulSoup(res.text, 'html.parser')

print('STATUS:', res.status_code)

# Check iframes
iframes = soup.select('iframe')
print(f'\nIFRAMES FOUND: {len(iframes)}')
for i in iframes:
    print(' ', i.get('src') or i.get('data-src'))

# Check download links
print('\nDOWNLOAD LINKS:')
for sel in ['a.DownloadBtn', '.downloadLinks a', '[class*="download"] a']:
    els = soup.select(sel)
    if els:
        print(f'  Selector "{sel}" found {len(els)}:')
        for el in els[:5]:
            print('   ', el.get('href'), '|', el.get_text(strip=True)[:50])

# Check scripts for embed URLs
print('\nEMBED URLs IN SCRIPTS:')
for script in soup.find_all('script'):
    text = script.get_text()
    found = re.findall(r'https?://[^\s"\'<>]{10,}', text)
    for f in found:
        if any(k in f.lower() for k in ['embed', 'player', 'stream', 'vidbom', 'streamwish', 'dood', 'filemoon']):
            print(' ', f)
