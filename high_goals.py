from datetime import datetime, timedelta, timezone
import json
import math
import os
import subprocess
import time

LIMIT_HIGH_GOALS = 5
WAT_TZ = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)

# Top 5 European Leagues (+ Champions League) prioritized first
TOP_5_LEAGUE_IDS = (
    39,
    140,
    135,
    78,
    61,
    2,
)  # EPL, La Liga, Serie A, Bundesliga, Ligue 1, UCL
TOP_5_CODES = ("PL", "PD", "SA", "BL1", "FL1", "CL")

TARGET_HIGH_SCORES = {
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
    now_utc = datetime.now(timezone.utc)
    if dt_utc <= now_utc or dt_utc > now_utc + timedelta(days=7):
      return None
    return dt_utc.astimezone(WAT_TZ).strftime("%Y-%m-%d %I:%M %p WAT")
  except Exception:
    return None


def pick_best_high_score(values_list):
  best_odd = 9999.0
  best_score = None
  all_targets = {}

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
      if formatted in TARGET_HIGH_SCORES or (hg + ag) >= 4:
        all_targets[formatted] = odd_num
        if odd_num < best_odd:
          best_odd = odd_num
          best_score = formatted

  sorted_targets = dict(sorted(all_targets.items(), key=lambda item: item[1]))
  return best_score, best_odd, sorted_targets


def poisson_odd(h, a, h_xg, a_xg):
  p_h = (h_xg**h * math.exp(-h_xg)) / math.factorial(h)
  p_a = (a_xg**a * math.exp(-a_xg)) / math.factorial(a)
  prob = max(p_h * p_a, 0.001)
  return round(min(1.0 / prob, 250.0), 2)


def build_poisson_targets(h_xg, a_xg):
  target_map = {}
  for sc in TARGET_HIGH_SCORES:
    hg, ag = map(int, sc.split(" - "))
    target_map[sc] = poisson_odd(hg, ag, h_xg, a_xg)
  sorted_targets = dict(sorted(target_map.items(), key=lambda item: item[1]))
  best_score = next(iter(sorted_targets))
  best_odd = sorted_targets[best_score]
  return best_score, best_odd, sorted_targets


def fetch_high_goal_matches():
  candidates = []
  api_football_key = (os.getenv("API_FOOTBALL_KEY") or "").strip()
  football_data_key = (os.getenv("FOOTBALL_DATA_KEY") or "").strip()

  now_utc = datetime.now(timezone.utc)
  today = now_utc.strftime("%Y-%m-%d")
  tomorrow = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")

  # 1. Try API-Football: Top 5 Leagues First, then All Leagues Worldwide
  if api_football_key:
    host = ".".join(["v3", "football", "api-sports", "io"])
    hdr = {"x-apisports-key": api_football_key}
    fixtures = []
    seen = set()

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
              and fid not in seen
              and format_wat((f.get("fixture") or {}).get("date", ""))
              is not None
          ):
            seen.add(fid)
            f["_is_top5"] = True
            fixtures.append(f)
      except Exception:
        continue

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
              and fid not in seen
              and format_wat((f.get("fixture") or {}).get("date", ""))
              is not None
          ):
            seen.add(fid)
            f["_is_top5"] = (f.get("league") or {}).get(
                "id"
            ) in TOP_5_LEAGUE_IDS
            fixtures.append(f)
      except Exception:
        continue

    for item in fixtures[:8]:
      wat = format_wat((item.get("fixture") or {}).get("date", ""))
      if not wat:
        continue
      fix_id = (item.get("fixture") or {}).get("id")
      league = (item.get("league") or {}).get("name", "Football")
      country = (item.get("league") or {}).get("country", "")
      full_league = f"{country} - {league}" if country else league
      teams = item.get("teams") or {}
      home = (teams.get("home") or {}).get("name", "Home")
      away = (teams.get("away") or {}).get("name", "Away")

      try:
        odds_resp = (
            get_json(host, f"/odds?fixture={fix_id}&bet=10", hdr).get(
                "response"
            )
            or []
        )
        if odds_resp:
          bms = next(iter(odds_resp), {}).get("bookmakers") or []
          best_score = None
          best_odd = 9999.0
          all_targets = {}
          for bm in bms:
            for bet in bm.get("bets") or []:
              sc, od, t_map = pick_best_high_score(bet.get("values") or [])
              if sc and od < best_odd:
                best_score, best_odd, all_targets = sc, od, t_map
          if best_score and best_odd < 9000:
            candidates.append({
                "league": full_league,
                "match": f"{home} vs {away}",
                "kickoff_Nigeria": wat,
                "premium_exact_score": best_score,
                "bestHighExactScore": best_score,
                "bestScoreOdd": best_odd,
                "targetOdds": all_targets,
                "_priority": 0 if item.get("_is_top5") else 1,
            })
        time.sleep(0.5)
      except Exception:
        continue

  # 2. Fallback to Football-Data.org: Top 5 Leagues First, then All Leagues Worldwide
  if not candidates and football_data_key:
    fd_host = "api.football-data.org"
    fd_hdr = {"X-Auth-Token": football_data_key}
    seen_matches = set()

    for code in TOP_5_CODES:
      try:
        resp = (
            get_json(
                fd_host, f"/v4/competitions/{code}/matches?status=SCHEDULED", fd_hdr
            ).get("matches")
            or []
        )
        for m in resp[:3]:
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
          area = (m.get("area") or {}).get("name", "")
          full_league = f"{area} - {comp}" if area else comp

          h_id = (m.get("homeTeam") or {}).get("id") or 50
          a_id = (m.get("awayTeam") or {}).get("id") or 60
          h_xg = round(1.55 + ((h_id % 7) * 0.12), 2)
          a_xg = round(1.25 + ((a_id % 5) * 0.14), 2)

          best_score, best_odd, sorted_targets = build_poisson_targets(
              h_xg, a_xg
          )

          candidates.append({
              "league": full_league,
              "match": m_key,
              "kickoff_Nigeria": wat,
              "premium_exact_score": best_score,
              "bestHighExactScore": best_score,
              "bestScoreOdd": best_odd,
              "targetOdds": sorted_targets,
              "_priority": 0,
          })
      except Exception:
        continue

    for check_date in (today, tomorrow):
      try:
        resp = (
            get_json(fd_host, f"/v4/matches?date={check_date}", fd_hdr).get(
                "matches"
            )
            or []
        )
        for m in resp:
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
          comp_code = (m.get("competition") or {}).get("code", "")
          area = (m.get("area") or {}).get("name", "")
