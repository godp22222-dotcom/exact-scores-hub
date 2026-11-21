import os
import json
import subprocess
from datetime import datetime, timezone

LIMIT_PER_API = 3  # Gets 2–3 exact scores from each API


def curl_get_json(url, headers=None):
    """Fetches JSON using curl, automatically falling back to Google DNS-over-HTTPS if runner DNS fails."""
    base_cmd = ["curl", "-sS", "-L", "-m", "12", "-H", "Accept: application/json"]
    if headers:
        for k, v in headers.items():
            base_cmd.extend(["-H", f"{k}: {v}"])

    # 1. Try normal request
    res = subprocess.run(base_cmd + [url], capture_output=True, text=True)

    # 2. If DNS failed (curl exit code 6), retry using Google DNS-over-HTTPS
    if res.returncode == 6:
        doh_cmd = base_cmd + ["--doh-url", "https://dns.google", url]
        res = subprocess.run(doh_cmd, capture_output=True, text=True)

    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"curl exit {res.returncode}")

    body = res.stdout.strip()
    if not body:
        raise RuntimeError("Empty response from API")

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError(f"Non-JSON response: {body[:100]}")


# 1. API-FOOTBALL
def fetch_api_football():
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("API_FOOTBALL_KEY secret is empty")

    headers = {"x-apisports-key": key}
    data = curl_get_json("https://api-sports.io", headers=headers)
    items = data.get("response") or []

    if not items:
        data = curl_get_json("https://api-sports.io", headers=headers)
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


# 2. FOOTBALL-DATA.ORG
def fetch_football_data():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("FOOTBALL_DATA_KEY secret is empty")

    headers = {"X-Auth-Token": key}
    data = curl_get_json("https://football-data.org", headers=headers)

    if data.get("message") and not data.get("matches"):
        raise ValueError(data["message"])

    matches = data.get("matches") or []
    if not matches:
        data = curl_get_json("https://football-data.org", headers=headers)
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


# 3. SPORTMONKS
def fetch_sportmonks():
    token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not token:
        raise ValueError("SPORTMONKS_TOKEN secret is empty")

    data = curl_get_json(
        f"https://sportmonks.com{token}&include=scores;participants"
    )
    if data.get("message") and not data.get("data"):
        raise ValueError(data["message"])

    fixtures = data.get("data") or []
    if not fixtures:
        data = curl_get_json(
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


# 4. GOAL API
def fetch_goal_api():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("GOAL_API_KEY secret is empty")

    headers = {"Authorization": f"Bearer {key}", "X-API-Key": key}
    matches = []
    last_err = None

    for url in [
        "https://api.goal-api.com/v1/fixtures/live",
        "https://api.goal-api.com/v1/matches",
        "https://goal-api.com"
    ]:
        try:
            data = curl_get_json(url, headers=headers)
            if isinstance(data, dict) and data.get("error"):
                last_err = RuntimeError(str(data["error"]))
                continue
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
    api_status = {}

    for name, fn in fetchers:
        try:
            items = fn()
            api_status[name] = f"OK ({len(items)} matches)"
            print(f"[OK] {name}: fetched {len(items)} matches")
            all_scores.extend(items)
        except Exception as e:
            api_status[name] = f"Skipped: {e}"
            print(f"[Skipped] {name}: {e}")

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_scores),
        "api_status": api_status,
        "matches": all_scores
    }

    with open("scores.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(all_scores)} total exact scores to scores.json")


if __name__ == "__main__":
    main()
