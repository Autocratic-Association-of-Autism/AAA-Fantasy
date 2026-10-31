"""Prospective scoring of immutable pregame AAA Action artifacts.

Uses predictions recorded BEFORE an individual NFL kickoff. Future outcomes,
postkickoff projections, current-week partial scores, and missing snapshots
are never interpreted as completed performance.
"""
from __future__ import annotations
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from .engine import date, optimize
from .download_export import github_json


def _mae(rows, key):
    a=[abs(x[key]-x["actual"]) for x in rows]
    return round(sum(a)/len(a),4) if a else None


def evaluate_archive(snapshot, forecast, workload, kickoffs, source_run_id=None):
    """Evaluate an archived pregame forecast against a newer completed ESPN export."""
    current=int(snapshot["League"][0]["current_week"])
    week=int(forecast["week"])
    if week >= current:
        return {"status":"PENDING_UNFINISHED_WEEK","week":week}
    if week != int(workload.get("week",-1)) or week != int(kickoffs.get("week",-1)):
        return {"status":"BLOCKED_ARCHIVE_WEEK_MISMATCH","week":week}
    if workload.get("status") != "UNVALIDATED_SHADOW__NOT_PRIMARY_CALIBRATED_FORECAST":
        return {"status":"BLOCKED_MISSING_WORKLOAD_ARCHIVE","week":week}
    timestamp=date(forecast["as_of"])
    if date(workload["as_of"]) != timestamp:
        return {"status":"BLOCKED_AS_OF_MISMATCH","week":week}
    actual = {(int(r["team_id"]),int(r["player_id"])):r
              for r in snapshot["Weekly_Lineups"] if int(r["week"]) == week}
    by_team={}
    paired=[]
    skipped={"after_kickoff":0,"missing_actual":0,"no_opportunity_projection":0}
    for tid_text,team in workload["all_rosters"].items():
        tid=int(tid_text)
        baseline=forecast["all_rosters"].get(str(tid)) or forecast["all_rosters"].get(tid) or {}
        projections=team.get("player_projections",[])
        relevant=[]
        for p in projections:
            kickoff=kickoffs.get("kickoffs",{}).get(p["nfl_team"])
            if not kickoff or date(kickoff) <= timestamp:
                skipped["after_kickoff"]+=1
                continue
            row=actual.get((tid,int(p["id"])))
            if not row or row.get("points") in (None,""):
                skipped["missing_actual"]+=1
                continue
            # ESPN uses projections as bye/no-game filter in historical extracts.
            if float(row.get("projected_points") or 0) <= 0:
                continue
            val=float(row["points"])
            workload_val=p.get("workload",{}).get("ppr_points")
            if workload_val is None:
                skipped["no_opportunity_projection"]+=1
                continue
            relevant.append({"pid":int(p["id"]),"pos":p["position"],
                             "name":p["name"],"baseline":float(p["baseline"]),
                             "workload":float(workload_val),"actual":val})
        paired+=relevant
        choice={}
        # A full-lineup retrospective requires all eligible players to be
        # predicted before their kickoff and to have actual league scoring.
        full_roster=bool(projections) and all(
            p["nfl_team"] in kickoffs.get("kickoffs",{})
            and timestamp < date(kickoffs["kickoffs"][p["nfl_team"]])
            and (tid,int(p["id"])) in actual
            for p in projections)
        if full_roster and team.get("best") and baseline.get("best"):
            means={int(p["id"]):float(actual[(tid,int(p["id"]))]["points"])
                   for p in projections}
            pool=[{"pid":int(p["id"]),"pos":p["position"]} for p in projections]
            try:
                hindsight=optimize(pool,means)
                actual_base=sum(means[int(pid)] for pid in
                                baseline["best"]["lineup"].values())
                actual_work=sum(means[int(pid)] for pid in
                                team["best"]["lineup"].values())
                choice={"status":"FULL_PREGAME_LINEUP_SCORED",
                        "hindsight_optimal":hindsight["expected_points"],
                        "baseline_actual":round(actual_base,2),
                        "workload_actual":round(actual_work,2),
                        "baseline_regret":round(hindsight["expected_points"]-actual_base,2),
                        "workload_regret":round(hindsight["expected_points"]-actual_work,2)}
            except (ValueError,KeyError,TypeError) as ex:
                choice={"status":"LINEUP_SCORE_BLOCKED","reason":str(ex)}
        else:
            choice={"status":"NO_COMPLETE_PREGAME_LINEUP","reason":
                    "One or more roster players kicked off before prediction, are missing actual scores, or lack a legal lineup"}
        by_team[str(tid)]={"eligible_paired_players":len(relevant),"lineup":choice}
    n=len(paired)
    out={
        "status":"PROSPECTIVE_EVALUATION" if n else "NO_ELIGIBLE_PREGAME_PLAYER_PAIRS",
        "week":week,"source_run_id":source_run_id,
        "forecast_saved_at":forecast["as_of"],
        "new_export_as_of":snapshot["League"][0].get("exported_utc"),
        "paired_players":n,
        "baseline_mae":_mae(paired,"baseline"),
        "workload_mae":_mae(paired,"workload"),
        "workload_minus_baseline_mae":round(_mae(paired,"workload")-_mae(paired,"baseline"),4) if n else None,
        "skipped":skipped,
        "team_lineup_results":by_team,
        "promotion_eligible":False,
        "caution":"Only frozen pre-kickoff point estimates are compared; retrospective lineup score requires a wholly pregame legal roster. No auto-promotion from one small sample.",
    }
    return out


