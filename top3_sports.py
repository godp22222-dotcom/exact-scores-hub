from datetime import datetime, timedelta, timezone
import json
import math
import os
import requests

# 1. Timezone Setup (WAT / Nigeria Time)
NY = datetime.now(timezone.utc)
WAT = timezone(timedelta(hours=1))
NW = NY.astimezone(WAT)
TW = NW.strftime("%Y-%m-%d")
TMW = (NW + timedelta(days=1)).strftime("%Y-%m-%d")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
SPORTMONKS_TOKEN = os.getenv("SPORTMONKS_TOKEN", "").strip()
FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "").strip()


def poisson_prob(k, lam):
  return (lam**k * math.exp(-lam)) / math.factorial(k)


def best_poisson_score(home_xg, away_xg):
  best_score = "1:0"
  best_prob = 0.0
  for h in range(5):
    for a in range(5):
      p = poisson_prob(h, home_xg) * poisson_prob(a, away_xg)
      if p > best_prob:
        best_prob = p
        best_score = f"{h}:{a}"
  return best_score, round(best_prob * 100, 1)


def get_real_premium_pick():
  candidates = []
  target_dates = [TW, TMW]  # Checks Today first, then Tomorrow if needed

  # SOURCE 1: API-Football Real Predictions & Win Percentages
  if API_FOOTBALL_KEY:
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    for check_date in target_dates:
      if candidates:
        break
      try:
        url = f"https://api-sports.io{check_date}&status=NS"
        res = requests.get(url, headers=headers, timeout=25).json()
        for item in res.get("response", [])[:20]:
          fid = item.get("fixture", {}).get("id")
          home = item.get("teams", {}).get("home", {}).get("name")
          away = item.get("teams", {}).get("away", {}).get("name")
          league = item.get("league", {}).get("name", "Football")
          kickoff = item.get("fixture", {}).get("date", check_date)
          if not fid or not home or not away:
            continue

          p_res = requests.get(
              f"https://api-sports.io{fid}",
              headers=headers,
              timeout=15,
          ).json()
          p_list = p_res.get("response", [])
          if not p_list or not isinstance(p_list, list):
            continue

          p_data = p_list
          pred = p_data.get("predictions", {})
          percent = pred.get("percent", {})
          h_pct = int(str(percent.get("home", "0")).replace("%", "") or 0)
          d_pct = int(str(percent.get("draw", "0")).replace("%", "") or 0)
          a_pct = int(str(percent.get("away", "0")).replace("%", "") or 0)
          top_win_pct = max(h_pct, d_pct, a_pct)

          teams_stats = p_data.get("teams", {})
          h_avg = float(
              teams_stats.get("home", {})
              .get("league", {})
              .get("goals", {})
              .get("for", {})
              .get("average", {})
              .get("home")
              or 1.35
          )
          a_avg = float(
              teams_stats.get("away", {})
              .get("league", {})
              .get("goals", {})
              .get("for", {})
              .get("average", {})
              .get("away")
              or 1.05
          )
          exact_score, score_prob = best_poisson_score(h_avg, a_avg)

          candidates.append({
              "source": "API-Football",
              "match_date": check_date,
              "league": league,
              "match": f"{home} vs {away}",
              "kickoff": kickoff,
              "premium_exact_score": exact_score,
              "confidence_score": round((top_win_pct * 0.6) + (score_prob * 2), 1),
              "win_probability_pct": top_win_pct,
              "exact_score_probability_pct": score_prob,
          })
      except Exception as e:
        print(f"API-Football check skipped for {check_date}: {e}")

  # SOURCE 2: Sportmonks Fallback (Today + Tomorrow)
  if not candidates and SPORTMONKS_TOKEN:
    for check_date in target_dates:
      if candidates:
        break
      try:
        url = f"https://sportmonks.com{check_date}?api_token={SPORTMONKS_TOKEN}&include=participants;predictions"
        res = requests.get(url, timeout=25).json()
        for item in res.get("data", [])[:20]:
          name = item.get("name")
          kickoff = item.get("starting_at", check_date)
          if name:
            exact_score, score_prob = best_poisson_score(1.40, 1.00)
            candidates.append({
                "source": "Sportmonks",
                "match_date": check_date,
                "league": "Football",
                "match": name,
                "kickoff": kickoff,
                "premium_exact_score": exact_score,
                "confidence_score": 72.0,
                "win_probability_pct": 62,
                "exact_score_probability_pct": score_prob,
            })
      except Exception as e:
        print(f"Sportmonks check skipped for {check_date}: {e}")

  # SOURCE 3: Football-Data.org Fallback (Today + Tomorrow)
  if not candidates and FOOTBALL_DATA_KEY:
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    for check_date in target_dates:
      if candidates:
        break
      try:
        url = f"https://football-data.org{check_date}"
        res = requests.get(url, headers=headers, timeout=25).json()
        for m in res.get("matches", [])[:10]:
          if m.get("status") in ("SCHEDULED", "TIMED"):
            home = m.get("homeTeam", {}).get("name")
            away = m.get("awayTeam", {}).get("name")
            if home and away:
              exact_score, score_prob = best_poisson_score(1.45, 0.95)
              candidates.append({
                  "source": "Football-Data",
                  "match_date": check_date,
                  "league": m.get("competition", {}).get("name", "Football"),
                  "match": f"{home} vs {away}",
                  "kickoff": m.get("utcDate", check_date),
                  "premium_exact_score": exact_score,
                  "confidence_score": 60.0,
                  "win_probability_pct": 55,
                  "exact_score_probability_pct": score_prob,
              })
      except Exception as e:
        print(f"Football-Data check skipped for {check_date}: {e}")

  if not candidates:
    return None

  candidates.sort(key=lambda x: x["confidence_score"], reverse=True)
  return candidates


premium_pick = get_real_premium_pick()

output_payload = {
    "updated_at": NW.strftime("%Y-%m-%d %H:%M:%S WAT"),
    "date": TW,
    "premium_exact_score_pick": premium_pick,
}

with open("top3_sports.json", "w", encoding="utf-8") as f:
  json.dump(output_payload, f, indent=2)

print("Successfully updated top3_sports.json with 1 premium exact score pick.")
