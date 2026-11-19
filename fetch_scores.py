import os
import json
import requests
from datetime import datetime, timezone

API_KEY = (os.environ.get("API_FOOTBALL_KEY") or "").strip()
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

def safe_get_json(url, headers):
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if not r.text or not r.text.strip():
            return {"_http": r.status_code, "error_note": f"Empty response (HTTP {r.status_code})"}
        data = r.json()
        data["_http"] = r.status_code
        return data
    except Exception as e:
        return {"_http": getattr(r, 'status_code', 0), "error_note": f"Non-JSON response (HTTP {getattr(r, 'status_code', 'unknown')}): {str(e)}"}

# 1. Try direct API-Sports endpoint first
base_url = "https://api-sports.io"
headers = {"x-apisports-key": API_KEY}
fixtures_res = safe_get_json(f"{base_url}/fixtures?date={today}", headers)

# 2. If 403 or RapidAPI message, automatically try RapidAPI endpoint
if fixtures_res.get("_http") == 403 or "RapidAPI" in str(fixtures_res):
    base_url = "https://rapidapi.com"
    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "://rapidapi.com"
    }
    fixtures_res = safe_get_json(f"{base_url}/fixtures?date={today}", headers)

odds_res = safe_get_json(f"{base_url}/odds?date={today}&bet=10", headers)

team_map = {}
raw_fixtures = fixtures_res.get("response")
if isinstance(raw_fixtures, list):
    for item in raw_fixtures:
        fid = item.get("fixture", {}).get("id")
        home = item.get("teams", {}).get("home", {}).get("name", "Home")
        away = item.get("teams", {}).get("away", {}).get("name", "Away")
        if fid:
            team_map[fid] = f"{home} vs {away}"

results = []
raw_odds = odds_res.get("response")
if isinstance(raw_odds, list):
    for item in raw_odds:
        fixture_id = item.get("fixture", {}).get("id")
        bookmakers = item.get("bookmakers")
        if not isinstance(bookmakers, list) or len(bookmakers) == 0:
            continue
        
        first_bookie = bookmakers.pop(0)
        bets = first_bookie.get("bets", [])
        exact_bet = next((b for b in bets if b.get("id") == 10), None)

        top_scores = []
        if exact_bet and isinstance(exact_bet.get("values"), list):
            sorted_vals = sorted(exact_bet["values"], key=lambda x: float(x.get("odd", 999)))[:3]
            top_scores = [{"score": v.get("value"), "odd": v.get("odd")} for v in sorted_vals]

        results.append({
            "match": team_map.get(fixture_id, f"Match #{fixture_id}"),
            "top_exact_scores": top_scores
        })

output = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "date": today,
    "host_used": base_url,
    "key_length": len(API_KEY),
    "total_matches": len(results),
    "fixtures_status": fixtures_res.get("error_note") or fixtures_res.get("errors") or "OK",
    "odds_status": odds_res.get("error_note") or odds_res.get("errors") or "OK",
    "matches": results
}

with open("scores.json", "w") as f:
    json.dump(output, f, indent=2)
