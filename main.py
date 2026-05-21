import asyncio
import os
import re
import json
import time
from datetime import datetime
from playwright.async_api import async_playwright
import requests

BASE44_API_KEY = os.environ.get("BASE44_API_KEY")
BASE44_APP_ID  = os.environ.get("BASE44_APP_ID")
BASE44_BASE    = "https://mycima.base44.app/api"
HEADERS_B44    = {"api_key": BASE44_API_KEY, "Content-Type": "application/json"}

WECIMA_BASE = "https://wecima.cx"

VALID_TYPES     = ["movie", "series", "anime", "show"]
VALID_QUALITIES = ["CAM", "360p", "480p", "720p", "1080p", "4K"]
VALID_LANGUAGES = ["Arabic", "English", "Turkish", "Indian", "Asian", "French", "Other"]

def b44_get(entity, q=None):
    params = {}
    if q:
        params["q"] = json.dumps(q)
    try:
        res = requests.get(f"{BASE44_BASE}/entities/{entity}", headers=HEADERS_B44, params=params, timeout=15)
        if res.status_code == 200:
            return res.json()
        print(f"  ❌ GET failed {entity}: {res.status_code} - {res.text[:100]}")
    except Exception as e:
        print(f"  ❌ GET exception: {e}")
    return []

def b44_post(entity, payload):
    try:
        res = requests.post(f"{BASE44_BASE}/entities/{entity}", headers=HEADERS_B44, json=payload, timeout=15)
        if res.status_code in [200, 201]:
            return res.json()
        print(f"  ❌ POST failed {entity}: {res.status_code} - {res.text[:200]}")
    except Exception as e:
        print(f"  ❌ POST exception: {e}")
    return None

def b44_put(entity, record_id, payload):
    try:
        res = requests.put(f"{BASE44_BASE}/entities/{entity}/{record_id}", headers=HEADERS_B44, json=payload, timeout=15)
        return res.status_code in [200, 204]
    except Exception as e:
        print(f"  ❌ PUT exception: {e}")
        return False

def get_checkpoint():
    try:
        records = b44_get("Setting", {"key": "last_scraped_url"})
        if records and len(records) > 0:
            return records[0].get("value"), records[0].get("id")
    except:
        pass
    return None, None

def save_checkpoint(url, record_id=None):
    if record_id:
        b44_put("Setting", record_id, {"key": "last_scraped_url", "value": url})
    else:
        b44_post("Setting", {"key": "last_scraped_url", "value": url})
    print(f"  📌 Checkpoint saved")

def make_slug(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].strip("-")

def detect_type(url, title=""):
    if "مسلسل" in title or "/series/" in url.lower():
        return "series"
    if "انمي" in title or "anime" in url.lower():
        return "anime"
    if "برنامج" in title or "show" in url.lower():
        return "show"
    return "movie"

def detect_quality(text):
    for q in ["4K", "1080p", "720p", "480p", "360p", "CAM"]:
        if q.lower() in text.lower():
            return q
    return "720p"

def detect_language(page_text):
    if "إنجليزي" in page_text or "english" in page_text.lower():
        return "English"
    if "تركي" in page_text:
        return "Turkish"
    if "هندي" in page_text:
        return "Indian"
    if "آسيوي" in page_text or "asian" in page_text.lower():
        return "Asian"
    if "فرنسي" in page_text or "french" in page_text.lower():
        return "French"
    return "Arabic"

def already_exists(slug):
    try:
        records = b44_get("Content", {"slug": slug})
        return isinstance(records, list) and len(records) > 0
    except:
        return False

