"""One-off historical AAA lineup archive, using the configured ESPN credentials.

Only historical weekly player IDs, names, teams and points are kept. No owner
records, auth cookies, trades or member identifiers are written to artifacts.
The regular season only is exported, and incomplete weeks cause a hard failure.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from espn_api.football import League

LEAGUE_ID=1438350867
SEASONS=(2024,2025)


def player_row(p):
    return {
        "player_id":int(getattr(p,"playerId",0) or 0),
        "player":str(getattr(p,"name","")),
        "position":str(getattr(p,"position","")),
        "pro_team":str(getattr(p,"proTeam","")),
        "lineup_slot":str(getattr(p,"slot_position","")),
        "points":float(getattr(p,"points",0) or 0),
        "projected_points":float(getattr(p,"projected_points",0) or 0),
        "injury_status":str(getattr(p,"injuryStatus","")),
    }


def archive(year, swid, s2):
    league=League(league_id=LEAGUE_ID,year=year,swid=swid,espn_s2=s2)
    settings=league.settings
    reg_weeks=int(settings.reg_season_count)
    if not (12<=reg_weeks<=15):
        raise ValueError(f"Unexpected regular season length {reg_weeks}")
    teams=[{"team_id":int(t.team_id),"team_name":str(t.team_name)}
           for t in league.teams]
    if len(teams)<6:
        raise ValueError("Incomplete historical AAA team list")
    rows={"League":[{
          "league_id":LEAGUE_ID,"season":year,
          # Prior entire season is complete, unlike the live-season API's
          # week index which may refer to final playoff or offseason states.
          "current_week":reg_weeks+1,
          "regular_season_weeks":reg_weeks,
          "exported_utc":datetime.now(timezone.utc).isoformat(),
          "historical_complete":True}],
          "Teams":teams,"Weekly_Lineups":[],"Weekly_Matchups":[]}
    for week in range(1,reg_weeks+1):
        boxes=league.box_scores(week)
        if len(boxes)*2 != len(teams):
            raise ValueError(f"Week {week} missing matchups: {len(boxes)}")
        for box in boxes:
            h,a=box.home_team,box.away_team
            if h is None or a is None:
                raise ValueError(f"Week {week} missing an opponent")
            record={"week":week,
                    "home_team_id":int(h.team_id),"away_team_id":int(a.team_id),
                    "home_score":float(box.home_score),
                    "away_score":float(box.away_score)}
            rows["Weekly_Matchups"].append(record)
            for side,team,lineup in (
                ("home",h,box.home_lineup),
                ("away",a,box.away_lineup)):
                if not lineup:
                    raise ValueError(f"Week {week} missing lineup for {team.team_id}")
                for p in lineup:
                    r={"week":week,"side":side,
                       "team_id":int(team.team_id)}
                    r.update(player_row(p))
                    rows["Weekly_Lineups"].append(r)
    out=Path("historical_export")
    out.mkdir(exist_ok=True,parents=True)
    path=out/f"AAA_Season_{year}_Historical_Box_Scores.json"
    path.write_text(json.dumps(rows,indent=2),encoding="utf-8")
    return {"year":year,"teams":len(teams),
            "weeks":reg_weeks,"matchups":len(rows["Weekly_Matchups"]),
            "player_weeks":len(rows["Weekly_Lineups"]),"file":path.name}


def main():
    swid=os.environ["ESPN_SWID"].strip()
    s2=os.environ["ESPN_S2"].strip()
    for season in SEASONS:
        print(json.dumps(archive(season,swid,s2)))


if __name__=="__main__":
    main()
