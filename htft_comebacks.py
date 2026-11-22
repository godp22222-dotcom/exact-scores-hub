import os
import json
import requests
from datetime import datetime, timezone, timedelta

APISPORTS_KEY = (
    os.environ.get("API_FOOTBALL_KEY")
    or os.environ.get("API_KEY")
)
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY")
SPORTMONKS_TOKEN = os.environ.get("SPORTMONKS_TOKEN")

WAT = timezone(timedelta(hours=1))
NOW_WAT = datetime.now(WAT)
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

BASE_APISPORTS = "api-sports.io"
OTHER_SPORTS = {
    "hockey": ("v1.hockey." + BASE_APISPORTS, "/games", "/odds", "game"),
    "nba": ("v2.nba." + BASE_APISPORTS, "/games", "/odds", "game"),
    "basketball": ("v1.basketball." + BASE_APISPORTS, "/games", "/odds", "game"),
    "nfl": ("v1.american-football." + BASE_APISPORTS, "/games", "/odds", "game"),
    "rugby": ("v1.rugby." + BASE_APISPORTS, "/games", "/odds", "game")
}

TOKENS_2_1 = ["2/1", "away/home", "visitor/home", "away / home", "2 / 1"]
TOKENS_1_2 = ["1/2", "home/away", "home/visitor", "home / away", "1 / 2"]

def extract_htft_odds(odds_list):
    found = {"1/2 (Home HT / Away FT)": None, "2/1 (Away HT / Home FT)": None}
    for item in odds_list:
        for bk in item.get("bookmakers", []):
            for bet in bk.get("bets", []):
                m_name = bet.get("name", "")
                if any(k in m_name.lower() for k in ["ht/ft", "half", "double result", "1st period", "period"]):
                    for val in bet.get("values", []):
                        sel = str(val.get("value", "")).strip().lower()
                        try:
                            odd_val = float(val.get("odd", 0))
                        except (ValueError, TypeError):
                            continue
                        if any(t in sel for t in TOKENS_1_2):
                            if not found["1/2 (Home HT / Away FT)"] or odd_val > found["1/2 (Home HT / Away FT)"]:
                                found["1/2 (Home HT / Away FT)"] = odd_val
                        elif any(t in sel for t in TOKENS_2_1):
                            if not found["2/1 (Away HT / Home FT)"] or odd_val > found["2/1 (Away HT / Home FT)"]:
                                found["2/1 (Away HT / Home FT)"] = odd_val
    return found

