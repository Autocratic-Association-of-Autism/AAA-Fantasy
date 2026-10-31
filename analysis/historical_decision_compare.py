"""Cross-season AAA historical lineup comparison, not prospective validation.

Replay the v5 baseline versus v6 opportunity scorer on 2024/2025 ESPN
season-week rosters. NFL inputs are used only from PRIOR weeks. Show per-team,
per-week, and role-level differences; no hidden calibration or auto-promotion.
"""
from __future__ import annotations
import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from aaa_engine.decision_backtest import backtest
from aaa_engine.game_environment import download_pbp
from aaa_engine.game_environment_backtest import evaluate as evaluate_game_environment
from aaa_engine.workload import download

OUT=Path("historical_results")
OUT.mkdir(exist_ok=True)
SEASONS=(2024,2025)
SHRINK=5.0
RECENT=0.0


def avg(values):
    return round(sum(values)/len(values),3) if values else None


def summary_for(data):
    rows=data["all_team_weeks"]
    changes=[r for r in rows if abs(r["workload_minus_baseline"])>0.0001]
    week_numbers=sorted(set(r["week"] for r in rows))
    teams=sorted(set(r["team_id"] for r in rows))
    by_team={}
    for team_id in teams:
        subset=[r for r in rows if r["team_id"]==team_id]
        with_opp=[r for r in subset if r["opponent"] is not None]
        by_team[str(team_id)]={
            "team_id":team_id,"team_weeks":len(subset),
            "different_lineups":sum(bool(x["changed_players"]) for x in subset),
            "workload_better":sum(x["workload_minus_baseline"]>0.001 for x in subset),
            "workload_worse":sum(x["workload_minus_baseline"]<-.001 for x in subset),
            "tie":sum(abs(x["workload_minus_baseline"])<=.001 for x in subset),
            "points_delta":round(sum(r["workload_minus_baseline"] for r in subset),2),
            "per_week_delta":avg([r["workload_minus_baseline"] for r in subset]),
            "baseline_regret":avg([r["baseline_regret"] for r in subset]),
            "workload_regret":avg([r["workload_regret"] for r in subset]),
            "baseline_wins":sum(bool(x["opponent"]["baseline_beats_actual_opponent"]) for x in with_opp),
            "workload_wins":sum(bool(x["opponent"]["workload_beats_actual_opponent"]) for x in with_opp),
        }
    by_week=[]
    for week in week_numbers:
        subset=[r for r in rows if r["week"]==week]
        by_week.append({
            "week":week,"team_weeks":len(subset),
            "actual_points_delta":round(sum(x["workload_minus_baseline"] for x in subset),2),
            "lineups_changed":sum(bool(x["changed_players"]) for x in subset),
            "wins_baseline":sum(bool(x["opponent"]["baseline_beats_actual_opponent"])
                                for x in subset if x["opponent"]),
            "wins_workload":sum(bool(x["opponent"]["workload_beats_actual_opponent"])
                                for x in subset if x["opponent"]),
        })
    total=sum(r["workload_minus_baseline"] for r in rows)
    return {
        "team_weeks":len(rows),
        "different_selections":sum(bool(r["changed_players"]) for r in rows),
        "workload_better":sum(x["workload_minus_baseline"]>.001 for x in rows),
        "workload_worse":sum(x["workload_minus_baseline"]<-.001 for x in rows),
        "lineup_ties":sum(abs(x["workload_minus_baseline"])<=.001 for x in rows),
        "total_points_delta":round(total,2),
        "mean_points_delta":round(total/len(rows),3) if rows else None,
        "baseline_mean_regret":avg([r["baseline_regret"] for r in rows]),
        "workload_mean_regret":avg([r["workload_regret"] for r in rows]),
        "baseline_wins":sum(bool(r["opponent"]["baseline_beats_actual_opponent"])
                             for r in rows if r["opponent"]),
        "workload_wins":sum(bool(r["opponent"]["workload_beats_actual_opponent"])
                             for r in rows if r["opponent"]),
        "by_team":by_team,"by_week":by_week
    }


