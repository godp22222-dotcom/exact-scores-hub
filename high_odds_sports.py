import os
import json
import requests
from datetime import datetime, timezone, timedelta

APISPORTS_KEY = (
    os.environ.get("API_KEY")
    or os.environ.get("API_FOOTBALL_KEY")
    or os.environ.get("APISPORTS_KEY")
)

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
        "id_param": "game"
    },
    "nba": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game"
    },
    "basketball": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game"
    },
    "nfl": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game"
    },
    "rugby": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game"
    },
    "volleyball": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game"
    },
    "baseball": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "game"
    },
    "mma": {
        "games_url": f"https://api-sports.io{TODAY}",
        "odds_url": "https://api-sports.io",
        "id_param": "fight"
    }
}

def extract_all_highest_odds(odds_response):
    best_picks = []
    for item in odds_response:
        for bookmaker in item.get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                bet_name = bet.get("name", "Market")
                for val in bet.get("values", []):
                    try:
                        odd_float = float(val.get("odd", 0))
                        if odd_float >= 1.80:
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
        return
    url = f"https://sportmonks.com{TODAY}"
    params = {"api_token": SPORTMONKS_TOKEN, "include": "odds"}
    try:
        res = requests.get(url, params=params, timeout=20).json()
        for fx in res.get("data", []):
            match_name = fx.get("name", "Unknown Match")
            high_odds = []
            for odd in fx.get("odds", []):
                try:
                    val = float(odd.get("value", 0))
                    if val >= 2.50:
                        high_odds.append({
                            "market": odd.get("market_description", "Market"),
                            "selection": str(odd.get("label")),
                            "odd": val,
                            "bookmaker": "Sportmonks"
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
        print(f"[SPORTMONKS] Skipped: {e}")

def run():
    final_output = {
        "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
        "date": TODAY,
        "count": 0,
        "picks": []
    }

    fetch_sportmonks(final_output["picks"])

    if APISPORTS_KEY:
        for sport, cfg in SPORTS_CONFIG.items():
            try:
                g_res = requests.get(cfg["games_url"], headers=APISPORTS_HEADERS, timeout=20).json()
                games = g_res.get("response", [])
                for g in games[:5]:
                    game_id = g.get("id") or g.get("game", {}).get("id")
                    teams = g.get("teams", {})
                    if isinstance(teams, dict):
                        home = teams.get("home", {}).get("name") or teams.get("visitors", {}).get("name") or "Home"
                        away = teams.get("away", {}).get("name") or "Away"
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

                    top_odds = extract_all_highest_odds(o_res.get("response", []))
                    final_output["picks"].append({
                        "source": "API-Sports",
                        "sport": sport.upper(),
                        "match": match_name,
                        "status": g.get("status", {}).get("long", "Scheduled") if isinstance(g.get("status"), dict) else "Scheduled",
                        "highest_odds": top_odds if top_odds else "Odds restricted on free tier - check Football.com"
                    })
            except Exception as e:
                print(f"[{sport.upper()}] Skipped: {e}")

    final_output["count"] = len(final_output["picks"])
    with open("high_odds_sports.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)
    print(f"Saved high_odds_sports.json with {final_output['count']} total events.")

if __name__ == "__main__":
    run()
