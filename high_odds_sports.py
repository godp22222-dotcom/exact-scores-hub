from datetime import datetime, timedelta, timezone
import json
import os
import time
import requests

APISPORTS_KEY = (
    os.environ.get("API_FOOTBALL_KEY") or os.environ.get("API_KEY") or ""
).strip()

NOW_UTC = datetime.now(timezone.utc)
WAT = timezone(timedelta(hours=1))
NOW_WAT = NOW_UTC.astimezone(WAT)
TODAY = NOW_UTC.strftime("%Y-%m-%d")
TOMORROW = (NOW_UTC + timedelta(days=1)).strftime("%Y-%m-%d")

BASE_APISPORTS = "api-sports.io"
OTHER_SPORTS = {
    "hockey": ("v1.hockey." + BASE_APISPORTS, "/games", "/odds", "game"),
    "nba": ("v2.nba." + BASE_APISPORTS, "/games", "/odds", "game"),
    "basketball": (
        "v1.basketball." + BASE_APISPORTS,
        "/games",
        "/odds",
        "game",
    ),
    "nfl": (
        "v1.american-football." + BASE_APISPORTS,
        "/games",
        "/odds",
        "game",
    ),
    "rugby": ("v1.rugby." + BASE_APISPORTS, "/games", "/odds", "game"),
}

TOKENS_2_1 = ("2/1", "away/home", "visitor/home", "away / home", "2 / 1")
TOKENS_1_2 = ("1/2", "home/away", "home/visitor", "home / away", "1 / 2")


def decide_best_htft(odds_list, home, away):
  odd_1_2 = None
  odd_2_1 = None
  for item in odds_list:
    for bk in item.get("bookmakers", []):
      for bet in bk.get("bets", []):
        m_name = str(bet.get("name", "")).lower()
        if any(
            k in m_name
            for k in (
                "ht/ft",
                "half time/full time",
                "double result",
                "period / full",
            )
        ):
          for val in bet.get("values", []):
            sel = str(val.get("value", "")).strip().lower()
            try:
              odd_val = float(val.get("odd", 0))
            except (ValueError, TypeError):
              continue
            if odd_val < 3.50:
              continue
            if any(t in sel for t in TOKENS_1_2):
              if not odd_1_2 or odd_val < odd_1_2:
                odd_1_2 = odd_val
            elif any(t in sel for t in TOKENS_2_1):
              if not odd_2_1 or odd_val < odd_2_1:
                odd_2_1 = odd_val

  if not odd_1_2 and not odd_2_1:
    return None

  if odd_2_1 and (not odd_1_2 or odd_2_1 <= odd_1_2):
    return {
        "recommended_pick": "2/1 (Away HT / Home FT)",
        "odd": odd_2_1,
        "note": (
            f"Real Bookmaker 2/1 ({odd_2_1}): {home} are favored to overturn"
            f" an early {away} halftime lead."
        ),
    }
  else:
    return {
        "recommended_pick": "1/2 (Home HT / Away FT)",
        "odd": odd_1_2,
        "note": (
            f"Real Bookmaker 1/2 ({odd_1_2}): {away} are favored to overturn"
            f" an early {home} halftime lead."
        ),
    }


def run():
  final_output = {
      "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
      "date": TODAY,
      "count": 0,
      "football_picks": [],
      "other_sports_picks": [],
  }

  if not APISPORTS_KEY:
    with open("high_odds_sports.json", "w", encoding="utf-8") as f:
      json.dump(final_output, f, indent=2)
    return

  headers = {"x-apisports-key": APISPORTS_KEY}

  # 1. FOOTBALL: Official API-Sports /predictions Only
  try:
    fb_url = "https://v3.football." + BASE_APISPORTS
    fixtures = []
    for check_date in (TODAY, TOMORROW):
      res = requests.get(
          f"{fb_url}/fixtures",
          headers=headers,
          params={"date": check_date, "status": "NS"},
          timeout=15,
      ).json()
      for f in res.get("response", []):
        utc_str = (f.get("fixture") or {}).get("date", "")
        if utc_str:
          k_dt = datetime.fromisoformat(str(utc_str).replace("Z", "+00:00"))
          if k_dt > NOW_UTC:
            fixtures.append((k_dt, f))
      if len(fixtures) >= 10:
        break

    fixtures.sort(key=lambda x: x[0])
    for k_dt, item in fixtures[:6]:
      fid = (item.get("fixture") or {}).get("id")
      home = ((item.get("teams") or {}).get("home") or {}).get("name", "Home")
      away = ((item.get("teams") or {}).get("away") or {}).get("name", "Away")
      comp = (item.get("league") or {}).get("name", "Football")
      wat_time = k_dt.astimezone(WAT).strftime("%Y-%m-%d %I:%M %p WAT")

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

      pred_obj = (p_list[0] or {}).get("predictions") or {}
      winner_info = pred_obj.get("winner") or {}
      percent = pred_obj.get("percent") or {}
      goals = pred_obj.get("goals") or {}
      advice = pred_obj.get("advice") or ""

      if advice or winner_info.get("name"):
        final_output["football_picks"].append({
            "source": "API-Sports Official Predictions",
            "competition": comp,
            "match": f"{home} vs {away}",
            "kickoff_Nigeria": wat_time,
            "api_predicted_winner": winner_info.get("name", "N/A"),
            "api_probabilities": {
                "home": percent.get("home", "0%"),
                "draw": percent.get("draw", "0%"),
                "away": percent.get("away", "0%"),
            },
            "api_goal_line": {
                "home": goals.get("home", "N/A"),
                "away": goals.get("away", "N/A"),
            },
            "api_official_advice": advice,
        })
      if len(final_output["football_picks"]) >= 5:
        break
      time.sleep(0.7)
  except Exception:
    pass

  # 2. OTHER SPORTS: Real Bookmaker Odds Only
  for sport, (host, games_ep, odds_ep, id_param) in OTHER_SPORTS.items():
    try:
      base_url = f"https://{host}"
      g_res = requests.get(
          f"{base_url}{games_ep}",
          headers=headers,
          params={"date": TODAY},
          timeout=12,
      ).json()
      for g in g_res.get("response", [])[:3]:
        gid = g.get("id")
        teams = g.get("teams") or {}
        home_obj = teams.get("home") or {}
        away_obj = teams.get("away") or teams.get("visitors") or {}
        home = (
            home_obj.get("name", "Home") if isinstance(home_obj, dict) else "Home"
        )
        away = (
            away_obj.get("name", "Away") if isinstance(away_obj, dict) else "Away"
        )

        o_res = requests.get(
            f"{base_url}{odds_ep}",
            headers=headers,
            params={id_param: gid},
            timeout=12,
        ).json()
        decision = decide_best_htft(o_res.get("response", []), home, away)
        if decision:
          final_output["other_sports_picks"].append({
              "sport": sport.upper(),
              "match": f"{home} vs {away}",
              "recommended_pick": decision["recommended_pick"],
              "target_odd": decision["odd"],
              "note": decision["note"],
          })
          break
    except Exception:
      continue

  final_output["count"] = len(final_output["football_picks"]) + len(
      final_output["other_sports_picks"]
  )

  with open("high_odds_sports.json", "w", encoding="utf-8") as f:
    json.dump(final_output, f, indent=2)
  print(
      f"Saved {final_output['count']} verified API picks to"
      " high_odds_sports.json."
  )


if __name__ == "__main__":
  run()
