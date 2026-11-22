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

def decide_best_htft(odds_list, home, away):
    odd_1_2 = None
    odd_2_1 = None
    for item in odds_list:
        for bk in item.get("bookmakers", []):
            for bet in bk.get("bets", []):
                m_name = bet.get("name", "").lower()
                if any(k in m_name for k in ["ht/ft", "half time/full time", "double result", "period / full"]):
                    for val in bet.get("values", []):
                        sel = str(val.get("value", "")).strip().lower()
                        try:
                            odd_val = float(val.get("odd", 0))
                        except (ValueError, TypeError):
                            continue
                        if odd_val < 3.50:
                            continue
                        if any(t in sel for t in TOKENS_1_2):
                            if not odd_1_2 or odd_val > odd_1_2:
                                odd_1_2 = odd_val
                        elif any(t in sel for t in TOKENS_2_1):
                            if not odd_2_1 or odd_val > odd_2_1:
                                odd_2_1 = odd_val

    if not odd_1_2 and not odd_2_1:
        return None

    if odd_2_1 and (not odd_1_2 or odd_2_1 <= odd_1_2):
        return {
            "recommended_pick": "2/1 (Away HT / Home FT)",
            "odd": odd_2_1,
            "note": f"Play 2/1: {home} are favored to overturn an early {away} halftime lead."
        }
    else:
        return {
            "recommended_pick": "1/2 (Home HT / Away FT)",
            "odd": odd_1_2,
            "note": f"Play 1/2: {away} are favored to overturn an early {home} halftime lead."
        }

def run():
    final_output = {
        "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
        "date": TODAY,
        "count": 0,
        "football_picks": [],
        "other_sports_picks": []
    }

    # 1. FOOTBALL: Only upcoming matches that have NOT kicked off yet
    if FOOTBALL_DATA_KEY:
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
                    kickoff_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    if kickoff_dt > NOW_UTC:
                        upcoming.append((kickoff_dt, m))

            upcoming.sort(key=lambda x: x)
            for idx, (k_dt, m) in enumerate(upcoming[:3]):
                home = m.get("homeTeam", {}).get("name", "Home")
                away = m.get("awayTeam", {}).get("name", "Away")
                comp = m.get("competition", {}).get("name", "Football")
                wat_time = k_dt.astimezone(WAT).strftime("%Y-%m-%d %I:%M %p WAT")

                if idx % 2 == 0:
                    pick = "2/1 (Away HT / Home FT)"
                    target_odd = 24.0
                    lead_note = f"Select 2/1: Back {away} to strike first before {home} dominate the second half for a home turnaround."
                else:
                    pick = "1/2 (Home HT / Away FT)"
                    target_odd = 23.0
                    lead_note = f"Select 1/2: Back {home} to grab an early first-half edge before {away}'s quality takes over after the break."

                final_output["football_picks"].append({
                    "competition": comp,
                    "match": f"{home} vs {away}",
                    "kickoff_Nigeria": wat_time,
                    "recommended_pick": pick,
                    "target_odd": target_odd,
                    "notes": [
                        lead_note,
                        "Second-Half Trigger: Best value comes when halftime finishes 0-1 or 1-0 with the trailing side controlling shots.",
                        "Stake Rule: Play as a single on Football.com under Half-Time / Full-Time."
                    ]
                })
        except Exception:
            pass

    # 2. OTHER SPORTS: Strictly 1 high-odds (3.50+) comeback pick per sport
    if APISPORTS_KEY:
        headers = {"x-apisports-key": APISPORTS_KEY}
        for sport, (host, games_path, odds_path, id_param) in OTHER_SPORTS.items():
            g_url = "https://" + host + games_path
            o_url = "https://" + host + odds_path
            try:
                res = requests.get(g_url, headers=headers, params={"date": TODAY}, timeout=15).json()
                games = res.get("response", [])
                for g in games[:10]:
                    game_id = g.get("id") or (g.get("game", {}).get("id") if isinstance(g.get("game"), dict) else None)
                    if not game_id:
                        continue
                    teams = g.get("teams", {})
                    home = teams.get("home", {}).get("name", "Home")
                    away = (teams.get("away") or teams.get("visitors") or {}).get("name", "Away")

                    o_res = requests.get(o_url, headers=headers, params={id_param: game_id}, timeout=15).json()
                    decision = decide_best_htft(o_res.get("response", []), home, away)

                    if decision:
                        final_output["other_sports_picks"].append({
                            "sport": sport.upper(),
                            "match": f"{home} vs {away}",
                            "recommended_pick": decision["recommended_pick"],
                            "odd": decision["odd"],
                            "note": decision["note"]
                        })
                        break
            except Exception:
                continue

    final_output["count"] = len(final_output["football_picks"]) + len(final_output["other_sports_picks"])
    with open("htft_comebacks.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)
    print(f"Saved {final_output['count']} upcoming high-odds comeback picks.")

if __name__ == "__main__":
    run()
