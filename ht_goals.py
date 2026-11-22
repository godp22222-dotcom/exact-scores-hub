import os
import json
import subprocess
from datetime import datetime, timezone, timedelta

LIMIT_HT_GOALS = 5
WAT_TZ = timezone(timedelta(hours=1))  # Nigeria Time (UTC+1)

# High-scoring First Half (HT) exact scores (2+ first-half goals)
TARGET_HT_SCORES = {
    "1 - 1",
    "2 - 0", "0 - 2",
    "2 - 1", "1 - 2",
    "2 - 2",
    "3 - 0", "0 - 3",
    "3 - 1", "1 - 3"
}


def resolve_ip(host):
    ip_addr = ".".join(["8", "8", "8", "8"])
    url = f"https://{ip_addr}/resolve?name={host}&type=A"
    res = subprocess.run(
        ["curl", "-sS", "-k", "-m", "8", "-H", "Accept: application/dns-json", url],
        capture_output=True, text=True
    )
    if res.returncode == 0 and res.stdout.strip():
        for ans in json.loads(res.stdout).get("Answer", []):
            if ans.get("type") == 1:
                return ans["data"]
    return None


def get_json(host, path, headers=None):
    ip = resolve_ip(host)
    cmd = ["curl", "-sS", "-L", "-m", "12", "-H", "Accept: application/json", "-H", "User-Agent: Mozilla/5.0"]
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
    """Finds the lowest-odds high-scoring First Half exact score (2+ goals in 1st half)."""
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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    resp_data = get_json(host, f"/fixtures?date={today}&status=NS", hdr)
    errors = resp_data.get("errors")
    if errors:
        raise RuntimeError(f"API-Football limit/error: {errors}")

    fixtures = resp_data.get("response") or []
    candidates = []

    # Scan up to 15 upcoming fixtures to stay within API-Football's daily free quota
    for item in fixtures[:15]:
        wat = format_wat((item.get("fixture") or {}).get("date", ""))
        if not wat:
            continue

        fix_id = (item.get("fixture") or {}).get("id")
        league = (item.get("league") or {}).get("name", "Football")
        teams = item.get("teams") or {}
        home = (teams.get("home") or {}).get("name", "Home")
        away = (teams.get("away") or {}).get("name", "Away")

        try:
            # bet=31 is First-Half Exact Score on API-Football
            odds_resp = get_json(host, f"/odds?fixture={fix_id}&bet=31", hdr).get("response") or []
            if not odds_resp:
                continue
            bms = next(iter(odds_resp), {}).get("bookmakers") or []
            if not bms:
                continue
            bets = next(iter(bms), {}).get("bets") or []
            if not bets:
                continue

            best_score, best_odd, ht_odds = pick_best_ht_score(next(iter(bets), {}).get("values") or [])
            if best_score:
                candidates.append({
                    "league": league,
                    "match": f"{home} vs {away}",
                    "kickoff_Nigeria": wat,
                    "bestHalfTimeHighScore": best_score,
                    "bestScoreOdd": best_odd,
                    "htTargetOdds": ht_odds
                })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["bestScoreOdd"])
    return candidates[:LIMIT_HT_GOALS]


def main():
    try:
        picks = fetch_ht_goal_matches()
        status = f"OK ({len(picks)})"
    except Exception as e:
        picks = []
        status = str(e)[:120]

    with open("ht_goals.json", "w", encoding="utf-8") as f:
        json.dump({
            "updated_at_Nigeria": datetime.now(WAT_TZ).strftime("%Y-%m-%d %I:%M %p WAT"),
            "status": status,
            "count": len(picks),
            "picks": picks
        }, f, indent=2)


if __name__ == "__main__":
    main()
