import os
import json
import requests
from datetime import datetime, timezone

SPORTMONKS_TOKEN = (os.environ.get("SPORTMONKS_TOKEN") or "").strip()
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

url = f"https://sportmonks.com{today}?api_token={SPORTMONKS_TOKEN}&include=participants;league;predictions"

try:
    res = requests.get(url, timeout=25).json()
except Exception as e:
    res = {"error": str(e)}

predictions_list = []

for fixture in res.get("data", []):
    participants = fixture.get("participants", [])
    home = next((p.get("name") for p in participants if p.get("meta", {}).get("location") == "home"), "Home")
    away = next((p.get("name") for p in participants if p.get("meta", {}).get("location") == "away"), "Away")
    league_name = fixture.get("league", {}).get("name", "Unknown League")

    # Extract Type ID 240 (Correct Score Probability model)
    preds = fixture.get("predictions", [])
    cs_obj = next((p for p in preds if p.get("type_id") == 240), None)

    ranked_scores = []
    if cs_obj and isinstance(cs_obj.get("predictions"), dict):
        for score_str, prob in cs_obj["predictions"].items():
            if str(score_str).startswith("Other"):
                continue
            try:
                ranked_scores.append({
                    "predicted_score": str(score_str).replace("-", ":"),
                    "probability_pct": round(float(prob), 2)
                })
            except (ValueError, TypeError):
                continue

    ranked_scores.sort(key=lambda x: x["probability_pct"], reverse=True)

    if ranked_scores:
        top_pick = ranked_scores.copy().pop(0)
        predictions_list.append({
            "fixture_id": fixture.get("id"),
            "league": league_name,
            "match": f"{home} vs {away}",
            "kickoff_utc": fixture.get("starting_at", ""),
            "best_predicted_exact_score": top_pick["predicted_score"],
            "confidence_pct": f"{top_pick['probability_pct']}%",
            "top_3_predicted_scores": ranked_scores[:3]
        })

# Sort matches by highest prediction confidence first
predictions_list.sort(key=lambda x: float(x["confidence_pct"].replace("%", "")), reverse=True)

output = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "date": today,
    "total_predictions": len(predictions_list),
    "api_message": res.get("message") or "OK",
    "predictions": predictions_list
}

with open("scores.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Saved {len(predictions_list)} exact score predictions.")
