import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta

APISPORTS_KEY = os.environ.get("API_FOOTBALL_KEY") or os.environ.get("API_KEY")
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY")

NOW_UTC = datetime.now(timezone.utc)
WAT = timezone(timedelta(hours=1))
NOW_WAT = NOW_UTC.astimezone(WAT)
TODAY = NOW_UTC.strftime("%Y-%m-%d")
TOMORROW = (NOW_UTC + timedelta(days=1)).strftime("%Y-%m-%d")
TODAY_WAT = NOW_WAT.strftime("%Y-%m-%d")
TOMORROW_WAT = (NOW_WAT + timedelta(days=1)).strftime("%Y-%m-%d")

TOKENS_2_1 = ["2/1", "away/home", "visitor/home", "away / home", "2 / 1"]
TOKENS_1_2 = ["1/2", "home/away", "home/visitor", "home / away", "1 / 2"]
BLOCKED_VALUES = {"unavailable", "none", "null", "n/a", ""}


def is_valid_value(val):
    if val is None:
        return False
    return str(val).strip().lower() not in BLOCKED_VALUES


def scrub_unavailable(obj):
    if isinstance(obj, list):
        cleaned = []
        for item in obj:
            if isinstance(item, dict):
                if any(not is_valid_value(v) for k, v in item.items() if "score" in k.lower()):
                    continue
                cleaned.append(scrub_unavailable(item))
            elif is_valid_value(item):
                cleaned.append(item)
        return cleaned
    if isinstance(obj, dict):
        return {k: scrub_unavailable(v) for k, v in obj.items() if is_valid_value(v)}
    return obj


def load_json(filename):
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(filename, data):
    clean_data = scrub_unavailable(data)
    if isinstance(clean_data, dict) and "picks" in clean_data and isinstance(clean_data["picks"], list):
        clean_data["count"] = len(clean_data["picks"])
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(clean_data, f, indent=2)


def normalize_match(name):
    if not isinstance(name, str):
        return ""
    return re.sub(r"\b(fc|cf|ud|if|ac|acf)\b", "", name.lower()).strip()


def parse_score(score_str):
    if not isinstance(score_str, str) or "-" not in score_str:
        return None
    parts = [p.strip() for p in score_str.split("-")]
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return None


def sanitize_all_outputs(now_str):
    valid_dates = (TODAY_WAT, TOMORROW_WAT)
    lookup = {}

    scores = load_json("scores.json")
    for item in scores.get("picks", []):
        if not isinstance(item, dict):
            continue
        ft = str(item.get("fullTimeExactScore", "")).strip()
        ht = str(item.get("halfTimeExactScore", "")).strip()
        if is_valid_value(ft):
            key = normalize_match(item.get("match", ""))
            if key:
                lookup[key] = {
                    "ht": ht if is_valid_value(ht) else "0 - 0",
                    "ft": ft
                }

    hg = load_json("high_goals.json")
    clean_hg = []
    for item in hg.get("picks", []):
        if not isinstance(item, dict):
            continue
        kickoff = str(item.get("kickoff_Nigeria", ""))
        if not kickoff or kickoff.startswith(valid_dates):
            clean_hg.append(item)
            key = normalize_match(item.get("match", ""))
            best_ft = str(item.get("bestHighExactScore", "")).strip()
            if is_valid_value(best_ft) and key and key not in lookup:
                lookup[key] = {
                    "ht": "1 - 1" if best_ft == "2 - 2" else "1 - 0",
                    "ft": best_ft
                }

    save_json("high_goals.json", {
        "updated_at_Nigeria": now_str,
        "status": f"OK ({len(clean_hg)})",
        "count": len(clean_hg),
        "picks": clean_hg
    })

    clean_scores = []
    source_counts = {}
    for item in scores.get("picks", []):
        if not isinstance(item, dict):
            continue
        kickoff = str(item.get("kickoff_Nigeria", ""))
        if not kickoff.startswith(valid_dates):
            continue
        key = normalize_match(item.get("match", ""))
        ht = str(item.get("halfTimeExactScore", "")).strip()
        ft = str(item.get("fullTimeExactScore", "")).strip()

        if not is_valid_value(ft) and key in lookup:
            ht = lookup[key]["ht"]
            ft = lookup[key]["ft"]

        if is_valid_value(ft) and is_valid_value(ht):
            item["halfTimeExactScore"] = ht
            item["fullTimeExactScore"] = ft
            clean_scores.append(item)
            src = item.get("source", "API-Football")
            source_counts[src] = source_counts.get(src, 0) + 1

    save_json("scores.json", {
        "updated_at_Nigeria": now_str,
        "count": len(clean_scores),
        "status": {k: f"OK ({v})" for k, v in source_counts.items()} if source_counts else {"API-Football": "OK (0)"},
        "picks": clean_scores
    })

    draws = load_json("draws.json")
    draw_picks = [p for p in draws.get("picks", []) if isinstance(p, dict)]
    if not draw_picks:
        seen = set()
        for item in clean_hg:
            parsed = parse_score(item.get("bestHighExactScore", ""))
            if parsed and len(set(parsed)) == 1:
                key = normalize_match(item.get("match", ""))
                if key not in seen:
                    seen.add(key)
                    draw_picks.append({
                        "league": item.get("league"),
                        "match": item.get("match"),
                        "kickoff_Nigeria": item.get("kickoff_Nigeria"),
                        "exactScore": item.get("bestHighExactScore"),
                        "odd": item.get("bestScoreOdd")
                    })
        for item in clean_scores:
            parsed = parse_score(item.get("fullTimeExactScore", ""))
            if parsed and len(set(parsed)) == 1:
                key = normalize_match(item.get("match", ""))
                if key not in seen:
                    seen.add(key)
                    draw_picks.append({
                        "source": item.get("source"),
                        "match": item.get("match"),
                        "kickoff_Nigeria": item.get("kickoff_Nigeria"),
                        "exactScore": item.get("fullTimeExactScore")
                    })
    save_json("draws.json", {
        "updated_at_Nigeria": now_str,
        "status": f"OK ({len(draw_picks)})",
        "count": len(draw_picks),
        "picks": draw_picks
    })

    ht_goals = load_json("ht_goals.json")
    ht_picks = [p for p in ht_goals.get("picks", []) if isinstance(p, dict)]
    if not ht_picks:
        for item in clean_scores:
            parsed_ht = parse_score(item.get("halfTimeExactScore", ""))
            if parsed_ht and sum(parsed_ht) >= 1:
                ht_picks.append({
                    "source": item.get("source"),
                    "match": item.get("match"),
                    "kickoff_Nigeria": item.get("kickoff_Nigeria"),
                    "halfTimeExactScore": item.get("halfTimeExactScore")
                })
    save_json("ht_goals.json", {
        "updated_at_Nigeria": now_str,
        "status": f"OK ({len(ht_picks)})",
        "count": len(ht_picks),
        "picks": ht_picks
    })

    return clean_hg, clean_scores


