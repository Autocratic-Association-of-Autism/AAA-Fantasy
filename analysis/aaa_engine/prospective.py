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


def evaluate_archive(snapshot, forecast, workload, kickoffs, source_run_id=None, v2=None):
    """Score only archived, pre-kickoff predictions against completed ESPN games.

    v2 is optional because archives preceding its deployment do not contain it.
    The v2 comparison uses only players with a genuine v2 point projection, and
    compares all three methods on that IDENTICAL paired player sample.
    """
    current = int(snapshot["League"][0]["current_week"])
    week = int(forecast["week"])
    if week >= current:
        return {"status": "PENDING_UNFINISHED_WEEK", "week": week}
    if week != int(workload.get("week", -1)) or week != int(kickoffs.get("week", -1)):
        return {"status": "BLOCKED_ARCHIVE_WEEK_MISMATCH", "week": week}
    if workload.get("status") != "UNVALIDATED_SHADOW__NOT_PRIMARY_CALIBRATED_FORECAST":
        return {"status": "BLOCKED_MISSING_WORKLOAD_ARCHIVE", "week": week}

    timestamp = date(forecast["as_of"])
    if date(workload["as_of"]) != timestamp:
        return {"status": "BLOCKED_AS_OF_MISMATCH", "week": week}

    v2_valid = bool(
        isinstance(v2, dict)
        and v2.get("status") == "UNVALIDATED_OPPORTUNITY_V2_SHADOW"
        and int(v2.get("week", -1)) == week
        and v2.get("as_of")
        and date(v2["as_of"]) == timestamp
        and isinstance(v2.get("all_rosters"), dict)
    )
    v2_status = ("AVAILABLE_FROZEN_SHADOW" if v2_valid
                 else "NO_V2_IN_ARCHIVE" if v2 is None
                 else "BLOCKED_INVALID_V2_ARCHIVE")
    actual = {(int(r["team_id"]), int(r["player_id"])): r
              for r in snapshot["Weekly_Lineups"] if int(r["week"]) == week}
    by_team = {}
    paired = []
    paired_v2 = []
    skipped = {"after_kickoff": 0, "missing_actual": 0,
               "no_opportunity_projection": 0, "no_genuine_v2_projection": 0}

    for tid_text, team in workload["all_rosters"].items():
        tid = int(tid_text)
        baseline = (forecast["all_rosters"].get(str(tid))
                    or forecast["all_rosters"].get(tid) or {})
        projections = team.get("player_projections", [])
        v2_team = (v2["all_rosters"].get(str(tid))
                   or v2["all_rosters"].get(tid) or {}) if v2_valid else {}
        v2_rows = {int(p["id"]): p for p in v2_team.get("players", [])}
        relevant = []
        relevant_v2 = []

        for p in projections:
            kickoff = kickoffs.get("kickoffs", {}).get(p["nfl_team"])
            if not kickoff or date(kickoff) <= timestamp:
                skipped["after_kickoff"] += 1
                continue
            row = actual.get((tid, int(p["id"])))
            if not row or row.get("points") in (None, ""):
                skipped["missing_actual"] += 1
                continue
            # The historical ESPN projection is used only to filter bye/no game.
            if float(row.get("projected_points") or 0) <= 0:
                continue
            score = p.get("workload", {}).get("ppr_points")
            if score is None:
                skipped["no_opportunity_projection"] += 1
                continue
            sample = {"pid": int(p["id"]), "pos": p["position"],
                      "name": p["name"], "baseline": float(p["baseline"]),
                      "workload": float(score), "actual": float(row["points"])}
            relevant.append(sample)
            v2_row = v2_rows.get(int(p["id"]), {})
            genuine = v2_row.get("v2") or {}
            if (genuine.get("status") == "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED"
                    and v2_row.get("nfl_team") == p["nfl_team"]
                    and v2_row.get("position") == p["position"]
                    and not v2_row.get("locked_actual")):
                relevant_v2.append({**sample, "v2": float(genuine["ppr_points"])})
            elif v2_valid:
                skipped["no_genuine_v2_projection"] += 1

        paired.extend(relevant)
        paired_v2.extend(relevant_v2)

        # Lineup regret is comparable only if the entire saved lineup was
        # selected before every rostered player's kickoff and their outcomes
        # are present in the subsequent export.
        full_roster = bool(projections) and all(
            p["nfl_team"] in kickoffs.get("kickoffs", {})
            and timestamp < date(kickoffs["kickoffs"][p["nfl_team"]])
            and (tid, int(p["id"])) in actual
            and actual[(tid, int(p["id"]))].get("points") not in (None, "")
            for p in projections)
        if full_roster and team.get("best") and baseline.get("best"):
            means = {int(p["id"]): float(actual[(tid, int(p["id"]))]["points"])
                     for p in projections}
            pool = [{"pid": int(p["id"]), "pos": p["position"]} for p in projections]
            try:
                hindsight = optimize(pool, means)
                ideal = hindsight["expected_points"]
                actual_base = sum(means[int(pid)] for pid in baseline["best"]["lineup"].values())
                actual_work = sum(means[int(pid)] for pid in team["best"]["lineup"].values())
                choice = {"status": "FULL_PREGAME_LINEUP_SCORED",
                          "hindsight_optimal": ideal,
                          "baseline_actual": round(actual_base, 2),
                          "workload_actual": round(actual_work, 2),
                          "baseline_regret": round(ideal - actual_base, 2),
                          "workload_regret": round(ideal - actual_work, 2)}
                v2_lineup = (v2_team.get("best_shadow") or {}).get("lineup")
                if v2_lineup:
                    actual_v2 = sum(means[int(pid)] for pid in v2_lineup.values())
                    choice.update({"v2_hybrid_shadow_actual": round(actual_v2, 2),
                                   "v2_hybrid_shadow_regret": round(ideal - actual_v2, 2),
                                   "v2_lineup_note": "May use v6 fallbacks; original pregame selection only"})
            except (ValueError, KeyError, TypeError) as ex:
                choice = {"status": "LINEUP_SCORE_BLOCKED", "reason": str(ex)}
        else:
            choice = {"status": "NO_COMPLETE_PREGAME_LINEUP",
                      "reason": "Roster not fully predicted before kickoff, missing actuals, or no legal lineup"}
        by_team[str(tid)] = {"eligible_paired_players": len(relevant),
                             "eligible_genuine_v2_players": len(relevant_v2),
                             "lineup": choice}

    n = len(paired)
    m = len(paired_v2)
    return {
        "status": "PROSPECTIVE_EVALUATION" if n else "NO_ELIGIBLE_PREGAME_PLAYER_PAIRS",
        "week": week, "source_run_id": source_run_id,
        "forecast_saved_at": forecast["as_of"],
        "new_export_as_of": snapshot["League"][0].get("exported_utc"),
        "paired_players": n,
        "baseline_mae": _mae(paired, "baseline"),
        "workload_mae": _mae(paired, "workload"),
        "workload_minus_baseline_mae": round(
            _mae(paired, "workload") - _mae(paired, "baseline"), 4) if n else None,
        "v2_archive_status": v2_status,
        "v2_paired_players": m,
        "v2_paired_baseline_mae": _mae(paired_v2, "baseline"),
        "v2_paired_workload_mae": _mae(paired_v2, "workload"),
        "v2_mae": _mae(paired_v2, "v2"),
        "v2_minus_paired_baseline_mae": round(
            _mae(paired_v2, "v2") - _mae(paired_v2, "baseline"), 4) if m else None,
        "v2_minus_paired_workload_mae": round(
            _mae(paired_v2, "v2") - _mae(paired_v2, "workload"), 4) if m else None,
        "skipped": skipped,
        "team_lineup_results": by_team,
        "promotion_eligible": False,
        "caution": "Only frozen pre-kickoff projections. Genuine v2 MAE comparisons use identical matched players; lineup v2 may contain labeled v6 fallbacks. No automatic promotion.",
    }


