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

SOURCE_BASE = "https://topcinemaa.com"
HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
}

# ── DEBUG ─────────────────────────────────────────────
def debug_env():
    app_id  = BASE44_APP_ID  or "MISSING"
    api_key = BASE44_API_KEY or "MISSING"
    print(f"🔑 APP_ID  : {app_id[:6]}...{app_id[-4:] if len(app_id) > 10 else app_id}")
    print(f"🔑 API_KEY : {api_key[:6]}...{api_key[-4:] if len(api_key) > 10 else api_key}")
    print(f"🔗 Base URL: {BASE44_BASE}")
    if not BASE44_APP_ID or not BASE44_API_KEY:
        print("❌ FATAL: Missing environment variables. Check GitHub Secrets.")
        exit(1)

# ── BASE44 HELPERS ────────────────────────────────────
def b44_get(entity, q=None, limit=100):
    params = {"limit": limit}
    if q:
        params["q"] = json.dumps(q)
    try:
        res = requests.get(
            f"{BASE44_BASE}/entities/{entity}",
            headers=HEADERS_B44, params=params, timeout=15
        )
        if res.status_code == 200:
            return res.json()
        print(f"  ⚠️ GET {entity} returned {res.status_code}: {res.text[:80]}")
    except Exception as e:
        print(f"  ⚠️ GET {entity} error: {e}")
    return []

def b44_post(entity, payload):
    try:
        res = requests.post(
            f"{BASE44_BASE}/entities/{entity}",
            headers=HEADERS_B44, json=payload, timeout=15
        )
        if res.status_code in [200, 201]:
            return res.json()
        print(f"  ❌ POST {entity} {res.status_code}: {res.text[:80]}")
    except Exception as e:
        print(f"  ❌ POST {entity} error: {e}")
    return None

def b44_put(entity, record_id, payload):
    try:
        res = requests.put(
            f"{BASE44_BASE}/entities/{entity}/{record_id}",
            headers=HEADERS_B44, json=payload, timeout=15
        )
        return res.status_code in [200, 204]
    except:
        return False

def test_connection():
    print("\n🧪 Testing Base44 connection...")
    result = b44_get("Content", limit=1)
    if result is not None:
        print("  ✅ Connection OK")
        return True
    print("  ❌ Connection FAILED")
    return False

# ── CHECKPOINT ────────────────────────────────────────
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

# ── SLUG ──────────────────────────────────────────────
def make_slug(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].strip("-")

# ── DETECT TYPE FROM RSS CATEGORY + TITLE ────────────
def detect_type(title, categories):
    cats = " ".join(categories).lower()
    title_lower = title.lower()
    if "انمي" in cats or "anime" in cats or "انمي" in title_lower:
        return "anime"
    if "مسلسل" in title_lower or "مسلسلات" in cats or "الموسم" in title_lower:
        return "series"
    if "برنامج" in title_lower or "show" in cats:
        return "show"
    if "فيلم" in title_lower or "افلام" in cats or "movie" in cats:
        return "movie"
    return "movie"

# ── DETECT LANGUAGE FROM CATEGORY ────────────────────
def detect_language(categories, description):
    cats  = " ".join(categories).lower()
    desc  = description.lower()
    if "هندي" in cats or "هندي" in desc:
        return "Indian"
    if "تركي" in cats or "تركي" in desc:
        return "Turkish"
    if "اسيوي" in cats or "تايلاند" in desc or "فلبيني" in desc or "كوري" in desc:
        return "Asian"
    if "اجنبي" in cats or "english" in desc:
        return "English"
    if "فرنسي" in cats:
        return "French"
    if "عربي" in cats or "عربي" in desc:
        return "Arabic"
    return "Arabic"

