"""Cross-position, source-verified waiver scouting for AAA's game environments.

An ESPN free agent is availability information, not a predicted fantasy score.
We never assign a fictional baseline to free-agent K or DST, nor treat ESPN
projections as the underlying prediction model. This is shadow scouting only.
"""
from __future__ import annotations
from collections import defaultdict
from .engine import position,team_key
from .workload import lookup,expected,number
from .game_environment import scenario_points

MAX_BY_POSITION={"QB":15,"RB":30,"WR":30,"TE":18,"D/ST":16,"K":16}
SKILL={"QB","RB","WR","TE"}


def scan(snapshot,stats,environment,schedule):
    rows=snapshot.get("Free_Agents",[])
    contexts=environment.get("matchups",{})
    if environment.get("status")!="SOURCE_BACKED_SCOUTING_AND_UNVALIDATED_SCENARIOS":
        return {"status":"BLOCKED_NO_VERIFIED_MATCHUP_CONTEXT"}
    cutoff=int(environment["observed_through_week"])
    seen=set()
    grouped=defaultdict(list)
    rostered={int(r["player_id"]) for r in snapshot.get("Current_Rosters",[])
             if str(r.get("player_id") or "").lstrip("-").isdigit()}
    for r in rows:
        if str(r.get("player_id") or "").lstrip("-").isdigit():
            pid=int(r["player_id"])
        else:
            continue
        if pid in seen or pid in rostered:
            continue
        seen.add(pid)
        pos=position(r.get("position",""))
        if pos not in MAX_BY_POSITION:
            continue
        team=team_key(r.get("pro_team",""))
        if team not in schedule.get("kickoffs",{}):
            continue
        if str(r.get("injury_status","")).upper() in ("OUT","IR","INJURY_RESERVE"):
            continue
        # ESPN's projection is used ONLY for playable-week/bye eligibility.
        if number(r.get("projected_points"))<=0:
            continue
        game=contexts.get(team)
        if not game or game.get("status")!="OBSERVED_MATCHUP_WITH_UNVALIDATED_VOLUME_SCENARIOS":
            continue
        item={"name":r["player"],"player_id":pid,
              "position":pos,"nfl_team":team,
              "opponent":game["opponent"],
              "injury_label_espn":r.get("injury_status"),
              "expected_team_pass_attempts_proxy":game["expected_dropbacks_proxy"],
              "expected_team_rushing_attempts_proxy":game["expected_rushes_proxy"],
              "matchup_pass_rush_sack_rate_proxy":game["sack_matchup_ratio"],
              "passing_efficiency_edge":game["pass_epa_matchup_edge"],
              "rushing_efficiency_edge":game["rush_epa_matchup_edge"],
              "opponent_reported_injuries":
                 (game.get("week_specific_injury_reports") or {}).get(
                     "opponent_team_all_positions",[]),
              "method":"SOURCE_VERIFIED_TEAM_MATCHUP_SHADOW_ONLY",
              "applied_to_primary_model":False}
        if pos in SKILL:
            history,reason=lookup(stats,item["name"],team,pos,cutoff)
            if not history:
                item["opportunity_status"]="NO_VERIFIED_PLAYER_HISTORY"
                item["score_scenario"]=None
                item["player_history_note"]=reason
            else:
                workload=expected(history,pos,cutoff+1,cutoff)
                points=scenario_points(pos,0.,workload,game)
                item["opportunity_status"]="OBSERVED_PRIOR_GAMES"
                item["past_weeks"]=[x["week"] for x in history]
                item["workload_projection_unvalidated"]=workload["ppr_points"]
                item["game_environment_scenario_unvalidated"]=points["point_estimate"]
                item["predicted_carries"]=workload["expected_carries"]
                item["predicted_targets"]=workload["expected_targets"]
                item["predicted_pass_attempts"]=workload["expected_pass_attempts"]
                item["role_warnings"]=workload["role_flags"]
        else:
            item["opportunity_status"]="K_DST_NO_VERIFIED_ESPN_INDEPENDENT_PLAYER_MEAN"
            item["score_scenario"]=None
            item["scoring_note"]="Team matchup is visible, but no credible K/DST point projection is available for this unrostered player."
        grouped[pos].append(item)
    for pos,items in grouped.items():
        if pos in SKILL:
            items.sort(key=lambda x:(-float(x.get("game_environment_scenario_unvalidated") or -999),
                                     x["name"]))
        else:
            items.sort(key=lambda x:x["name"])
    return {
        "status":"SOURCE_BACKED_WAIVER_SCOUTING_NO_AUTOMATIC_ADD",
        "snapshot_exported_utc":snapshot["League"][0]["exported_utc"],
        "historical_cutoff_week":cutoff,
        "by_position":{pos:grouped.get(pos,[])[:limit]
                       for pos,limit in MAX_BY_POSITION.items()},
        "notes":[
            "Free agent availability is from the latest league export, not guaranteed at claim time.",
            "A positive ESPN projection is a playable-week eligibility check only, not an input to the AAA scoring model.",
            "Opportunity and matchup scoring are experimental; no lineup or roster changes occur.",
            "K and D/ST matchup profiles have no independently verified individual scoring mean and do not invent one.",
            "Official kickoff and inactive status must be rechecked before submitting a claim."
        ]
    }
