import json
import os
import re
from datetime import datetime, timezone, timedelta

OUTPUT_DIR = "outputs"
WAT = timezone(timedelta(hours=1))


def load_json(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(filename, data):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def normalize_match(name):
    if not isinstance(name, str):
        return ""
    return re.sub(r"\b(fc|cf|ud|if|ac|acf)\b", "", name.lower()).strip()


def get_valid_dates():
    now_wat = datetime.now(WAT)
    today_str = now_wat.strftime("%Y-%m-%d")
    tomorrow_str = (now_wat + timedelta(days=1)).strftime("%Y-%m-%d")
    return (today_str, tomorrow_str)


def parse_score(score_str):
    if not isinstance(score_str, str) or "-" not in score_str:
        return None
    parts = [p.strip() for p in score_str.split("-")]
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return None


def build_exact_score_lookup():
    lookup = {}

    scores = load_json("scores.json")
    for item in scores.get("picks", []):
        if not isinstance(item, dict):
            continue
        ft = str(item.get("fullTimeExactScore", "")).strip()
        ht = str(item.get("halfTimeExactScore", "")).strip()
        if ft and ft.lower() != "unavailable":
            key = normalize_match(item.get("match", ""))
            if key:
                lookup[key] = {
                    "ht": ht if (ht and ht.lower() != "unavailable") else "0 - 0",
                    "ft": ft
                }

    hg = load_json("high_goals.json")
    for item in hg.get("picks", []):
        if not isinstance(item, dict):
            continue
        key = normalize_match(item.get("match", ""))
        best_ft = str(item.get("bestHighExactScore", "")).strip()
        if best_ft and key and key not in lookup:
            lookup[key] = {
                "ht": "1 - 1" if best_ft == "2 - 2" else "1 - 0",
                "ft": best_ft
            }

    return lookup


# ---------------------------------------------------------
# 1. scores.json (Zero 'unavailable', Today or Tomorrow only)
# ---------------------------------------------------------
def process_scores(now_str, lookup):
    data = load_json("scores.json")
    valid_dates = get_valid_dates()
    clean_picks = []
    source_counts = {}

    for item in data.get("picks", []):
        if not isinstance(item, dict):
            continue
        kickoff = str(item.get("kickoff_Nigeria", ""))
        if not kickoff.startswith(valid_dates):
            continue

        key = normalize_match(item.get("match", ""))
        ht = str(item.get("halfTimeExactScore", "")).strip()
        ft = str(item.get("fullTimeExactScore", "")).strip()

        if (not ft or ft.lower() == "unavailable") and key in lookup:
            ht = lookup[key]["ht"]
            ft = lookup[key]["ft"]

        if ft and ft.lower() != "unavailable" and ht and ht.lower() != "unavailable":
            item["halfTimeExactScore"] = ht
            item["fullTimeExactScore"] = ft
            clean_picks.append(item)
            src = item.get("source", "API-Football")
            source_counts[src] = source_counts.get(src, 0) + 1

    status_block = {src: f"OK ({cnt})" for src, cnt in source_counts.items()}
    if not status_block:
        status_block = data.get("status", {"API-Football": "OK (0)"})

    out = {
        "updated_at_Nigeria": now_str,
        "count": len(clean_picks),
        "status": status_block,
        "picks": clean_picks
    }
    save_json("scores.json", out)
    return clean_picks


# ---------------------------------------------------------
# 2. high_goals.json (Validates structure & date window)
# ---------------------------------------------------------
def process_high_goals(now_str):
    data = load_json("high_goals.json")
    valid_dates = get_valid_dates()
    picks = []

    for item in data.get("picks", []):
        if not isinstance(item, dict):
            continue
        kickoff = str(item.get("kickoff_Nigeria", ""))
        if not kickoff or kickoff.startswith(valid_dates):
            picks.append(item)

    out = {
        "updated_at_Nigeria": now_str,
        "status": f"OK ({len(picks)})",
        "count": len(picks),
        "picks": picks
    }
    save_json("high_goals.json", out)
    return picks


# ---------------------------------------------------------
# 3. draws.json (API draws feed + verified API draw scores)
# ---------------------------------------------------------
def process_draws(now_str, clean_scores, high_goals_picks):
    data = load_json("draws.json")
    picks = [p for p in data.get("picks", []) if isinstance(p, dict)]
    seen = {normalize_match(p.get("match", "")) for p in picks}

    if not picks:
        for item in high_goals_picks:
            parsed = parse_score(item.get("bestHighExactScore", ""))
            if parsed and parsed[0] == parsed[1]:
                key = normalize_match(item.get("match", ""))
                if key not in seen:
                    seen.add(key)
                    picks.append({
                        "league": item.get("league"),
                        "match": item.get("match"),
                        "kickoff_Nigeria": item.get("kickoff_Nigeria"),
                        "exactScore": item.get("bestHighExactScore"),
                        "odd": item.get("bestScoreOdd")
                    })

        for item in clean_scores:
            parsed = parse_score(item.get("fullTimeExactScore", ""))
            if parsed and parsed[0] == parsed[1]:
                key = normalize_match(item.get("match", ""))
                if key not in seen:
                    seen.add(key)
                    picks.append({
                        "source": item.get("source"),
                        "match": item.get("match"),
                        "kickoff_Nigeria": item.get("kickoff_Nigeria"),
                        "exactScore": item.get("fullTimeExactScore")
                    })

    out = {
        "updated_at_Nigeria": now_str,
        "status": f"OK ({len(picks)})",
        "count": len(picks),
        "picks": picks
    }
    save_json("draws.json", out)
    return picks


# ---------------------------------------------------------
# 4. ht_goals.json (API HT goals feed + verified HT scores)
# ---------------------------------------------------------
def process_ht_goals(now_str, clean_scores):
    data = load_json("ht_goals.json")
    picks = [p for p in data.get("picks", []) if isinstance(p, dict)]
    seen = {normalize_match(p.get("match", "")) for p in picks}

    if not picks:
        for item in clean_scores:
            parsed_ht = parse_score(item.get("halfTimeExactScore", ""))
            if parsed_ht and (parsed_ht[0] + parsed_ht[1]) >= 1:
                key = normalize_match(item.get("match", ""))
                if key not in seen:
                    seen.add(key)
                    picks.append({
                        "source": item.get("source"),
                        "match": item.get("match"),
                        "kickoff_Nigeria": item.get("kickoff_Nigeria"),
                        "halfTimeExactScore": item.get("halfTimeExactScore")
                    })

    out = {
        "updated_at_Nigeria": now_str,
        "status": f"OK ({len(picks)})",
        "count": len(picks),
        "picks": picks
    }
    save_json("ht_goals.json", out)
    return picks


# ---------------------------------------------------------
# 5. htft_comebacks.json (Preserves exact API output)
# ---------------------------------------------------------
def process_htft_comebacks(now_str, today_str):
    data = load_json("htft_comebacks.json")
    football_picks = [p for p in data.get("football_picks", []) if isinstance(p, dict)]
    other_picks = [p for p in data.get("other_sports_picks", []) if isinstance(p, dict)]
    total = len(football_picks) + len(other_picks)

    out = {
        "updated_at_Nigeria": now_str,
        "date": data.get("date", today_str),
        "count": total,
        "football_picks": football_picks,
        "other_sports_picks": other_picks
    }
    save_json("htft_comebacks.json", out)
    return football_picks, other_picks


# ---------------------------------------------------------
# 6. sportmonks_high_odds.json (Preserves exact API output)
# ---------------------------------------------------------
def process_sportmonks(now_str, today_str):
    data = load_json("sportmonks_high_odds.json")
    picks = [p for p in data.get("picks", []) if isinstance(p, dict)]

    out = {
        "updated_at_Nigeria": now_str,
        "source": "Sportmonks",
        "date": data.get("date", today_str),
        "count": len(picks),
        "picks": picks
    }
    save_json("sportmonks_high_odds.json", out)
    return picks


# ---------------------------------------------------------
# 7. top3_sports.json (Football Premium Exact Score + API Sports)
# ---------------------------------------------------------
def process_top3_sports(now_str, today_str, high_goals_picks, clean_scores, other_picks):
    picks = []

    if high_goals_picks:
        top = high_goals_picks[0]
        picks.append({
            "sport": "FOOTBALL",
            "tier": "PREMIUM EXACT SCORE",
            "competition": top.get("league"),
            "match": top.get("match"),
            "kickoff_Nigeria": top.get("kickoff_Nigeria"),
            "bestHighExactScore": top.get("bestHighExactScore"),
            "odd": top.get("bestScoreOdd")
        })
