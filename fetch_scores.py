import os
import json
import subprocess
from datetime import datetime, timezone
from urllib.parse import quote

LIMIT_PER_API = 3


def resolve_host_8888(host):
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


# 1. SPORTMONKS (Real Official Correct-Score Probabilities)
def fetch_sportmonks_real():
    raw_token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not raw_token:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    if "api_token=" in raw_token:
        raw_token = raw_token.split("api_token=")[-1].split("&").strip()
    safe_token = quote(raw_token, safe="")
    host = "api." + "sportmonks.com"

    data = get_json(
        host,
        f"/v3/football/fixtures?api_token={safe_token}&include=participants;predictions&filters=fixtureStates:1&per_page=10"
    )
    fixtures = data.get("data") or []
    out = []
    for f in fixtures[:LIMIT_PER_API]:
        parts = f.get("participants") or []
        home = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "home"), "Home")
        away = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "away"), "Away")

        best_score = "No model score on current plan"
        best_prob = 0
        for pred in (f.get("predictions") or []):
            scores_map = (pred.get("predictions") or {}).get("scores") or {}
            if isinstance(scores_map, dict):
                for score_str, prob in scores_map.items():
                    if isinstance(prob, (int, float)) and prob > best_prob:
                        best_prob = prob
                        best_score = score_str.replace("-", " - ")

        out.append({
            "source": "Sportmonks (Official Model)",
            "match": f"{home} vs {away}",
            "modelExactScore": best_score,
            "probability": f"{round(best_prob, 1)}%" if best_prob else "N/A",
            "kickoff": f.get("starting_at", "")
        })
    return out


# 2. API-FOOTBALL (Real Official /predictions Goal Forecast — Premier League ID 39)
def fetch_api_football_real():
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("Missing API_FOOTBALL_KEY")
    host = "v3.football." + "api-sports.io"
    headers = {"x-apisports-key": key}

    data = get_json(host, "/fixtures?league=39&status=NS&next=5", headers)
    items = data.get("response") or []
    out = []
    for item in items[:LIMIT_PER_API]:
        fix_id = (item.get("fixture") or {}).get("id")
        teams = item.get("teams") or {}
        home = (teams.get("home") or {}).get("name", "Home")
        away = (teams.get("away") or {}).get("name", "Away")

        model_score = "N/A"
        advice = "Upcoming Fixture"
        try:
            pred_data = get_json(host, f"/predictions?fixture={fix_id}", headers)
            pred_list = pred_data.get("response") or []
            if pred_list:
                pred_obj = pred_list.get("predictions") or {}
                goals = pred_obj.get("goals") or {}
                if goals.get("home") is not None and goals.get("away") is not None:
                    h_g = round(abs(float(goals["home"])))
                    a_g = round(abs(float(goals["away"])))
                    model_score = f"{h_g} - {a_g}"
                advice = pred_obj.get("advice") or advice
        except Exception:
            pass

        out.append({
            "source": "API-Football (Official Model)",
            "match": f"{home} vs {away}",
            "modelExactScore": model_score,
            "advice": advice,
            "kickoff": (item.get("fixture") or {}).get("date", "")
        })
    return out


# 3. FOOTBALL-DATA.ORG (Real Upcoming Fixtures — No Fake Scores)
def fetch_football_data_real():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("Missing FOOTBALL_DATA_KEY")
    host = "api." + "football-data.org"
    data = get_json(host, "/v4/matches?status=SCHEDULED", {"X-Auth-Token": key})
    matches = data.get("matches") or []
    out = []
    for m in matches[:LIMIT_PER_API]:
        home = (m.get("homeTeam") or {}).get("name", "Home")
        away = (m.get("awayTeam") or {}).get("name", "Away")
        out.append({
            "source": "Football-Data (Fixture Feed)",
            "match": f"{home} vs {away}",
            "competition": (m.get("competition") or {}).get("name", ""),
            "kickoff": m.get("utcDate", "")
        })
    return out


# 4. GOAL-API (Real Upcoming Fixtures — No Fake Scores)
def fetch_goal_api_real():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("GOAL_API_KEY missing")
    host = "api." + "goal-api.com"
    data = get_json(host, "/v1/fixtures?limit=20", {"Authorization": f"Bearer {key}"})
    raw = data if isinstance(data, list) else (data.get("data") or [])
    upcoming = [m for m in raw if str(m.get("matchStatus") or "").upper() not in ("LIVE", "FT", "FINISHED", "HT", "1H", "2H")]
    out = []
    for m in upcoming[:LIMIT_PER_API]:
        home = m.get("homeTeamName") or "Home"
        away = m.get("awayTeamName") or "Away"
        out.append({
            "source": "GOAL-API (Fixture Feed)",
            "match": f"{home} vs {away}",
            "league": m.get("leagueName", ""),
            "kickoff": m.get("kickoffUtc") or m.get("date") or ""
        })
    return out


def main():
    all_items = []
    status = {}
    fetchers = [
        ("Sportmonks", fetch_sportmonks_real),
        ("API-Football", fetch_api_football_real),
        ("Football-Data", fetch_football_data_real),
        ("GOAL-API", fetch_goal_api_real),
    ]

    for name, fn in fetchers:
        try:
            res = fn()
            status[name] = f"OK ({len(res)})"
            all_items.extend(res)
        except Exception as e:
            status[name] = str(e)[:100]

    with open("scores.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(all_items),
            "status": status,
            "data": all_items
        }, f, indent=2)


if __name__ == "__main__":
    main()
