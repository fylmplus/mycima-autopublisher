import requests
from bs4 import BeautifulSoup
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
}

url = "https://wecima.cx/watch/%D9%85%D8%B3%D9%84%D8%B3%D9%84-%D8%A7%D9%84%D9%84%D8%B9%D8%A8%D8%A9-%D9%85%D9%88%D8%B3%D9%85-5-%D8%AD%D9%84%D9%82%D8%A9-30"

res = requests.get(url, headers=headers, timeout=15)
soup = BeautifulSoup(res.text, 'html.parser')

# Find iframe with data attributes
print('=== IFRAMES ===')
for i in soup.find_all('iframe'):
    print(i)

# Find download links with data attributes  
print('\n=== DOWNLOAD ELEMENTS ===')
for el in soup.select('[class*="download"]')[:5]:
    print(el)

# Find any data-src or data-url attributes
print('\n=== ALL data-src / data-url ATTRIBUTES ===')
for tag in soup.find_all(True):
    for attr in ['data-src', 'data-url', 'data-link', 'data-href', 'data-embed']:
        val = tag.get(attr)
        if val and val.startswith('http'):
            print(f'{tag.name} {attr}="{val}"')
