from datetime import datetime, timedelta, timezone
import json
import os
import requests

SM_TOKEN = (
    os.environ.get("SPORTMONKS_TOKEN")
    or os.environ.get("SPORTMONKS_API_KEY")
    or os.environ.get("SPORTMONKS_KEY")
    or ""
).strip()

WAT = timezone(timedelta(hours=1))
NOW_WAT = datetime.now(WAT)
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TOMORROW = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

TARGET_MARKETS = (
    "correct score",
    "exact score",
    "half time/full time",
    "ht/ft",
    "double result",
)


def run():
  output = {
      "updated_at_Nigeria": NOW_WAT.strftime("%Y-%m-%d %I:%M %p WAT"),
      "source": "Sportmonks",
      "date": TODAY,
      "count": 0,
      "picks": [],
  }

  if not SM_TOKEN:
    print("WARNING: No Sportmonks token found in environment variables.")
    with open("sportmonks_high_odds.json", "w", encoding="utf-8") as f:
      json.dump(output, f, indent=2)
    return

  params = {"api_token": SM_TOKEN, "include": "odds;participants"}

  for check_date in (TODAY, TOMORROW):
    if output["picks"]:
      break
    url = f"https://sportmonks.com{check_date}"
    try:
      res = requests.get(url, params=params, timeout=20).json()
      fixtures = res.get("data", [])

      for fx in fixtures:
        match_name = fx.get("name", "Unknown Match")
        kickoff = fx.get("starting_at", "")
        high_odds = []

        for odd in fx.get("odds", []):
          market_desc = str(odd.get("market_description", ""))
          if any(t in market_desc.lower() for t in TARGET_MARKETS):
            try:
              val = float(odd.get("value", 0))
              if val >= 5.00:
                high_odds.append({
                    "market": market_desc,
                    "selection": odd.get("label"),
                    "odd": val,
                })
            except (ValueError, TypeError):
              continue

        high_odds.sort(key=lambda x: x["odd"], reverse=True)
        if high_odds:
          output["picks"].append({
              "match": match_name,
              "kickoff_UTC": kickoff,
              "highest_odds": high_odds[:3],
          })
    except Exception as e:
      print(f"[Sportmonks] Skipped {check_date} due to error: {e}")

  output["count"] = len(output["picks"])
  with open("sportmonks_high_odds.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)
  print(f"Saved sportmonks_high_odds.json ({output['count']} matches).")


if __name__ == "__main__":
  run()