# ── SCRAPE RSS ────────────────────────────────────────
def scrape_rss(stop_at_url=None, max_pages=20):
    new_items = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        rss_url = f"{SOURCE_BASE}/feed/?paged={page}"
        try:
            res  = requests.get(rss_url, headers=HEADERS_WEB, timeout=15)
            soup = BeautifulSoup(res.content, "xml")
            items = soup.find_all("item")

            if not items:
                print(f"  📡 RSS page {page}: no items — stopping")
                break

            found_stop = False
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
                    print(f"  ✅ Reached checkpoint on RSS page {page}")
                    found_stop = True
                    break

                # Categories
                categories = [c.get_text(strip=True) for c in item.find_all("category")]

                # Description
                desc_tag    = item.find("description")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                # Year from pubDate or title
                pub_date = item.find("pubDate")
                year     = str(datetime.now().year)
                if pub_date:
                    m = re.search(r"\d{4}", pub_date.get_text())
                    if m:
                        year = m.group()
                year_in_title = re.search(r"(20\d{2})", item_title)
                if year_in_title:
                    year = year_in_title.group(1)

                # Poster from media:content or enclosure
                poster      = ""
                media_cont  = item.find("media:content")
                if media_cont:
                    poster = media_cont.get("url", "")
                if not poster:
                    enclosure = item.find("enclosure")
                    if enclosure:
                        poster = enclosure.get("url", "")
                if not poster:
                    # Try to extract from content:encoded
                    content_enc = item.find("content:encoded")
                    if content_enc:
                        img_match = re.search(
                            r'<img[^>]+src=["\']([^"\']+)["\']',
                            content_enc.get_text()
                        )
                        if img_match:
                            poster = img_match.group(1)

                new_items.append({
                    "url":         item_url,
                    "title":       item_title,
                    "poster":      poster,
                    "year":        year,
                    "type":        detect_type(item_title, categories),
                    "language":    detect_language(categories, description),
                    "description": description,
                    "categories":  categories,
                })

            print(f"  📡 RSS page {page}: {len(items)} items")

            if found_stop:
                break

            time.sleep(1)

        except Exception as e:
            print(f"  ⚠️ RSS page {page} error: {e}")
            break

    print(f"  📦 RSS total: {len(new_items)} new items")
    return new_items

