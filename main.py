import requests
from bs4 import BeautifulSoup
import time
import json
import os
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────
BASE44_API_KEY = "1bd0b8448aeb43488ebb5bfbe8ff7e4a"
BASE44_APP_ID  = "6a0e5dbc61dc7c96d9538c95"
STATE_FILE     = "last_seen.json"   # tracks where we stopped
CHECK_INTERVAL = 4 * 60 * 60       # 4 hours in seconds
WECIMA_BASE    = "https://wecima.cx"
HEADERS        = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ── STATE: remember last scraped URL ────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_url": None, "last_run": None}

def save_state(last_url):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_url": last_url, "last_run": str(datetime.now())}, f)

# ── SCRAPE WECIMA HOMEPAGE ───────────────────────────
def scrape_latest(stop_at_url=None):
    new_items = []
    page = 1

    while True:
        url = f"{WECIMA_BASE}/home/page/{page}"
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        cards = soup.select("div.GridItem")  # adjust selector if needed
        if not cards:
            break

        for card in cards:
            link_tag = card.select_one("a")
            if not link_tag:
                continue

            item_url = link_tag.get("href", "")
            if item_url == stop_at_url:
                # reached where we stopped last time
                return new_items

            title = card.select_one(".Title")
            poster = card.select_one("img")
            year_tag = card.select_one(".year, .Year")

            item = {
                "url":    item_url,
                "title":  title.get_text(strip=True) if title else "",
                "poster": poster.get("data-src") or poster.get("src", "") if poster else "",
                "year":   year_tag.get_text(strip=True) if year_tag else "",
                "type":   detect_type(item_url),
            }
            new_items.append(item)

        page += 1
        time.sleep(1)  # be polite

    return new_items

# ── DETECT MOVIE vs SERIES ───────────────────────────
def detect_type(url):
    if "/series/" in url or "مسلسل" in url:
        return "series"
    elif "/anime/" in url or "انمي" in url:
        return "anime"
    return "movie"

# ── SCRAPE INDIVIDUAL CONTENT PAGE ──────────────────
def scrape_detail(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        description = ""
        desc_tag = soup.select_one(".StoryMovieContent, .Description, p.story")
        if desc_tag:
            description = desc_tag.get_text(strip=True)

        genres = []
        for g in soup.select(".GenresList a, .Genres a"):
            genres.append(g.get_text(strip=True))

        # grab embed iframes
        embeds = []
        for iframe in soup.select("iframe"):
            src = iframe.get("src") or iframe.get("data-src", "")
            if src:
                embeds.append(src)

        # grab download links
        downloads = []
        for a in soup.select("a.DownloadBtn, a[href*='download'], .downloadLinks a"):
            href = a.get("href", "")
            label = a.get_text(strip=True)
            if href:
                downloads.append({"url": href, "label": label})

        return {
            "description": description,
            "genres":      genres[:5],
            "embeds":      embeds,
            "downloads":   downloads,
        }
    except Exception as e:
        print(f"  Detail scrape failed for {url}: {e}")
        return {}

# ── GENERATE SLUG ────────────────────────────────────
def make_slug(title):
    import re
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\u0600-\u06FF\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug[:80]

# ── PUSH TO BASE44 ───────────────────────────────────
def push_to_base44(item, detail):
    endpoint = f"https://api.base44.com/v1/apps/{BASE44_APP_ID}/entities/Content"
    headers = {
        "Authorization": f"Bearer {BASE44_API_KEY}",
        "Content-Type": "application/json"
    }

    slug = make_slug(item.get("title", "content"))

    payload = {
        "title_ar":       item.get("title", ""),
        "title_en":       item.get("title", ""),
        "slug":           slug,
        "type":           item.get("type", "movie"),
        "poster_url":     item.get("poster", ""),
        "description":    detail.get("description", ""),
        "year":           int(item.get("year", 2024)) if item.get("year", "").isdigit() else 2024,
        "genre":          detail.get("genres", []),
        "status":         "published",
        "is_featured":    False,
        "views":          0,
    }

    res = requests.post(endpoint, json=payload, headers=headers)
    
    if res.status_code in [200, 201]:
        content_id = res.json().get("id")
        print(f"  ✅ Created: {payload['title_ar']} (id={content_id})")

        # push video links
        for i, embed in enumerate(detail.get("embeds", [])):
            push_video_link(content_id, embed, detail.get("downloads", []), i)

        return content_id
    else:
        print(f"  ❌ Failed: {res.status_code} - {res.text[:100]}")
        return None

# ── PUSH VIDEO LINKS ─────────────────────────────────
def push_video_link(content_id, embed_url, downloads, index):
    endpoint = f"https://api.base44.com/v1/apps/{BASE44_APP_ID}/entities/VideoLink"
    headers = {
        "Authorization": f"Bearer {BASE44_API_KEY}",
        "Content-Type": "application/json"
    }

    qualities = ["480p", "720p", "1080p", "4K"]
    quality = qualities[index] if index < len(qualities) else "720p"

    download_url = downloads[index]["url"] if index < len(downloads) else ""

    payload = {
        "content":      content_id,
        "embed_url":    embed_url,
        "download_url": download_url,
        "quality":      quality,
        "host_name":    "Auto",
        "link_type":    "watch",
    }

    requests.post(endpoint, json=payload, headers=headers)

# ── MAIN LOOP ────────────────────────────────────────
def run():
    print(f"\n🚀 Starting MyCima Auto-Publisher — {datetime.now()}")
    state = load_state()
    stop_at = state.get("last_url")

    print(f"📌 Will stop at: {stop_at or 'nothing (first run — get all)'}")

    items = scrape_latest(stop_at_url=stop_at)
    print(f"📦 Found {len(items)} new items")

    if not items:
        print("✅ Nothing new.")
        return

    # save the newest URL as the new stop point
    save_state(items[0]["url"])

    for i, item in enumerate(items):
        print(f"\n[{i+1}/{len(items)}] {item['title']}")
        detail = scrape_detail(item["url"])
        time.sleep(1)
        push_to_base44(item, detail)

    print(f"\n✅ Done. Next run in 4 hours.")

# ── SCHEDULER ────────────────────────────────────────
if __name__ == "__main__":
    while True:
        try:
            run()
        except Exception as e:
            print(f"💥 Error: {e}")
        print(f"😴 Sleeping 4 hours...")
        time.sleep(CHECK_INTERVAL)
