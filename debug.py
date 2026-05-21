import requests
from bs4 import BeautifulSoup

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
}

res = requests.get('https://wecima.cx', headers=headers)
soup = BeautifulSoup(res.text, 'html.parser')

print('STATUS:', res.status_code)
print('--- First 3000 chars of HTML ---')
print(res.text[:3000])