def clustered_bootstrap(seasons, draws=10000):
    # Cluster at NFL-week level: all fantasy teams in one week share outcomes.
    chunks=defaultdict(list)
    for yr,results in seasons.items():
        for r in results["all_team_weeks"]:
            chunks[(int(yr),r["week"])].append(r["workload_minus_baseline"])
    if len(chunks)<8:
        return {"status":"INSUFFICIENT_INDEPENDENT_WEEK_CLUSTERS",
                "week_clusters":len(chunks)}
    values=list(chunks.values())
    rng=random.Random(20261030)
    boots=[]
    for _ in range(draws):
        sample=[values[rng.randrange(len(values))] for _ in values]
        points=sum(sum(x) for x in sample)
        count=sum(len(x) for x in sample)
        boots.append(points/count)
    boots.sort()
    return {
        "status":"EXPLORATORY_CLUSTER_BOOTSTRAP",
        "week_clusters":len(values),"draws":draws,
        "mean_diff_ppr_95_interval":[round(boots[int(.025*draws)],3),
                                     round(boots[int(.975*draws)],3)],
        "method":"Resample season-week clusters; NOT a sealed prospective or independent model-tuning test"
    }


def main():
    season_results={}
    environment_results={}
    combined=[]
    season_reports=[]
    for season in SEASONS:
        path=Path("historical_export")/f"AAA_Season_{season}_Historical_Box_Scores.json"
        snapshot=json.loads(path.read_text())
        if int(snapshot["League"][0]["season"])!=season:
            raise ValueError(f"Historical ESPN data year mismatch for {season}")
        if len(snapshot["Teams"])!=10:
            raise ValueError(f"2026 AAA comparison requires 10 teams; got {len(snapshot['Teams'])} in {season}")
        stats,provenance=download(season,datetime.now(timezone.utc).isoformat())
        cutoff=int(snapshot["League"][0]["regular_season_weeks"])
        # Year-specific NFL weekly stats; no future inputs in prediction.
        report=backtest(snapshot,stats,shrink=SHRINK,recent=RECENT,
                        first_week=5,last_week=cutoff)
        if report["status"]!="RETROSPECTIVE_WALK_FORWARD_NOT_PROSPECTIVE":
            raise ValueError(f"Insufficient usable lineups for {season}: {report['status']}")
        report["season"]=season
        report["provenance"]={"espn_export_file":path.name,
                              "nflverse_source":provenance}
        report["team_names"]={str(x["team_id"]):x["team_name"] for x in snapshot["Teams"]}
        (OUT/f"AAA_{season}_historical_replay.json").write_text(json.dumps(report,indent=2))
        season_results[str(season)]=report
        # Additional ALL-POSITION game-environment head-to-head backtest.
        # The PBP source is cut off at the end of the historical season, but
        # evaluate() uses only games before each week for its features.
        try:
            pbp,pbp_source=download_pbp(season,cutoff,
                                        datetime.now(timezone.utc).isoformat())
            environment_result=evaluate_game_environment(
                snapshot,stats,pbp,shrink=SHRINK,recent=RECENT,
                first_week=5,last_week=cutoff)
            environment_result["source"]=pbp_source
            environment_result["season"]=season
        except Exception as error:
            environment_result={
                "status":"BLOCKED_NO_VERIFIABLE_PBP",
                "season":season,"reason":str(error),
                "promotion_eligible":False}
        environment_results[str(season)]=environment_result
        (OUT/f"AAA_{season}_game_environment_backtest.json").write_text(
            json.dumps(environment_result,indent=2))
        combined+= [{**r,"season":season,
                     "team_name":report["team_names"].get(str(r["team_id"]),"?")}
                    for r in report["all_team_weeks"]]
        season_reports.append({
            "season":season,"teams":len(snapshot["Teams"]),
            "regular_weeks":cutoff,
            "roster_rows":len(snapshot["Weekly_Lineups"]),
            "legal_team_weeks":report["summary"]["legal_team_weeks"],
            "excluded_team_weeks":len(report["exclusions"]),
            "summary":summary_for(report),
            "team_names":report["team_names"],
            "nfl_source_sha256":provenance["sha256"]
        })
        print(json.dumps({"season":season,
             "team_weeks":report["summary"]["legal_team_weeks"],
             "excluded":len(report["exclusions"])}))

    n=len(combined)
    total=sum(x["workload_minus_baseline"] for x in combined)
    all_seasons={
        "status":"RETROSPECTIVE_CROSS_SEASON_COMPARISON_NO_AUTO_PROMOTION",
        "years":list(SEASONS),
        "as_of":datetime.now(timezone.utc).isoformat(),
        "baseline_parameters":{"shrink":SHRINK,"recent":RECENT,
                               "origin":"2026 v5 selected on 2026 Weeks 2-4"},
        "mean_workload_minus_baseline":round(total/n,3),
        "total_points_delta":round(total,2),
        "team_weeks":n,
        "different_starters":sum(bool(x["changed_players"]) for x in combined),
        "workload_better":sum(x["workload_minus_baseline"]>.001 for x in combined),
        "workload_worse":sum(x["workload_minus_baseline"]<-.001 for x in combined),
        "ties":sum(abs(x["workload_minus_baseline"])<=.001 for x in combined),
        "baseline_win_count":sum(bool(x["opponent"]["baseline_beats_actual_opponent"])
                               for x in combined if x["opponent"]),
        "workload_win_count":sum(bool(x["opponent"]["workload_beats_actual_opponent"])
                               for x in combined if x["opponent"]),
        "baseline_mean_regret":avg([x["baseline_regret"] for x in combined]),
        "workload_mean_regret":avg([x["workload_regret"] for x in combined]),
        "confidence":clustered_bootstrap(season_results),
        "season_summaries":season_reports,
        "caveats":[
            "No frozen pregame ESPN historical rosters: end-of-week rosters may change after kickoff.",
            "2026 formulas were designed after the 2024 and 2025 games. This is retrospective model reuse, NOT independent prospective validation.",
            "The v5 baseline's coefficients were selected on 2026 Weeks 2-4, not the historical seasons.",
            "2026 week 8 is still incomplete; no Sunday outcome is used.",
            "If nflverse has no exact player/team match, both models use the same historical baseline.",
            "Archived ESPN projected-points field only identifies playable weeks, not the fantasy point estimate.",
            "Injury/snap/opponent context is not applied as a scoring multiplier.",
            "Opponent comparisons fix the actual opposing lineup rather than simulating alternate opposing managers' decisions.",
        ]}
    all_seasons["game_environment_v9_backtest"]={
        "status":"EXPERIMENTAL_NOT_PROMOTED",
        "by_season":{year:res.get("summary",{"reason":res.get("reason")})
                     for year,res in environment_results.items()},
        "valid_season_count":sum(res.get("status")=="EXPLORATORY_RETROSPECTIVE_NO_AUTOMATIC_PROMOTION"
                                for res in environment_results.values()),
        "note":"Separate v9 game environment shadow; not equivalent to pregame forecasts"}
    (OUT/"AAA_cross_season_game_environment.json").write_text(
        json.dumps(all_seasons["game_environment_v9_backtest"],indent=2))
    (OUT/"AAA_cross_season_summary.json").write_text(json.dumps(all_seasons,indent=2))
    (OUT/"AAA_cross_season_all_teamweeks.json").write_text(json.dumps(combined,indent=2))
    lines=[
        "# AAA Historical Lineup Replay — Cross-Season Results",
        "",
        "No auto-promotion: retrospective roster replay, not a true recorded pregame forecast.",
        "",
        "| Season | Team-weeks | Model better | Model worse | Tied | Avg PPR change | Baseline wins | Workload wins |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"
    ]
    for s in season_reports:
        x=s["summary"]
        lines.append(f"| {s['season']} | {x['team_weeks']} | {x['workload_better']} | {x['workload_worse']} | {x['lineup_ties']} | {x['mean_points_delta']:+.2f} | {x['baseline_wins']} | {x['workload_wins']} |")
    lines+=["","## Team-by-team by season"]
    for s in season_reports:
        lines+=["",f"### {s['season']}","",
                "| Manager | Team-weeks | Changed | Better | Worse | Total PPR gain | Wins baseline → workload |",
                "|---|---:|---:|---:|---:|---:|---|"]
        for tid, t in sorted(s["summary"]["by_team"].items(),key=lambda p:-p[1]["points_delta"]):
            name=s["team_names"].get(tid,tid)
            lines.append(f"| {name} | {t['team_weeks']} | {t['different_lineups']} | {t['workload_better']} | {t['workload_worse']} | {t['points_delta']:+.2f} | {t['baseline_wins']} → {t['workload_wins']} |")
    lines+=["","## Methodology and limitations"]+[f"- {x}" for x in all_seasons["caveats"]]
    (OUT/"AAA_cross_season_report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({"cross_season_team_weeks":n,"average_gain":round(total/n,3),
                      "bootstrap":all_seasons["confidence"]}))


if __name__=="__main__":
    main()
