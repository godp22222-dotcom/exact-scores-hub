import os
import json
import requests
from datetime import datetime, timezone, timedelta

# Automatically detects your API-Sports key
APISPORTS_KEY = (
    os.environ.get("API_KEY")
    or os.environ.get("API_FOOTBALL_KEY")
    or os.environ.get("APISPORTS_KEY")
)

# Automatically detects your Sportmonks token
SPORTMONKS_TOKEN = (
    os.environ.get("SPORTMONKS_TOKEN")
    or os.environ.get("SPORTMONKS_API_KEY")
    or os.environ.get("SPORTMONKS_KEY")
)

WAT = timezone(timedelta(hours=1))
NOW_WAT = datetime.now(WAT)
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

APISPORTS_HEADERS = {
    "x-apisports-key": APISPORTS_KEY or ""
}

SPORTS_CONFIG = {
    "hockey": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game",
        "target_markets": ["Correct Score", "Exact Score", "1st Period / Full Time", "HT/FT", "Home/Away"]
    },
    "nba": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game",
        "target_markets": ["HT/FT", "Double Result", "Winning Margin", "Overtime", "Home/Away"]
    },
    "basketball": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game",
        "target_markets": ["HT/FT", "Double Result", "Winning Margin", "Home/Away"]
    },
    "nfl": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game",
        "target_markets": ["HT/FT", "Double Result", "Winning Margin", "Home/Away"]
    },
    "rugby": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game",
        "target_markets": ["HT/FT", "Double Result", "Winning Margin", "Home/Away"]
    },
    "volleyball": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game",
        "target_markets": ["Correct Score", "Set Betting", "Home/Away"]
    },
    "baseball": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game",
        "target_markets": ["Winning Margin", "Home/Away"]
    },
    "mma": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "fight",
        "target_markets": ["Method of Victory", "Home/Away", "Fight Winner"]
    }
}

def extract_apisports_odds(odds_response, target_markets):
    best_picks = []
    for item in odds_response:
        for bookmaker in item.get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                bet_name = bet.get("name", "")
                if any(t.lower() in bet_name.lower() for t in target_markets):
                    for val in bet.get("values", []):
                        try:
                            odd_float = float(val.get("odd", 0))
                            if odd_float >= 3.00:
                                best_picks.append({
                                    "market": bet_name,
                                    "selection": str(val.get("value")),
                                    "odd": odd_float,
                                    "bookmaker": bookmaker.get("name")
                                })
                        except (ValueError, TypeError):
                            continue
    best_picks.sort(key=lambda x: x["odd"], reverse=True)
    seen = set()
    unique_top = []
    for p in best_picks:
        key = (p["market"], p["selection"])
        if key not in seen:
            seen.add(key)
            unique_top.append(p)
        if len(unique_top) == 3:
            break
    return unique_top

def fetch_sportmonks(picks_list):
    if not SPORTMONKS_TOKEN:
        print("[SPORTMONKS] Skipped: No Sportmonks token found.")
        return

    sm_markets = ["Correct Score", "Exact Score", "Half Time/Full Time", "HT/FT", "Double Result"]
    url = f"https://sportmonks.com{TODAY}"
    params = {"api_token": SPORTMONKS_TOKEN, "include": "odds"}

    try:
        res = requests.get(url, params=params, timeout=20).json()
        for fx in res.get("data", []):
            match_name = fx.get("name", "Unknown Match")
            high_odds = []
            for odd in fx.get("odds", []):
                market_desc = odd.get("market_description", "")
                if any(t.lower() in market_desc.lower() for t in sm_markets):
                    try:
                        val = float(odd.get("value", 0))
                        if val >= 5.00:
                            high_odds.append({
                                "market": market_desc,
                                "selection": str(odd.get("label")),
                                "odd": val,
                                "bookmaker": "Sportmonks Feed"
                            })
                    except (ValueError, TypeError):
                        continue

            high_odds.sort(key=lambda x: x["odd"], reverse=True)
            seen = set()
            unique_sm = []
            for p in high_odds:
                key = (p["market"], p["selection"])
                if key not in seen:
                    seen.add(key)
                    unique_sm.append(p)
                if len(unique_sm) == 3:
                    break

            if unique_sm:
                picks_list.append({
                    "source": "Sportmonks",
                    "sport": "FOOTBALL",
                    "match": match_name,
                    "highest_odds": unique_sm
                })
    except Exception as e:
        print(f"[SPORTMONKS] Skipped due to error: {e}")

def run():
    final_output = {
        "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
        "date": TODAY,
        "count": 0,
        "picks": []
    }

    # 1. Pull Sportmonks high-odds football picks
    fetch_sportmonks(final_output["picks"])

    # 2. Pull API-Sports high-odds multi-sport picks
    if APISPORTS_KEY:
        for sport, cfg in SPORTS_CONFIG.items():
            try:
                g_res = requests.get(cfg["games_url"], headers=APISPORTS_HEADERS, timeout=20).json()
                games = g_res.get("response", [])
                for g in games[:5]:
                    game_id = g.get("id") or g.get("game", {}).get("id")
                    teams = g.get("teams", {})
                    if isinstance(teams, dict):
                        home = teams.get("home", {}).get("name", "Home")
                        away = teams.get("away", {}).get("name", "Away")
                        match_name = f"{home} vs {away}"
                    else:
                        match_name = f"{sport.upper()} Event #{game_id}"

                    if not game_id:
                        continue

                    o_res = requests.get(
                        cfg["odds_url"],
                        headers=APISPORTS_HEADERS,
                        params={cfg["id_param"]: game_id},
                        timeout=20
                    ).json()

                    top_odds = extract_apisports_odds(o_res.get("response", []), cfg["target_markets"])
                    if top_odds:
                        final_output["picks"].append({
                            "source": "API-Sports",
                            "sport": sport.upper(),
                            "match": match_name,
                            "highest_odds": top_odds
                        })
            except Exception as e:
                print(f"[{sport.upper()}] Skipped: {e}")
    else:
        print("[API-SPORTS] Skipped: No API-Sports key found.")

    final_output["count"] = len(final_output["picks"])
    with open("high_odds_sports.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)
    print(f"Saved high_odds_sports.json with {final_output['count']} total events.")

if __name__ == "__main__":
    run()
