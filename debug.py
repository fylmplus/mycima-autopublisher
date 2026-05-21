import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://wecima.cx', wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(3000)
        
        content = await page.content()
        print('HTML LENGTH:', len(content))
        
        cards = await page.query_selector_all('.GridItem')
        print('CARDS FOUND:', len(cards))
        
        if cards:
            for card in cards[:3]:
                html = await card.inner_html()
                print('\n--- CARD HTML ---')
                print(html[:500])
        
        links = await page.query_selector_all('a[href*="/watch/"]')
        print('\nWATCH LINKS FOUND:', len(links))
        for link in links[:5]:
            href = await link.get_attribute('href')
            print(href)
        
        await browser.close()

asyncio.run(main())
