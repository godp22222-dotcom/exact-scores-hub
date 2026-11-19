import os
import json
import re
import time
import requests
from datetime import datetime, timezone

API_KEY = (os.environ.get("API_FOOTBALL_KEY") or "").strip()
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
base_url = "https://" + "v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

def safe_fetch(url):
    try:
        r = requests.get(url, headers=headers, timeout=25)
        if not r.text or not r.text.strip():
            return {"response": [], "errors": f"Empty HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        return {"response": [], "errors": str(e)}

# Only 3 total API calls (well within 10 requests/minute limit!)
fixtures_res = safe_fetch(f"{base_url}/fixtures?date={today}")
time.sleep(2)
ft_res = safe_fetch(f"{base_url}/odds?date={today}&bet=10")
time.sleep(2)
ht_res = safe_fetch(f"{base_url}/odds?date={today}&bet=31")

def parse_total_goals(score_str):
    nums = re.findall(r'\d+', str(score_str))
    if len(nums) == 2:
        return sum(int(n) for n in nums)
    return -1

def extract_all_scores(odds_response, bet_id):
    extracted = {}
    for item in odds_response.get("response", []):
        fid = item.get("fixture", {}).get("id")
        if not fid:
            continue
        for bookie in item.get("bookmakers", []):
            target_bet = next((b for b in bookie.get("bets", []) if b.get("id") == bet_id), None)
            if target_bet and isinstance(target_bet.get("values"), list) and len(target_bet["values"]) > 0:
                parsed_list = []
                for v in target_bet["values"]:
                    score_label = str(v.get("value", "")).strip()
                    total_goals = parse_total_goals(score_label)
                    if total_goals < 0:
                        continue
                    try:
                        odd_num = float(v.get("odd"))
                        if odd_num <= 0:
                            continue
                        parsed_list.append({
                            "score": score_label,
                            "total_goals": total_goals,
                            "odd": f"{odd_num:.2f}",
                            "probability": f"{round(100 / odd_num, 1)}%",
                            "_odd_num": odd_num
                        })
                    except (ValueError, TypeError):
                        continue
                if parsed_list:
                    extracted[fid] = parsed_list
                    break
    return extracted

matches_map = {}
for item in fixtures_res.get("response", []):
    fid = item.get("fixture", {}).get("id")
    if not fid:
        continue
    country = item.get("league", {}).get("country", "World")
    league_name = item.get("league", {}).get("name", "Unknown League")
    matches_map[fid] = {
        "fixture_id": fid,
        "country": country,
        "league": league_name,
        "league_full": f"{country}: {league_name}",
        "match": f"{item.get('teams', {}).get('home', {}).get('name', 'Home')} vs {item.get('teams', {}).get('away', {}).get('name', 'Away')}",
        "kickoff_utc": item.get("fixture", {}).get("date", "")
    }

ft_all = extract_all_scores(ft_res, bet_id=10)
ht_all = extract_all_scores(ht_res, bet_id=31)

all_matches = []
high_goal_matches = []
leagues_grouped = {}

def clean(items):
    return [{k: v for k, v in x.items() if k != "_odd_num"} for x in items]

for fid, info in matches_map.items():
    ft_list = ft_all.get(fid, [])
    ht_list = ht_all.get(fid, [])
    if not ft_list and not ht_list:
        continue

    ft_by_prob = sorted(ft_list, key=lambda x: x["_odd_num"])
    ft_high_goals = sorted([x for x in ft_list if x["total_goals"] >= 3], key=lambda x: (-x["total_goals"], x["_odd_num"]))
    ft_likely_high = sorted([x for x in ft_list if x["total_goals"] >= 3], key=lambda x: x["_odd_num"])
    ht_high_goals = sorted([x for x in ht_list if x["total_goals"] >= 2], key=lambda x: (-x["total_goals"], x["_odd_num"]))

    match_obj = {
        **info,
        "ft_most_likely_high_goal_scores": clean(ft_likely_high[:5]),
        "ft_highest_goal_scores": clean(ft_high_goals[:6]),
        "ht_highest_goal_scores": clean(ht_high_goals[:5]),
        "ft_top_exact_scores": clean(ft_by_prob[:5])
    }

    all_matches.append(match_obj)
    lg_key = info["league_full"]
    leagues_grouped.setdefault(lg_key, []).append(match_obj)

    # Flag as high-scoring match if top 3+ goal exact score has strong odds (<= 8.50)
    if ft_likely_high and ft_likely_high["_odd_num"] <= 8.50:
        high_goal_matches.append(match_obj)

all_matches.sort(key=lambda x: (x["league_full"], x["kickoff_utc"]))

output = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "date": today,
    "summary": {
        "total_leagues": len(leagues_grouped),
        "total_matches": len(all_matches),
        "high_scoring_matches_count": len(high_goal_matches),
        "api_status": {
            "fixtures": fixtures_res.get("errors") or "OK",
            "ft_odds": ft_res.get("errors") or "OK",
            "ht_odds": ht_res.get("errors") or "OK"
        }
    },
    "high_scoring_matches": high_goal_matches,
    "by_league": leagues_grouped,
    "all_matches": all_matches
}

with open("scores.json", "w") as f:
    json.dump(output, f, indent=2)
