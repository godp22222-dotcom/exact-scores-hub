import os
import json
import requests
from datetime import datetime, timezone

API_KEY = (os.environ.get("API_FOOTBALL_KEY") or "").strip()
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# 1. Try direct API-Sports endpoint first
base_url = "https://api-sports.io"
headers = {"x-apisports-key": API_KEY}

fixtures_res = requests.get(f"{base_url}/fixtures?date={today}", headers=headers).json()

# 2. If key is from RapidAPI, automatically switch to RapidAPI host
if fixtures_res.get("message") and "RapidAPI" in str(fixtures_res.get("message")):
    base_url = "https://rapidapi.com"
    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "://rapidapi.com"
    }
    fixtures_res = requests.get(f"{base_url}/fixtures?date={today}", headers=headers).json()

odds_res = requests.get(f"{base_url}/odds?date={today}&bet=10", headers=headers).json()

# Map fixture IDs to team names safely
team_map = {}
raw_fixtures = fixtures_res.get("response")
if isinstance(raw_fixtures, list):
    for item in raw_fixtures:
        fid = item.get("fixture", {}).get("id")
        home = item.get("teams", {}).get("home", {}).get("name", "Home")
        away = item.get("teams", {}).get("away", {}).get("name", "Away")
        if fid:
            team_map[fid] = f"{home} vs {away}"

# Extract Exact Score odds safely
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
    "total_matches": len(results),
    "api_errors": odds_res.get("errors") or fixtures_res.get("errors") or None,
    "matches": results
}

with open("scores.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Successfully saved {len(results)} matches to scores.json")
