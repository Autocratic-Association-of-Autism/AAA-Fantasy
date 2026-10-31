"""v9 walk-forward lineup decision test for the game environment layer.

Only historical NFL games strictly BEFORE the evaluated week enter model
features. The target-week NFL PBP is permitted solely to identify already
published team-vs-team schedules; no target-game plays or EPA enter estimates.
This remains RETROSPECTIVE, since final ESPN rosters are not pregame snapshots.
"""
from __future__ import annotations
from collections import defaultdict
from .engine import historical,history_index,optimize,predict,position,PRIOR
from .workload import lookup,expected
from .game_environment import preview,scenario_points,num

SKILL=("QB","RB","WR","TE")


def evaluate(snapshot,stats,pbp,shrink=5.,recent=0.,first_week=5,
             last_week=None):
    end=min(last_week or 99,int(snapshot["League"][0]["current_week"])-1,
            int(pbp["included_through_week"]))
    if first_week<5:
        raise ValueError("Chronological test must start after baseline training Weeks 2-4")
    if end<first_week:
        return {"status":"PENDING_NOT_ENOUGH_COMPLETED_GAMES"}
    idx=history_index(historical(snapshot,end))
    schedule=pbp["opponents"]
    # Cache opponent-specific game environment with a strictly earlier cutoff.
    previews={}
    def matchup(w,t):
        key=(w,t)
        if key not in previews:
            other=schedule.get((w,t))
            previews[key]=preview(pbp,t,other,w-1) if other else {
                "status":"NO_VERIFIED_HISTORICAL_OPPONENT"}
        return previews[key]
    indexed=defaultdict(list)
    for row in snapshot["Weekly_Lineups"]:
        w=int(row["week"])
        if first_week<=w<=end and position(row["position"]) in PRIOR:
            indexed[(w,int(row["team_id"]))].append(row)

    teamweeks=[]
    paired=[]
    player_positions=defaultdict(list)
    exclusions=[]
    for (week,team_id),roster in sorted(indexed.items()):
        pool=[]
        means={"baseline":{},"workload":{},"environment":{},"actual":{}}
        for r in roster:
            if r["lineup_slot"]=="IR" or num(r.get("projected_points"))<=0:
                continue
            pos=position(r["position"])
            pid=int(r["player_id"])
            team=r["pro_team"]
            base=predict(pid,week,pos,idx,shrink,recent)
            workload=base
            work=None
            if pos in SKILL:
                series,_=lookup(stats,r["player"],team,pos,week-1)
                if series:
                    work=expected(series,pos,week,week-1)
                    workload=float(work["ppr_points"])
            game=matchup(week,team)
            contextual=scenario_points(pos,base,work,game)
            shadow=contextual.get("point_estimate")
            shadow=float(shadow) if shadow is not None else workload
            actual=float(r["points"])
            pool.append({"pid":pid,"pos":pos})
            means["baseline"][pid]=base
            means["workload"][pid]=workload
            means["environment"][pid]=shadow
            means["actual"][pid]=actual
            if work is not None:
                paired.append({"week":week,"team":team_id,
                               "position":pos,
                               "baseline_error":abs(base-actual),
                               "workload_error":abs(workload-actual),
                               "environment_error":abs(shadow-actual)})
                player_positions[pos].append(paired[-1])
        try:
            base=optimize(pool,means["baseline"])
            work=optimize(pool,means["workload"])
            env=optimize(pool,means["environment"])
            best=optimize(pool,means["actual"])
        except ValueError as error:
            exclusions.append({"week":week,"team":team_id,"reason":str(error)})
            continue
        score=lambda data:round(sum(means["actual"][p] for p in data["lineup"].values()),2)
        ba,wa,ea,ideal=map(score,(base,work,env,best))
        teamweeks.append({
            "week":week,"team_id":team_id,
            "baseline_actual":ba,"workload_actual":wa,
            "environment_actual":ea,"hindsight_optimal_actual":ideal,
            "environment_minus_workload":round(ea-wa,2),
            "environment_minus_baseline":round(ea-ba,2),
            "environment_regret":round(ideal-ea,2),
            "workload_regret":round(ideal-wa,2),
            "baseline_regret":round(ideal-ba,2),
            "environment_changes_vs_workload":sorted(
                set(env["lineup"].values())-set(work["lineup"].values())),
            "note":"Same final ESPN weekly pool, which is NOT verified as original pregame roster.",
        })

    avg=lambda values:round(sum(values)/len(values),4) if values else None
    def scoring(rows):
        return {
            "observations":len(rows),
            "baseline_mae":avg([x["baseline_error"] for x in rows]),
            "workload_mae":avg([x["workload_error"] for x in rows]),
            "environment_mae":avg([x["environment_error"] for x in rows]),
        }
    return {
        "status":"EXPLORATORY_RETROSPECTIVE_NO_AUTOMATIC_PROMOTION",
        "tested_weeks":list(range(first_week,end+1)),
        "summary":{
            "legal_team_weeks":len(teamweeks),
            "exclusions":len(exclusions),
            "different_starters_vs_workload":sum(
                bool(r["environment_changes_vs_workload"]) for r in teamweeks),
            "environment_better_vs_workload":sum(
                r["environment_minus_workload"]>.001 for r in teamweeks),
            "environment_worse_vs_workload":sum(
                r["environment_minus_workload"]<-.001 for r in teamweeks),
            "environment_ties_vs_workload":sum(
                abs(r["environment_minus_workload"])<=.001 for r in teamweeks),
            "mean_environment_minus_workload":avg(
                [r["environment_minus_workload"] for r in teamweeks]),
            "mean_environment_minus_baseline":avg(
                [r["environment_minus_baseline"] for r in teamweeks]),
            "baseline_regret":avg([r["baseline_regret"] for r in teamweeks]),
            "workload_regret":avg([r["workload_regret"] for r in teamweeks]),
            "environment_regret":avg([r["environment_regret"] for r in teamweeks]),
            "paired_skill_player_error":scoring(paired),
            "by_position":{pos:scoring(rows)
                           for pos,rows in sorted(player_positions.items())},
        },
        "per_team_week":teamweeks,
        "exclusions":exclusions,
        "limitations":[
            "2026 Weeks 2-4 AAA baseline tuning occurs before evaluated weeks.",
            "Every historical game-environment feature uses < target week; opponent identity is fixed schedule data.",
            "2026 v9 coefficients were developed after historical results; retrospective results are not a sealed prospective holdout.",
            "2024/2025 final ESPN rosters are not validated pregame, including injury scratches and waivers.",
            "All game-environment scoring modifiers are heuristic; do not auto-promote from one historical replay.",
            "K and D/ST scenario scores are illustrative opportunity/pressure scenarios, not validated kick and return scoring models.",
            "Missing player opportunities retain original AAA baseline, not invented volume."
        ],
        "promotion_eligible":False
    }
