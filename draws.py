from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import time

LIMIT_DRAWS = 5
WAT_TZ = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)
PREMIER_LEAGUE_ID = 39
OTHER_TOP_LEAGUES = (140, 135, 78, 2)  # La Liga, Serie A, Bundesliga, UCL


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


def pick_best_draw(values_list):
  best_odd = 9999.0
  best_score = None
  draw_odds = {}

  for v in values_list:
    val_str = str(v.get("value", "")).replace(":", "-").strip()
    try:
      odd_num = float(v.get("odd", 9999))
    except Exception:
      odd_num = 9999.0

    parts = val_str.split("-")
    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
      hg, ag = map(int, parts)
      if hg == ag:  # 0-0, 1-1, 2-2, 3-3, 4-4, 5-5, 6-6, 7-7 and above
        formatted = f"{hg} - {ag}"
        draw_odds[formatted] = odd_num
        if odd_num < best_odd:
          best_odd = odd_num
          best_score = formatted

  sorted_draws = dict(sorted(draw_odds.items(), key=lambda item: item))
  return best_score, best_odd, sorted_draws


def fetch_draw_matches():
  key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
  if not key:
    raise ValueError("Missing API_FOOTBALL_KEY")

  host = ".".join(["v3", "football", "api-sports", "io"])
  hdr = {"x-apisports-key": key}
  today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

  fixtures = []
  seen_ids = set()

  # 1. Always fetch upcoming Premier League fixtures first
  try:
    epl_fix = (
        get_json(
            host, f"/fixtures?league={PREMIER_LEAGUE_ID}&status=NS&next=5", hdr
        ).get("response")
        or []
    )
    for f in epl_fix:
      fid = (f.get("fixture") or {}).get("id")
      if fid and fid not in seen_ids:
        seen_ids.add(fid)
        fixtures.append(f)
  except Exception:
    pass

  # 2. Add today's unstarted fixtures
  try:
    today_fix = (
        get_json(host, f"/fixtures?date={today}&status=NS", hdr).get("response")
        or []
    )
    for f in today_fix:
      fid = (f.get("fixture") or {}).get("id")
      if (
          fid
          and fid not in seen_ids
          and format_wat((f.get("fixture") or {}).get("date", "")) is not None
      ):
        seen_ids.add(fid)
        fixtures.append(f)
  except Exception:
    pass

  # 3. Fill remaining slots with top European leagues if needed
  if len(fixtures) < 8:
    for lg in OTHER_TOP_LEAGUES:
      try:
        lg_fix = (
            get_json(host, f"/fixtures?league={lg}&status=NS&next=2", hdr).get(
                "response"
            )
            or []
        )
        for f in lg_fix:
          fid = (f.get("fixture") or {}).get("id")
          if fid and fid not in seen_ids:
            seen_ids.add(fid)
            fixtures.append(f)
        if len(fixtures) >= 8:
          break
      except Exception:
        continue

  candidates = []
  for item in fixtures[:8]:
    wat = format_wat((item.get("fixture") or {}).get("date", ""))
    if not wat:
      continue

    fix_id = (item.get("fixture") or {}).get("id")
    league = (item.get("league") or {}).get("name", "Premier League")
    teams = item.get("teams") or {}
    home = (teams.get("home") or {}).get("name", "Home")
    away = (teams.get("away") or {}).get("name", "Away")

    try:
      odds_resp = (
          get_json(host, f"/odds?fixture={fix_id}&bet=10", hdr).get("response")
          or []
      )
      if not odds_resp:
        time.sleep(0.6)
        continue

      bms = next(iter(odds_resp), {}).get("bookmakers") or []
      best_score = None
      best_odd = 9999.0
      draw_odds = {}

      for bm in bms:
        for bet in bm.get("bets") or []:
          sc, od, d_map = pick_best_draw(bet.get("values") or [])
          if sc and od < best_odd:
            best_score, best_odd, draw_odds = sc, od, d_map

      if best_score and best_odd < 9000:
        candidates.append({
            "league": league,
            "match": f"{home} vs {away}",
            "kickoff_Nigeria": wat,
            "premium_exact_score": best_score,
            "bestDrawExactScore": best_score,
            "bestDrawOdd": best_odd,
            "drawOdds": draw_odds,
        })
      time.sleep(0.6)
    except Exception:
      continue

  candidates.sort(key=lambda x: x["bestDrawOdd"])
  return candidates[:LIMIT_DRAWS]


def main():
  try:
    picks = fetch_draw_matches()
    status = f"OK ({len(picks)})"
  except Exception as e:
    picks = []
    status = str(e)[:120]

  with open("draws.json", "w", encoding="utf-8") as f:
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
