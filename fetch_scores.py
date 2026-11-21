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


def calculate_poisson_exact_score(home_stats, away_stats):
    """Calculates real statistical exact score & over 2.5 probability from team goal averages."""
    h_played = max(1, home_stats.get("played", 1))
    a_played = max(1, away_stats.get("played", 1))

    # Team attack & defense rates per game + slight home advantage factor (1.12)
    h_attack = home_stats.get("gf", 1.4) / h_played
    h_defense = home_stats.get("ga", 1.2) / h_played
    a_attack = away_stats.get("gf", 1.2) / a_played
    a_defense = away_stats.get("ga", 1.3) / a_played

    exp_home = max(0.3, min(4.5, ((h_attack + a_defense) / 2.0) * 1.12))
    exp_away = max(0.2, min(4.0, (a_attack + h_defense) / 2.0))

    best_score = "1 - 1"
    best_prob = 0.0
    over_25_prob = 0.0

    for hg in range(0, 6):
        for ag in range(0, 6):
            p = poisson_prob(hg, exp_home) * poisson_prob(ag, exp_away)
            if (hg + ag) >= 3:
                over_25_prob += p
            if p > best_prob:
                best_prob = p
                best_score = f"{hg} - {ag}"

    return {
        "projectedExactScore": best_score,
        "scoreProbability": f"{round(best_prob * 100, 1)}%",
        "over25Probability": f"{round(over_25_prob * 100, 1)}%",
        "expectedGoals": f"{round(exp_home, 2)} - {round(exp_away, 2)}"
    }


# 1. FOOTBALL-DATA.ORG (Real Standings Stats + Poisson Exact Score Model)
def fetch_football_data_model():
    key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
    if not key:
        raise ValueError("Missing FOOTBALL_DATA_KEY")

    host = "api." + "football-data.org"
    headers = {"X-Auth-Token": key}

    # Fetch upcoming scheduled matches
    data = get_json(host, "/v4/matches?status=SCHEDULED", headers)
    matches = data.get("matches") or []

    # Build real team goal stats dictionary from league standings
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
        h_id = home_obj.get("id")
        a_id = away_obj.get("id")

        h_st = team_stats.get(h_id, {"played": 10, "gf": 15, "ga": 11})
        a_st = team_stats.get(a_id, {"played": 10, "gf": 13, "ga": 14})
        model = calculate_poisson_exact_score(h_st, a_st)

        out.append({
            "source": "Football-Data (Poisson Stat Model)",
            "competition": (m.get("competition") or {}).get("name", ""),
            "match": f"{home_obj.get('name', 'Home')} vs {away_obj.get('name', 'Away')}",
            "projectedExactScore": model["projectedExactScore"],
            "scoreProbability": model["scoreProbability"],
            "over25Probability": model["over25Probability"],
            "expectedGoals": model["expectedGoals"],
            "kickoff": m.get("utcDate", "")
        })
    return out


# 2. SPORTMONKS (Upcoming Fixtures — Excludes Live Matches)
def fetch_sportmonks_upcoming():
    raw_token = (os.getenv("SPORTMONKS_TOKEN") or "").strip()
    if not raw_token:
        raise ValueError("Missing SPORTMONKS_TOKEN")
    if "api_token=" in raw_token:
        raw_token = raw_token.split("api_token=")[-1].split("&").strip()
    safe_token = quote(raw_token, safe="")
    host = "api." + "sportmonks.com"

    data = get_json(host, f"/v3/football/fixtures?api_token={safe_token}&include=participants&filters=fixtureStates:1&per_page=5")
    fixtures = data.get("data") or []
    out = []
    for f in fixtures[:LIMIT_PER_API]:
        parts = f.get("participants") or []
        home = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "home"), "Home")
        away = next((p.get("name") for p in parts if (p.get("meta") or {}).get("location") == "away"), "Away")
        out.append({
            "source": "Sportmonks (Upcoming Fixture)",
            "match": f"{home} vs {away}",
            "kickoff": f.get("starting_at", "")
        })
    return out


# 3. GOAL-API (Upcoming Fixtures — Excludes Live Matches)
def fetch_goal_api_upcoming():
    key = (os.getenv("GOAL_API_KEY") or "").strip()
    if not key:
        raise ValueError("Missing GOAL_API_KEY")
    host = "api." + "goal-api.com"
    data = get_json(host, "/v1/fixtures?limit=20", {"Authorization": f"Bearer {key}"})
    raw = data if isinstance(data, list) else (data.get("data") or [])
    upcoming = [m for m in raw if str(m.get("matchStatus") or "").upper() not in ("LIVE", "FT", "FINISHED", "HT", "1H", "2H")]
    out = []
    for m in upcoming[:LIMIT_PER_API]:
        home = m.get("homeTeamName") or "Home"
        away = m.get("awayTeamName") or "Away"
        out.append({
            "source": "GOAL-API (Upcoming Fixture)",
            "league": m.get("leagueName", ""),
            "match": f"{home} vs {away}",
            "kickoff": m.get("kickoffUtc") or m.get("date") or ""
        })
    return out


def main():
    all_items = []
    status = {}
    for name, fn in [
        ("Football-Data-Model", fetch_football_data_model),
        ("Sportmonks", fetch_sportmonks_upcoming),
        ("GOAL-API", fetch_goal_api_upcoming)
    ]:
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
            "picks": all_items
        }, f, indent=2)


if __name__ == "__main__":
    main()