def eligible_report_from_directory(directory):
    d=Path(directory)
    paths=[d/"forecast.json",d/"workload_forecast.json",d/"nfl_kickoffs.json"]
    if not all(x.exists() for x in paths):
        return None
    main = tuple(json.loads(x.read_text()) for x in paths)
    v2_file = d / "opportunity_v2_forecast.json"
    return (*main, json.loads(v2_file.read_text()) if v2_file.exists() else None)


def download_prior_artifact(repo,token,run_id):
    with tempfile.TemporaryDirectory() as tmp:
        cmd=["gh","run","download",str(run_id),"--repo",repo,
             "--name",f"AAA-Forecast-Validation-{run_id}","--dir",tmp]
        env={**os.environ,"GH_TOKEN":token}
        subprocess.run(cmd,check=True,env=env,timeout=75,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        return eligible_report_from_directory(tmp)


def prospective_report(snapshot, repo, token, run_id=0, archive_loader=None):
    """Score the most recent completed NFL week from frozen, main-branch runs.

    GitHub lists newest-first. Earlier code accidentally sliced a sorted list
    and then examined only its oldest six runs, frequently missing the desired
    week entirely. Search newest-first and retain the best complete pregame
    cohort. Pull-request forecasts are not production validation evidence.
    """
    current = int(snapshot["League"][0]["current_week"])
    target = current - 1
    if target < 8:
        return {"status": "PENDING_NO_FROZEN_V6_ARCHIVES",
                "target_week": target,
                "note": "Prospective v6 archives begin in Week 8; older games cannot be backfilled."}

    base = f"https://api.github.com/repos/{repo}"
    rows = github_json(
        base + "/actions/workflows/aaa-forecast.yml/runs?status=success&per_page=100",
        token)
    candidates = [
        r for r in rows.get("workflow_runs", [])
        if int(r["id"]) != int(run_id)
        and r.get("conclusion") == "success"
        and r.get("head_branch") == "main"
        and r.get("event") != "pull_request"
    ]
    candidates.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    loader = archive_loader or download_prior_artifact
    max_attempts = 45
    inspected = 0
    failures = []
    eligible = 0
    best = None

    for entry in candidates:
        if inspected >= max_attempts:
            break
        inspected += 1
        try:
            records = loader(repo, token, int(entry["id"]))
            if not records or len(records) < 3:
                continue
            forecast, workload, kickoffs = records[:3]
            v2 = records[3] if len(records) > 3 else None
            if int(forecast.get("week", -1)) != target:
                continue
            result = evaluate_archive(
                snapshot, forecast, workload, kickoffs,
                source_run_id=int(entry["id"]), v2=v2)
            if result["status"] != "PROSPECTIVE_EVALUATION":
                continue
            eligible += 1
            # Prefer the broadest pregame cohort; on a tie, prefer a genuine
            # v2 sample, then the earliest frozen snapshot.
            if (best is None
                or result["paired_players"] > best["paired_players"]
                or (result["paired_players"] == best["paired_players"]
                    and result["v2_paired_players"] > best["v2_paired_players"])
                or (result["paired_players"] == best["paired_players"]
                    and result["v2_paired_players"] == best["v2_paired_players"]
                    and result["forecast_saved_at"] < best["forecast_saved_at"])):
                best = result
        except Exception as e:
            failures.append({"run_id": entry["id"], "reason": str(e)[:180]})

    if best:
        best["candidate_archives_inspected"] = inspected
        best["candidate_archives_eligible"] = eligible
        best["archive_errors"] = failures[:4]
        best["archive_error_count"] = len(failures)
        return best
    return {
        "status": "PENDING_NO_ELIGIBLE_PRIOR_FORECAST",
        "target_week": target,
        "candidate_archives_inspected": inspected,
        "candidate_archives_eligible": eligible,
        "archive_errors": failures[:4],
        "archive_error_count": len(failures),
        "note": "No eligible saved main-branch pre-kickoff forecast; never fabricate prospective scores.",
    }
