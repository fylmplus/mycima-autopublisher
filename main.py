import requests
from bs4 import BeautifulSoup
import time
import os
import re
import json
import base64
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

def decode_wecima_url(encoded):
    try:
        encoded = encoded.replace('+', '').replace(' ', '')
        trimmed = encoded[3:]
        padded = trimmed + "=" * (4 - len(trimmed) % 4)
        decoded = base64.b64decode(padded).decode("utf-8")
        # Add https: if missing
        if decoded.startswith("//"):
            decoded = "https:" + decoded
        if decoded.startswith("http"):
            return decoded
    except Exception as e:
        print(f"    ⚠️ Decode failed: {e}")
    return ""

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
    text = text.lower()
    if "4k" in text or "2160" in text:
        return "4K"
    if "1080" in text or "full hd" in text:
        return "1080p"
    if "720" in text or " hd" in text:
        return "720p"
    if "480" in text:
        return "480p"
    if "360" in text:
        return "360p"
    if "cam" in text:
        return "CAM"
    return "720p"

def detect_language(text):
    if "إنجليزي" in text or "english" in text.lower():
        return "English"
    if "تركي" in text:
        return "Turkish"
    if "هندي" in text:
        return "Indian"
    if "آسيوي" in text or "asian" in text.lower():
        return "Asian"
    if "فرنسي" in text or "french" in text.lower():
        return "French"
    return "Arabic"

def already_exists(slug):
    try:
        records = b44_get("Content", {"slug": slug})
        return isinstance(records, list) and len(records) > 0
    except:
        return False

def scrape_rss(stop_at_url=None):
    new_items = []
    print("🔍 Scraping Wecima RSS feed...")
    try:
        res = requests.get(f"{WECIMA_BASE}/feed/", headers=HEADERS_WEB, timeout=15)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all("item")
        print(f"  📡 RSS returned {len(items)} items")

        for item in items:
            link = item.find("link")
            title = item.find("title")
            item_url = link.get_text(strip=True) if link else ""
            item_title = title.get_text(strip=True) if title else ""

            if not item_url or not item_title:
                continue
            if stop_at_url and item_url == stop_at_url:
                print(f"  ✅ Reached checkpoint — stopping")
                break

            poster = ""
            content = item.find("content:encoded") or item.find("description")
            if content:
                img_match = re.search(r'src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']', content.get_text())
                if img_match:
                    poster = img_match.group(1)

            year_match = re.search(r'\b(20\d{2})\b', item_title)
            year = year_match.group(1) if year_match else str(datetime.now().year)

            new_items.append({
                "url":    item_url,
                "title":  item_title,
                "poster": poster,
                "year":   year,
                "type":   detect_type(item_url, item_title),
            })

    except Exception as e:
        print(f"  ❌ RSS error: {e}")

    print(f"  📦 Found {len(new_items)} new items")
    return new_items

def scrape_detail(url):
    try:
        res = requests.get(url, headers=HEADERS_WEB, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        page_text = soup.get_text()

        # Description
        description = ""
        for sel in [".StoryMovieContent", ".Description", "p.story", ".BlockDescription"]:
            tag = soup.select_one(sel)
            if tag:
                description = tag.get_text(strip=True)
                break

        # Genres
        genres = []
        for sel in [".GenresList a", ".Genres a", "a[href*='genre']"]:
            tags = soup.select(sel)
            if tags:
                genres = [g.get_text(strip=True) for g in tags[:6]]
                break

        # Rating
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

        # Poster from og:image
        poster = ""
        og_image = soup.find("meta", property="og:image")
        if og_image:
            poster = og_image.get("content", "")

        # Embed — check script tags for iframe src
        embeds = []
        for script in soup.find_all("script"):
            text = script.get_text()
            # Look for iframe src set via JS
            found = re.findall(r'["\']https?://[^"\']*(?:embed|player|stream|vidbom|streamwish|dood|filemoon|uqload)[^"\']*["\']', text)
            for f in found:
                clean = f.strip('"\'')
                if clean not in embeds:
                    embeds.append(clean)

        # Download links — decode base64 data-href
        downloads = []
        for li in soup.select("li.download-item[data-href]"):
            encoded = li.get("data-href", "")
            decoded_url = decode_wecima_url(encoded)

            # Get quality from the li content
            resolution = li.select_one(".resolution")
            quality_tag = li.select_one(".quality")
            label = ""
            if resolution:
                label += resolution.get_text(strip=True)
            if quality_tag:
                label += " " + quality_tag.get_text(strip=True)

            quality = detect_quality(label)

            host = "Unknown"
            if decoded_url:
                host_match = re.search(r"https?://(?:www\.)?([^/]+)", decoded_url)
                if host_match:
                    host = host_match.group(1).split(".")[0].capitalize()

            print(f"    🔗 Download: {quality} | {decoded_url[:60] if decoded_url else 'DECODE FAILED: ' + encoded[:30]}")

            if decoded_url:
                downloads.append({
                    "url":     decoded_url,
                    "quality": quality,
                    "host":    host or "Unknown"
                })
            else:
                # Store encoded URL as fallback so at least something is saved
                downloads.append({
                    "url":     f"https://wecima.cx/go/?url={encoded}",
                    "quality": quality,
                    "host":    "Wecima"
                })

        return {
            "description":   description,
            "genres":        genres,
            "rating":        rating,
            "poster":        poster,
            "language":      detect_language(page_text),
            "embeds":        embeds[:6],
            "downloads":     downloads[:12],
            "is_dubbed":     "مدبلج" in page_text,
            "is_translated": "مترجم" in page_text,
        }
    except Exception as e:
        print(f"  ❌ Detail error: {e}")
        return {}

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

    poster = detail.get("poster") or item.get("poster", "")

    payload = {
        "title_ar":      item.get("title", "") or "بدون عنوان",
        "title_en":      item.get("title", "") or "No Title",
        "slug":          slug,
        "content_type":  content_type,
        "poster_url":    poster,
        "backdrop_url":  poster,
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

    new_items = scrape_rss(stop_at_url=last_url)
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
