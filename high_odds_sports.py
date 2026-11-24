from datetime import datetime, timedelta, timezone
import json
import os
import time
import requests

APISPORTS_KEY = (
    os.environ.get("API_FOOTBALL_KEY") or os.environ.get("API_KEY") or ""
).strip()

NOW_UTC = datetime.now(timezone.utc)
WAT = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)
NOW_WAT = NOW_UTC.astimezone(WAT)
TODAY = NOW_UTC.strftime("%Y-%m-%d")
TOMORROW = (NOW_UTC + timedelta(days=1)).strftime("%Y-%m-%d")

# Strictly your 14 standalone single exact score targets
ALLOWED_EXACT_SCORES = (
    "0:0",
    "1:0",
    "0:1",
    "2:0",
    "2:1",
    "2:2",
    "0:2",
    "1:2",
    "3:1",
    "1:3",
    "4:1",
    "1:4",
    "2:3",
    "3:2",
)

# Tier 1: Top Elite Leagues (Checked & Ranked First)
TIER_1_LEAGUES = (
    39,  # Premier League
    140,  # La Liga
    135,  # Serie A
    78,  # Bundesliga
    61,  # Ligue 1
    2,  # UEFA Champions League
    3,  # UEFA Europa League
    71,  # Brasileirao Serie A
)

# Tier 2: Strong Secondary Leagues (Checked Before Smaller Leagues)
TIER_2_LEAGUES = (
    88,  # Eredivisie
    94,  # Primeira Liga
    40,  # Championship
    253,  # MLS
    307,  # Saudi Pro League
    203,  # Super Lig
    144,  # Belgian Pro League
)


def get_league_tier(league_id):
  if league_id in TIER_1_LEAGUES:
    return 1
  if league_id in TIER_2_LEAGUES:
    return 2
  return 3


def parse_pct(pct_str):
  try:
    return float(str(pct_str).replace("%", "").strip())
  except Exception:
    return 0.0


def parse_goal_cap(goal_str):
  try:
    return abs(float(str(goal_str).strip()))
  except Exception:
    return 1.5


def select_single_exact_score(pred_obj):
  """Maps API-Sports official /predictions data strictly to one of your 14 single exact scores."""
  percent = pred_obj.get("percent") or {}
  goals = pred_obj.get("goals") or {}

  h_pct = parse_pct(percent.get("home", "0%"))
  d_pct = parse_pct(percent.get("draw", "0%"))
  a_pct = parse_pct(percent.get("away", "0%"))

  h_cap = parse_goal_cap(goals.get("home", "1.5"))
  a_cap = parse_goal_cap(goals.get("away", "1.5"))
  total_cap = h_cap + a_cap

  # 1. Draw dominant or tight balanced match -> 0:0 or 2:2
  if d_pct >= h_pct and d_pct >= a_pct or abs(h_pct - a_pct) <= 7.0:
    score = "0:0" if total_cap <= 2.2 else "2:2"
    return score if score in ALLOWED_EXACT_SCORES else "0:0"

  # 2. Home win favored -> 1:0, 2:0, 2:1, 3:1, 3:2, or 4:1
  if h_pct > a_pct:
    edge = h_pct - a_pct
    if edge >= 38.0 and h_cap >= 3.0:
      score = "4:1" if a_cap >= 1.2 else "3:1"
    elif edge >= 25.0 and h_cap >= 2.5:
      score = "3:1" if a_cap >= 1.2 else "2:0"
    elif total_cap >= 3.5 and a_cap >= 1.5:
      score = "3:2"
    elif total_cap >= 2.6 and a_cap >= 1.1:
      score = "2:1"
    elif edge >= 18.0:
      score = "2:0"
    else:
      score = "1:0"
    return score if score in ALLOWED_EXACT_SCORES else "1:0"

  # 3. Away win favored -> 0:1, 0:2, 1:2, 1:3, 2:3, or 1:4
  edge = a_pct - h_pct
  if edge >= 38.0 and a_cap >= 3.0:
    score = "1:4" if h_cap >= 1.2 else "1:3"
  elif edge >= 25.0 and a_cap >= 2.5:
    score = "1:3" if h_cap >= 1.2 else "0:2"
  elif total_cap >= 3.5 and h_cap >= 1.5:
    score = "2:3"
  elif total_cap >= 2.6 and h_cap >= 1.1:
    score = "1:2"
  elif edge >= 18.0:
    score = "0:2"
  else:
    score = "0:1"
  return score if score in ALLOWED_EXACT_SCORES else "0:1"


