"""Retrospective walk-forward lineup-decision replay for all AAA fantasy teams.

Scoring inputs for target week w are strictly limited to weeks < w.
Uses the historical week-w ESPN roster as the selection pool, which may be
an end-of-week representation rather than a timestamped pre-kickoff roster.
This is RETROSPECTIVE, not an independently sealed prospective test.
"""
from __future__ import annotations
from collections import defaultdict
from .engine import (historical, history_index, optimize, predict, position, PRIOR)
from .workload import expected, lookup

SKILL = {"QB","RB","WR","TE"}


def _eligible(r):
    return (r["lineup_slot"] != "IR"
            and position(r["position"]) in PRIOR
            and float(r.get("projected_points") or 0) > 0)


def _lineup_score(lineup, actuals):
    return round(sum(actuals[pid] for pid in lineup.values()),2)


def _names(lineup, names):
    return {slot:names[pid] for slot,pid in lineup.items()}


def backtest(snapshot, stats, shrink=5., recent=0., first_week=5,
             last_week=None, user_team_id=1):
    """Frozen-v6 baseline vs workload lineup accuracy.

    Refuses replay before the baseline hyperparameter selection window, and
    never uses rows >= target week to project a target-week player.
    Injury/snap/opponent context remains informational, not point modifiers.
    """
    completed=int(snapshot["League"][0]["current_week"])-1
    end=min(last_week or completed,completed)
    if first_week<5:
        raise ValueError("Baseline parameters trained on weeks 2-4; test starts week 5")
    if end<first_week:
        return {"status":"PENDING_NOT_ENOUGH_COMPLETED_WEEKS"}
    idx=history_index(historical(snapshot, end))
    weekly=defaultdict(list)
    for row in snapshot["Weekly_Lineups"]:
        w=int(row["week"])
        if first_week<=w<=end:
            weekly[(w,int(row["team_id"]))].append(row)

    opponents={}
    for m in snapshot["Weekly_Matchups"]:
        w=int(m["week"])
        if not first_week<=w<=end:
            continue
        a=int(m["home_team_id"])
        b=int(m["away_team_id"])
        opponents[(w,a)]=(b,float(m["away_score"]))
        opponents[(w,b)]=(a,float(m["home_score"]))

    results=[]
    paired_errors=[]
    exclusions=[]
    for week in range(first_week,end+1):
        for team in sorted(int(t["team_id"]) for t in snapshot["Teams"]):
            roster=weekly.get((week,team),[])
            candidates=[r for r in roster if _eligible(r)]
            names={int(r["player_id"]):r["player"] for r in candidates}
            actuals={int(r["player_id"]):float(r["points"]) for r in candidates}
            players=[{"pid":int(r["player_id"]),"pos":position(r["position"])}
                     for r in candidates]
            baseline={}
            workload={}
            methods={}
            for r in candidates:
                pid=int(r["player_id"])
                pos=position(r["position"])
                old=predict(pid,week,pos,idx,shrink,recent)
                baseline[pid]=old
                if pos in SKILL:
                    hist,reason=lookup(stats,r["player"],r["pro_team"],pos,week-1)
                    if hist:
                        value=expected(hist,pos,week,week-1)["ppr_points"]
                        methods[pid]="WORKLOAD"
                        paired_errors.append({
                            "week":week,"team":team,"pid":pid,
                            "baseline_abs_error":abs(old-actuals[pid]),
                            "workload_abs_error":abs(value-actuals[pid])
                        })
                    else:
                        value=old
                        methods[pid]="BASELINE_FALLBACK_"+str(reason)
                else:
                    value=old
                    methods[pid]="BASELINE_ONLY_NON_SKILL"
                workload[pid]=value
            try:
                original=optimize(players,baseline)
                revised=optimize(players,workload)
                hindsight=optimize(players,actuals)
            except ValueError as exc:
                exclusions.append({"week":week,"team":team,"reason":str(exc)})
                continue
            a=original["lineup"]
            b=revised["lineup"]
            h=hindsight["lineup"]
            sb=_lineup_score(a,actuals)
            sw=_lineup_score(b,actuals)
            sh=_lineup_score(h,actuals)
            actual_starters=[r for r in roster if r["lineup_slot"] not in ("BE","IR")]
            observed_actual=round(sum(float(r["points"]) for r in actual_starters),2) if len(actual_starters)==9 else None
            opp=opponents.get((week,team))
            if not opp:
                opponent_result=None
            else:
                opponent_result={
                    "team_id":opp[0],"actual_score":round(opp[1],2),
                    "baseline_beats_actual_opponent":sb>opp[1],
                    "workload_beats_actual_opponent":sw>opp[1],
                    "manager_beats_actual_opponent":(observed_actual>opp[1] if observed_actual is not None else None),
                }
            only_base=sorted(set(a.values())-set(b.values()))
            only_work=sorted(set(b.values())-set(a.values()))
            changed=[]
            for pid in only_base:
                changed.append({"model":"baseline_only","name":names[pid],
                                "actual":actuals[pid],
                                "baseline_projection":round(baseline[pid],2),
                                "workload_projection":round(workload[pid],2)})
            for pid in only_work:
                changed.append({"model":"workload_only","name":names[pid],
                                "actual":actuals[pid],
                                "baseline_projection":round(baseline[pid],2),
                                "workload_projection":round(workload[pid],2)})
            results.append({
                "week":week,"team_id":team,"selected_from_roster":len(players),
                "workload_matched_players":sum(x=="WORKLOAD" for x in methods.values()),
                "baseline_actual":sb,"workload_actual":sw,
                "workload_minus_baseline":round(sw-sb,2),
                "hindsight_optimal_actual":sh,
                "baseline_regret":round(sh-sb,2),
                "workload_regret":round(sh-sw,2),
                "actual_manager_score":observed_actual,
                "baseline_lineup":_names(a,names),
                "workload_lineup":_names(b,names),
                "hindsight_lineup":_names(h,names),
                "changed_players":changed,
                "opponent":opponent_result,
                "availability_caveat":"ESPN historical lineup is postgame; pregame roster and injury timestamps not independently verified",
            })
    if not results:
        return {"status":"BLOCKED_NO_LEGAL_HISTORICAL_LINEUPS","exclusions":exclusions}
    n=len(results)
    e=len(paired_errors)
    mean=lambda key:round(sum(x[key] for x in results)/n,2)
    pair_mean=lambda key:round(sum(x[key] for x in paired_errors)/e,3) if e else None
    changes=[r for r in results if r["changed_players"]]
    user=[r for r in results if r["team_id"]==int(user_team_id)]
    eligible_outcomes=[r for r in results if r["opponent"]]
    win=lambda key:sum(bool(r["opponent"][key]) for r in eligible_outcomes)
    return {
        "status":"RETROSPECTIVE_WALK_FORWARD_NOT_PROSPECTIVE",
        "method":"Same historical week roster, same actual PPR outcomes. Predict target week w from weeks <w only. Baseline hyperparameters fixed from training weeks 2-4. NFL player opportunity stats only from weeks <w. DST/K held equal.",
        "first_week":first_week,"last_week":end,
        "summary":{
            "legal_team_weeks":n,"teams":len(set(r["team_id"] for r in results)),
            "lineups_with_different_starters":len(changes),
            "mean_baseline_regret":mean("baseline_regret"),
            "mean_workload_regret":mean("workload_regret"),
            "mean_workload_minus_baseline_actual":mean("workload_minus_baseline"),
            "total_workload_minus_baseline_actual":round(sum(x["workload_minus_baseline"] for x in results),2),
            "paired_skill_player_weeks":e,
            "paired_baseline_mae":pair_mean("baseline_abs_error"),
            "paired_workload_mae":pair_mean("workload_abs_error"),
            "baseline_wins_vs_actual_opponents":win("baseline_beats_actual_opponent"),
            "workload_wins_vs_actual_opponents":win("workload_beats_actual_opponent"),
            "manager_wins_vs_actual_opponents":win("manager_beats_actual_opponent"),
            "win_comparisons":"Each model lineup compared with opponent's ACTUAL score, not concurrent counterfactual opponent."
        },
        "your_weeks":user,
        "all_team_weeks":results,
        "exclusions":exclusions,
        "limitations":[
            "Historical ESPN rosters represent end-of-week state and may contain changes made after kickoff; no pregame roster snapshot is available for Weeks 5-7.",
            "The workload formula was authored after these weeks; this is NOT prospective or an independent out-of-sample validation of the new formula.",
            "The baseline hyperparameters were selected on Weeks 2-4; only later weeks are scored.",
            "Player availability uses nonzero archived ESPN projections solely to exclude a bye/no-game, not for point predictions; game-day injury status was not archived and cannot be backfilled without leakage.",
            "The v7/v8 snap-share, opponent, injury and pass-protection values have no forecast multiplier. Thus the baseline-vs-workload decision difference does NOT measure an injury-adjusted model.",
            "Outcomes are deterministic actual-score replay, not a simulation of potential football outcomes; apparent gains on three weeks could be chance."
        ],
    }
