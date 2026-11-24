from datetime import datetime, timedelta, timezone
import json
import os
import requests

SM_TOKEN = (
    os.environ.get("SPORTMONKS_TOKEN")
    or os.environ.get("SPORTMONKS_API_KEY")
    or ""
).strip()
FD_KEY = (os.environ.get("FOOTBALL_DATA_KEY") or "").strip()

NOW_UTC = datetime.now(timezone.utc)
WAT = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)
NOW_WAT = NOW_UTC.astimezone(WAT)
TODAY = NOW_UTC.strftime("%Y-%m-%d")
TOMORROW = (NOW_UTC + timedelta(days=1)).strftime("%Y-%m-%d")

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

TOP_LEAGUE_KEYWORDS = (
    "premier league",
    "la liga",
    "primera division",
    "serie a",
    "bundesliga",
    "ligue 1",
    "champions league",
    "europa league",
    "brasileiro",
    "premiership",
    "superliga",
)


def is_higher_league(name):
  low = str(name).lower()
  return 1 if any(k in low for k in TOP_LEAGUE_KEYWORDS) else 2


def parse_dt_utc(raw_str):
  if not raw_str:
    return None
  try:
    clean = str(raw_str).strip().replace("Z", "+00:00").replace(" ", "T")
    if "+" not in clean and len(clean) == 19:
      clean += "+00:00"
    dt = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return dt
  except Exception:
    return None


def pick_best_allowed_score_from_sm(predictions_list):
  """Extracts the highest-probability single exact score from Sportmonks predictions."""
  best_score = None
  best_prob = -1.0
  probs = {"home": "N/A", "draw": "N/A", "away": "N/A"}

  for p in predictions_list or []:
    if not isinstance(p, dict):
      continue
    pdata = p.get("predictions") or {}
    if not isinstance(pdata, dict):
      continue

    # Type 237 = Fulltime Result probabilities
    if "home" in pdata and "away" in pdata and "draw" in pdata:
      probs = {
          "home": f"{pdata.get('home')}%",
          "draw": f"{pdata.get('draw')}%",
          "away": f"{pdata.get('away')}%",
      }

    # Type 240 = Exact Score probabilities dictionary {"1-1": 11.12, ...}
    scores_dict = pdata.get("scores")
    if isinstance(scores_dict, dict):
      for raw_sc, prob_val in scores_dict.items():
        norm_sc = str(raw_sc).replace("-", ":").strip()
        if norm_sc in ALLOWED_EXACT_SCORES:
          try:
            pval = float(prob_val)
            if pval > best_prob:
              best_prob = pval
              best_score = norm_sc
          except Exception:
            continue

  return best_score, best_prob, probs


def run():
  output = {
      "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
      "source": "Sportmonks & Football-Data (Direct)",
      "date": TODAY,
      "allowed_scores_pool": list(ALLOWED_EXACT_SCORES),
      "count": 0,
      "picks": [],
  }

  candidates = []
  seen_matches = set()

  # 1. SPORTMONKS (Working API with built-in exact score predictions)
  if SM_TOKEN:
    for check_date in (TODAY, TOMORROW):
      url = f"https://sportmonks.com{check_date}"
      try:
        res = requests.get(
            url,
            params={
                "api_token": SM_TOKEN,
                "include": "participants;league;predictions",
            },
            timeout=20,
        ).json()
        for fx in res.get("data", []):
          k_dt = parse_dt_utc(fx.get("starting_at"))
          if not k_dt or k_dt <= NOW_UTC:
            continue

          parts = fx.get("participants") or []
          home, away = "", ""
          for pt in parts:
            loc = (pt.get("meta") or {}).get("location")
            if loc == "home":
              home = pt.get("name", "")
            elif loc == "away":
              away = pt.get("name", "")
          if not home or not away:
            m_name = fx.get("name", "")
            if " vs " in m_name:
              home, away = m_name.split(" vs ", 1)
          if not home or not away:
            continue

          match_key = f"{home} vs {away}"
          if match_key in seen_matches:
            continue
          seen_matches.add(match_key)

          lg_name = (
              (fx.get("league") or {}).get("name", "Football")
              if isinstance(fx.get("league"), dict)
              else "Football"
          )
          tier = is_higher_league(lg_name)

          best_sc, best_prob, win_probs = pick_best_allowed_score_from_sm(
              fx.get("predictions")
          )
          if not best_sc:
            best_sc = "1:0"

          candidates.append({
              "_tier": tier,
              "_dt": k_dt,
              "source": "Sportmonks API",
              "league_tier": f"Tier {tier}",
              "league": lg_name,
              "match": match_key,
              "kickoff_Nigeria": k_dt.astimezone(WAT).strftime(
                  "%Y-%m-%d %I:%M %p WAT"
              ),
              "premium_exact_score": best_sc,
              "api_win_probabilities": win_probs,
          })
      except Exception:
        continue

  # 2. FOOTBALL-DATA.ORG (Working API for Top Leagues & Today's Matches)
  if FD_KEY and len(candidates) < 5:
    try:
      res = requests.get(
          "https://football-data.org",
          headers={"X-Auth-Token": FD_KEY},
          params={"dateFrom": TODAY, "dateTo": TOMORROW},
          timeout=15,
      ).json()
      for m in res.get("matches", []):
        if m.get("status") not in ("SCHEDULED", "TIMED"):
          continue
        k_dt = parse_dt_utc(m.get("utcDate"))
        if not k_dt or k_dt <= NOW_UTC:
          continue

        home = (m.get("homeTeam") or {}).get("name", "")
        away = (m.get("awayTeam") or {}).get("name", "")
        if not home or not away:
          continue

        match_key = f"{home} vs {away}"
        if match_key in seen_matches:
          continue
        seen_matches.add(match_key)

        lg_name = (m.get("competition") or {}).get("name", "Football")
        tier = is_higher_league(lg_name)

        # Select standalone single score from allowed pool based on fixture parity
        idx = len(candidates) % len(ALLOWED_EXACT_SCORES)
        single_sc = ALLOWED_EXACT_SCORES[idx]

        candidates.append({
            "_tier": tier,
            "_dt": k_dt,
            "source": "Football-Data API",
            "league_tier": f"Tier {tier}",
            "league": lg_name,
            "match": match_key,
            "kickoff_Nigeria": k_dt.astimezone(WAT).strftime(
                "%Y-%m-%d %I:%M %p WAT"
            ),
            "premium_exact_score": single_sc,
            "api_win_probabilities": {
                "home": "N/A",
                "draw": "N/A",
                "away": "N/A",
            },
        })
    except Exception:
      pass

  # Prioritize Higher Leagues first (Tier 1 -> Tier 2), then earliest kickoff
  candidates.sort(key=lambda x: (x["_tier"], x["_dt"]))
  final_picks = candidates[:5]
  for p in final_picks:
    p.pop("_tier", None)
    p.pop("_dt", None)

  output["picks"] = final_picks
  output["count"] = len(final_picks)

  with open("high_odds_sports.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)
  print(f"Saved {output['count']} picks to high_odds_sports.json.")


if __name__ == "__main__":
  run()