def run():
  output = {
      "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
      "source": "API-Sports Official Predictions (Direct)",
      "date": TODAY,
      "allowed_scores_pool": list(ALLOWED_EXACT_SCORES),
      "count": 0,
      "picks": [],
  }

  if not APISPORTS_KEY:
    with open("high_odds_sports.json", "w", encoding="utf-8") as f:
      json.dump(output, f, indent=2)
    return

  fb_url = "https://api-sports.io"
  headers = {"x-apisports-key": APISPORTS_KEY}

  fixtures = []
  seen_ids = set()

  # Fetch Today & Tomorrow upcoming fixtures directly from API-Sports (never touches scores.json)
  for check_date in (TODAY, TOMORROW):
    try:
      res = requests.get(
          f"{fb_url}/fixtures",
          headers=headers,
          params={"date": check_date, "status": "NS"},
          timeout=15,
      ).json()
      for item in res.get("response", []):
        fix = item.get("fixture") or {}
        fid = fix.get("id")
        utc_str = fix.get("date", "")
        if not fid or fid in seen_ids or not utc_str:
          continue
        k_dt = datetime.fromisoformat(str(utc_str).replace("Z", "+00:00"))
        if k_dt <= NOW_UTC:
          continue
        seen_ids.add(fid)
        lg_id = (item.get("league") or {}).get("id", 99999)
        tier = get_league_tier(lg_id)
        fixtures.append((tier, k_dt, item))
    except Exception:
      continue

  # Sort strictly by Higher League Tier first (Tier 1 -> Tier 2 -> Tier 3), then earliest kickoff
  fixtures.sort(key=lambda x: (x, x))

  # Query official API predictions for top 8 prioritized fixtures (safe within 10 req/min limit)
  for tier, k_dt, item in fixtures[:8]:
    fix = item.get("fixture") or {}
    fid = fix.get("id")
    league_obj = item.get("league") or {}
    league_name = league_obj.get("name", "Football")
    country_name = league_obj.get("country", "")
    full_league = f"{country_name} - {league_name}" if country_name else league_name

    teams = item.get("teams") or {}
    home = (teams.get("home") or {}).get("name", "")
    away = (teams.get("away") or {}).get("name", "")
    if not home or not away:
      continue

    try:
      p_res = requests.get(
          f"{fb_url}/predictions",
          headers=headers,
          params={"fixture": fid},
          timeout=15,
      ).json()
      p_list = p_res.get("response") or []
      if not p_list or not isinstance(p_list, list):
        time.sleep(0.7)
        continue

      pred_obj = (p_list or {}).get("predictions") or {}
      if not pred_obj:
        time.sleep(0.7)
        continue

      single_score = select_single_exact_score(pred_obj)
      percent = pred_obj.get("percent") or {}
      advice = pred_obj.get("advice") or ""

      output["picks"].append({
          "league_tier": f"Tier {tier}",
          "league": full_league,
          "match": f"{home} vs {away}",
          "kickoff_Nigeria": k_dt.astimezone(WAT).strftime(
              "%Y-%m-%d %I:%M %p WAT"
          ),
          "premium_exact_score": single_score,
          "api_win_probabilities": {
              "home": percent.get("home", "0%"),
              "draw": percent.get("draw", "0%"),
              "away": percent.get("away", "0%"),
          },
          "api_official_advice": advice,
      })

      if len(output["picks"]) >= 5:
        break
      time.sleep(0.7)
    except Exception:
      time.sleep(0.7)
      continue

  output["count"] = len(output["picks"])
  with open("high_odds_sports.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)
  print(
      f"Saved {output['count']} standalone single exact scores to"
      " high_odds_sports.json."
  )


if __name__ == "__main__":
  run()