# ── SCRAPE DETAIL PAGE ────────────────────────────────
def scrape_detail(url):
    try:
        res  = requests.get(url, headers=HEADERS_WEB, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        # Poster — og:image is most reliable
        poster = ""
        og = soup.find("meta", property="og:image")
        if og:
            poster = og.get("content", "")
        if not poster:
            for sel in [".poster img", ".MovieImg img", "img.wp-post-image", "article img"]:
                img = soup.select_one(sel)
                if img:
                    poster = img.get("src") or img.get("data-src") or ""
                    break

        # Description — og:description or first paragraph
        description = ""
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            description = og_desc.get("content", "")
        if not description:
            for sel in [".entry-content p", "article p", ".post-content p"]:
                tag = soup.select_one(sel)
                if tag:
                    description = tag.get_text(strip=True)
                    break

        # Rating
        rating = 0.0
        for sel in [".imdb", ".rating", "[class*='imdb']", "[class*='rate']"]:
            tag = soup.select_one(sel)
            if tag:
                num = re.search(r"(\d+\.?\d*)", tag.get_text())
                if num:
                    rating = min(float(num.group(1)), 10.0)
                    break

        page_text = soup.get_text().lower()

        # Embeds
        embeds = []
        for iframe in soup.select("iframe"):
            src = (iframe.get("src") or iframe.get("data-src") or "").strip()
            if src and len(src) > 10 and "youtube" not in src:
                embeds.append(src)
        for script in soup.select("script"):
            found = re.findall(
                r'https?://[^\s"\'<>]+(?:embed|player)[^\s"\'<>]*',
                script.get_text()
            )
            for f in found:
                if f not in embeds:
                    embeds.append(f)

        # Downloads
        downloads = []
        for sel in [
            "a.download-btn", "a.btn-download", ".download-links a",
            "[class*='download'] a", "a[href*='/d/']", "a[href*='download']"
        ]:
            for a in soup.select(sel):
                href  = a.get("href", "").strip()
                label = a.get_text(strip=True)
                if not href or not href.startswith("http"):
                    continue
                if href in [d["url"] for d in downloads]:
                    continue
                quality = "720p"
                for q in ["4K", "2160p", "1080p", "720p", "480p", "360p", "CAM"]:
                    if q.lower() in label.lower() or q.lower() in href.lower():
                        quality = q
                        break
                host_match = re.search(r"https?://(?:www\.)?([^/]+)", href)
                host = host_match.group(1).split(".")[0].capitalize() if host_match else "Unknown"
                downloads.append({"url": href, "quality": quality, "host": host})

        return {
            "poster":        poster,
            "description":   description,
            "rating":        rating,
            "embeds":        embeds[:8],
            "downloads":     downloads[:15],
            "is_dubbed":     "مدبلج" in page_text,
            "is_translated": "مترجم" in page_text,
        }

    except Exception as e:
        print(f"  ❌ Detail error: {e}")
        return {}

# ── CHECK EXISTS ──────────────────────────────────────
def get_existing(slug):
    try:
        records = b44_get("Content", {"slug": slug}, limit=1)
        if records and len(records) > 0:
            return records[0]
    except:
        pass
    return None

# ── PUSH TO BASE44 ────────────────────────────────────
def push_content(item, detail):
    raw_slug = item["url"].rstrip("/").split("/")[-1]
    slug     = make_slug(raw_slug)[:80]
    existing = get_existing(slug)

    try:
        year = int(item.get("year", str(datetime.now().year))[:4])
    except:
        year = datetime.now().year

    poster = detail.get("poster") or item.get("poster", "")
    desc   = detail.get("description") or item.get("description", "")

    # Extract genres from categories
    skip_cats = {"افلام", "مسلسلات", "انمي", "اجنبي", "عربي", "هندي",
                 "تركي", "اسيوية", "مترجم", "مدبلج", "اون لاين"}
    genres = [
        c for c in item.get("categories", [])
        if c and c not in skip_cats and len(c) < 30
    ][:5]

    payload = {
        "title_ar":      item.get("title", ""),
        "title_en":      item.get("title", ""),
        "slug":          slug,
        "content_type":  item.get("type", "movie"),
        "poster_url":    poster,
        "backdrop_url":  poster,
        "description":   desc,
        "year":          year,
        "genre":         genres,
        "language":      item.get("language", "Arabic"),
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
        new_embeds     = [e for e in detail.get("embeds", []) if e not in existing_urls]

        added = 0
        for e in new_embeds:
            b44_post("VideoLink", {
                "content_id": content_id, "embed_url": e,
                "download_url": "", "quality": "720p",
                "host_name": "Auto", "link_type": "watch",
            })
            added += 1
            time.sleep(0.2)
        for d in new_links:
            b44_post("VideoLink", {
                "content_id": content_id, "embed_url": "",
                "download_url": d["url"], "quality": d["quality"],
                "host_name": d["host"], "link_type": "download",
            })
            added += 1
            time.sleep(0.2)

        if added:
            print(f"  🔗 Added {added} new links to existing")
        else:
            print(f"  ⏭️ Already up to date")
        return content_id

    # Create new content
    result = b44_post("Content", payload)
    if not result:
        return None

    content_id = result.get("id")
    print(f"  ✅ Created: {payload['title_ar'][:50]}")

    qualities = ["480p", "720p", "1080p", "4K"]
    for i, embed_url in enumerate(detail.get("embeds", [])):
        q      = qualities[i] if i < len(qualities) else "720p"
        dl_url = next((d["url"] for d in detail.get("downloads", []) if d["quality"] == q), "")
        b44_post("VideoLink", {
            "content_id": content_id, "embed_url": embed_url,
            "download_url": dl_url, "quality": q,
            "host_name": "Auto", "link_type": "watch",
        })
        time.sleep(0.2)

    for d in detail.get("downloads", []):
        b44_post("VideoLink", {
            "content_id": content_id, "embed_url": "",
            "download_url": d["url"], "quality": d["quality"],
            "host_name": d["host"], "link_type": "download",
        })
        time.sleep(0.2)

    return content_id

# ── MAIN ──────────────────────────────────────────────
def run():
    print(f"\n{'='*50}")
    print(f"🚀 MyCima Auto-Publisher — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    debug_env()

    if not test_connection():
        print("❌ Cannot connect to Base44. Exiting.")
        exit(1)

    last_url, checkpoint_id = get_checkpoint()
    print(f"\n📌 Last scraped: {last_url[:70] if last_url else 'First run — full scrape'}")

    items = scrape_rss(stop_at_url=last_url, max_pages=20)

    if not items:
        print("✅ Nothing new.")
        return

    save_checkpoint(items[0]["url"], checkpoint_id)

    success = failed = 0
    for i, item in enumerate(items):
        print(f"\n[{i+1}/{len(items)}] {item['title'][:60]}")
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
