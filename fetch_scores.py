import os
import json
import subprocess
from datetime import datetime, timezone
from urllib.parse import quote

LIMIT_PER_API = 3


def resolve_host_8888(host):
    """Resolves any domain using Google's raw IP 8.8.8.8 (requires zero DNS)."""
    cmd = ["curl", "-sS", "-k", "-m", "8", "-H", "Accept: application/dns-json", f"https://8.8.8{host}&type=A"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        data = json.loads(res.stdout)
        for ans in data.get("Answer", []):
            if ans.get("type") == 1:
                return ans["data"]
    return None


def get_json(host, path, headers=None):
    url = f"https://{host}{path}"
    ip = resolve_host_8888(host)
    cmd = ["curl", "-sS", "-L", "-m", "12", "-H", "Accept: application/json", "-H", "User-Agent: Mozilla/5.0"]
    if ip:
        cmd.extend(["--resolve", f"{host}:443:{ip}"])
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
    host = "api." + "goal-api.com"
    data = get_json(host, "/v1/fixtures?limit=20", {"Authorization": f"Bearer {key}"})
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
    host = "api." + "football-data.org"
    data = get_json(host, "/v4/matches?status=SCHEDULED", {"X-Auth-Token": key})
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
    host = "v3.football." + "api-sports.io"
    data = get_json(host, "/fixtures?status=NS&next=10", {"x-apisports-key": key})
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
    raw_token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not raw_token:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    if "api_token=" in raw_token:
        raw_token = raw_token.split("api_token=")[-1].split("&").strip()
    safe_token = quote(raw_token, safe="")
    host = "api." + "sportmonks.com"
    data = get_json(host, f"/v3/football/fixtures?api_token={safe_token}&include=participants&filters=fixtureStates:1&per_page=5")
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
            status[name] = str(e)[:100]

    with open("scores.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(all_picks),
            "status": status,
            "picks": all_picks
        }, f, indent=2)


if __name__ == "__main__":
    main()
