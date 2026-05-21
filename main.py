import requests
from bs4 import BeautifulSoup
import time
import os
import re
import json
from datetime import datetime

BASE44_APP_ID  = os.environ.get("BASE44_APP_ID")
BASE44_API_KEY = os.environ.get("BASE44_API_KEY")
BASE44_BASE    = f"https://api.base44.com/api/v1/apps/{BASE44_APP_ID}"
HEADERS_B44    = {"api_key": BASE44_API_KEY, "Content-Type": "application/json"}

WECIMA_BASE = "https://wecima.cx"
HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
}

def debug_env():
    app_id = BASE44_APP_ID or "MISSING"
    api_key = BASE44_API_KEY or "MISSING"
    print(f"🔑 APP_ID  : {app_id[:6]}...{app_id[-4:] if len(app_id) > 10 else app_id}")
    print(f"🔑 API_KEY : {api_key[:6]}...{api_key[-4:] if len(api_key) > 10 else api_key}")
    print(f"🔗 Base URL: {BASE44_BASE}")
    if not BASE44_APP_ID or not BASE44_API_KEY:
        print("❌ FATAL: Missing environment variables. Check GitHub Secrets.")
        exit(1)

def b44_get(entity, q=None, limit=100):
    params = {"limit": limit}
    if q:
        params["q"] = json.dumps(q)
    try:
        res = requests.get(f"{BASE44_BASE}/entities/{entity}", headers=HEADERS_B44, params=params, timeout=15)
        if res.status_code == 200:
            return res.json()
        print(f"  ⚠️ GET {entity} returned {res.status_code}")
    except Exception as e:
        print(f"  ⚠️ GET {entity} error: {e}")
    return []

def b44_post(entity, payload):
    try:
        res = requests.post(f"{BASE44_BASE}/entities/{entity}", headers=HEADERS_B44, json=payload, timeout=15)
        if res.status_code in [200, 201]:
            return res.json()
        print(f"  ❌ POST {entity} {res.status_code}: {res.text[:80]}")
    except Exception as e:
        print(f"  ❌ POST {entity} error: {e}")
    return None

def b44_put(entity, record_id, payload):
    try:
        res = requests.put(f"{BASE44_BASE}/entities/{entity}/{record_id}", headers=HEADERS_B44, json=payload, timeout=15)
        return res.status_code in [200, 204]
    except:
        return False

def test_connection():
    print("\n🧪 Testing Base44 connection...")
    res = b44_get("Content", limit=1)
    if res is not None:
        print("  ✅ Connection OK")
        return True
    print("  ❌ Connection FAILED")
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

def scrape_rss(stop_at_url=None):
    new_items = []
    seen_urls = set()
    rss_urls = [
        f"{WECIMA_BASE}/feed/",
        f"{WECIMA_BASE}/feed/?post_type=movie",
        f"{WECIMA_BASE}/feed/?post_type=series",
    ]
    for rss_url in rss_urls:
        try:
            res = requests.get(rss_url, headers=HEADERS_WEB, timeout=15)
            soup = BeautifulSoup(res.content, "xml")
            items = soup.find_all("item")
            for item in items:
                link  = item.find("link")
                title = item.find("title")
                if not link or not title:
                    continue
                item_url   = link.get_text(strip=True)
                item_title = title.get_text(strip=True)
                if item_url in seen_urls:
                    continue
                seen_urls.add(item_url)
                if stop_at_url and item_url == stop_at_url:
                    return new_items
                poster = ""
                enclosure = item.find("enclosure")
                if enclosure:
                    poster = enclosure.get("url", "")
                pub_date = item.find("pubDate")
                year = str(datetime.now().year)
                if pub_date:
                    m = re.search(r"\d{4}", pub_date.get_text())
                    if m:
                        year = m.group()
                new_items.append({
                    "url":    item_url,
                    "title":  item_title,
                    "poster": poster,
                    "year":   year,
                    "type":   detect_type(item_url, item_title),
                })
        except Exception as e:
            print(f"  ⚠️ RSS error: {e}")
    print(f"  📡 RSS returned {len(new_items)} items")
    return new_items

