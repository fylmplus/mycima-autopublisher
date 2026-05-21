import requests
import json

BASE44_API_KEY = "YOUR_API_KEY_HERE"
BASE44_BASE    = "https://mycima.base44.app/api"
HEADERS_B44    = {"api_key": BASE44_API_KEY, "Content-Type": "application/json"}

# Delete the checkpoint so scraper runs again
res = requests.get(f"{BASE44_BASE}/entities/Setting", headers=HEADERS_B44, 
                   params={"q": json.dumps({"key": "last_scraped_url"})})
records = res.json()
if records:
    record_id = records[0]["id"]
    requests.delete(f"{BASE44_BASE}/entities/Setting/{record_id}", headers=HEADERS_B44)
    print("✅ Checkpoint deleted — scraper will re-run on next trigger")
else:
    print("No checkpoint found")
