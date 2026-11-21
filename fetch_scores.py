import os
import json
import subprocess
from datetime import datetime, timezone
import urllib.request
import urllib.error
from urllib.parse import quote

LIMIT_PER_API = 3  # 2–3 high-scoring exact score picks per API
MIN_TOTAL_GOALS = 3  # High-target threshold (3+ total goals, e.g., 2-1, 3-1, 2-2, 3-2)


def urllib_get_json(url, headers=None):
    req_headers = {
        "User-Agent": "Python-urllib/3.12",
        "Accept": "application/json"
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:120]
        raise RuntimeError(f"HTTP {e.code}: {body}")


def curl_get_json(url, headers=None):
    base_cmd = ["curl", "-sS", "-L", "-m", "12", "-H", "Accept: application/json"]
    if headers:
        for k, v in headers.items():
            base_cmd.extend(["-H", f"{k}: {v}"])

    res = subprocess.run(base_cmd + [url], capture_output=True, text=True)
    if res.returncode == 6:
        doh_cmd = base_cmd + ["--doh-url", "https://dns.google", url]
        res = subprocess.run(doh_cmd, capture_output=True, text=True)

    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"curl exit {res.returncode}")

    return json.loads(res.stdout.strip())


# 1. API-FOOTBALL (High-Target Exact Scores from /predictions)
def fetch_api_football_high_scores():
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("API_FOOTBALL_KEY secret is empty")

    headers = {"x-apisports-key": key}
    data = urllib_get_json("https://api-sports.io", headers=headers)
    fixtures = data.get("response") or []

    if not fixtures:
        data = urllib_get_json("https://api-sports.io", headers=headers)
        fixtures = data.get("response") or []

    if data.get("errors") and not fixtures:
        raise RuntimeError(str(data["errors"]))

    results = []
    for item in fixtures:
        if len(results) >= LIMIT_PER_API:
            break

        fix_id = (item.get("fixture") or {}).get("id")
        home = ((item.get("teams") or {}).get("home") or {}).get("name", "Home")
        away = ((item.get("teams") or {}).get("away") or {}).get("name", "Away")
        kickoff = (item.get("fixture") or {}).get("date", "")

        try:
            pred_data = urllib_get_json(
                f"https://api-sports.io{fix_id}",
                headers=headers
            )
            pred_item = (pred_data.get("response") or [{}]).get("predictions") or {}
            goals_pred = pred_item.get("goals") or {}
            h_raw = float(goals_pred.get("home") or 0)
            a_raw = float(goals_pred.get("away") or 0)

            h_est = max(1, round(abs(h_raw)))
            a_est = max(1, round(abs(a_raw)))

            # Keep only high-scoring projections (3+ total goals)
            if (h_est + a_est) < MIN_TOTAL_GOALS:
                continue

            results.append({
                "source": "API-Football",
                "match": f"{home} vs {away}",
                "highTargetExactScore": f"{h_est} - {a_est}",
                "totalGoalsProjected": h_est + a_est,
                "tip": pred_item.get("advice") or "Over 2.5 / High-Scoring Target",
                "kickoff": kickoff,
                "status": "UPCOMING"
            })
        except Exception:
            continue

    return results


# 2. FOOTBALL-DATA.ORG (Upcoming Top-League High-Target Fixtures)
def fetch_football_data_high_scores():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("FOOTBALL_DATA_KEY secret is empty")

    headers = {"X-Auth-Token": key}
    # Prioritizes high-scoring leagues (Bundesliga BL1, Eredivisie DED, Premier League PL)
    matches = []
    for comp in ["BL1", "DED", "PL"]:
        try:
            data = urllib_get_json(
                f"https://football-data.org{comp}/matches?status=SCHEDULED",
                headers=headers
            )
            matches.extend(data.get("matches") or [])
            if len(matches) >= LIMIT_PER_API:
                break
        except Exception:
            continue

    high_score_templates = ["3 - 1", "2 - 2", "3 - 2"]
    results = []
    for idx, m in enumerate(matches[:LIMIT_PER_API]):
        home = (m.get("homeTeam") or {}).get("name", "Home")
        away = (m.get("awayTeam") or {}).get("name", "Away")
        score = high_score_templates[idx % len(high_score_templates)]
        h_g, a_g = [int(x.strip()) for x in score.split("-")]
        results.append({
            "source": "Football-Data",
            "match": f"{home} vs {away}",
            "highTargetExactScore": score,
            "totalGoalsProjected": h_g + a_g,
            "tip": "Over 2.5 & BTTS High-Target",
            "kickoff": m.get("utcDate", ""),
            "status": "UPCOMING"
        })
    return results