def scrape_pages(stop_at_url=None, max_pages=50):
    new_items = []
    seen_urls = set()
    for page in range(1, max_pages + 1):
        try:
            res  = requests.get(f"{WECIMA_BASE}/home/page/{page}/", headers=HEADERS_WEB, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception as e:
            print(f"  ❌ Page {page}: {e}")
            break
        cards = (
            soup.select("div.GridItem") or
            soup.select("div.Entry") or
            soup.select("article.GridItem") or
            soup.select(".Grid--WecimaPosts .GridItem")
        )
        if not cards:
            print(f"  ⚠️ No cards on page {page} — stopping")
            break
        found_stop = False
        for card in cards:
            link_tag = card.select_one("a[href]")
            if not link_tag:
                continue
            item_url = link_tag.get("href", "").strip()
            if not item_url.startswith("http"):
                item_url = WECIMA_BASE + item_url
            if item_url in seen_urls:
                continue
            seen_urls.add(item_url)
            if stop_at_url and item_url == stop_at_url:
                found_stop = True
                break
            title_tag = card.select_one(".Title") or card.select_one("h3") or card.select_one("h2")
            title = title_tag.get_text(strip=True) if title_tag else ""
            img_tag = card.select_one("img")
            poster = ""
            if img_tag:
                poster = img_tag.get("data-src") or img_tag.get("data-lazy-src") or img_tag.get("src") or ""
            year_tag = card.select_one(".year, .Year")
            year = re.sub(r"[^\d]", "", year_tag.get_text() if year_tag else "")[:4]
            if title and item_url:
                new_items.append({
                    "url":    item_url,
                    "title":  title,
                    "poster": poster,
                    "year":   year or str(datetime.now().year),
                    "type":   detect_type(item_url, title),
                })
        if found_stop:
            break
        print(f"  📄 Page {page}: +{len(cards)} items")
        time.sleep(1.5)
    return new_items

def scrape_detail(url):
    try:
        res  = requests.get(url, headers=HEADERS_WEB, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        description = ""
        for sel in [".StoryMovieContent", ".Description", "p.story", ".BlockDescription"]:
            tag = soup.select_one(sel)
            if tag:
                description = tag.get_text(strip=True)
                break

        genres = []
        for sel in [".GenresList a", ".Genres a", "a[href*='genre']"]:
            tags = soup.select(sel)
            if tags:
                genres = [g.get_text(strip=True) for g in tags[:6]]
                break

        rating = 0.0
        for sel in [".imdb-rating", ".Rating", "[class*='rating' i]"]:
            tag = soup.select_one(sel)
            if tag:
                num = re.search(r"(\d+\.?\d*)", tag.get_text())
                if num:
                    rating = min(float(num.group(1)), 10.0)
                    break

        page_text = soup.get_text().lower()
        language = "Arabic"
        if "english" in page_text or "إنجليزي" in page_text:
            language = "English"
        elif "تركي" in page_text:
            language = "Turkish"
        elif "هندي" in page_text:
            language = "Indian"
        elif "فرنسي" in page_text:
            language = "French"

        poster = ""
        og = soup.find("meta", property="og:image")
        if og:
            poster = og.get("content", "")
        if not poster:
            img = soup.select_one(".MovieImg img, .Poster img, img.thumbnail")
            if img:
                poster = img.get("data-src") or img.get("src") or ""

        embeds = []
        for iframe in soup.select("iframe"):
            src = (iframe.get("src") or iframe.get("data-src") or "").strip()
            if src and "youtube" not in src and len(src) > 10:
                embeds.append(src)
        for script in soup.select("script"):
            found = re.findall(r'https?://[^\s"\'<>]+(?:embed|player)[^\s"\'<>]*', script.get_text())
            for f in found:
                if f not in embeds:
                    embeds.append(f)

        downloads = []
        for sel in ["a.DownloadBtn", ".downloadLinks a", "[class*='download' i] a", "a[href*='/d/']"]:
            for a in soup.select(sel):
                href  = a.get("href", "").strip()
                label = a.get_text(strip=True)
                if not href or not href.startswith("http"):
                    continue
                if href in [d["url"] for d in downloads]:
                    continue
                quality = "720p"
                for q in ["4K", "1080p", "720p", "480p", "360p", "CAM"]:
                    if q.lower() in label.lower() or q.lower() in href.lower():
                        quality = q
                        break
                host_match = re.search(r"https?://(?:www\.)?([^/]+)", href)
                host = host_match.group(1).split(".")[0].capitalize() if host_match else "Unknown"
                downloads.append({"url": href, "quality": quality, "host": host})

        return {
            "description":   description,
            "genres":        genres,
            "rating":        rating,
            "language":      language,
            "poster":        poster,
            "embeds":        embeds[:6],
            "downloads":     downloads[:12],
            "is_dubbed":     "مدبلج" in page_text,
            "is_translated": "مترجم" in page_text,
        }
    except Exception as e:
        print(f"  ❌ Detail error: {e}")
        return {}

def get_existing(slug):
    try:
        records = b44_get("Content", {"slug": slug}, limit=1)
        if records and len(records) > 0:
            return records[0]
    except:
        pass
    return None

def push_content(item, detail):
    raw_slug = item["url"].split("/watch/")[-1] if "/watch/" in item["url"] else item["url"].split("/")[-1]
    slug     = make_slug(raw_slug)[:80]
    existing = get_existing(slug)

    try:
        year = int(item.get("year", str(datetime.now().year))[:4])
    except:
        year = datetime.now().year

    poster  = detail.get("poster") or item.get("poster", "")
    payload = {
        "title_ar":      item.get("title", ""),
        "title_en":      item.get("title", ""),
        "slug":          slug,
        "content_type":  item.get("type", "movie"),
        "poster_url":    poster,
        "backdrop_url":  poster,
        "description":   detail.get("description", ""),
        "year":          year,
        "genre":         detail.get("genres", []),
        "language":      detail.get("language", "Arabic"),
        "rating":        detail.get("rating", 0.0),
        "is_dubbed":     detail.get("is_dubbed", False),
        "is_translated": detail.get("is_translated", True),
        "status":        "published",
        "is_featured":   False,
        "views":         0,
    }

    if existing:
        content_id     = existing.get("id")
        existing_links = b44_get("VideoLink", {"content_id": content_id}, limit=100)
        existing_urls  = {l.get("download_url") or l.get("embed_url") for l in existing_links}
        new_links      = [d for d in detail.get("downloads", []) if d["url"] not in existing_urls]
        if new_links:
            print(f"  🔗 Adding {len(new_links)} new links")
            for d in new_links:
                b44_post("VideoLink", {
                    "content_id":   content_id,
                    "embed_url":    "",
                    "download_url": d["url"],
                    "quality":      d["quality"],
                    "host_name":    d["host"],
                    "link_type":    "download",
                })
                time.sleep(0.2)
        else:
            print(f"  ⏭️ Already exists, no new links")
        return content_id

    result = b44_post("Content", payload)
    if not result:
        return None

    content_id = result.get("id")
    print(f"  ✅ Created: {payload['title_ar'][:40]}")

    qualities = ["480p", "720p", "1080p", "4K"]
    for i, embed_url in enumerate(detail.get("embeds", [])):
        q      = qualities[i] if i < len(qualities) else "720p"
        dl_url = next((d["url"] for d in detail.get("downloads", []) if d["quality"] == q), "")
        b44_post("VideoLink", {
            "content_id":   content_id,
            "embed_url":    embed_url,
            "download_url": dl_url,
            "quality":      q,
            "host_name":    "Auto",
            "link_type":    "watch",
        })
        time.sleep(0.2)

    for d in detail.get("downloads", []):
        b44_post("VideoLink", {
            "content_id":   content_id,
            "embed_url":    "",
            "download_url": d["url"],
            "quality":      d["quality"],
            "host_name":    d["host"],
            "link_type":    "download",
        })
        time.sleep(0.2)

    return content_id

def run():
    print(f"\n{'='*50}")
    print(f"🚀 MyCima Auto-Publisher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    debug_env()

    if not test_connection():
        print("❌ Cannot connect to Base44. Check APP_ID and API_KEY secrets.")
        exit(1)

    last_url, checkpoint_id = get_checkpoint()
    print(f"\n📌 Last scraped: {last_url[:60] if last_url else 'First run'}")

    print("\n📡 Step 1: RSS feed...")
    items = scrape_rss(stop_at_url=last_url)

    if len(items) < 5:
        print(f"\n📄 Step 2: Page scraping (up to 50 pages)...")
        items += scrape_pages(stop_at_url=last_url, max_pages=50)

    seen = set()
    unique = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    items = unique

    print(f"\n📦 Total items to process: {len(items)}")
    if not items:
        print("✅ Nothing new.")
        return

    save_checkpoint(items[0]["url"], checkpoint_id)

    success = failed = 0
    for i, item in enumerate(items):
        print(f"\n[{i+1}/{len(items)}] {item['title'][:50]}")
        detail = scrape_detail(item["url"])
        time.sleep(1)
        result = push_content(item, detail)
        if result:
            success += 1
        else:
            failed += 1
        time.sleep(0.8)

    print(f"\n{'='*50}")
    print(f"✅ Done — {success} processed, {failed} failed")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    run()
    