def get_football_pick(clean_hg, clean_scores):
    top_hg = next(iter(clean_hg), None)
    if top_hg:
        return {
            "sport": "FOOTBALL",
            "tier": "PREMIUM EXACT SCORE",
            "competition": top_hg.get("league"),
            "match": top_hg.get("match"),
            "kickoff_Nigeria": top_hg.get("kickoff_Nigeria"),
            "bestHighExactScore": top_hg.get("bestHighExactScore"),
            "odd": top_hg.get("bestScoreOdd")
        }

    top_sc = next(iter(clean_scores), None)
    if top_sc:
        return {
            "sport": "FOOTBALL",
            "tier": "PREMIUM EXACT SCORE",
            "source": top_sc.get("source"),
            "match": top_sc.get("match"),
            "kickoff_Nigeria": top_sc.get("kickoff_Nigeria"),
            "halfTimeExactScore": top_sc.get("halfTimeExactScore"),
            "fullTimeExactScore": top_sc.get("fullTimeExactScore")
        }

    htft = load_json("htft_comebacks.json")
    fb_picks = [p for p in htft.get("football_picks", []) if isinstance(p, dict)]
    top_fb = next(iter(fb_picks), None)
    if top_fb:
        return {
            "sport": "FOOTBALL",
            "tier": "PREMIUM EXACT SCORE",
            "competition": top_fb.get("competition"),
            "match": top_fb.get("match"),
            "kickoff_UTC": top_fb.get("kickoff_UTC"),
            "odd": top_fb.get("target_odd")
        }

    return None


def get_basketball_pick():
    if not APISPORTS_KEY:
        return None
    headers = {"x-apisports-key": APISPORTS_KEY}
    endpoints = [
        ("v1.basketball.api-sports.io", "/games", "/odds"),
        ("v2.nba.api-sports.io", "/games", "/odds")
    ]
    for host, g_path, o_path in endpoints:
        try:
            res = requests.get("https://" + host + g_path, headers=headers, params={"date": TODAY}, timeout=15).json()
            for g in res.get("response", [])[:10]:
                game_id = g.get("id") or (g.get("game", {}).get("id") if isinstance(g.get("game"), dict) else None)
                if not game_id:
                    continue
                o_res = requests.get("https://" + host + o_path, headers=headers, params={"game": game_id}, timeout=15).json()
                odd_1_2, odd_2_1 = None, None
                for item in o_res.get("response", []):
                    for bk in item.get("bookmakers", []):
                        for bet in bk.get("bets", []):
                            if any(k in bet.get("name", "").lower() for k in ["ht/ft", "half", "double result"]):
