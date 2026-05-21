import requests
from bs4 import BeautifulSoup
import time
import os
import re
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────
BASE44_API_KEY = os.environ.get("BASE44_API_KEY")
BASE44_APP_ID  = os.environ.get("BASE44_APP_ID")
WECIMA_BASE    = "https://wecima.cx"
HEADERS        = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
}
BASE44_HEADERS = {
    "Authorization": f"Bearer {BASE44_API_KEY}",
    "Content-Type": "application/json"
}

# ── BASE44 API HELPERS ───────────────────────────────
def b44_get(entity, filters=None):
    url = f"https://api.base44.com/api/v1/apps/{BASE44_APP_ID}/entities/{entity}"
    params = {}
    if filters:
        params.update(filters)
    res = requests.get(url, headers=BASE44_HEADERS, params=params)
    if res.status_code == 200:
        return res.json()
    return []

def b44_post(entity, payload):
    url = f"https://api.base44.com/api/v1/apps/{BASE44_APP_ID}/entities/{entity}"
    res = requests.post(url, headers=BASE44_HEADERS, json=payload)
    if res.status_code in [200, 201]:
        return res.json()
    print(f"  ❌ POST failed {entity}: {res.status_code} - {res.text[:150]}")
    return None

def b44_patch(entity, record_id, payload):
    url = f"https://api.base44.com/api/v1/apps/{BASE44_APP_ID}/entities/{entity}"
    res = requests.patch(url, headers=BASE44_HEADERS, json=payload)
    return res.status_code in [200, 204]

# ── CHECKPOINT (saved in Base44) ─────────────────────
# We store the last scraped URL in a Base44 "Setting" entity
# so it persists between GitHub Actions runs

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
        b44_patch("Setting", record_id, {"value": url})
    else:
        b44_post("Setting", {"key": "last_scraped_url", "value": url})
    print(f"  📌 Checkpoint saved: {url[:60]}...")

# ── SLUG GENERATOR ───────────────────────────────────
def make_slug(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].strip("-")

# ── DETECT CONTENT TYPE ──────────────────────────────
def detect_type(url, title=""):
    url_lower = url.lower()
    title_lower = title.lower()
    if "مسلسل" in title or "/series/" in url_lower:
        return "series"
    if "انمي" in title or "anime" in url_lower:
        return "anime"
    if "برنامج" in title or "show" in url_lower:
        return "show"
    return "movie"

# ── SCRAPE HOMEPAGE (get list of new content) ────────
def scrape_homepage(stop_at_url=None):
    new_items = []
    page = 1
    found_stop = False

    print(f"🔍 Scraping Wecima homepage...")

    while not found_stop:
        url = f"{WECIMA_BASE}/home/page/{page}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception as e:
            print(f"  ❌ Failed to load page {page}: {e}")
            break

        # Try multiple card selectors (Wecima sometimes changes classes)
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

            # Stop if we've reached the last scraped URL
            if stop_at_url and item_url == stop_at_url:
                print(f"  ✅ Reached checkpoint — stopping scrape")
                found_stop = True
                break

            # Extract title
            title_tag = (
                card.select_one(".Title") or
                card.select_one("h3") or
                card.select_one("h2") or
                card.select_one("[class*='title' i]")
            )
            title = title_tag.get_text(strip=True) if title_tag else ""

            # Extract poster
            img_tag = card.select_one("img")
            poster = ""
            if img_tag:
                poster = (
                    img_tag.get("data-src") or
                    img_tag.get("data-lazy-src") or
                    img_tag.get("src") or ""
                )

            # Extract year
            year_tag = card.select_one(".year, .Year, [class*='year' i]")
            year = year_tag.get_text(strip=True) if year_tag else str(datetime.now().year)
            year = re.sub(r"[^\d]", "", year)[:4]

            if title and item_url:
                new_items.append({
                    "url":    item_url,
                    "title":  title,
                    "poster": poster,
                    "year":   year or str(datetime.now().year),
                    "type":   detect_type(item_url, title),
                })

        if not found_stop:
            page += 1
            time.sleep(1.5)

        # Safety limit — max 10 pages per run
        if page > 10:
            break

    print(f"  📦 Found {len(new_items)} new items")
    return new_items

