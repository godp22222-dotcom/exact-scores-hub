import os
import json
import requests
from datetime import datetime, timezone

API_KEY = os.environ.get("API_FOOTBALL_KEY")
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
headers = {"x-apisports-key": API_KEY}

fixtures_res = requests.get(f"https://api-sports.io{today}", headers=headers).json()
odds_res = requests.get(f"https://api-sports.io{today}&bet=10", headers=headers).json()

print("Fixtures count:", len(fixtures_res.get("response", [])))
print("Odds count:", len(odds_res.get("response", [])))
if odds_res.get("errors"):
    print("API Errors:", odds_res.get("errors"))

team_map = {}
for item in fixtures_res.get("response", []):
    team_map[item["fixture"]["id"]] = f"{item['teams']['home']['name']} vs {item['teams']['away']['name']}"

results = []
for item in odds_res.get("response", []):
    fixture_id = item["fixture"]["id"]
    bookmakers = item.get("bookmakers", [])
    if not bookmakers:
        continue
    exact_bet = next((b for b in bookmakers.get("bets", []) if b["id"] == 10), None)
    
    top_scores = []
    if exact_bet:
        sorted_vals = sorted(exact_bet["values"], key=lambda x: float(x["odd"]))[:3]
        top_scores = [{"score": v["value"], "odd": v["odd"]} for v in sorted_vals]

    results.append({
        "match": team_map.get(fixture_id, f"Match #{fixture_id}"),
        "top_exact_scores": top_scores
    })

with open("scores.json", "w") as f:
    json.dump({"updated_at": datetime.now(timezone.utc).isoformat(), "matches": results}, f, indent=2)
