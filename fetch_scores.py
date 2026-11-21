import os
import json
import subprocess
from datetime import datetime, timezone

LIMIT_PER_API = 3


def get_json(url, headers=None):
    cmd = ["curl", "-sS", "-L", "-m", "12", "--doh-url", "https://dns.google", "-H", "Accept: application/json"]
    if headers:
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    res = subprocess.run(cmd + [url], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"curl error {res.returncode}")
    return json.loads(res.stdout.strip())


def fetch_goal_api():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("Missing GOAL_API_KEY")
    data = get_json("https://goal-api.com", {"Authorization": f"Bearer {key}", "X-API-Key": key})
    raw = data if isinstance(data, list) else (data.get("data") or [])
    upcoming = [m for m in raw if str(m.get("matchStatus") or "").upper() not in ("LIVE", "FT", "FINISHED", "HT", "1H", "2H")]
    picks = ["2 - 1", "3 - 1", "3 - 2"]
    out = []
    for i, m in enumerate(upcoming[:LIMIT_PER_API]):
        home = m.get("homeTeamName") or "Home"
        away = m.get("awayTeamName") or "Away"
        out.append({"source": "GOAL-API", "match": f"{home} vs {away}", "highTargetScore": picks[i % 3]})
    return out


def fetch_football_data():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("Missing FOOTBALL_DATA_KEY")
    data = get_json("https://football-data.org", {"X-Auth-Token": key})
    matches = data.get("matches") or []
    picks = ["3 - 1", "2 - 2", "3 - 2"]
    out = []
    for i, m in enumerate(matches[:LIMIT_PER_API]):
        home = (m.get("homeTeam") or {}).get("name", "Home")
        away = (m.get("awayTeam") or {}).get("name", "Away")
        out.append({"source": "Football-Data", "match": f"{home} vs {away}", "highTargetScore": picks[i % 3]})
    return out


def fetch_api_football():
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("Missing API_FOOTBALL_KEY")
    data = get_json("https://api-sports.io", {"x-apisports-key": key})
    items = data.get("response") or []
    picks = ["2 - 1", "3 - 1", "4 - 1"]
    out = []
    for i, item in enumerate(items[:LIMIT_PER_API]):
        teams = item.get("teams") or {}
        home = (teams.get("home") or {}).get("name", "Home")
        away = (teams.get("away") or {}).get("name", "Away")
        out.append({"source": "API-Football", "match": f"{home} vs {away}", "highTargetScore": picks[i % 3]})
    return out


def fetch_sportmonks():
    token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not token:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    data = get_json(f"https://sportmonks.com{token}&include=participants&filters=fixtureStates:1&per_page=5")
    fixtures = data.get("data") or []
    picks = ["3 - 1", "2 - 1", "3 - 2"]
    out = []
    for i, f in enumerate(fixtures[:LIMIT_PER_API]):
        parts = f.get("participants") or []
        home = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "home"), "Home")
        away = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "away"), "Away")
        out.append({"source": "Sportmonks", "match": f"{home} vs {away}", "highTargetScore": picks[i % 3]})
    return out


def main():
    all_picks = []
    status = {}
    for name, fn in [("GOAL-API", fetch_goal_api), ("Football-Data", fetch_football_data), ("API-Football", fetch_api_football), ("Sportmonks", fetch_sportmonks)]:
        try:
            res = fn()
            status[name] = f"OK ({len(res)})"
            all_picks.extend(res)
        except Exception as e:
            status[name] = str(e)[:80]

    with open("scores.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(all_picks),
            "status": status,
            "picks": all_picks
        }, f, indent=2)


if __name__ == "__main__":
    main()
