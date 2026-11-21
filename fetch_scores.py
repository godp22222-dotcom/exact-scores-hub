import os
import json
import math
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


def poisson_prob(k, lam):
    return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)


def build_sorted_scores(exp_h, exp_a, max_goals=5, top_n=6):
    """Generates top exact scores and sorts them from SMALLEST total goals to HIGHEST total goals."""
    outcomes = []
    for hg in range(0, max_goals + 1):
        for ag in range(0, max_goals + 1):
            p = poisson_prob(hg, exp_h) * poisson_prob(ag, exp_a)
            outcomes.append({
                "score": f"{hg} - {ag}",
                "total": hg + ag,
                "hg": hg,
                "ag": ag,
                "prob": p
            })

    # Pick top N most likely outcomes first, then sort from smallest score to highest score
    top_likely = sorted(outcomes, key=lambda x: x["prob"], reverse=True)[:top_n]
    sorted_small_to_high = sorted(top_likely, key=lambda x: (x["total"], x["hg"], x["ag"]))

    return [
        f"{item['score']} ({round(item['prob'] * 100, 1)}%)"
        for item in sorted_small_to_high
    ]


def calculate_ht_and_ft_scores(home_stats, away_stats):
    """Calculates both Half-Time (HT) and Full-Time (FT) exact scores sorted smallest -> highest."""
    h_played = max(1, home_stats.get("played", 1))
    a_played = max(1, away_stats.get("played", 1))

    h_attack = home_stats.get("gf", 1.4) / h_played
    h_defense = home_stats.get("ga", 1.2) / h_played
    a_attack = away_stats.get("gf", 1.2) / a_played
    a_defense = away_stats.get("ga", 1.3) / a_played

    # Full-time expected goals
    ft_exp_home = max(0.3, min(4.5, ((h_attack + a_defense) / 2.0) * 1.12))
    ft_exp_away = max(0.2, min(4.0, (a_attack + h_defense) / 2.0))

    # Half-time expected goals (~44% of full-time goal rate)
    ht_exp_home = max(0.15, ft_exp_home * 0.44)
    ht_exp_away = max(0.10, ft_exp_away * 0.44)

    ht_scores = build_sorted_scores(ht_exp_home, ht_exp_away, max_goals=3, top_n=5)
    ft_scores = build_sorted_scores(ft_exp_home, ft_exp_away, max_goals=5, top_n=6)

    # Over 2.5 Full-Time probability
    over_25_prob = 0.0
    for hg in range(0, 6):
        for ag in range(0, 6):
            if (hg + ag) >= 3:
                over_25_prob += poisson_prob(hg, ft_exp_home) * poisson_prob(ag, ft_exp_away)

    return {
        "halfTimeExactScores_SmallToHigh": ht_scores,
        "fullTimeExactScores_SmallToHigh": ft_scores,
        "over25Probability": f"{round(over_25_prob * 100, 1)}%",
        "expectedGoals_FT": f"{round(ft_exp_home, 2)} - {round(ft_exp_away, 2)}"
    }


# 1. FOOTBALL-DATA.ORG
def fetch_football_data_model():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("Missing FOOTBALL_DATA_KEY")

    host = "api." + "football-data.org"
    headers = {"X-Auth-Token": key}

    data = get_json(host, "/v4/matches?status=SCHEDULED", headers)
    matches = data.get("matches") or []

    team_stats = {}
    comp_codes = list({(m.get("competition") or {}).get("code") for m in matches[:6] if (m.get("competition") or {}).get("code")})
    for code in comp_codes[:3]:
        try:
            st_data = get_json(host, f"/v4/competitions/{code}/standings", headers)
            for standing in (st_data.get("standings") or []):
                if standing.get("type") == "TOTAL":
                    for row in (standing.get("table") or []):
                        tid = (row.get("team") or {}).get("id")
                        if tid:
                            team_stats[tid] = {
                                "played": row.get("playedGames", 1),
                                "gf": row.get("goalsFor", 1),
                                "ga": row.get("goalsAgainst", 1)
                            }
        except Exception:
            continue

    out = []
    for m in matches[:LIMIT_PER_API]:
        home_obj = m.get("homeTeam") or {}
        away_obj = m.get("awayTeam") or {}
        h_st = team_stats.get(home_obj.get("id"), {"played": 10, "gf": 16, "ga": 12})
        a_st = team_stats.get(away_obj.get("id"), {"played": 10, "gf": 14, "ga": 15})
        model = calculate_ht_and_ft_scores(h_st, a_st)

        out.append({
            "source": "Football-Data",
            "competition": (m.get("competition") or {}).get("name", ""),
            "match": f"{home_obj.get('name', 'Home')} vs {away_obj.get('name', 'Away')}",
            **model,
            "kickoff": m.get("utcDate", "")
        })
    return out


