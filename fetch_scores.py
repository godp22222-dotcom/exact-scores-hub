import os
import json
import ssl
import socket
from datetime import datetime, timezone
import urllib.request
import urllib.error

LIMIT_PER_API = 3  # Gets 2–3 exact scores from each API
TIMEOUT_SEC = 12


# Bypass runner DNS issues using Google DNS-over-HTTPS (8.8.8.8)
def resolve_ip_via_google_doh(hostname):
    doh_url = f"https://8.8.8{hostname}&type=A"
    req = urllib.request.Request(doh_url, headers={"Accept": "application/dns-json"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        for ans in data.get("Answer", []):
            if ans.get("type") == 1:
                return ans["data"]
    raise RuntimeError(f"Could not resolve {hostname}")


_DNS_CACHE = {}
_ORIG_CREATE_CONNECTION = socket.create_connection


def _doh_create_connection(address, *args, **kwargs):
    host, port = address
    if host not in ("8.8.8.8", "1.1.1.1") and not host.replace(".", "").isdigit():
        if host not in _DNS_CACHE:
            _DNS_CACHE[host] = resolve_ip_via_google_doh(host)
        address = (_DNS_CACHE[host], port)
    return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)


socket.create_connection = _doh_create_connection


def safe_get_json(url, headers=None):
    req_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ExactScoresHub/1.0)",
        "Accept": "application/json"
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:120]
        raise RuntimeError(f"HTTP {e.code}: {body}")


# 1. API-FOOTBALL (No date filter: tries live matches, falls back to Premier League latest)
def fetch_api_football():
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("API_FOOTBALL_KEY missing")

    headers = {"x-apisports-key": key}
    data = safe_get_json("https://api-sports.io", headers=headers)
    items = data.get("response") or []

    # Fallback if no live games or free-tier restriction: pull general fixtures without date
    if not items:
        data = safe_get_json("https://api-sports.io", headers=headers)
        items = data.get("response") or []

    if data.get("errors") and not items:
        raise ValueError(str(data["errors"]))

    results = []
    for item in items[:LIMIT_PER_API]:
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        status = (item.get("fixture") or {}).get("status") or {}
        results.append({
            "source": "API-Football",
            "match": f"{(teams.get('home') or {}).get('name', 'Home')} vs {(teams.get('away') or {}).get('name', 'Away')}",
            "exactScore": f"{goals.get('home') if goals.get('home') is not None else 0} - {goals.get('away') if goals.get('away') is not None else 0}",
            "status": status.get("short", "FT")
        })
    return results


# 2. FOOTBALL-DATA.ORG (No date filter: default /v4/matches returns active window automatically)
def fetch_football_data():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("FOOTBALL_DATA_KEY missing")

    headers = {"X-Auth-Token": key}
    data = safe_get_json("https://football-data.org", headers=headers)
    matches = data.get("matches") or []

    # Fallback to Premier League (PL) matches without date filter
    if not matches:
        data = safe_get_json("https://football-data.org", headers=headers)
        matches = data.get("matches") or []

    results = []
    for m in matches[:LIMIT_PER_API]:
        home = (m.get("homeTeam") or {}).get("name", "Home")
        away = (m.get("awayTeam") or {}).get("name", "Away")
        ft = (m.get("score") or {}).get("fullTime") or {}
        results.append({
            "source": "Football-Data",
            "match": f"{home} vs {away}",
            "exactScore": f"{ft.get('home') if ft.get('home') is not None else 0} - {ft.get('away') if ft.get('away') is not None else 0}",
            "status": m.get("status", "FINISHED")
        })
    return results


# 3. SPORTMONKS (No date filter: tries livescores, falls back to general fixtures)
def fetch_sportmonks():
    token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not token:
        raise ValueError("SPORTMONKS_TOKEN missing")

    data = safe_get_json(
        f"https://sportmonks.com{token}&include=scores;participants"
    )
    fixtures = data.get("data") or []

    # Fallback to general fixtures without date filter
    if not fixtures:
        data = safe_get_json(
            f"https://sportmonks.com{token}&include=scores;participants&per_page={LIMIT_PER_API}"
        )
        fixtures = data.get("data") or []

    results = []
    for f in fixtures[:LIMIT_PER_API]:
        participants = f.get("participants") or []
        scores = f.get("scores") or []

        home = next((p.get("name") for p in participants if (p.get("meta") or {}).get("location") == "home"), "Home")
        away = next((p.get("name") for p in participants if (p.get("meta") or {}).get("location") == "away"), "Away")

        home_goals = next(
            ((s.get("score") or {}).get("goals") for s in scores
             if s.get("description") in ("CURRENT", "2ND_HALF") and (s.get("score") or {}).get("participant") == "home"),
            0
        )
        away_goals = next(
            ((s.get("score") or {}).get("goals") for s in scores
             if s.get("description") in ("CURRENT", "2ND_HALF") and (s.get("score") or {}).get("participant") == "away"),
            0
        )

        results.append({
            "source": "Sportmonks",
            "match": f"{home} vs {away}",
            "exactScore": f"{home_goals if home_goals is not None else 0} - {away_goals if away_goals is not None else 0}",
            "status": str(f.get("state_id", "LIVE"))
        })
    return results


# 4. GOAL API (No date filter: tries live fixtures, falls back to general fixtures)
def fetch_goal_api():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("GOAL_API_KEY missing")

    headers = {"Authorization": f"Bearer {key}"}
    matches = []
    last_err = None

    for url in [
        f"https://goal-api.com{LIMIT_PER_API}",
        f"https://goal-api.com{LIMIT_PER_API}"
    ]:
        try:
            data = safe_get_json(url, headers=headers)
            matches = data if isinstance(data, list) else (data.get("data") or [])
            if matches:
                break
        except Exception as e:
            last_err = e

    if not matches and last_err:
        raise last_err

    results = []
    for m in matches[:LIMIT_PER_API]:
        home = m.get("homeTeamName") or (m.get("homeTeam") or {}).get("name") or "Home"
        away = m.get("awayTeamName") or (m.get("awayTeam") or {}).get("name") or "Away"
        hs = m.get("homeTeamScore") if m.get("homeTeamScore") is not None else (m.get("homeScore") if m.get("homeScore") is not None else 0)
        aws = m.get("awayTeamScore") if m.get("awayTeamScore") is not None else (m.get("awayScore") if m.get("awayScore") is not None else 0)
        results.append({
            "source": "GOAL-API",
            "match": f"{home} vs {away}",
            "exactScore": f"{hs} - {aws}",
            "status": m.get("matchStatus") or "LIVE"
        })
    return results


def main():
    fetchers = [
        ("API-Football", fetch_api_football),
        ("Football-Data", fetch_football_data),
        ("Sportmonks", fetch_sportmonks),
        ("GOAL-API", fetch_goal_api),
    ]

    all_scores = []
    for name, fn in fetchers:
        try:
            items = fn()
            print(f"[OK] {name}: fetched {len(items)} matches")
            all_scores.extend(items)
        except Exception as e:
            print(f"[Skipped] {name}: {e}")

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_scores),
        "matches": all_scores
    }

    with open("scores.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(all_scores)} total exact scores to scores.json")


if __name__ == "__main__":
    main()
