from datetime import datetime, timedelta, timezone
import json
import math
import os
import subprocess

LIMIT_HIGH_GOALS = 5
WAT_TZ = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)
TOP_5_CODES = ("PL", "PD", "SA", "BL1", "FL1", "CL")

TARGET_HIGH_SCORES = (
    "2 - 2",
    "3 - 3",
    "4 - 4",
    "5 - 5",
    "4 - 0",
    "0 - 4",
    "4 - 1",
    "1 - 4",
    "3 - 2",
    "2 - 3",
    "4 - 2",
    "2 - 4",
    "5 - 0",
    "0 - 5",
    "5 - 1",
    "1 - 5",
)


def get_json(url, headers=None):
  cmd = [
      "curl",
      "-sS",
      "-L",
      "-m",
      "15",
      "-H",
      "Accept: application/json",
      "-H",
      "User-Agent: Mozilla/5.0",
  ]
  if headers:
    for k, v in headers.items():
      cmd.extend(["-H", f"{k}: {v}"])
  res = subprocess.run(cmd + [url], capture_output=True, text=True)
  if res.returncode != 0 or not res.stdout.strip():
    return {}
  return json.loads(res.stdout.strip())


def format_wat(raw_dt):
  if not raw_dt:
    return None
  try:
    clean = str(raw_dt).strip().replace("Z", "+00:00").replace(" ", "T")
    if "+" not in clean and len(clean) == 19:
      clean += "+00:00"
    dt_utc = datetime.fromisoformat(clean)
    if dt_utc.tzinfo is None:
      dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    if dt_utc <= now_utc or dt_utc > now_utc + timedelta(days=7):
      return None
    return dt_utc.astimezone(WAT_TZ).strftime("%Y-%m-%d %I:%M %p WAT")
  except Exception:
    return None


def calc_high_goal_odds(h_xg, a_xg):
  target_map = {}
  for sc in TARGET_HIGH_SCORES:
    hg, ag = map(int, sc.split(" - "))
    p_h = (h_xg**hg * math.exp(-h_xg)) / math.factorial(hg)
    p_a = (a_xg**ag * math.exp(-a_xg)) / math.factorial(ag)
    prob = max(p_h * p_a, 0.001)
    target_map[sc] = round(min(1.0 / prob, 250.0), 2)
  sorted_targets = dict(sorted(target_map.items(), key=lambda x: x))
  best_score = next(iter(sorted_targets))
  return best_score, sorted_targets[best_score], sorted_targets


def fetch_high_goal_matches():
  candidates = []
  seen_matches = set()
  fd_key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()
  now_utc = datetime.now(timezone.utc)
  today = now_utc.strftime("%Y-%m-%d")
  tomorrow = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")

  if fd_key:
    hdr = {"X-Auth-Token": fd_key}
    urls = [
        f"https://football-data.org{c}/matches?status=SCHEDULED"
        for c in TOP_5_CODES
    ]
    urls.extend([
        f"https://football-data.org{today}",
        f"https://football-data.org{tomorrow}",
    ])

    for url in urls:
      try:
        matches = get_json(url, hdr).get("matches") or []
        for m in matches[:6]:
          if m.get("status") not in ("SCHEDULED", "TIMED"):
            continue
          wat = format_wat(m.get("utcDate", ""))
          if not wat:
            continue
          home = (m.get("homeTeam") or {}).get("name")
          away = (m.get("awayTeam") or {}).get("name")
          if not home or not away:
            continue
          m_key = f"{home} vs {away}"
          if m_key in seen_matches:
            continue
          seen_matches.add(m_key)

          comp = (m.get("competition") or {}).get("name", "Football")
          code = (m.get("competition") or {}).get("code", "")
          area = (m.get("area") or {}).get("name", "")
          full_league = f"{area} - {comp}" if area else comp

          h_id = (m.get("homeTeam") or {}).get("id") or 50
          a_id = (m.get("awayTeam") or {}).get("id") or 60
          h_xg = round(1.55 + ((h_id % 7) * 0.12), 2)
          a_xg = round(1.25 + ((a_id % 5) * 0.14), 2)

          best_score, best_odd, sorted_targets = calc_high_goal_odds(h_xg, a_xg)
          candidates.append({
              "league": full_league,
              "match": m_key,
              "kickoff_Nigeria": wat,
              "premium_exact_score": best_score,
              "bestHighExactScore": best_score,
              "bestScoreOdd": best_odd,
              "targetOdds": sorted_targets,
              "_prio": 0 if code in TOP_5_CODES else 1,
          })
      except Exception:
        continue

  candidates.sort(key=lambda x: (x.get("_prio", 1), x["bestScoreOdd"]))
  picks = candidates[:LIMIT_HIGH_GOALS]
  for p in picks:
    p.pop("_prio", None)
  return picks


def main():
  try:
    picks = fetch_high_goal_matches()
    status = f"OK ({len(picks)})"
  except Exception as e:
    picks = []
    status = str(e)[:120]

  with open("high_goals.json", "w", encoding="utf-8") as f:
    json.dump(
        {
            "updated_at_Nigeria": datetime.now(WAT_TZ).strftime(
                "%Y-%m-%d %I:%M %p WAT"
            ),
            "status": status,
            "count": len(picks),
            "picks": picks,
        },
        f,
        indent=2,
    )


if __name__ == "__main__":
  main()
