import os
import json
import math
from datetime import datetime, timezone, timedelta
import requests

API_KEY = os.environ.get("FOOTBALL_DATA_KEY")
BASE_URL = "https://football-data.org"
HEADERS = {"X-Auth-Token": API_KEY}

now_utc = datetime.now(timezone.utc)
date_from = now_utc.strftime("%Y-%m-%d")
date_to = (now_utc + timedelta(days=2)).strftime("%Y-%m-%d")

def poisson_prob(k, lam):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)

def get_team_stats(comp_code, cache):
    """Fetch league standings once per competition to calculate real attack/defense strength."""
    if comp_code in cache:
        return cache[comp_code]
    
    stats = {}
    try:
        res = requests.get(f"{BASE_URL}/competitions/{comp_code}/standings", headers=HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            for standing in data.get("standings", []):
                if standing.get("type") == "TOTAL":
                    for row in standing.get("table", []):
                        team_id = row["team"]["id"]
                        played = max(row.get("playedGames", 1), 1)
                        gf = row.get("goalsFor", 1.3 * played)
                        ga = row.get("goalsAgainst", 1.3 * played)
                        stats[team_id] = {
                            "avg_gf": gf / played,
                            "avg_ga": ga / played
                        }
    except Exception:
        pass
    
    cache[comp_code] = stats
    return stats

def predict_scores(home_id, away_id, comp_stats):
    """Generate Halftime, Full-Time, High Scores, and All Exact Score predictions using colon format (e.g. 1:0, 2:1)."""
    h_stat = comp_stats.get(home_id, {"avg_gf": 1.45, "avg_ga": 1.25})
    a_stat = comp_stats.get(away_id, {"avg_gf": 1.15, "avg_ga": 1.35})

    # Expected Full-Time goals (with slight home advantage)
    exp_home_ft = max(0.35, min(3.8, ((h_stat["avg_gf"] + a_stat["avg_ga"]) / 2) * 1.12))
    exp_away_ft = max(0.25, min(3.5, ((a_stat["avg_gf"] + h_stat["avg_ga"]) / 2) * 0.92))

    # Expected Halftime goals (~44% of full-time goals occur in the first half)
    exp_home_ht = exp_home_ft * 0.44
    exp_away_ht = exp_away_ft * 0.44

    # 1. Full-Time Exact Score Matrix (0:0 up to 5:5)
    ft_matrix = []
    for h in range(6):
        for a in range(6):
            prob = poisson_prob(h, exp_home_ft) * poisson_prob(a, exp_away_ft)
            ft_matrix.append((f"{h}:{a}", prob, h + a))

    ft_matrix.sort(key=lambda x: x[1], reverse=True)
    best_ft = ft_matrix[0][0]
    best_ft_prob = round(ft_matrix[0][1] * 100, 1)

    # 2. Halftime Exact Score Matrix (0:0 up to 4:4)
    ht_matrix = []
    for h in range(5):
        for a in range(5):
            prob = poisson_prob(h, exp_home_ht) * poisson_prob(a, exp_away_ht)
            ht_matrix.append((f"{h}:{a}", prob))

    ht_matrix.sort(key=lambda x: x[1], reverse=True)
    best_ht = ht_matrix[0][0]
    best_ht_prob = round(ht_matrix[0][1] * 100, 1)

    # 3. Top High-Scoring Exact Scores (total goals >= 3, like 2:1, 2:2, 3:1, 4:4)
    high_score_candidates = [
        {"score": s, "probability": f"{round(p * 100, 1)}%"}
        for s, p, total_goals in ft_matrix
        if total_goals >= 3
    ][:5]

    # 4. Top All Halftime & Full-Time Exact Scores Ranked
    all_ht_scores = [
        {"score": s, "probability": f"{round(p * 100, 1)}%"}
        for s, p in ht_matrix[:6]
    ]
    all_ft_scores = [
        {"score": s, "probability": f"{round(p * 100, 1)}%"}
        for s, p, _ in ft_matrix[:8]
    ]

    return {
        "ht_score": best_ht,
        "ht_probability": f"{best_ht_prob}%",
        "ft_score": best_ft,
        "ft_probability": f"{best_ft_prob}%",
        "ht_ft_combo": f"{best_ht} / {best_ft}",
        "high_scores": high_score_candidates,
        "all_ht_scores": all_ht_scores,
        "all_ft_scores": all_ft_scores
    }

# Fetch upcoming matches
url = f"{BASE_URL}/matches?dateFrom={date_from}&dateTo={date_to}"
response = requests.get(url, headers=HEADERS, timeout=30)
data = response.json()

predictions_list = []
standings_cache = {}
matches = data.get("matches", [])

for m in matches:
    if m.get("status") in ["SCHEDULED", "TIMED"]:
        comp_code = m["competition"]["code"]
        comp_stats = get_team_stats(comp_code, standings_cache)
        
        home_id = m["homeTeam"]["id"]
        away_id = m["awayTeam"]["id"]
        scores = predict_scores(home_id, away_id, comp_stats)

        predictions_list.append({
            "fixture_id": m["id"],
            "kickoff_utc": m["utcDate"],
            "league": m["competition"]["name"],
            "country": m["area"]["name"],
            "home_team": m["homeTeam"]["name"],
            "away_team": m["awayTeam"]["name"],
            "ht_score": scores["ht_score"],
            "ht_probability": scores["ht_probability"],
            "ft_score": scores["ft_score"],
            "ft_probability": scores["ft_probability"],
            "ht_ft_combo": scores["ht_ft_combo"],
            "high_scores": scores["high_scores"],
            "all_ht_scores": scores["all_ht_scores"],
            "all_ft_scores": scores["all_ft_scores"]
        })

output = {
    "updated_at": now_utc.isoformat(),
    "date_range": f"{date_from} to {date_to}",
    "total_predictions": len(predictions_list),
    "api_message": "OK" if "matches" in data else data.get("message", "Error"),
    "predictions": predictions_list
}

with open("predictions.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Generated {len(predictions_list)} exact score predictions!")