# ── SCRAPE CONTENT DETAIL PAGE ───────────────────────
def scrape_detail(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        # ── Description
        description = ""
        for sel in [".StoryMovieContent", ".Description", "p.story", ".BlockDescription", "[class*='story' i]"]:
            tag = soup.select_one(sel)
            if tag:
                description = tag.get_text(strip=True)
                break

        # ── Genres
        genres = []
        for sel in [".GenresList a", ".Genres a", "[class*='genre' i] a", "a[href*='genre']"]:
            tags = soup.select(sel)
            if tags:
                genres = [g.get_text(strip=True) for g in tags[:6]]
                break

        # ── Rating
        rating = 0.0
        for sel in [".imdb-rating", ".Rating", "[class*='rating' i]", "[class*='imdb' i]"]:
            tag = soup.select_one(sel)
            if tag:
                num = re.search(r"(\d+\.?\d*)", tag.get_text())
                if num:
                    rating = float(num.group(1))
                    break

        # ── Language / Country
        language = "Arabic"
        country = ""
        for info_row in soup.select(".InfoTable tr, .MetaInfo li, [class*='info' i] span"):
            text = info_row.get_text(strip=True).lower()
            if "english" in text or "إنجليزي" in text:
                language = "English"
            elif "turkish" in text or "تركي" in text:
                language = "Turkish"
            elif "hindi" in text or "هندي" in text:
                language = "Indian"

        # ── Embed video links
        embeds = []
        # Method 1: direct iframes
        for iframe in soup.select("iframe"):
            src = iframe.get("src") or iframe.get("data-src") or ""
            src = src.strip()
            if src and "youtube" not in src and len(src) > 10:
                embeds.append(src)

        # Method 2: embedded in script tags (some sites do this)
        for script in soup.select("script"):
            script_text = script.get_text()
            found_urls = re.findall(r'https?://[^\s"\'<>]+(?:embed|player|watch)[^\s"\'<>]*', script_text)
            for fu in found_urls:
                if fu not in embeds:
                    embeds.append(fu)

        # ── Download links
        downloads = []
        for sel in [
            "a.DownloadBtn",
            "a[href*='download']",
            ".downloadLinks a",
            "[class*='download' i] a",
            "a[class*='btn' i][href*='http']"
        ]:
            for a in soup.select(sel):
                href = a.get("href", "").strip()
                label = a.get_text(strip=True)
                if href and href.startswith("http") and href not in [d["url"] for d in downloads]:
                    # Try to detect quality from label
                    quality = "720p"
                    for q in ["4K", "1080p", "720p", "480p", "360p", "CAM"]:
                        if q.lower() in label.lower() or q.lower() in href.lower():
                            quality = q
                            break
                    # Try to detect host name
                    host = "Unknown"
                    host_match = re.search(r"https?://(?:www\.)?([^/]+)", href)
                    if host_match:
                        host = host_match.group(1).split(".")[0].capitalize()

                    downloads.append({
                        "url":     href,
                        "label":   label,
                        "quality": quality,
                        "host":    host,
                    })

        # is_dubbed / is_translated
        page_text = soup.get_text().lower()
        is_dubbed     = "مدبلج" in page_text or "dubbed" in page_text
        is_translated = "مترجم" in page_text or "translated" in page_text

        return {
            "description":    description,
            "genres":         genres,
            "rating":         rating,
            "language":       language,
            "country":        country,
            "embeds":         embeds[:6],      # max 6 embed links
            "downloads":      downloads[:12],  # max 12 download links
            "is_dubbed":      is_dubbed,
            "is_translated":  is_translated,
        }

    except Exception as e:
        print(f"  ❌ Detail scrape error: {e}")
        return {}

# ── CHECK IF CONTENT ALREADY EXISTS ─────────────────
def already_exists(item_url):
    try:
        # Use the original URL as a unique identifier stored in slug or a notes field
        slug = make_slug(item_url.split("/")[-1])
        records = b44_get("Content", {"slug": slug})
        return len(records) > 0
    except:
        return False

# ── PUSH CONTENT TO BASE44 ───────────────────────────
def push_content(item, detail):
    raw_slug = item["url"].split("/watch/")[-1] if "/watch/" in item["url"] else item["url"].split("/")[-1]
    slug = make_slug(raw_slug)[:80]

    year_str = item.get("year", str(datetime.now().year))
    try:
        year = int(year_str[:4])
    except:
        year = datetime.now().year

    payload = {
        "title_ar":       item.get("title", ""),
        "title_en":       item.get("title", ""),
        "slug":           slug,
        "type":           item.get("type", "movie"),
        "poster_url":     item.get("poster", ""),
        "backdrop_url":   item.get("poster", ""),
        "description":    detail.get("description", ""),
        "year":           year,
        "genre":          detail.get("genres", []),
        "language":       detail.get("language", "Arabic"),
        "country":        detail.get("country", ""),
        "rating":         detail.get("rating", 0.0),
        "is_dubbed":      detail.get("is_dubbed", False),
        "is_translated":  detail.get("is_translated", True),
        "status":         "published",
        "is_featured":    False,
        "views":          0,
    }

    result = b44_post("Content", payload)
    if not result:
        return None

    content_id = result.get("id")
    print(f"  ✅ Created content: {payload['title_ar'][:40]} (id={content_id})")

    # ── Push embed video links
    qualities = ["480p", "720p", "1080p", "4K"]
    for i, embed_url in enumerate(detail.get("embeds", [])):
        q = qualities[i] if i < len(qualities) else "720p"
        # Match download for same quality if possible
        dl_url = ""
        for d in detail.get("downloads", []):
            if d["quality"] == q:
                dl_url = d["url"]
                break

        b44_post("VideoLink", {
            "content":      content_id,
            "embed_url":    embed_url,
            "download_url": dl_url,
            "quality":      q,
            "host_name":    "Auto",
            "link_type":    "watch",
        })
        time.sleep(0.3)

    # ── Push download-only links (ones without embed)
    for d in detail.get("downloads", []):
        b44_post("VideoLink", {
            "content":      content_id,
            "embed_url":    "",
            "download_url": d["url"],
            "quality":      d["quality"],
            "host_name":    d["host"],
            "link_type":    "download",
        })
        time.sleep(0.3)

    return content_id

# ── MAIN RUN ─────────────────────────────────────────
def run():
    print(f"\n{'='*50}")
    print(f"🚀 MyCima Auto-Publisher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    # Load checkpoint
    last_url, checkpoint_id = get_checkpoint()
    print(f"📌 Last scraped: {last_url[:60] if last_url else 'Nothing yet (first run)'}")

    # Scrape new items
    new_items = scrape_homepage(stop_at_url=last_url)

    if not new_items:
        print("✅ No new content found. Site is up to date.")
        return

    # Save new checkpoint (first item = most recent)
    save_checkpoint(new_items[0]["url"], checkpoint_id)

    # Process each item
    success = 0
    skipped = 0
    failed  = 0

    for i, item in enumerate(new_items):
        print(f"\n[{i+1}/{len(new_items)}] {item['title'][:50]}")
        print(f"  🔗 {item['url'][:60]}")

        if already_exists(item["url"]):
            print(f"  ⏭️ Already exists — skipping")
            skipped += 1
            continue

        detail = scrape_detail(item["url"])
        time.sleep(1.5)

        result = push_content(item, detail)
        if result:
            success += 1
        else:
            failed += 1

        time.sleep(1)

    print(f"\n{'='*50}")
    print(f"✅ Done — {success} added, {skipped} skipped, {failed} failed")
    print(f"{'='*50}\n")

# ── ENTRY POINT ──────────────────────────────────────
if __name__ == "__main__":
    run()
