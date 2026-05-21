import requests

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
}

# Test different URLs
urls = [
    'https://wecima.cx/feed/',
    'https://wecima.cx/sitemap.xml',
    'https://wecima.cx/sitemap_index.xml',
    'https://wecima.cx/post-sitemap.xml',
    'https://wecima.cx/?feed=rss2',
]

for url in urls:
    res = requests.get(url, headers=headers, timeout=10)
    print(f'{res.status_code} — {url}')
    if res.status_code == 200:
        print(res.text[:500])
        print('---')
