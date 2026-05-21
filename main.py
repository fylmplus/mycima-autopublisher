import requests
from bs4 import BeautifulSoup
import time
import os
import re
import json
from datetime import datetime

BASE44_API_KEY = os.environ.get("BASE44_API_KEY")
BASE44_APP_ID  = os.environ.get("BASE44_APP_ID")
BASE44_BASE    = "https://mycima.base44.app/api"
HEADERS_B44    = {"api_key": BASE44_API_KEY, "Content-Type": "application/json"}

WECIMA_BASE = "https://wecima.cx"
HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
}

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
        print(f"  ❌ GET exception {entity}: {e}")
    return []

def b44_post(entity, payload):
    try:
        res = requests.post(f"{BASE44_BASE}/entities/{entity}", headers=HEADERS_B44, json=payload, timeout=15)
        if res.status_code in [200, 201]:
            return res.json()
        print(f"  ❌ POST failed {entity}: {res.status_code} - {res.text[:200]}")
    except Exception as e:
        print(f"  ❌ POST exception {entity}: {e}")
    return None

def b44_put(entity, record_id, payload):
    try:
        res = requests.put(f"{BASE44_BASE}/entities/{entity}/{record_id}", headers=HEADERS_B44, json=payload, timeout=15)
        return res.status_code in [200, 204]
    except Exception as e:
        print(f"  ❌ PUT exception {entity}: {e}")
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

def scrape_homepage(stop_at_url=None):
    new_items = []
    page = 1
    found_stop = False
    print("🔍 Scraping Wecima homepage...")

    while not found_stop and page <= 10:
        try:
            res = requests.get(f"{WECIMA_BASE}/home/page/{page}", headers=HEADERS_WEB, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception as e:
            print(f"  ❌ Page {page} failed: {e}")
            break

        cards = (
            soup.select("div.GridItem") or
            soup.select("div.Entry") or
            soup.select("article.GridItem") or
            soup.select(".Grid--WecimaPosts .GridItem")
        )

        if not cards:
            print(f"  ⚠️ No cards found on page {page} — stopping")
            break

        for card in cards:
            link_tag = card.select_one("a[href]")
            if not link_tag:
                continue

            item_url = link_tag.get("href", "").strip()
            if not item_url.startswith("http"):
                item_url = WECIMA_BASE + item_url

            if stop_at_url and item_url == stop_at_url:
                print(f"  ✅ Reached checkpoint — stopping")
                found_stop = True
                break

            title_tag = (
                card.select_one(".Title") or
                card.select_one("h3") or
                card.select_one("h2")
            )
            title = title_tag.get_text(strip=True) if title_tag else ""

            img_tag = card.select_one("img")
            poster = ""
            if img_tag:
                poster = (
                    img_tag.get("data-src") or
                    img_tag.get("data-lazy-src") or
                    img_tag.get("src") or ""
                )

            year_tag = card.select_one(".year, .Year")
            year = re.sub(r"[^\d]", "", year_tag.get_text() if year_tag else "")[:4]

            if title and item_url:
                new_items.append({
                    "url":   item_url,
                    "title": title,
                    "poster": poster,
                    "year":  year or str(datetime.now().year),
                    "type":  detect_type(item_url, title),
                })

        page += 1
        time.sleep(1.5)

    print(f"  📦 Found {len(new_items)} new items")
    return new_items

def scrape_detail(url):
    try:
        res = requests.get(url, headers=HEADERS_WEB, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        page_text = soup.get_text()

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
                    try:
                        rating = float(num.group(1))
                    except:
                        pass
                    break

        embeds = []
        for iframe in soup.select("iframe"):
            src = (iframe.get("src") or iframe.get("data-src") or "").strip()
            if src and "youtube" not in src and len(src) > 10:
                embeds.append(src)

        downloads = []
        for sel in ["a.DownloadBtn", ".downloadLinks a", "[class*='download' i] a"]:
            for a in soup.select(sel):
                href = a.get("href", "").strip()
                label = a.get_text(strip=True)
                if not href or not href.startswith("http"):
                    continue
                if href in [d["url"] for d in downloads]:
                    continue
                quality = detect_quality(label + " " + href)
                host_match = re.search(r"https?://(?:www\.)?([^/]+)", href)
                host = host_match.group(1).split(".")[0].capitalize() if host_match else "Unknown"
                if not host:
                    host = "Unknown"
                downloads.append({"url": href, "quality": quality, "host": host})

        return {
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
        return {}

def already_exists(slug):
    try:
        records = b44_get("Content", {"slug": slug})
        return isinstance(records, list) and len(records) > 0
    except:
        return False

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

def run():
    print(f"\n{'='*50}")
    print(f"🚀 MyCima Auto-Publisher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    last_url, checkpoint_id = get_checkpoint()
    print(f"📌 Last scraped: {last_url[:60] if last_url else 'First run'}")

    new_items = scrape_homepage(stop_at_url=last_url)
    if not new_items:
        print("✅ Nothing new.")
        return

    save_checkpoint(new_items[0]["url"], checkpoint_id)

    success = skipped = failed = 0
    for i, item in enumerate(new_items):
        print(f"\n[{i+1}/{len(new_items)}] {item['title'][:50]}")
        detail = scrape_detail(item["url"])
        time.sleep(1.5)
        result = push_content(item, detail)
        if result == "exists":
            skipped += 1
        elif result:
            success += 1
        else:
            failed += 1
        time.sleep(1)

    print(f"\n{'='*50}")
    print(f"✅ Done — {success} added, {skipped} skipped, {failed} failed")
    print(f"{'='*50}")

if __name__ == "__main__":
    run()