def run():
    final_output = {
        "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
        "date": TODAY,
        "markets": "1/2 (Home HT / Away FT) & 2/1 (Away HT / Home FT)",
        "count": 0,
        "football_picks": [],
        "other_sports_picks": []
    }

    # 1. FOOTBALL: Pull up to 3 matches from Football-Data with 2-3 detailed notes
    if FOOTBALL_DATA_KEY:
        fd_url = "https://" + "api.football-data.org" + "/v4/matches"
        try:
            fd_res = requests.get(
                fd_url,
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params={"dateFrom": TODAY, "dateTo": TODAY},
                timeout=15
            ).json()
            scheduled = [m for m in fd_res.get("matches", []) if m.get("status") in ["SCHEDULED", "TIMED"]]
            for m in scheduled[:3]:
                home = m.get("homeTeam", {}).get("name", "Home")
                away = m.get("awayTeam", {}).get("name", "Away")
                comp = m.get("competition", {}).get("name", "Football")
                final_output["football_picks"].append({
                    "source": "Football-Data",
                    "competition": comp,
                    "match": f"{home} vs {away}",
                    "kickoff_UTC": m.get("utcDate", ""),
                    "markets": {
                        "1/2 (Home HT / Away FT)": "21.00 - 29.00",
                        "2/1 (Away HT / Home FT)": "21.00 - 29.00"
                    },
                    "notes": [
                        f"1/2 Angle: Back if {home} press aggressively early while {away} hold stronger second-half bench depth.",
                        f"2/1 Angle: Back if {away} catch an early counter goal before {home} dominate second-half possession.",
                        "Execution: Play as singles or 2-of-3 system on Football.com; hedge live if halftime leader leads 1-0."
                    ]
                })
        except Exception:
            pass

    # 2. FOOTBALL BACKUP (Sportmonks): Pull up to 3 matches if Football-Data has fewer than 3
    if SPORTMONKS_TOKEN and len(final_output["football_picks"]) < 3:
        needed = 3 - len(final_output["football_picks"])
        sm_url = "https://" + "://sportmonks.com" + f"/v3/football/fixtures/date/{TODAY}"
        try:
            sm_res = requests.get(
                sm_url,
                params={"api_token": SPORTMONKS_TOKEN, "include": "odds"},
                timeout=15
            ).json()
            for fx in sm_res.get("data", [])[:needed]:
                match_name = fx.get("name", "Football Match")
                odd_1_2 = None
                odd_2_1 = None
                for o in fx.get("odds", []):
                    if "half time/full time" in o.get("market_description", "").lower():
                        lbl = str(o.get("label", "")).strip()
                        try:
                            val = float(o.get("value", 0))
                        except (ValueError, TypeError):
                            continue
                        if lbl in ["1/2", "Home/Away"]:
                            odd_1_2 = val
                        elif lbl in ["2/1", "Away/Home"]:
                            odd_2_1 = val
                final_output["football_picks"].append({
                    "source": "Sportmonks",
                    "competition": "Football",
                    "match": match_name,
                    "kickoff_UTC": fx.get("starting_at", ""),
                    "markets": {
                        "1/2 (Home HT / Away FT)": odd_1_2 if odd_1_2 else "21.00 - 29.00",
                        "2/1 (Away HT / Home FT)": odd_2_1 if odd_2_1 else "21.00 - 29.00"
                    },
                    "notes": [
                        "1/2 Angle: Targets early home territorial burst followed by second-half road turnaround.",
                        "2/1 Angle: Targets early away counter-attack lead overturned after halftime adjustments.",
                        "Execution: Small-stake high-odds comeback play on Football.com."
                    ]
                })
        except Exception:
            pass

    # 3. OTHER SPORTS: Strictly 1 match per sport (1/2 & 2/1) with 1 concise note
    if APISPORTS_KEY:
        headers = {"x-apisports-key": APISPORTS_KEY}
        for sport, (host, games_path, odds_path, id_param) in OTHER_SPORTS.items():
            g_url = "https://" + host + games_path
            o_url = "https://" + host + odds_path
            try:
                res = requests.get(g_url, headers=headers, params={"date": TODAY}, timeout=15).json()
                games = res.get("response", [])
                if not games:
                    continue
                g = games[0]  # Strictly 1 head-to-head match per sport
                game_id = g.get("id") or (g.get("game", {}).get("id") if isinstance(g.get("game"), dict) else None)
                teams = g.get("teams", {})
                home = teams.get("home", {}).get("name", "Home")
                away = (teams.get("away") or teams.get("visitors") or {}).get("name", "Away")

                htft_odds = {"1/2 (Home HT / Away FT)": None, "2/1 (Away HT / Home FT)": None}
                if game_id:
                    o_res = requests.get(o_url, headers=headers, params={id_param: game_id}, timeout=15).json()
                    htft_odds = extract_htft_odds(o_res.get("response", []))

                final_output["other_sports_picks"].append({
                    "sport": sport.upper(),
                    "match": f"{home} vs {away}",
                    "markets": {
                        "1/2 (Home HT / Away FT)": htft_odds["1/2 (Home HT / Away FT)"] or "Check 1/2 on Football.com",
                        "2/1 (Away HT / Home FT)": htft_odds["2/1 (Away HT / Home FT)"] or "Check 2/1 on Football.com"
                    },
                    "note": f"Single {sport.upper()} comeback target: watch halftime deficit for live 1/2 or 2/1 swing on Football.com."
                })
            except Exception:
                continue

    final_output["count"] = len(final_output["football_picks"]) + len(final_output["other_sports_picks"])
    with open("htft_comebacks.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)
    print(f"Saved htft_comebacks.json ({final_output['count']} picks).")

if __name__ == "__main__":
    run()