def eligible_report_from_directory(directory):
    d=Path(directory)
    paths=[d/"forecast.json",d/"workload_forecast.json",d/"nfl_kickoffs.json"]
    if not all(x.exists() for x in paths):
        return None
    return tuple(json.loads(x.read_text()) for x in paths)


def download_prior_artifact(repo,token,run_id):
    with tempfile.TemporaryDirectory() as tmp:
        cmd=["gh","run","download",str(run_id),"--repo",repo,
             "--name",f"AAA-Forecast-Validation-{run_id}","--dir",tmp]
        env={**os.environ,"GH_TOKEN":token}
        subprocess.run(cmd,check=True,env=env,timeout=75,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        return eligible_report_from_directory(tmp)


def prospective_report(snapshot, repo, token, run_id=0, archive_loader=None):
    """One completed week at a time; no claimed calibration on historical backfills.

    Find saved pregame forecasts from previous successful Actions runs. The
    first usable forecast with the most player pairs is selected; the run ID
    makes results auditable. A missing artifact stays PENDING.
    """
    current=int(snapshot["League"][0]["current_week"])
    target=current-1
    if target < 8:
        return {"status":"PENDING_NO_FROZEN_V6_ARCHIVES",
                "target_week":target,
                "note":"The first v6 pregame workload snapshots were archived in Week 8. Earlier completed games cannot retroactively qualify as prospective."}
    base=f"https://api.github.com/repos/{repo}"
    rows=github_json(base+"/actions/workflows/aaa-forecast.yml/runs?status=success&per_page=60",token)
    candidates=[r for r in rows.get("workflow_runs",[])
                if int(r["id"]) != int(run_id)]
    # earliest successful run wins on a tie: avoid picking later updates
    candidates.sort(key=lambda r:r.get("created_at",""))
    best=None
    inspected=0
    failures=[]
    loader=archive_loader or download_prior_artifact
    for entry in candidates[-30:]:
        if inspected >= 6:
            break
        inspected+=1
        try:
            records=loader(repo,token,int(entry["id"]))
            if not records:
                continue
            forecast,workload,kickoffs=records
            if int(forecast.get("week",-1)) != target:
                continue
            result=evaluate_archive(snapshot,forecast,workload,kickoffs,int(entry["id"]))
            if result["status"] not in ("PROSPECTIVE_EVALUATION",):
                continue
            if best is None or result["paired_players"] > best["paired_players"]:
                best=result
        except Exception as e:
            failures.append({"run_id":entry["id"],
                             "reason":str(e)[:180]})
    if best:
        best["candidate_archives_inspected"]=inspected
        best["archive_errors"]=failures[:4]
        return best
    return {"status":"PENDING_NO_ELIGIBLE_PRIOR_FORECAST",
            "target_week":target,"candidate_archives_inspected":inspected,
            "archive_errors":failures[:4],
            "note":"Prospective scoring begins when a saved forecast made BEFORE kickoff has subsequently completed. Historical in-sample replay does not qualify."}