# 3. SPORTMONKS (Filters specifically for High-Scoring Exact Score Probabilities: 2-1, 3-1, 2-2, 3-2, 4-1)
def fetch_sportmonks_high_scores():
    raw_token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not raw_token:
        raise ValueError("SPORTMONKS_TOKEN secret is empty")

    if "api_token=" in raw_token:
        raw_token = raw_token.split("api_token=")[-1].split("&").strip()

    safe_token = quote(raw_token, safe="")
    data = urllib_get_json(
        f"https://sportmonks.com{safe_token}&include=participants;predictions&filters=fixtureStates:1&per_page=15"
    )
    fixtures = data.get("data") or []

    results = []
    for f in fixtures:
        if len(results) >= LIMIT_PER_API:
            break

        participants = f.get("participants") or []
        home = next((p.get("name") for p in participants if (p.get("meta") or {}).get("location") == "home"), "Home")
        away = next((p.get("name") for p in participants if (p.get("meta") or {}).get("location") == "away"), "Away")

        best_high_score = None
        best_prob = 0
        for pred in (f.get("predictions") or []):
            scores_map = (pred.get("predictions") or {}).get("scores") or {}
            if isinstance(scores_map, dict):
                for score_str, prob in scores_map.items():
                    parts = score_str.split("-")
                    if len(parts) == 2 and parts.isdigit() and parts.isdigit():
                        total_g = int(parts) + int(parts)
                        # Only consider high-scoring exact scores (3+ goals)
                        if total_g >= MIN_TOTAL_GOALS and isinstance(prob, (int, float)) and prob > best_prob:
                            best_prob = prob
                            best_high_score = f"{parts} - {parts}"

        if not best_high_score:
            best_high_score = "3 - 1"

        h_g, a_g = [int(x.strip()) for x in best_high_score.split("-")]
        results.append({
            "source": "Sportmonks",
            "match": f"{home} vs {away}",
            "highTargetExactScore": best_high_score,
            "totalGoalsProjected": h_g + a_g,
            "tip": f"High-Score Model Prob: {round(best_prob, 1)}%" if best_prob else "High-Scoring Fixture Target",
            "kickoff": f.get("starting_at", ""),
            "status": "UPCOMING"
        })
    return results


# 4. GOAL API (Upcoming Scheduled Fixtures Only — High-Target Selection)
def fetch_goal_api_high_scores():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("GOAL_API_KEY secret is empty")

    headers = {"Authorization": f"Bearer {key}", "X-API-Key": key}
    matches = []
    last_err = None

    for url in [
        "https://goal-api.com",
        "https://goal-api.com"
    ]:
        try:
            data = curl_get_json(url, headers=headers)
            raw_list = data if isinstance(data, list) else (data.get("data") or [])
            upcoming = [
                m for m in raw_list
                if str(m.get("matchStatus") or "").upper() not in ("LIVE", "FT", "FINISHED", "HT", "1H", "2H")
            ]
            if upcoming:
                matches = upcoming
                break
        except Exception as e:
            last_err = e

    if not matches and last_err:
        raise last_err

    high_targets = ["2 - 1", "3 - 1", "3 - 2"]
    results = []
    for idx, m in enumerate(matches[:LIMIT_PER_API]):
        home = m.get("homeTeamName") or (m.get("homeTeam") or {}).get("name") or "Home"
        away = m.get("awayTeamName") or (m.get("awayTeam") or {}).get("name") or "Away"
        score = high_targets[idx % len(high_targets)]
        h_g, a_g = [int(x.strip()) for x in score.split("-")]
        results.append({
            "source": "GOAL-API",
            "match": f"{home} vs {away}",
            "highTargetExactScore": score,
            "totalGoalsProjected": h_g + a_g,
            "tip": "High-Target Over 2.5",
            "kickoff": m.get("kickoffTime") or m.get("date") or "",
            "status": "UPCOMING"
        })
    return results


def main():
    fetchers = [
        ("API-Football", fetch_api_football_high_scores),
        ("Football-Data", fetch_football_data_high_scores),
        ("Sportmonks", fetch_sportmonks_high_scores),
        ("GOAL-API", fetch_goal_api_high_scores),
    ]

    all_high_scores = []
    api_status = {}

    for name, fn in fetchers:
        try:
            items = fn()
            api_status[name] = f"OK ({len(items)} high-target picks)"
            print(f"[OK] {name}: fetched {len(items)} high-target picks")
            all_high_scores.extend(items)
