import os
import json
import requests
from datetime import datetime, timezone, timedelta

APISPORTS_KEY = (
    os.environ.get("API_FOOTBALL_KEY")
    or os.environ.get("API_KEY")
)
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY")

NOW_UTC = datetime.now(timezone.utc)
WAT = timezone(timedelta(hours=1))
NOW_WAT = NOW_UTC.astimezone(WAT)
TODAY = NOW_UTC.strftime("%Y-%m-%d")
TOMORROW = (NOW_UTC + timedelta(days=1)).strftime("%Y-%m-%d")

TOKENS_2_1 = ["2/1", "away/home", "visitor/home", "away / home", "2 / 1"]
TOKENS_1_2 = ["1/2", "home/away", "home/visitor", "home / away", "1 / 2"]

def get_football_pick():
    if not FOOTBALL_DATA_KEY:
        return None
    fd_url = "https://" + "api.football-data.org" + "/v4/matches"
    try:
        fd_res = requests.get(
            fd_url,
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            params={"dateFrom": TODAY, "dateTo": TOMORROW},
            timeout=15
        ).json()
        upcoming = []
        for m in fd_res.get("matches", []):
            utc_str = m.get("utcDate", "")
            if m.get("status") in ["SCHEDULED", "TIMED"] and utc_str:
                k_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                if k_dt > NOW_UTC:
                    upcoming.append((k_dt, m))
        upcoming.sort(key=lambda x: x)
        if upcoming:
            k_dt, m = upcoming
            home = m.get("homeTeam", {}).get("name", "Home")
            away = m.get("awayTeam", {}).get("name", "Away")
            comp = m.get("competition", {}).get("name", "Football")
            return {
                "sport": "FOOTBALL",
                "competition": comp,
                "match": f"{home} vs {away}",
                "kickoff_Nigeria": k_dt.astimezone(WAT).strftime("%Y-%m-%d %I:%M %p WAT"),
                "recommended_pick": "2/1 (Away HT / Home FT)",
                "target_odd": 24.0,
                "note": f"Back {away} to lead at Halftime before {home} overturn it Full-Time on Football.com."
            }
    except Exception:
        pass
    return None

def get_basketball_pick():
    if not APISPORTS_KEY:
        return None
    headers = {"x-apisports-key": APISPORTS_KEY}
    endpoints = [
        ("v1.basketball.api-sports.io", "/games", "/odds"),
        ("v2.nba.api-sports.io", "/games", "/odds")
    ]
    for host, g_path, o_path in endpoints:
        try:
            res = requests.get("https://" + host + g_path, headers=headers, params={"date": TODAY}, timeout=15).json()
            for g in res.get("response", [])[:10]:
                game_id = g.get("id") or (g.get("game", {}).get("id") if isinstance(g.get("game"), dict) else None)
                if not game_id:
                    continue
                o_res = requests.get("https://" + host + o_path, headers=headers, params={"game": game_id}, timeout=15).json()
                odd_1_2, odd_2_1 = None, None
                for item in o_res.get("response", []):
                    for bk in item.get("bookmakers", []):
                        for bet in bk.get("bets", []):
                            if any(k in bet.get("name", "").lower() for k in ["ht/ft", "half", "double result"]):
                                for val in bet.get("values", []):
                                    sel = str(val.get("value", "")).strip().lower()
                                    try:
                                        ov = float(val.get("odd", 0))
                                    except (ValueError, TypeError):
                                        continue
                                    if ov < 3.50:
                                        continue
                                    if any(t in sel for t in TOKENS_1_2) and (not odd_1_2 or ov > odd_1_2):
                                        odd_1_2 = ov
                                    elif any(t in sel for t in TOKENS_2_1) and (not odd_2_1 or ov > odd_2_1):
                                        odd_2_1 = ov
                if odd_1_2 or odd_2_1:
                    teams = g.get("teams", {})
                    home = teams.get("home", {}).get("name", "Home")
                    away = (teams.get("away") or teams.get("visitors") or {}).get("name", "Away")
                    if odd_2_1 and (not odd_1_2 or odd_2_1 <= odd_1_2):
                        pick, odd_val = "2/1 (Away HT / Home FT)", odd_2_1
                    else:
                        pick, odd_val = "1/2 (Home HT / Away FT)", odd_1_2
                    return {
                        "sport": "BASKETBALL",
                        "match": f"{home} vs {away}",
                        "recommended_pick": pick,
                        "odd": odd_val,
                        "note": f"Verified Basketball HT/FT comeback line ({pick}) on Football.com."
                    }
        except Exception:
            continue
    return None

def get_table_tennis_pick():
    # Table Tennis uses 1st Set / Match Winner (2/1 = Player 2 wins 1st Set / Player 1 wins Match)
    return {
        "sport": "TABLE TENNIS",
        "competition": "Czech Liga Pro / TT Cup / Setka Cup (Live Daily on Football.com)",
        "match": "Target Pre-Match Favorite (1.35 - 1.55 Match Odds)",
        "recommended_pick": "2/1 (Away/Player 2 1st Set / Home/Player 1 Match Winner)",
        "target_odd": "5.50 - 8.50",
        "note": "API-Sports & Sportmonks do not cover Table Tennis; open Table Tennis -> 1st Set/Match Winner on Football.com and back 2/1 on a strong favorite."
    }

def run():
    picks = []
    fb = get_football_pick()
    if fb:
        picks.append(fb)
    bb = get_basketball_pick()
    if bb:
        picks.append(bb)
    picks.append(get_table_tennis_pick())

    output = {
        "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
        "date": TODAY,
        "count": len(picks),
        "picks": picks
    }

    with open("top3_sports.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Saved top3_sports.json ({len(picks)} picks).")

if __name__ == "__main__":
    run()
