from datetime import datetime, timedelta, timezone
import json
import os
import requests  # Make sure 'requests' is in your requirements.txt

# 1. Timezone & Date Setup (WAT / Africa/Lagos)
NY = datetime.now(timezone.utc)
WAT = timezone(timedelta(hours=1))
NW = NY.astimezone(WAT)

TD = NY.strftime("%Y-%m-%d")
YD = (NY - timedelta(days=1)).strftime("%Y-%m-%d")
TW = NW.strftime("%Y-%m-%d")
TMW = (NW + timedelta(days=1)).strftime("%Y-%m-%d")

BLT = {"unavailable", "none", "null", "n/a", ""}


# 2. Data Cleaning Helpers (Filters out invalid/missing scores)
def ok(v):
  return v is not None and str(v).strip().lower() not in BLT


def scr(o):
  if isinstance(o, list):
    r = []
    for i in o:
      if isinstance(i, dict):
        if any(not ok(v) for k, v in i.items() if "score" in k.lower()):
          continue
        r.append(scr(i))
      elif ok(i):
        r.append(i)
    return r
  if isinstance(o, dict):
    return {k: scr(v) for k, v in o.items() if ok(v)}
  return o


# 3. Fetch Your Exact Score Data
# Replace API_URL and HEADERS with your actual sports API endpoint (e.g., Sportmonks)
API_URL = "YOUR_API_ENDPOINT_HERE"
HEADERS = {"Authorization": os.getenv("API_TOKEN", "")}

response = requests.get(API_URL, headers=HEADERS, timeout=30)
response.raise_for_status()
raw_data = response.json()

# 4. Clean & Package Output
cleaned_matches = scr(raw_data)

output_payload = {
    "updated_at": NW.strftime("%Y-%m-%d %H:%M:%S WAT"),
    "date": TW,
    "top3_exact_scores": (
        cleaned_matches[:3]
        if isinstance(cleaned_matches, list)
        else cleaned_matches
    ),
}

# 5. Save to outputs/top3_sports.json
os.makedirs("outputs", exist_ok=True)
with open("outputs/top3_sports.json", "w", encoding="utf-8") as f:
  json.dump(output_payload, f, indent=2)

print("Successfully updated outputs/top3_sports.json")
