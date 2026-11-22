import os
import json
import requests
from datetime import datetime, timezone, timedelta

APISPORTS_KEY = (
    os.environ.get("API_FOOTBALL_KEY")
    or os.environ.get("API_KEY")
)
SPORTMONKS_TOKEN = os.environ.get("SPORTMONKS_TOKEN")
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY")

WAT = timezone(timedelta(hours=1))
NOW_WAT = datetime.now(WAT)
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

SPORTS_CONFIG = {
    "hockey": f"https://api-sports.io{TODAY}",
    "nba": f"https://api-sports.io{TODAY}",
    "basketball": f"https://api-sports.io{TODAY}",
    "nfl": f"https://api-sports.io{TODAY}",
    "rugby": f"https://api-sports.io{TODAY}",
    "volleyball": f"https://api-sports.io{TODAY}",
    "baseball": f"https://api-sports.io{TODAY}",
    "mma": f"https://api-sports.io{TODAY}"
}

def run():
    final_output = {
        "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
        "date": TODAY,
        "diagnostics": {},
        "count": 0,
        "picks": []
    }

    # 1. Check API-Sports multi-sport endpoints
    if APISPORTS_KEY:
        headers = {"x-apisports-key": APISPORTS_KEY}
        for sport, url in SPORTS_CONFIG.items():
            try:
                res = requests.get(url, headers=headers, timeout=15).json()
                errors = res.get("errors")
                games = res.get("response", [])
                if errors:
                    final_output["diagnostics"][sport] = str(errors)
                else:
                    final_output["diagnostics"][sport] = f"OK ({len(games)} games)"
                    for g in games[:5]:
                        teams = g.get("teams", {})
                        home = teams.get("home", {}).get("name") or teams.get("visitors", {}).get("name") or "Home"
                        away = teams.get("away", {}).get("name") or "Away"
                        final_output["picks"].append({
                            "source": "API-Sports",
                            "sport": sport.upper(),
                            "match": f"{home} vs {away}",
                            "high_odds_target": "Check HT/FT Comeback (2/1) or Winning Margin on Football.com"
                        })
            except Exception as e:
                final_output["diagnostics"][sport] = f"Error: {e}"

    # 2. Pull guaranteed upcoming matches from Football-Data.org (already in your secrets!)
    if FOOTBALL_DATA_KEY:
        try:
            fd_res = requests.get(
                f"https://football-data.org{TODAY}&dateTo={TODAY}",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                timeout=15
            ).json()
            matches = fd_res.get("matches", [])
            final_output["diagnostics"]["Football-Data"] = f"OK ({len(matches)} matches)"
            for m in matches:
                if m.get("status") in ["SCHEDULED", "TIMED"]:
                    home = m.get("homeTeam", {}).get("name", "Home")
                    away = m.get("awayTeam", {}).get("name", "Away")
                    comp = m.get("competition", {}).get("name", "Football")
                    utc_time = m.get("utcDate", "")
                    final_output["picks"].append({
                        "source": "Football-Data",
                        "sport": f"FOOTBALL ({comp})",
                        "match": f"{home} vs {away}",
                        "kickoff_UTC": utc_time,
                        "high_odds_targets": [
                            {"market": "HT/FT Comeback (Away HT / Home FT)", "target_odd": "21.00 - 29.00"},
                            {"market": "Exact Score Comeback (2-1 or 3-1)", "target_odd": "8.50 - 13.00"},
                            {"market": "0-0 HT / 1-1 FT Exact Progression", "target_odd": "16.50 - 19.00"}
                        ]
                    })
        except Exception as e:
            final_output["diagnostics"]["Football-Data"] = f"Error: {e}"

    final_output["count"] = len(final_output["picks"])
    with open("high_odds_sports.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)
    print(f"Done: {final_output['count']} picks saved.")

if __name__ == "__main__":
    run()
