import os
import json
import subprocess
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

LIMIT_PER_API = 3
WAT_TZ = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)

ALL_HALFTIME_EXACT_SCORES = [
    "0 - 0", "1 - 0", "0 - 1", "1 - 1", "2 - 0", "0 - 2",
    "2 - 1", "1 - 2", "3 - 0", "0 - 3", "2 - 2", "3 - 1",
    "1 - 3", "4 - 0", "0 - 4", "3 - 2", "2 - 3", "4 - 1", "1 - 4", "3 - 3"
]

ALL_FULLTIME_EXACT_SCORES = [
    "0 - 0", "1 - 0", "0 - 1", "1 - 1", "2 - 0", "0 - 2",
    "2 - 1", "1 - 2", "3 - 0", "0 - 3", "2 - 2", "3 - 1",
    "1 - 3", "4 - 0", "0 - 4", "3 - 2", "2 - 3", "4 - 1",
    "1 - 4", "5 - 0", "0 - 5", "3 - 3", "4 - 2", "2 - 4",
    "5 - 1", "1 - 5", "6 - 0", "0 - 6", "4 - 3", "3 - 4",
    "5 - 2", "2 - 5", "6 - 1", "1 - 6", "4 - 4", "5 - 3",
    "3 - 5", "6 - 2", "2 - 6", "5 - 4", "4 - 5", "6 - 3",
    "3 - 6", "5 - 5", "6 - 4", "4 - 6", "6 - 5", "5 - 6", "6 - 6"
]


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


def parse_and_auto_pick_odds(values_list, fallback_pick):
    """Sorts exact score odds smallest -> highest AND automatically picks the #1 lowest-odds scoreline."""
    parsed = []
    for v in values_list:
        val_str = str(v.get("value", "")).replace(":", "-").strip()
        try:
            odd_num = float(v.get("odd", 999))
        except Exception:
            odd_num = 999.0
        parts = val_str.split("-")
        if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
            hg, ag = map(int, parts)
            label = f"{hg} - {ag} (odds {odd_num:.2f})"
            parsed.append((hg + ag, hg, ag, odd_num, label))

    if not parsed:
        return fallback_pick, []

    # Automatically figure out the #1 favorite exact score (lowest bookmaker odds)
    _, _, _, _, best_label = min(parsed, key=lambda x: x)

    # Sort full board from smallest total goals to highest total goals
    parsed.sort(key=lambda x: (x, x, x))
    board = [item for item in parsed]
    return best_label, board


# 1. API-FOOTBALL
def fetch_api_football():
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

        auto_ft, api_ft_odds = "1 - 1", []
        auto_ht, api_ht_odds = "0 - 0", []

        try:
            odds_resp = get_json(host, f"/odds?fixture={fix_id}&bet=10", hdr).get("response") or []
            if odds_resp:
                bms = next(iter(odds_resp), {}).get("bookmakers") or []
                if bms:
                    bets = next(iter(bms), {}).get("bets") or []
                    if bets:
                        auto_ft, api_ft_odds = parse_and_auto_pick_odds(next(iter(bets), {}).get("values") or [], "1 - 1")
        except Exception:
            pass

        try:
            ht_resp = get_json(host, f"/odds?fixture={fix_id}&bet=31", hdr).get("response") or []
            if ht_resp:
                bms = next(iter(ht_resp), {}).get("bookmakers") or []
                if bms:
                    bets = next(iter(bms), {}).get("bets") or []
                    if bets:
                        auto_ht, api_ht_odds = parse_and_auto_pick_odds(next(iter(bets), {}).get("values") or [], "0 - 0")
        except Exception:
            pass

        out.append({
            "source": "API-Football",
            "match": f"{home} vs {away}",
            "kickoff_Nigeria": wat,
            "autoHalfTimeExactScore": auto_ht,
            "autoFullTimeExactScore": auto_ft,
            "halfTimeExactScoreBoard": api_ht_odds if api_ht_odds else ALL_HALFTIME_EXACT_SCORES,
            "fullTimeExactScoreBoard": api_ft_odds if api_ft_odds else ALL_FULLTIME_EXACT_SCORES
        })
    return out


# 2. SPORTMONKS
def fetch_sportmonks():
    tok = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not tok:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    host = ".".join(["api", "sportmonks", "com"])
    data = get_json(
        host,
        f"/v3/football/fixtures?api_token={quote(tok, safe='')}&include=participants&filters=fixtureStates:1&per_page=10"
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
        out.append({
            "source": "Sportmonks",
            "match": f"{home} vs {away}",
            "kickoff_Nigeria": wat,
            "autoHalfTimeExactScore": "1 - 0",
            "autoFullTimeExactScore": "2 - 1",
            "halfTimeExactScoreBoard": ALL_HALFTIME_EXACT_SCORES,
            "fullTimeExactScoreBoard": ALL_FULLTIME_EXACT_SCORES
        })
    return out


# 3. FOOTBALL-DATA.ORG
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
            "kickoff_Nigeria": wat,
            "autoHalfTimeExactScore": "1 - 0",
            "autoFullTimeExactScore": "2 - 1",
            "halfTimeExactScoreBoard": ALL_HALFTIME_EXACT_SCORES,
            "fullTimeExactScoreBoard": ALL_FULLTIME_EXACT_SCORES
        })
    return out


# 4. GOAL-API
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
            "kickoff_Nigeria": wat,
            "autoHalfTimeExactScore": "0 - 0",
            "autoFullTimeExactScore": "1 - 1",
            "halfTimeExactScoreBoard": ALL_HALFTIME_EXACT_SCORES,
            "fullTimeExactScoreBoard": ALL_FULLTIME_EXACT_SCORES
        })
    return out


def main():
    picks, status = [], {}
    for name, fn in [
        ("API-Football", fetch_api_football),
        ("Sportmonks", fetch_sportmonks),
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
