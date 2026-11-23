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


def extract_matches_from_local_jsons():
  """Reads already-fetched matches from sibling JSON files in outputs/."""
  candidates = []
  for fname in [
      "scores.json",
      "high_goals.json",
      "draws.json",
      "high_odds_sports.json",
  ]:
    if not os.path.exists(fname):
      continue
    try:
      with open(fname, "r", encoding="utf-8") as f:
        data = json.load(f)

      items = data if isinstance(data, list) else []
      if isinstance(data, dict):
        for val in data.values():
          if isinstance(val, list) and val:
            items = val
            break

      for m in items:
        if not isinstance(m, dict):
          continue
        home = (
            m.get("home")
            or m.get("home_team")
            or m.get("homeTeam")
            or (
                m.get("teams", {}).get("home", {}).get("name")
                if isinstance(m.get("teams"), dict)
                else None
            )
        )
        away = (
            m.get("away")
            or m.get("away_team")
            or m.get("awayTeam")
            or (
                m.get("teams", {}).get("away", {}).get("name")
                if isinstance(m.get("teams"), dict)
                else None
            )
        )
        match_name = m.get("match") or m.get("fixture") or m.get("name")
        if not match_name and home and away:
          match_name = f"{home} vs {away}"
        if not match_name or not isinstance(match_name, str):
          continue

        league = m.get("league") or m.get("competition") or "Football"
        if isinstance(league, dict):
          league = league.get("name", "Football")

        kickoff = (
            m.get("kickoff")
            or m.get("date")
            or m.get("utcDate")
            or m.get("time")
            or TW
        )

        h_odds = float(m.get("home_odds") or m.get("odd_1") or 1.85)
        a_odds = float(m.get("away_odds") or m.get("odd_2") or 3.80)
        h_xg = round(min(max(2.6 / max(h_odds, 1.1), 0.85), 2.4), 2)
        a_xg = round(min(max(2.6 / max(a_odds, 1.1), 0.65), 2.1), 2)

        exact_score, score_prob = best_poisson_score(h_xg, a_xg)
        win_prob = min(int(round((1 / max(h_odds, 1.15)) * 100)), 85)

        candidates.append({
            "source": f"Hub-Engine ({fname})",
            "league": str(league),
            "match": match_name,
            "kickoff": str(kickoff),
            "premium_exact_score": exact_score,
            "confidence_score": round((win_prob * 0.6) + (score_prob * 2), 1),
            "win_probability_pct": win_prob,
            "exact_score_probability_pct": score_prob,
        })
    except Exception as e:
      print(f"Skipping local {fname}: {e}")
  return candidates


def get_real_premium_pick():
  candidates = []

  # 1. Try Football-Data.org (Supports free-tier tomorrow & upcoming fixtures)
  if FOOTBALL_DATA_KEY:
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    for check_date in [TW, TMW]:
      if candidates:
        break
      try:
        url = f"https://football-data.org{check_date}"
        res = requests.get(url, headers=headers, timeout=20).json()
        for m in res.get("matches", [])[:15]:
          if m.get("status") in ("SCHEDULED", "TIMED"):
            home = m.get("homeTeam", {}).get("name")
            away = m.get("awayTeam", {}).get("name")
            if home and away:
              exact_score, score_prob = best_poisson_score(1.55, 0.90)
              candidates.append({
                  "source": "Football-Data",
                  "league": m.get("competition", {}).get("name", "Football"),
                  "match": f"{home} vs {away}",
                  "kickoff": m.get("utcDate", check_date),
                  "premium_exact_score": exact_score,
                  "confidence_score": 68.5,
                  "win_probability_pct": 60,
                  "exact_score_probability_pct": score_prob,
              })
      except Exception as e:
        print(f"Football-Data skipped: {e}")

  # 2. Try API-Football for Today's Live/Remaining Fixtures
  if not candidates and API_FOOTBALL_KEY:
    try:
      headers = {"x-apisports-key": API_FOOTBALL_KEY}
      url = f"https://api-sports.io{TW}"
      res = requests.get(url, headers=headers, timeout=20).json()
      for item in res.get("response", [])[:15]:
        status = item.get("fixture", {}).get("status", {}).get("short", "")
        if status in ("NS", "1H", "HT"):
          home = item.get("teams", {}).get("home", {}).get("name")
          away = item.get("teams", {}).get("away", {}).get("name")
          if home and away:
            exact_score, score_prob = best_poisson_score(1.45, 0.95)
            candidates.append({
                "source": "API-Football",
                "league": item.get("league", {}).get("name", "Football"),
                "match": f"{home} vs {away}",
                "kickoff": item.get("fixture", {}).get("date", TW),
                "premium_exact_score": exact_score,
                "confidence_score": 66.0,
                "win_probability_pct": 58,
                "exact_score_probability_pct": score_prob,
            })
    except Exception as e:
      print(f"API-Football skipped: {e}")

  # 3. Guaranteed Fallback: Pull from your already-generated Hub JSON files
  if not candidates:
    candidates = extract_matches_from_local_jsons()

  if not candidates:
    return None

  candidates.sort(key=lambda x: x["confidence_score"], reverse=True)
  return candidates[0]


premium_pick = get_real_premium_pick()

output_payload = {
    "updated_at": NW.strftime("%Y-%m-%d %H:%M:%S WAT"),
    "date": TW,
    "premium_exact_score_pick": premium_pick,
}

with open("top3_sports.json", "w", encoding="utf-8") as f:
  json.dump(output_payload, f, indent=2)

print("Successfully updated top3_sports.json.")
