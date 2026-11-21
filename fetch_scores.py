import os
import json
from datetime import datetime, timezone
import urllib.request
import urllib.error

LIMIT_PER_API = 3
TIMEOUT_SEC = 12


def get_today_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


# 1. API-FOOTBALL
def fetch_api_football(today):
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("API_FOOTBALL_KEY missing")

    url = f"https://api-sports.io{today}"
    data = safe_get_json(url, headers={"x-apisports-key": key})

    if data.get("errors"):
        raise ValueError(str(data["errors"]))

    results = []
    for item in (data.get("response") or [])[:LIMIT_PER_API]:
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        status = (item.get("fixture") or {}).get("status") or {}
        results.append({
            "source": "API-Football",
            "date": today,
            "match": f"{(teams.get('home') or {}).get('name', 'Home')} vs {(teams.get('away') or {}).get('name', 'Away')}",
            "exactScore": f"{goals.get('home') if goals.get('home') is not None else 0} - {goals.get('away') if goals.get('away') is not None else 0}",
            "status": status.get("short", "NS")
        })
    return results


# 2. FOOTBALL-DATA.ORG
def fetch_football_data(today):
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("FOOTBALL_DATA_KEY missing")

    url = f"https://football-data.org{today}&dateTo={today}"
    data = safe_get_json(url, headers={"X-Auth-Token": key})

    results = []
    for m in (data.get("matches") or [])[:LIMIT_PER_API]:
        home = (m.get("homeTeam") or {}).get("name", "Home")
        away = (m.get("awayTeam") or {}).get("name", "Away")
        ft = (m.get("score") or {}).get("fullTime") or {}
        results.append({
            "source": "Football-Data",
            "date": today,
            "match": f"{home} vs {away}",
            "exactScore": f"{ft.get('home') if ft.get('home') is not None else 0} - {ft.get('away') if ft.get('away') is not None else 0}",
            "status": m.get("status", "SCHEDULED")
        })
    return results


# 3. SPORTMONKS
def fetch_sportmonks(today):
    token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not token:
        raise ValueError("SPORTMONKS_TOKEN missing")

    url = f"https://sportmonks.com{today}?api_token={token}&include=scores;participants"
    data = safe_get_json(url)

    results = []
    for f in (data.get("data") or [])[:LIMIT_PER_API]:
        participants = f.get("participants") or []
        scores = f.get("scores") or []

        home = next((p.get("name") for p in participants if (p.get("meta") or {}).get("location") == "home"), "Home")
        away = next((p.get("name") for p in participants if (p.get("meta") or {}).get("location") == "away"), "Away")

        home_goals = next(
            ((s.get("score") or {}).get("goals") for s in scores
             if s.get("description") == "CURRENT" and (s.get("score") or {}).get("participant") == "home"),
            0
        )
        away_goals = next(
            ((s.get("score") or {}).get("goals") for s in scores
             if s.get("description") == "CURRENT" and (s.get("score") or {}).get("participant") == "away"),
            0
        )

        results.append({
            "source": "Sportmonks",
            "date": today,
            "match": f"{home} vs {away}",
            "exactScore": f"{home_goals if home_goals is not None else 0} - {away_goals if away_goals is not None else 0}",
            "status": str(f.get("state_id", "LIVE"))
        })
    return results


# 4. GOAL API
def fetch_goal_api(today):
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("GOAL_API_KEY missing")

    # Tries primary GOAL API host
    data = None
    last_err = None
    for base_url in ["https://goal-api.com", "https://goal-api.com"]:
        try:
            data = safe_get_json(f"{base_url}?date={today}", headers={"Authorization": f"Bearer {key}", "X-API-Key": key})
            break
        except Exception as e:
            last_err = e

    if data is None:
        raise last_err

    matches = data if isinstance(data, list) else (data.get("data") or data.get("matches") or [])
    results = []
    for m in matches[:LIMIT_PER_API]:
        home = m.get("home_team") or m.get("homeTeam") or "Home"
        away = m.get("away_team") or m.get("awayTeam") or "Away"
        hs = m.get("home_score") if m.get("home_score") is not None else 0
        aws = m.get("away_score") if m.get("away_score") is not None else 0
        results.append({
            "source": "GOAL-API",
            "date": today,
            "match": f"{home} vs {away}",
            "exactScore": f"{hs} - {aws}",
            "status": m.get("status", "SCHEDULED")
        })
    return results


def main():
    today = get_today_date()
    fetchers = [
        ("API-Football", fetch_api_football),
        ("Football-Data", fetch_football_data),
        ("Sportmonks", fetch_sportmonks),
        ("GOAL-API", fetch_goal_api),
    ]

    all_scores = []
    for name, fn in fetchers:
        try:
            items = fn(today)
            print(f"[OK] {name}: fetched {len(items)} matches")
            all_scores.extend(items)
        except Exception as e:
            print(f"[Skipped] {name}: {e}")

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "count": len(all_scores),
        "matches": all_scores
    }

    with open("scores.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(all_scores)} total exact scores to scores.json")


if __name__ == "__main__":
    main()
