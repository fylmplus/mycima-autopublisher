import requests
from bs4 import BeautifulSoup

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
}

res = requests.get('https://wecima.cx', headers=headers)
soup = BeautifulSoup(res.text, 'html.parser')

print('STATUS:', res.status_code)
print('TOTAL HTML LENGTH:', len(res.text))

# Print all unique class names found in divs and articles
print('\n--- ALL DIV/ARTICLE CLASSES ---')
classes = set()
for tag in soup.find_all(['div', 'article', 'li'], class_=True):
    for c in tag.get('class', []):
        classes.add(c)
for c in sorted(classes):
    print(c)

# Try to find any links that look like content
print('\n--- SAMPLE CONTENT LINKS ---')
for a in soup.find_all('a', href=True)[:30]:
    href = a.get('href', '')
    if '/watch/' in href or '/series/' in href or '/anime/' in href:
        print(href)