async def scrape_homepage_pw(browser, stop_at_url=None):
    new_items = []
    page = await browser.new_page()
    found_stop = False

    print("🔍 Scraping Wecima homepage...")

    for page_num in range(1, 11):
        if found_stop:
            break
        try:
            await page.goto(f"{WECIMA_BASE}/home/page/{page_num}", timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            cards = await page.query_selector_all("div.GridItem, article.GridItem")
            if not cards:
                print(f"  ⚠️ No cards on page {page_num}")
                break

            for card in cards:
                link_tag = await card.query_selector("a[href]")
                if not link_tag:
                    continue

                item_url = await link_tag.get_attribute("href") or ""
                item_url = item_url.strip()
                if not item_url.startswith("http"):
                    item_url = WECIMA_BASE + item_url

                if stop_at_url and item_url == stop_at_url:
                    found_stop = True
                    break

                title_tag = await card.query_selector(".Title, h3, h2")
                title = await title_tag.inner_text() if title_tag else ""
                title = title.strip()

                img_tag = await card.query_selector("img")
                poster = ""
                if img_tag:
                    poster = (await img_tag.get_attribute("data-src") or
                              await img_tag.get_attribute("data-lazy-src") or
                              await img_tag.get_attribute("src") or "")

                year_tag = await card.query_selector(".year, .Year")
                year_text = await year_tag.inner_text() if year_tag else ""
                year = re.sub(r"[^\d]", "", year_text)[:4]

                if title and item_url:
                    new_items.append({
                        "url":    item_url,
                        "title":  title,
                        "poster": poster,
                        "year":   year or str(datetime.now().year),
                        "type":   detect_type(item_url, title),
                    })

        except Exception as e:
            print(f"  ❌ Page {page_num} error: {e}")
            break

        await asyncio.sleep(1.5)

    await page.close()
    print(f"  📦 Found {len(new_items)} new items")
    return new_items

async def scrape_detail_pw(browser, url):
    page = await browser.new_page()
    detail = {}

    # Collect all network requests to catch video URLs
    video_urls = []

    def on_request(request):
        req_url = request.url
        for keyword in ["embed", "player", "stream", "vidbom", "streamwish",
                        "doodstream", "filemoon", "uqload", "mp4upload", "ok.ru"]:
            if keyword in req_url.lower():
                video_urls.append(req_url)

    page.on("request", on_request)

    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        page_text = await page.inner_text("body")

        # Description
        description = ""
        for sel in [".StoryMovieContent", ".Description", "p.story", ".BlockDescription"]:
            el = await page.query_selector(sel)
            if el:
                description = await el.inner_text()
                description = description.strip()
                break

        # Genres
        genres = []
        for sel in [".GenresList a", ".Genres a", "a[href*='genre']"]:
            els = await page.query_selector_all(sel)
            if els:
                for el in els[:6]:
                    t = await el.inner_text()
                    genres.append(t.strip())
                break

        # Rating
        rating = 0.0
        for sel in [".imdb-rating", ".Rating", "[class*='rating' i]"]:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                num = re.search(r"(\d+\.?\d*)", text)
                if num:
                    try:
                        rating = float(num.group(1))
                    except:
                        pass
                break

        # Iframes (static)
        embeds = []
        iframes = await page.query_selector_all("iframe")
        for iframe in iframes:
            src = await iframe.get_attribute("src") or await iframe.get_attribute("data-src") or ""
            src = src.strip()
            if src and "youtube" not in src and len(src) > 10:
                embeds.append(src)

        # Add dynamically captured video URLs
        for vu in video_urls:
            if vu not in embeds:
                embeds.append(vu)

        # Download links
        downloads = []
        for sel in ["a.DownloadBtn", ".downloadLinks a", "[class*='download' i] a",
                    "a[href*='mediafire']", "a[href*='gofile']", "a[href*='1fichier']"]:
            els = await page.query_selector_all(sel)
            for el in els:
                href = await el.get_attribute("href") or ""
                href = href.strip()
                label = await el.inner_text()
                label = label.strip()
                if not href or not href.startswith("http"):
                    continue
                if href in [d["url"] for d in downloads]:
                    continue
                quality = detect_quality(label + " " + href)
                host_match = re.search(r"https?://(?:www\.)?([^/]+)", href)
                host = host_match.group(1).split(".")[0].capitalize() if host_match else "Unknown"
                downloads.append({"url": href, "quality": quality, "host": host or "Unknown"})

        detail = {
            "description":   description,
            "genres":        genres,
            "rating":        rating,
            "language":      detect_language(page_text),
            "embeds":        embeds[:6],
            "downloads":     downloads[:12],
            "is_dubbed":     "مدبلج" in page_text,
            "is_translated": "مترجم" in page_text,
        }

    except Exception as e:
        print(f"  ❌ Detail error: {e}")

    await page.close()
    return detail

def push_content(item, detail):
    raw_slug = item["url"].split("/watch/")[-1] if "/watch/" in item["url"] else item["url"].split("/")[-1]
    slug = make_slug(raw_slug)[:80]

    if already_exists(slug):
        print(f"  ⏭️ Already exists")
        return "exists"

    try:
        year = int(item.get("year", str(datetime.now().year))[:4])
    except:
        year = datetime.now().year

    content_type = item.get("type", "movie")
    if content_type not in VALID_TYPES:
        content_type = "movie"

    language = detail.get("language", "Arabic")
    if language not in VALID_LANGUAGES:
        language = "Other"

    payload = {
        "title_ar":      item.get("title", "") or "بدون عنوان",
        "title_en":      item.get("title", "") or "No Title",
        "slug":          slug,
        "content_type":  content_type,
        "poster_url":    item.get("poster", ""),
        "backdrop_url":  item.get("poster", ""),
        "description":   detail.get("description", ""),
        "year":          year,
        "genre":         detail.get("genres", []),
        "language":      language,
        "rating":        detail.get("rating", 0.0),
        "is_dubbed":     detail.get("is_dubbed", False),
        "is_translated": detail.get("is_translated", True),
        "status":        "published",
        "is_featured":   False,
        "views":         0,
    }

    result = b44_post("Content", payload)
    if not result:
        return None

    content_id = result.get("id")
    print(f"  ✅ Created: {payload['title_ar'][:40]} (id={content_id})")

    qualities = ["480p", "720p", "1080p", "4K"]
    for i, embed_url in enumerate(detail.get("embeds", [])):
        q = qualities[i] if i < len(qualities) else "720p"
        dl_url = next((d["url"] for d in detail.get("downloads", []) if d["quality"] == q), "")
        b44_post("VideoLink", {
            "content_id":   content_id,
            "embed_url":    embed_url,
            "download_url": dl_url,
            "quality":      q,
            "host_name":    "Auto",
            "link_type":    "watch",
        })
        time.sleep(0.3)

    for d in detail.get("downloads", []):
        q = d["quality"] if d["quality"] in VALID_QUALITIES else "720p"
        host = d.get("host") or "Unknown"
        b44_post("VideoLink", {
            "content_id":   content_id,
            "embed_url":    "",
            "download_url": d["url"],
            "quality":      q,
            "host_name":    host,
            "link_type":    "download",
        })
        time.sleep(0.3)

    return content_id

async def main():
    print(f"\n{'='*50}")
    print(f"🚀 MyCima Auto-Publisher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    last_url, checkpoint_id = get_checkpoint()
    print(f"📌 Last scraped: {last_url[:60] if last_url else 'First run'}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        new_items = await scrape_homepage_pw(browser, stop_at_url=last_url)

        if not new_items:
            print("✅ Nothing new.")
            await browser.close()
            return

        save_checkpoint(new_items[0]["url"], checkpoint_id)

        success = skipped = failed = 0
        for i, item in enumerate(new_items):
            print(f"\n[{i+1}/{len(new_items)}] {item['title'][:50]}")
            detail = await scrape_detail_pw(browser, item["url"])
            await asyncio.sleep(1.5)
            result = push_content(item, detail)
            if result == "exists":
                skipped += 1
            elif result:
                success += 1
            else:
                failed += 1
            await asyncio.sleep(1)

        await browser.close()

    print(f"\n{'='*50}")
    print(f"✅ Done — {success} added, {skipped} skipped, {failed} failed")
    print(f"{'='*50}")

if __name__ == "__main__":
    asyncio.run(main())
