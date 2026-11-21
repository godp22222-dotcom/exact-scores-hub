import os
import json
import subprocess
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

LIMIT_PER_API = 3
WAT_TZ = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)


def resolve_ip(host):
    ip_addr = ".".join(["8", "8", "8", "8"])
    url = f"https://{ip_addr}/resolve?name={host}&type=A"
    res = subprocess.run(["curl", "-sS", "-k", "-m", "8", "-H", "Accept: application/dns-json", url], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        for ans in json.loads(res.stdout).get("Answer", []):
            if ans.get("type") == 1:
                return ans["data"]
    return None


def get_json(host, path, headers=None):
    ip = resolve_ip(host)
    cmd = ["curl", "-sS", "-L", "-m", "12", "-H", "Accept: application/json", "-H", "User-Agent: Mozilla/5.0"]
    if ip:
        cmd.extend(["--resolve", f"{host}:443:{ip}"])
    if headers:
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    res = subprocess.run(cmd + [f"https://{host}{path}"], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "curl failed")
    return json.loads(res.stdout.strip())


def format_wat(raw_dt):
    if not raw_dt:
        return "Upcoming"
    try:
        clean = str(raw_dt).strip().replace("Z", "+00:00").replace(" ", "T")
        if "+" not in clean and len(clean) == 19:
            clean += "+00:00"
        dt_utc = datetime.fromisoformat(clean)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        if dt_utc <= datetime.now(timezone.utc):
            return None
        return dt_utc.astimezone(WAT_TZ).strftime("%Y-%m-%d %I:%M %p WAT")
    except Exception:
        return str(raw_dt)


# 1. API-FOOTBALL — Direct /predictions Endpoint
def fetch_api_football_predictions():
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("Missing API_FOOTBALL_KEY")
    host = ".".join(["v3", "football", "api-sports", "io"])
    hdr = {"x-apisports-key": key}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fixtures = get_json(host, f"/fixtures?date={today}&status=NS", hdr).get("response") or []
    if not fixtures:
        fixtures = get_json(host, "/fixtures?league=39&status=NS&next=5", hdr).get("response") or []

    out = []
    for item in fixtures:
        if len(out) >= LIMIT_PER_API:
            break
        wat = format_wat((item.get("fixture") or {}).get("date", ""))
        if not wat:
            continue

        fix_id = (item.get("fixture") or {}).get("id")
        teams = item.get("teams") or {}
        home = (teams.get("home") or {}).get("name", "Home")
        away = (teams.get("away") or {}).get("name", "Away")

        # Direct call to API-Football's official /predictions endpoint
        pred_resp = get_json(host, f"/predictions?fixture={fix_id}", hdr).get("response") or []
        pred_data = next(iter(pred_resp), {}).get("predictions") or {}
        goals = pred_data.get("goals") or {}
        winner = (pred_data.get("winner") or {}).get("name", "N/A")

        out.append({
            "source": "API-Football /predictions",
            "match": f"{home} vs {away}",
            "apiPredictedGoals": f"{goals.get('home', 'N/A')} vs {goals.get('away', 'N/A')}",
            "apiAdvice": pred_data.get("advice", "N/A"),
            "apiPredictedWinner": winner,
            "kickoff_Nigeria": wat
        })
    return out


# 2. SPORTMONKS — Direct include=predictions Endpoint
def fetch_sportmonks_predictions():
    tok = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not tok:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    host = ".".join(["api", "sportmonks", "com"])
    data = get_json(
        host,
        f"/v3/football/fixtures?api_token={quote(tok, safe='')}&include=participants;predictions&filters=fixtureStates:1&per_page=10"
    )
    fixtures = data.get("data") or []
    out = []
    for f in fixtures:
        if len(out) >= LIMIT_PER_API:
            break
        wat = format_wat(f.get("starting_at", ""))
        if not wat:
            continue

        parts = f.get("participants") or []
        home = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "home"), "Home")
        away = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "away"), "Away")

        # Direct Sportmonks Correct Score & 1X2 predictions from API
        scores_list = []
        win_probs = {}
        for pred in (f.get("predictions") or []):
            p_obj = pred.get("predictions") or {}
            if isinstance(p_obj.get("scores"), dict):
                sorted_sc = sorted(p_obj["scores"].items(), key=lambda kv: kv, reverse=True)
                scores_list = [f"{sc} ({round(pr, 1)}%)" for sc, pr in sorted_sc[:6]]
            if "home" in p_obj and "away" in p_obj:
                win_probs = p_obj

        out.append({
            "source": "Sportmonks /predictions",
            "match": f"{home} vs {away}",
            "apiCorrectScorePredictions": scores_list or ["Not enabled on current Sportmonks plan"],
            "apiWinProbabilities": win_probs or "Not enabled on current plan",
            "kickoff_Nigeria": wat
        })
    return out


# 3. FOOTBALL-DATA.ORG — Direct Upcoming Fixtures
def fetch_football_data():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("Missing FOOTBALL_DATA_KEY")
    host = ".".join(["api", "football-data", "org"])
    matches = get_json(host, "/v4/matches?status=SCHEDULED", {"X-Auth-Token": key}).get("matches") or []
    out = []
    for m in matches:
        if len(out) >= LIMIT_PER_API:
            break
        wat = format_wat(m.get("utcDate", ""))
        if not wat:
            continue
        ho, ao = m.get("homeTeam") or {}, m.get("awayTeam") or {}
        out.append({
            "source": "Football-Data",
            "match": f"{ho.get('name', 'Home')} vs {ao.get('name', 'Away')}",
            "kickoff_Nigeria": wat
        })
    return out


# 4. GOAL-API — Direct Upcoming Fixtures
def fetch_goal_api():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("Missing GOAL_API_KEY")
    host = ".".join(["api", "goal-api", "com"])
    data = get_json(host, "/v1/fixtures?limit=25", {"Authorization": f"Bearer {key}"})
    raw = data if isinstance(data, list) else (data.get("data") or [])
    out = []
    for m in raw:
        if len(out) >= LIMIT_PER_API:
            break
        if str(m.get("matchStatus") or "").upper() in ("LIVE", "FT", "FINISHED", "HT", "1H", "2H"):
            continue
        wat = format_wat(m.get("kickoffUtc") or m.get("date") or "")
        if not wat:
            continue
        out.append({
            "source": "GOAL-API",
            "match": f"{m.get('homeTeamName', 'Home')} vs {m.get('awayTeamName', 'Away')}",
            "kickoff_Nigeria": wat
        })
    return out


def main():
    picks, status = [], {}
    for name, fn in [
        ("API-Football", fetch_api_football_predictions),
        ("Sportmonks", fetch_sportmonks_predictions),
        ("Football-Data", fetch_football_data),
        ("GOAL-API", fetch_goal_api)
    ]:
        try:
            r = fn()
            status[name] = f"OK ({len(r)})"
            picks.extend(r)
        except Exception as e:
            status[name] = str(e)[:100]

    with open("scores.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated_at_Nigeria": datetime.now(WAT_TZ).strftime("%Y-%m-%d %I:%M %p WAT"),
            "count": len(picks),
            "status": status,
            "picks": picks
        }, f, indent=2)


if __name__ == "__main__":
    main()