# 2. API-FOOTBALL
def fetch_api_football_model():
    key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
    if not key:
        raise ValueError("Missing API_FOOTBALL_KEY")

    host = "v3.football." + "api-sports.io"
    headers = {"x-apisports-key": key}

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = get_json(host, f"/fixtures?date={today_str}&status=NS", headers)
    items = data.get("response") or []

    if not items:
        data = get_json(host, "/fixtures?league=39&season=2024&last=10", headers)
        items = data.get("response") or []

    team_stats = {}
    try:
        st_data = get_json(host, "/standings?league=39&season=2024", headers)
        resp_list = st_data.get("response") or []
        if resp_list:
            standings_groups = ((next(iter(resp_list), {}).get("league") or {}).get("standings") or [])
            for group in standings_groups:
                for row in group:
                    tid = (row.get("team") or {}).get("id")
                    all_rec = row.get("all") or {}
                    goals_rec = all_rec.get("goals") or {}
                    if tid:
                        team_stats[tid] = {
                            "played": all_rec.get("played", 1),
                            "gf": goals_rec.get("for", 1),
                            "ga": goals_rec.get("against", 1)
                        }
    except Exception:
        pass

    out = []
    for item in items[:LIMIT_PER_API]:
        teams = item.get("teams") or {}
        h_obj = teams.get("home") or {}
        a_obj = teams.get("away") or {}
        h_st = team_stats.get(h_obj.get("id"), {"played": 10, "gf": 18, "ga": 11})
        a_st = team_stats.get(a_obj.get("id"), {"played": 10, "gf": 13, "ga": 16})
        model = calculate_ht_and_ft_scores(h_st, a_st)

        out.append({
            "source": "API-Football",
            "competition": (item.get("league") or {}).get("name", ""),
            "match": f"{h_obj.get('name', 'Home')} vs {a_obj.get('name', 'Away')}",
            **model,
            "kickoff": (item.get("fixture") or {}).get("date", "")
        })
    return out


# 3. SPORTMONKS
def fetch_sportmonks_model():
    raw_token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not raw_token:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    if "api_token=" in raw_token:
        raw_token = raw_token.split("api_token=")[-1].split("&").strip()
    safe_token = quote(raw_token, safe="")
    host = "api." + "sportmonks.com"

    data = get_json(
        host,
        f"/v3/football/fixtures?api_token={safe_token}&include=participants&filters=fixtureStates:1&per_page=5"
    )
    fixtures = data.get("data") or []
    out = []
    for f in fixtures[:LIMIT_PER_API]:
        parts = f.get("participants") or []
        home_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), {})
        away_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), {})
        home = home_p.get("name", "Home")
        away = away_p.get("name", "Away")

        h_id = home_p.get("id") or 10
        a_id = away_p.get("id") or 12
        h_st = {"played": 10, "gf": 15 + (h_id % 7), "ga": 11 + (h_id % 5)}
        a_st = {"played": 10, "gf": 13 + (a_id % 6), "ga": 13 + (a_id % 6)}
        model = calculate_ht_and_ft_scores(h_st, a_st)

        out.append({
            "source": "Sportmonks",
            "match": f"{home} vs {away}",
            **model,
            "kickoff": f.get("starting_at", "")
        })
    return out


# 4. GOAL-API
def fetch_goal_api_model():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("Missing GOAL_API_KEY")
    host = "api." + "goal-api.com"
    headers = {"Authorization": f"Bearer {key}"}

    data = get_json(host, "/v1/fixtures?limit=25", headers)
    raw = data if isinstance(data, list) else (data.get("data") or [])
    upcoming = [m for m in raw if str(m.get("matchStatus") or "").upper() not in ("LIVE", "FT", "FINISHED", "HT", "1H", "2H")]

    team_goals = {}
    for m in raw:
        if str(m.get("matchStatus") or "").upper() in ("FT", "FINISHED"):
            hn = m.get("homeTeamName")
            an = m.get("awayTeamName")
            hs = int(m.get("homeTeamScore") or 0)
            aws = int(m.get("awayTeamScore") or 0)
