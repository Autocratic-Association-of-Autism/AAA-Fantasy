from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="Build all-time AAA 35+ point matchup records")
parser.add_argument("--snapshot", required=True, help="Folder containing the latest ESPN 2026 snapshot")
args = parser.parse_args()

historic = json.loads(Path("blowout-history.json").read_text(encoding="utf-8"))
names = historic["managers"]
assert len(names) == 11 and len(set(names)) == 11
assert len(historic["games"]) == 127, "Historical source missing rows"

all_details = []
for season, week, winner_id, loser_id, winner_score, loser_score, playoff in historic["games"]:
    winner_score, loser_score = round(float(winner_score), 2), round(float(loser_score), 2)
    margin = round(winner_score - loser_score, 2)
    if margin < 35 or winner_score <= loser_score:
        raise ValueError("Historical margin does not meet 35+ threshold")
    all_details.append({"Season":season,"Week":week,"Winner":names[winner_id],
                        "Loser":names[loser_id],"Winner Score":winner_score,
                        "Loser Score":loser_score,"Margin":margin,
                        "Stage":"Playoffs" if playoff else "Regular"})

snapshot_path = next(Path(args.snapshot).rglob("ESPN_Current_Snapshot_1438350867_2026.json"))
snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
league_info = snapshot["League"][0]
if int(league_info["league_id"]) != 1438350867 or int(league_info["season"]) != 2026:
    raise ValueError("Wrong ESPN league/season in snapshot")
current_week = int(league_info["current_week"])
last_week = min(current_week - 1, int(league_info["regular_season_weeks"]))
manager_by_team = dict(enumerate(names[:10], start=1))
seen = set()
for game in snapshot["Weekly_Matchups"]:
    week = int(game["week"])
    if week > last_week or str(game.get("is_playoff", "")).lower() in ("true","1"):
        continue
    home_id, away_id = int(game["home_team_id"]), int(game["away_team_id"])
    key = (week, min(home_id,away_id), max(home_id,away_id))
    if key in seen:
        raise ValueError(f"Duplicate 2026 result: {key}")
    seen.add(key)
    home, away = float(game["home_score"]), float(game["away_score"])
    if home <= 0 or away <= 0:
        raise ValueError(f"Missing 2026 final score at week {week}: {key}")
    if home == away:
        continue
    margin = round(abs(home-away), 2)
    if margin < 35:
        continue
    winner_id, loser_id = (home_id,away_id) if home > away else (away_id,home_id)
    all_details.append({"Season":2026,"Week":week,"Winner":manager_by_team[winner_id],
                        "Loser":manager_by_team[loser_id],"Winner Score":round(max(home,away),2),
                        "Loser Score":round(min(home,away),2),"Margin":margin,"Stage":"Regular"})

if len(seen) != last_week * 5:
    raise ValueError(f"2026 completed games mismatch: {len(seen)}, expected {last_week*5}")

wins = Counter(g["Winner"] for g in all_details)
losses = Counter(g["Loser"] for g in all_details)
if sum(wins.values()) != len(all_details) or sum(losses.values()) != len(all_details):
    raise ValueError("Leaderboard integrity failure")

def leaderboard(counts,key):
    ordered = sorted(names,key=lambda name:(-counts[name],name))
    return [{"Rank":i+1,"Manager":name,key:counts[name]} for i,name in enumerate(ordered)]

all_details.sort(key=lambda x:(-x["Season"],-x["Week"],x["Winner"]))
output = {
  "BLOWOUT_WINS":leaderboard(wins,"Wins"),
  "BLOWOUT_LOSSES":leaderboard(losses,"Losses"),
  "BLOWOUT_DETAILS":all_details,
  "BLOWOUT_LOSS_DETAILS":all_details,
  "BLOWOUT_TOTAL":len(all_details),
  "BLOWOUT_SCOPE":f"2021–2025 + 2026 through completed Week {last_week}. Includes one-week playoff games; multi-week playoff aggregates and duplicate ESPN Week 18 entries are excluded.",
  "BLOWOUT_DATA_AS_OF":league_info.get("exported_utc","")
}
Path("blowout-losses.js").write_text("".join(
    "window."+key+" = "+json.dumps(value,ensure_ascii=False,separators=(",",":"))+";\n"
    for key,value in output.items()
),encoding="utf-8")
print("Records:",len(all_details),"qualifying games;",len(historic["games"]),
      "historical;",len(all_details)-len(historic["games"]),"in 2026")
print("Top wins:",output["BLOWOUT_WINS"][:3])
print("Top losses:",output["BLOWOUT_LOSSES"][:3])
