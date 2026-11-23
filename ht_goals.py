from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import time

LIMIT_HT_GOALS = 5
WAT_TZ = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)
TOP_5_LEAGUE_IDS = (
    39,
    140,
    135,
    78,
    61,
    2,
)  # EPL, La Liga, Serie A, Bundesliga, Ligue 1, UCL

TARGET_HT_SCORES = {
    "1 - 1",
    "2 - 0",
    "0 - 2",
    "2 - 1",
    "1 - 2",
    "2 - 2",
    "3 - 0",
    "0 - 3",
    "3 - 1",
    "1 - 3",
}


def resolve_ip(host):
  ip_addr = ".".join(["8", "8", "8", "8"])
  url = f"https://{ip_addr}/resolve?name={host}&type=A"
  res = subprocess.run(
      [
          "curl",
          "-sS",
          "-k",
          "-m",
          "8",
          "-H",
          "Accept: application/dns-json",
          url,
      ],
      capture_output=True,
      text=True,
  )
  if res.returncode == 0 and res.stdout.strip():
    for ans in json.loads(res.stdout).get("Answer", []):
      if ans.get("type") == 1:
        return ans["data"]
  return None


def get_json(host, path, headers=None):
  ip = resolve_ip(host)
  cmd = [
      "curl",
      "-sS",
      "-L",
      "-m",
      "12",
      "-H",
      "Accept: application/json",
      "-H",
      "User-Agent: Mozilla/5.0",
  ]
  if ip:
    cmd.extend(["--resolve", f"{host}:443:{ip}"])
  if headers:
    for k, v in headers.items():
      cmd.extend(["-H", f"{k}: {v}"])
  res = subprocess.run(cmd + [f"https://{host}{path}"], capture_output=True, text=True)
  if res.returncode != 0:
    raise RuntimeError(res.stderr.strip() or "curl failed")
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
    if dt_utc <= datetime.now(timezone.utc):
      return None
    return dt_utc.astimezone(WAT_TZ).strftime("%Y-%m-%d %I:%M %p WAT")
  except Exception:
    return None


def pick_best_ht_score(values_list):
  best_odd = 9999.0
  best_score = None
  ht_odds = {}

  for v in values_list:
    val_str = str(v.get("value", "")).replace(":", "-").strip()
    try:
      odd_num = float(v.get("odd", 9999))
    except Exception:
      odd_num = 9999.0

    parts = val_str.split("-")
    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
      hg, ag = map(int, parts)
      formatted = f"{hg} - {ag}"
      if formatted in TARGET_HT_SCORES:
        ht_odds[formatted] = odd_num
        if odd_num < best_odd:
          best_odd = odd_num
          best_score = formatted

  sorted_ht = dict(sorted(ht_odds.items(), key=lambda item: item[1]))
  return best_score, best_odd, sorted_ht


def fetch_ht_goal_matches():
  key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
  if not key:
    raise ValueError("Missing API_FOOTBALL_KEY")

  host = ".".join(["v3", "football", "api-sports", "io"])
  hdr = {"x-apisports-key": key}
  now_utc = datetime.now(timezone.utc)
  today = now_utc.strftime("%Y-%m-%d")
  tomorrow = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")

  fixtures = []
  seen_ids = set()

  # 1. Top 5 Leagues First
  for lg in TOP_5_LEAGUE_IDS:
    try:
      resp = (
          get_json(host, f"/fixtures?league={lg}&status=NS&next=2", hdr).get(
              "response"
          )
          or []
      )
      for f in resp:
        fid = (f.get("fixture") or {}).get("id")
        if (
            fid
            and fid not in seen_ids
            and format_wat((f.get("fixture") or {}).get("date", "")) is not None
        ):
          seen_ids.add(fid)
          f["_prio"] = 0
          fixtures.append(f)
    except Exception:
      continue

  # 2. All Leagues Worldwide (Today + Tomorrow)
  for check_date in (today, tomorrow):
    try:
      resp = (
          get_json(host, f"/fixtures?date={check_date}&status=NS", hdr).get(
              "response"
          )
          or []
      )
      for f in resp:
        fid = (f.get("fixture") or {}).get("id")
        if (
            fid
            and fid not in seen_ids
            and format_wat((f.get("fixture") or {}).get("date", "")) is not None
        ):
          seen_ids.add(fid)
          f["_prio"] = (
              0 if (f.get("league") or {}).get("id") in TOP_5_LEAGUE_IDS else 1
          )
          fixtures.append(f)
    except Exception:
      continue

  candidates = []
  for item in fixtures[:8]:
    wat = format_wat((item.get("fixture") or {}).get("date", ""))
    if not wat:
      continue

    fix_id = (item.get("fixture") or {}).get("id")
    league = (item.get("league") or {}).get("name", "Football")
    teams = item.get("teams") or {}
    home = (teams.get("home") or {}).get("name", "Home")
    away = (teams.get("away") or {}).get("name", "Away")

    try:
      odds_resp = (
          get_json(host, f"/odds?fixture={fix_id}&bet=31", hdr).get("response")
          or []
      )
      if not odds_resp:
        time.sleep(0.5)
        continue

      bms = next(iter(odds_resp), {}).get("bookmakers") or []
      best_score = None
      best_odd = 9999.0
      ht_odds = {}

      for bm in bms:
        for bet in bm.get("bets") or []:
          sc, od, h_map = pick_best_ht_score(bet.get("values") or [])
          if sc and od < best_odd:
            best_score, best_odd, ht_odds = sc, od, h_map

      if best_score and best_odd < 9000:
        candidates.append({
            "league": league,
            "match": f"{home} vs {away}",
            "kickoff_Nigeria": wat,
            "premium_exact_score": best_score,
            "bestHalfTimeHighScore": best_score,
            "bestScoreOdd": best_odd,
            "htTargetOdds": ht_odds,
            "_prio": item.get("_prio", 1),
        })
      time.sleep(0.5)
    except Exception:
      continue

  candidates.sort(key=lambda x: (x.get("_prio", 1), x["bestScoreOdd"]))
  picks = candidates[:LIMIT_HT_GOALS]
  for p in picks:
    p.pop("_prio", None)
  return picks


def main():
  try:
    picks = fetch_ht_goal_matches()
    status = f"OK ({len(picks)})"
  except Exception as e:
    picks = []
    status = str(e)[:120]

  with open("ht_goals.json", "w", encoding="utf-8") as f:
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
