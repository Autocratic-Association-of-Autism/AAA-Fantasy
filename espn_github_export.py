from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from espn_api.football import League

LEAGUE_ID = 1438350867
SEASON = 2026

def safe(v):
    if v is None: return ""
    if isinstance(v, (str, int, float, bool)): return v
    if isinstance(v, (list, tuple, set)): return " | ".join(str(x) for x in v)
    if isinstance(v, dict): return json.dumps(v, default=str)
    return str(v)

def team_name(t):
    return getattr(t, "team_name", str(t)) if t else ""

def owner_text(t):
    vals = []
    for o in (getattr(t, "owners", []) or []):
        vals.append(json.dumps(o, default=str, sort_keys=True) if isinstance(o, dict) else str(o))
    return " | ".join(vals)

def player_row(p):
    return {
        "player_id": getattr(p, "playerId", ""),
        "player": getattr(p, "name", ""),
        "position": getattr(p, "position", ""),
        "pro_team": getattr(p, "proTeam", ""),
        "lineup_slot": getattr(p, "slot_position", ""),
        "points": getattr(p, "points", ""),
        "projected_points": getattr(p, "projected_points", ""),
        "percent_owned": getattr(p, "percent_owned", getattr(p, "percentOwned", "")),
        "percent_started": getattr(p, "percent_started", getattr(p, "percentStarted", "")),
        "injury_status": getattr(p, "injuryStatus", getattr(p, "injury_status", "")),
        "status": getattr(p, "status", ""),
    }

swid = os.environ["ESPN_SWID"].strip()
espn_s2 = os.environ["ESPN_S2"].strip()
league = League(league_id=LEAGUE_ID, year=SEASON, swid=swid, espn_s2=espn_s2)

rows = {k: [] for k in ["League","Teams","Current_Rosters","Free_Agents","Draft","Weekly_Matchups","Weekly_Lineups","Transactions","Errors"]}
settings = getattr(league, "settings", None)
current_week = int(getattr(league, "current_week", 1) or 1)

rows["League"].append({
    "league_id": LEAGUE_ID, "season": SEASON, "current_week": current_week,
    "nfl_week": getattr(league, "nfl_week", ""),
    "scoring_period_id": getattr(league, "scoringPeriodId", ""),
    "team_count": getattr(settings, "team_count", len(getattr(league, "teams", []))),
    "regular_season_weeks": getattr(settings, "reg_season_count", ""),
    "exported_utc": datetime.now(timezone.utc).isoformat(),
})

for t in league.teams:
    rows["Teams"].append({
        "team_id": getattr(t, "team_id", ""), "team_name": team_name(t), "team_abbrev": getattr(t, "team_abbrev", ""),
        "owners": owner_text(t), "wins": getattr(t, "wins", ""), "losses": getattr(t, "losses", ""),
        "ties": getattr(t, "ties", ""), "standing": getattr(t, "standing", ""),
        "points_for": getattr(t, "points_for", ""), "points_against": getattr(t, "points_against", ""),
        "acquisitions": getattr(t, "acquisitions", ""), "drops": getattr(t, "drops", ""),
        "trades": getattr(t, "trades", ""), "faab_spent": getattr(t, "acquisition_budget_spent", ""),
    })
    for p in (getattr(t, "roster", []) or []):
        r = {"team_id": getattr(t, "team_id", ""), "team_name": team_name(t), "owners": owner_text(t)}
        r.update(player_row(p))
        rows["Current_Rosters"].append(r)

try:
    for rank, p in enumerate(league.free_agents(size=500), 1):
        r = {"availability_rank": rank}
        r.update(player_row(p))
        rows["Free_Agents"].append(r)
except Exception as e:
    rows["Errors"].append({"section": "free_agents", "error": str(e)})

