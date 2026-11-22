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


def pick_single_best_odd(values_list):
    """Returns ONLY the single #1 lowest-odds exact scoreline (e.g. '1 - 0') with zero extra options."""
    best_odd = 9999.0
    best_score = "unavailable"
    for v in values_list:
        val_str = str(v.get("value", "")).replace(":", "-").strip()
        try:
            odd_num = float(v.get("odd", 9999))
        except Exception:
            odd_num = 9999.0
        parts = val_str.split("-")
        if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
            hg, ag = map(int, parts)
            if odd_num < best_odd:
                best_odd = odd_num
                best_score = f"{hg} - {ag}"
    return best_score


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

        ht_score = "unavailable"
        ft_score = "unavailable"

        try:
            odds_resp = get_json(host, f"/odds?fixture={fix_id}&bet=10", hdr).get("response") or []
            if odds_resp:
                bms = next(iter(odds_resp), {}).get("bookmakers") or []
                if bms:
                    bets = next(iter(bms), {}).get("bets") or []
                    if bets:
                        ft_score = pick_single_best_odd(next(iter(bets), {}).get("values") or [])
        except Exception:
            pass

        try:
            ht_resp = get_json(host, f"/odds?fixture={fix_id}&bet=31", hdr).get("response") or []
            if ht_resp:
                bms = next(iter(ht_resp), {}).get("bookmakers") or []
                if bms:
                    bets = next(iter(bms), {}).get("bets") or []
                    if bets:
                        ht_score = pick_single_best_odd(next(iter(bets), {}).get("values") or [])
        except Exception:
            pass

        out.append({
            "source": "API-Football",
            "match": f"{home} vs {away}",
            "kickoff_Nigeria": wat,
            "halfTimeExactScore": ht_score,
            "fullTimeExactScore": ft_score
        })
    return out


# 2. SPORTMONKS
def fetch_sportmonks():
    tok = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not tok:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    host = ".".join(["api", "sportmonks", "com"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Try with predictions first; fallback to participants only if free plan blocks predictions
    data = get_json(
        host,
        f"/v3/football/fixtures/date/{today}?api_token={quote(tok, safe='')}&include=participants;predictions&per_page=25"
    )
    fixtures = data.get("data") or []
    if not fixtures:
        data = get_json(
            host,
            f"/v3/football/fixtures/date/{today}?api_token={quote(tok, safe='')}&include=participants&per_page=25"
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

        ft_score = "unavailable"
        best_prob = -1.0
        for pred in (f.get("predictions") or []):
            scores_map = (pred.get("predictions") or {}).get("scores")
            if isinstance(scores_map, dict):
                for sc, pr in scores_map.items():
                    pts = str(sc).split("-")
                    if len(pts) == 2 and all(x.strip().isdigit() for x in pts) and isinstance(pr, (int, float)):
                        hg, ag = map(int, pts)
                        if pr > best_prob:
                            best_prob = pr
                            ft_score = f"{hg} - {ag}"

        out.append({
            "source": "Sportmonks",
            "match": f"{home} vs {away}",
            "kickoff_Nigeria": wat,
            "halfTimeExactScore": "unavailable",
            "fullTimeExactScore": ft_score
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
            "halfTimeExactScore": "unavailable",
            "fullTimeExactScore": "unavailable"
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
            "halfTimeExactScore": "unavailable",
            "fullTimeExactScore": "unavailable"
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
            "updated_at_Nigeria": datetime.now(WAT_TZ).strftime("%Y-%m-%d %I:%M %p WAT"),
            "count": len(picks),
            "status": status,
            "picks": picks
        }, f, indent=2)


if __name__ == "__main__":
    main()
