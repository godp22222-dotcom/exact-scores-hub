from datetime import datetime, timedelta, timezone
import json
import os
import time
import requests

APISPORTS_KEY = (
    os.environ.get("API_FOOTBALL_KEY") or os.environ.get("API_KEY") or ""
).strip()

WAT = timezone(timedelta(hours=1))
NOW_WAT = datetime.now(WAT)
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TOMORROW = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

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


def is_future_utc(raw_dt):
  if not raw_dt:
    return False
  try:
    clean = str(raw_dt).strip().replace("Z", "+00:00").replace(" ", "T")
    dt_utc = datetime.fromisoformat(clean)
    if dt_utc.tzinfo is None:
      dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc > datetime.now(timezone.utc)
  except Exception:
    return False


def decide_best_htft(odds_list, home, away):
  odd_1_2 = None
  odd_2_1 = None
  for item in odds_list:
    for bk in item.get("bookmakers", []):
      for bet in bk.get("bets", []):
        m_name = bet.get("name", "")
        if any(
            k in m_name.lower()
            for k in (
                "ht/ft",
                "half time/full time",
                "halftime/fulltime",
                "double result",
                "1st period",
            )
        ):
          for val in bet.get("values", []):
            sel = str(val.get("value", "")).strip().lower()
            try:
              odd_val = float(val.get("odd", 0))
            except (ValueError, TypeError):
              continue
            if odd_val <= 1.01:
              continue
            if any(t in sel for t in TOKENS_1_2):
              if not odd_1_2 or odd_val < odd_1_2:
                odd_1_2 = odd_val
            elif any(t in sel for t in TOKENS_2_1):
              if not odd_2_1 or odd_val < odd_2_1:
                odd_2_1 = odd_val

  if not odd_1_2 and not odd_2_1:
    return None

  # Only select real bookmaker odds (lower decimal odd = stronger comeback probability)
  if odd_2_1 and (not odd_1_2 or odd_2_1 <= odd_1_2):
    return {
        "recommended_pick": "2/1 (Away HT / Home FT)",
        "target_odd": odd_2_1,
        "notes": [
            (
                f"Real Bookmaker 2/1 ({odd_2_1}): {home} are favored to"
                f" overturn an early {away} halftime lead."
            ),
            (
                "Second-Half Trigger: Best value comes when halftime finishes"
                " 0-1 with the home side controlling shots."
            ),
        ],
    }
  else:
    return {
        "recommended_pick": "1/2 (Home HT / Away FT)",
        "target_odd": odd_1_2,
        "notes": [
            (
                f"Real Bookmaker 1/2 ({odd_1_2}): {away} are favored to"
                f" overturn an early {home} halftime lead."
            ),
            (
                "Second-Half Trigger: Best value comes when halftime finishes"
                " 1-0 with the away side controlling shots."
            ),
        ],
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
    with open("htft_comebacks.json", "w", encoding="utf-8") as f:
      json.dump(final_output, f, indent=2)
    return

  headers = {"x-apisports-key": APISPORTS_KEY}

  # 1. FOOTBALL: Real Bookmaker HT/FT Odds Only (No Fake Alternating Picks)
  try:
    fb_host = "https://v3.football." + BASE_APISPORTS
    fixtures = []
    for check_date in (TODAY, TOMORROW):
      res = requests.get(
          f"{fb_host}/fixtures",
          headers=headers,
          params={"date": check_date, "status": "NS"},
          timeout=15,
      ).json()
      fixtures.extend(res.get("response", []))
      if len(fixtures) >= 10:
        break

    for item in fixtures[:6]:
      fix = item.get("fixture", {})
      if not is_future_utc(fix.get("date")):
        continue
      fid = fix.get("id")
      home = item.get("teams", {}).get("home", {}).get("name", "Home")
      away = item.get("teams", {}).get("away", {}).get("name", "Away")
      comp = item.get("league", {}).get("name", "Football")

      odds_res = requests.get(
          f"{fb_host}/odds",
          headers=headers,
          params={"fixture": fid, "bet": 7},
          timeout=15,
      ).json()
      decision = decide_best_htft(odds_res.get("response", []), home, away)
      if decision:
        final_output["football_picks"].append({
            "competition": comp,
            "match": f"{home} vs {away}",
            "kickoff_UTC": fix.get("date", ""),
            "recommended_pick": decision["recommended_pick"],
            "target_odd": decision["target_odd"],
            "notes": decision["notes"],
        })
      if len(final_output["football_picks"]) >= 3:
        break
      time.sleep(0.5)
  except Exception:
    pass

  # 2. OTHER SPORTS: Real Bookmaker Double Result / Period Comeback Odds
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
        teams = g.get("teams", {})
        home = (
            teams.get("home", {}).get("name", "Home")
            if isinstance(teams.get("home"), dict)
            else "Home"
        )
        away = (
            teams.get("away", {}).get("name", "Away")
            if isinstance(teams.get("away"), dict)
            else "Away"
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
              "target_odd": decision["target_odd"],
              "notes": decision["notes"],
          })
          break
    except Exception:
      continue

  final_output["count"] = len(final_output["football_picks"]) + len(
      final_output["other_sports_picks"]
  )

  with open("htft_comebacks.json", "w", encoding="utf-8") as f:
    json.dump(final_output, f, indent=2)

  print(
      f"Saved {final_output['count']} verified real-odds comeback picks to"
      " htft_comebacks.json."
  )


if __name__ == "__main__":
  run()