try:
    for overall, pick in enumerate(getattr(league, "draft", []) or [], 1):
        t = getattr(pick, "team", None)
        rows["Draft"].append({
            "overall_pick": overall, "round": getattr(pick, "round_num", ""), "round_pick": getattr(pick, "round_pick", ""),
            "team_id": getattr(t, "team_id", "") if t else "", "team_name": team_name(t), "owners": owner_text(t) if t else "",
            "player_id": getattr(pick, "playerId", ""), "player": getattr(pick, "playerName", ""),
            "bid_amount": getattr(pick, "bid_amount", ""), "keeper": getattr(pick, "keeper_status", ""),
        })
except Exception as e:
    rows["Errors"].append({"section": "draft", "error": str(e)})

for week in range(1, current_week + 1):
    try:
        for box in league.box_scores(week):
            home, away = getattr(box, "home_team", None), getattr(box, "away_team", None)
            rows["Weekly_Matchups"].append({
                "week": week, "home_team_id": getattr(home, "team_id", "") if home else "", "home_team": team_name(home),
                "away_team_id": getattr(away, "team_id", "") if away else "", "away_team": team_name(away),
                "home_score": getattr(box, "home_score", ""), "away_score": getattr(box, "away_score", ""),
                "home_projected": getattr(box, "home_projected", ""), "away_projected": getattr(box, "away_projected", ""),
                "is_playoff": getattr(box, "is_playoff", ""), "matchup_type": getattr(box, "matchup_type", ""),
            })
            for side, t, lineup in [("home", home, getattr(box, "home_lineup", []) or []), ("away", away, getattr(box, "away_lineup", []) or [])]:
                for p in lineup:
                    r = {"week": week, "side": side, "team_id": getattr(t, "team_id", "") if t else "", "team_name": team_name(t), "owners": owner_text(t) if t else ""}
                    r.update(player_row(p))
                    rows["Weekly_Lineups"].append(r)
    except Exception as e:
        rows["Errors"].append({"section": f"box_scores_week_{week}", "error": str(e)})

try:
    offset, page_size, seen = 0, 100, set()
    while True:
        acts = league.recent_activity(size=page_size, offset=offset)
        if not acts: break
        added = 0
        for act in acts:
            for a in getattr(act, "actions", []):
                t = a[0] if len(a)>0 else None
                action = a[1] if len(a)>1 else ""
                p = a[2] if len(a)>2 else None
                bid = a[3] if len(a)>3 else ""
                pr = player_row(p) if p is not None else {k:"" for k in player_row(type("X", (), {})()).keys()}
                sig = (getattr(act,"date",""), getattr(t,"team_id",""), action, pr["player_id"], pr["player"], bid)
                if sig in seen: continue
                seen.add(sig); added += 1
                rows["Transactions"].append({
                    "date_epoch_ms": getattr(act,"date",""), "team_id": getattr(t,"team_id","") if t else "",
                    "team_name": team_name(t), "owners": owner_text(t) if t else "", "action": action,
                    "player_id": pr["player_id"], "player": pr["player"], "position": pr["position"], "pro_team": pr["pro_team"], "faab_bid": bid
                })
        if len(acts) < page_size or added == 0: break
        offset += page_size
        if offset > 5000: break
except Exception as e:
    rows["Errors"].append({"section": "transactions", "error": str(e)})

out = Path("export"); out.mkdir(exist_ok=True)
xlsx = out / f"ESPN_Current_Snapshot_{LEAGUE_ID}_{SEASON}.xlsx"
with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
    for s, data in rows.items():
        pd.DataFrame(data).to_excel(writer, sheet_name=s[:31], index=False)

json_path = out / f"ESPN_Current_Snapshot_{LEAGUE_ID}_{SEASON}.json"
json_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
(out / "export_metadata.json").write_text(json.dumps({
    "league_id": LEAGUE_ID, "season": SEASON, "current_week": current_week,
    "exported_utc": datetime.now(timezone.utc).isoformat(),
    "files": [xlsx.name, json_path.name]
}, indent=2), encoding="utf-8")

print("Export complete")
