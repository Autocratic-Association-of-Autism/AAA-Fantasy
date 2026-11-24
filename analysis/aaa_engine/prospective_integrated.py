"""Strict whole-week prospective scorecard using completed main-branch archives."""
from collections import defaultdict, Counter
from datetime import timedelta
from pathlib import Path
import json, math, os, subprocess, tempfile
import numpy as np
from .engine import date, position, team_key, optimize, PRIOR
from .download_export import github_json
from .fetch_kickoffs import fetch

VERSION="prospective-integrated-1.0"
FILES=("forecast","nfl_kickoffs","espn_pregame","blend_forecast","workload_forecast",
       "opportunity_v2_forecast","game_first_forecast","participation_risk_forecast",
       "special_teams_forecast","distribution_forecast","matchup_win_forecast","manager_behavior_forecast")
CORE=("baseline","espn","v6_or_fallback","v2_or_fallback","game_volume_or_fallback",
      "game_pressure_or_fallback","game_individual_or_fallback","blend_baseline_v2","blend_baseline_volume")

def load_archive(repo,token,run_id):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["gh","run","download",str(run_id),"--repo",repo,"--name",
                        f"AAA-Forecast-Validation-{run_id}","--dir",tmp],
                       env={**os.environ,"GH_TOKEN":token},check=True,timeout=60,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        return {name:json.loads((Path(tmp)/(name+".json")).read_text())
                for name in FILES if (Path(tmp)/(name+".json")).exists()}

def verify_archive(a,entry,week,actual_schedule):
    f=a["forecast"];s=a["nfl_kickoffs"];e=a["espn_pregame"];b=a["blend_forecast"]
    if not (entry.get("status")=="completed" and entry.get("conclusion")=="success"
            and entry.get("head_branch")=="main" and entry.get("event")!="pull_request"):
        raise ValueError("Run is not a successful completed main-branch forecast")
    if int(f["week"])!=week or int(s["week"])!=week or not s.get("complete"):
        raise ValueError("Archive target week or schedule mismatch")
    if int(actual_schedule["week"])!=week or not actual_schedule.get("complete"):
        raise ValueError("Actual schedule mismatch")
    if set(s["kickoffs"])!=set(actual_schedule["kickoffs"]):
        raise ValueError("Archived and actual NFL team coverage disagree")
    completion=date(entry["updated_at"]);ts=date(f["as_of"])
    earliest=min(date(x) for x in list(s["kickoffs"].values())+list(actual_schedule["kickoffs"].values()))
    if not (date(entry["created_at"])<=ts<=completion<earliest):
        raise ValueError("Archive was not completed before every kickoff")
    if e["status"]!="PREGAME_EXPORT_PROJECTIONS_CAPTURED" or int(e["week"])!=week:
        raise ValueError("Missing frozen target-week ESPN projections")
    if (e["forecast_as_of"]!=f["as_of"] or not f.get("snapshot_sha256") or not f.get("schedule_sha256")
        or e["snapshot_sha256"]!=f["snapshot_sha256"] or e["schedule_sha256"]!=f["schedule_sha256"]
        or date(e["exported_utc"])>ts):
        raise ValueError("ESPN source timestamp or hash mismatch")
    if b["status"]!="UNVALIDATED_FIXED_BLEND_SHADOW" or int(b["week"])!=week or b["as_of"]!=f["as_of"]:
        raise ValueError("Blend archive unavailable or mismatched")
    return {"run_id":int(entry["id"]),"run_completed_utc":entry["updated_at"],
            "forecast_as_of":f["as_of"],"first_kickoff_utc":earliest.isoformat(),
            "snapshot_sha256":f["snapshot_sha256"],"schedule_sha256":f["schedule_sha256"]}

def metrics(rows,models):
    matched=[r for r in rows if all(m in r for m in models)]
    result={"n":len(matched),"models":{}}
    if not matched:return result
    for m in models:
        err=np.array([r[m]-r["actual"] for r in matched])
        result["models"][m]={"mae":float(abs(err).mean()),"rmse":float(np.sqrt((err**2).mean())),
                             "bias":float(err.mean())}
    return result

def actuals(snapshot,week):
    if int(snapshot["League"][0]["current_week"])<=week:
        raise ValueError("ESPN has not advanced beyond target week")
    rows={};starters=defaultdict(set)
    for r in snapshot["Weekly_Lineups"]:
        if int(r["week"])!=week:continue
        key=(int(r["team_id"]),int(r["player_id"]))
        if key in rows:raise ValueError("Duplicate final player score")
        if r.get("points") in (None,""):continue
        value=float(r["points"])
        if not math.isfinite(value):raise ValueError("Nonfinite final score")
        rows[key]={**r,"actual":value}
        if r["lineup_slot"] not in ("BE","IR"):starters[key[0]].add(key[1])
    scores={};matchups=[]
    for m in snapshot["Weekly_Matchups"]:
        if int(m["week"])!=week:continue
        a,b=int(m["home_team_id"]),int(m["away_team_id"])
        if a in scores or b in scores:raise ValueError("Duplicate final matchup")
        for tid,side in ((a,"home"),(b,"away")):
            score=float(m[side+"_score"]);scores[tid]=score
            if len(starters[tid])!=9 or abs(sum(rows[tid,p]["actual"] for p in starters[tid])-score)>.02:
                raise ValueError("Final submitted lineup does not reconcile for team "+str(tid))
        matchups.append((a,b))
    if set(scores)!={int(t["team_id"]) for t in snapshot["Teams"]}:
        raise ValueError("Incomplete final matchups")
    return rows,starters,scores,matchups

def evaluate(snapshot,a,entry,week,schedule):
    proof=verify_archive(a,entry,week,schedule)
    if not all(g.get("completed") is True and g.get("status_state")=="post" for g in schedule["games"]):
        raise ValueError("NFL games not all final")
    final,starters,scores,matchups=actuals(snapshot,week)
    f=a["forecast"];ts=f["as_of"];rows={};models_by_team=defaultdict(dict);skipped=Counter()
    def valid(name,status):
        d=a.get(name,{})
        return d.get("status")==status and d.get("week")==week and d.get("as_of")==ts
    def record(tid,pid,pos,nfl):
        key=(int(tid),int(pid));act=final.get(key)
        if act is None:
            skipped["missing_final_team_player"]+=1;return None
        if position(act["position"])!=pos:
            skipped["position_mismatch"]+=1;return None
        if nfl not in schedule["kickoffs"]:
            skipped["no_verified_game"]+=1;return None
        old=rows.setdefault(key,{"team_id":key[0],"player_id":key[1],"position":pos,"nfl_team":nfl,"actual":act["actual"]})
        if old["position"]!=pos or old["nfl_team"]!=nfl:raise ValueError("Archive identity disagreement")
        return old
    def attach(tid,pid,model,value,pos,nfl):
        if value is None:return
        row=record(tid,pid,pos,nfl)
        if row is not None:
            v=float(value)
            if not math.isfinite(v):raise ValueError("Nonfinite archived prediction")
            row[model]=v
    for p in a["espn_pregame"]["players"]:
        if date(p["kickoff_utc"])!=date(a["nfl_kickoffs"]["kickoffs"][p["nfl_team"]]):raise ValueError("ESPN kickoff mismatch")
        attach(p["team_id"],p["player_id"],"espn",p["projected_points"],p["position"],p["nfl_team"])
    for tid,r in a["blend_forecast"]["all_rosters"].items():
        for p in r.get("players",[]):
            for model in ("baseline","blend_baseline_v2","blend_baseline_volume"):
                attach(tid,p["pid"],model,p[model],p["position"],p["nfl_team"])
        for model,line in r.get("choices",{}).items():models_by_team[int(tid)][model]=line
    for tid,r in f["all_rosters"].items():models_by_team[int(tid)]["baseline"]=r.get("best")
    if valid("workload_forecast","UNVALIDATED_SHADOW__NOT_PRIMARY_CALIBRATED_FORECAST"):
        for tid,r in a["workload_forecast"]["all_rosters"].items():
            models_by_team[int(tid)]["v6_or_fallback"]=r.get("best")
            for p in r["player_projections"]:
                w=(p.get("workload") or {}).get("ppr_points")
                attach(tid,p["id"],"v6_or_fallback",p["baseline"] if w is None else w,p["position"],p["nfl_team"])
                attach(tid,p["id"],"v6_genuine",w,p["position"],p["nfl_team"])
    if valid("opportunity_v2_forecast","UNVALIDATED_OPPORTUNITY_V2_SHADOW"):
        for tid,r in a["opportunity_v2_forecast"]["all_rosters"].items():
            models_by_team[int(tid)]["v2_or_fallback"]=r.get("best_shadow")
            for p in r["players"]:
                attach(tid,p["id"],"v2_or_fallback",p["v2_ppr_or_fallback"],p["position"],p["nfl_team"])
                if (p.get("v2") or {}).get("status")=="EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED":
                    attach(tid,p["id"],"v2_genuine",p["v2"]["ppr_points"],p["position"],p["nfl_team"])
    if valid("game_first_forecast","UNVALIDATED_GAME_FIRST_SHADOW"):
        for tid,r in a["game_first_forecast"]["all_rosters"].items():
            models_by_team[int(tid)]["game_pressure_or_fallback"]=r.get("best_shadow")
            models_by_team[int(tid)]["game_individual_or_fallback"]=r.get("individual_efficiency_mean_only_best")
            for p in r["players"]:
                comp=p.get("components") or {}
                attach(tid,p["pid"],"game_volume_or_fallback",comp.get("game_volume",p["shadow_mean"]),p["position"],p["nfl_team"])
                attach(tid,p["pid"],"game_pressure_or_fallback",p["shadow_mean"],p["position"],p["nfl_team"])
                attach(tid,p["pid"],"game_individual_or_fallback",p["individual_efficiency_mean_shadow"],p["position"],p["nfl_team"])
                if comp:attach(tid,p["pid"],"game_volume_genuine",comp["game_volume"],p["position"],p["nfl_team"])
    if valid("special_teams_forecast","UNVALIDATED_SPECIAL_TEAMS_SHADOW"):
        for p in a["special_teams_forecast"]["players"]:
            if p.get("pool")!="Current_Rosters":continue
            for m in ("core","expanded"):
                if p.get(m+"_genuine"):
                    attach(p["fantasy_team_id"],p["player_id"],"special_"+m,p[m],p["position"],p["nfl_team"])
    # Participation only on genuine adjustments, with paired normal v6 control.
    if valid("participation_risk_forecast","UNVALIDATED_PARTICIPATION_RISK_SHADOW"):
        for tid,r in a["participation_risk_forecast"]["all_rosters"].items():
            models_by_team[int(tid)]["participation_conditional"]=r.get("conditional_shadow_lineup")
            for p in r["players"]:
                key=(int(tid),int(p["id"]))
                if key not in rows:continue
                old=(p.get("normal_v6") or {}).get("ppr_points")
                new=(p.get("conditional_candidate") or {}).get("ppr_points")
                if old is not None and new is not None and abs(old-new)>1e-8:
                    rows[key]["participation_normal"]=float(old);rows[key]["participation_conditional"]=float(new)
    values=list(rows.values())
    comparisons={}
    for m in sorted({k for r in values for k in r if k not in ("team_id","player_id","position","nfl_team","actual","baseline","espn")}):
        comparisons[m]=metrics(values,("baseline","espn",m))
    comparisons["special_teams_by_position"]={pos:metrics([r for r in values if r["position"]==pos],
                                  ("baseline","espn","special_core","special_expanded")) for pos in ("D/ST","K")}
    comparisons["participation_paired"]=metrics(values,("participation_normal","participation_conditional"))
    lineup_rows=[]
    for tid,choices in models_by_team.items():
        # Use the complete frozen optimizer pool, not intersection of successful outcomes.
        base=f["all_rosters"].get(str(tid),{})
        ids={int(k) for k in base.get("player_means",{})}
        if not ids or any((tid,pid) not in rows for pid in ids):
            skipped["incomplete_frozen_lineup_pool"]+=1;continue
        pool=[{"pid":pid,"pos":rows[tid,pid]["position"]} for pid in ids]
        actual={pid:rows[tid,pid]["actual"] for pid in ids}
        try:ideal=optimize(pool,actual)["expected_points"]
        except ValueError:continue
        if all("espn" in rows[tid,pid] for pid in ids):
            choices["espn_optimized"]=optimize(pool,{pid:rows[tid,pid]["espn"] for pid in ids})
        for model,line in choices.items():
            if not line or not line.get("lineup"):continue
            selected=list(line["lineup"].values())
            if len(set(selected))!=9 or not set(selected)<=ids:continue
            score=sum(actual[pid] for pid in selected)
            other=next((b if a==tid else a for a,b in matchups if tid in (a,b)),None)
            lineup_rows.append({"team_id":tid,"model":model,"actual_points":score,"regret":ideal-score,
                                "win_credit_vs_actual_opponent":1. if score>scores[other] else .5 if score==scores[other] else 0.})
    lineup_by_model={m:{r["team_id"]:r for r in lineup_rows if r["model"]==m} for m in {r["model"] for r in lineup_rows}}
    lineup_comparisons={}
    for m,rs in lineup_by_model.items():
        if m=="baseline":continue
        bs=lineup_by_model.get("baseline",{});common=set(rs)&set(bs)
        if common:lineup_comparisons[m]={"n":len(common),"baseline_regret":float(np.mean([bs[t]["regret"] for t in common])),
            "challenger_regret":float(np.mean([rs[t]["regret"] for t in common])),
            "baseline_win_credits":sum(bs[t]["win_credit_vs_actual_opponent"] for t in common),
            "challenger_win_credits":sum(rs[t]["win_credit_vs_actual_opponent"] for t in common)}
    # Actual submitted-lineup margin errors, all methods on identical matchups per comparison.
    margins=[]
    for ta,tb in matchups:
        keys=[(t,p) for t in (ta,tb) for p in starters[t]]
        if not all(k in rows for k in keys):continue
        r={"actual":scores[ta]-scores[tb],"a_id":ta,"b_id":tb}
        for m in CORE:
            if all(m in rows[k] for k in keys):
                r[m]=sum(rows[ta,p][m] for p in starters[ta])-sum(rows[tb,p][m] for p in starters[tb])
        margins.append(r)
    margin_pairs={}
    for m in CORE[2:]:
        same=[r for r in margins if all(k in r for k in ("baseline","espn",m))]
        result=metrics(same,("baseline","espn",m))
        for k,v in result["models"].items():v["winner_accuracy"]=float(np.mean([np.sign(r[k])==np.sign(r["actual"]) for r in same]))
        margin_pairs[m]=result
    distribution_rows=[]
    if valid("distribution_forecast","UNVALIDATED_PLAYER_DISTRIBUTIONS_SHADOW"):
        for tid,r in a["distribution_forecast"]["all_rosters"].items():
            for p in r["players"]:
                key=(int(tid),int(p["player_id"]))
                if key not in rows:continue
                y=rows[key]["actual"]
                for m,d in p["distributions"].items():
                    distribution_rows.append({"model":m,"team_id":key[0],"player_id":key[1],
                        "coverage80":float(d["p10"]<=y<=d["p90"]),"coverage90":float(d["p05"]<=y<=d["p95"]),
                        "tail_brier":(d["tail_probability"]-float(y>=d["tail_threshold"]))**2})
    dist={m:{"n":len(rr),"coverage80":float(np.mean([x["coverage80"] for x in rr])),
              "coverage90":float(np.mean([x["coverage90"] for x in rr])),
              "tail_brier":float(np.mean([x["tail_brier"] for x in rr]))}
          for m in {x["model"] for x in distribution_rows} if (rr:=[x for x in distribution_rows if x["model"]==m])}
    # Matchup probability scores are conditional on both actual starter sets
    # matching the archived lineup sets, never an unrelated realized matchup.
    probability_rows=[]
    if valid("distribution_forecast","UNVALIDATED_PLAYER_DISTRIBUTIONS_SHADOW"):
        for m in a["distribution_forecast"].get("matchups",[]):
            ta,tb=int(m["a_id"]),int(m["b_id"])
            if set(m.get("a_lineup",[]))!=starters[ta] or set(m.get("b_lineup",[]))!=starters[tb]:continue
            y=1. if scores[ta]>scores[tb] else .5 if scores[ta]==scores[tb] else 0.
            for name,r in m.get("results",{}).items():probability_rows.append({"a_id":ta,"b_id":tb,"model":name,"brier":(r["a_win_fraction"]-y)**2})
    manager_rows=[]
    if valid("manager_behavior_forecast","UNVALIDATED_MANAGER_BEHAVIOR_SHADOW"):
        for tid,r in a["manager_behavior_forecast"]["all_rosters"].items():
            tid=int(tid)
            if r.get("status")!="CONDITIONAL_ROSTER_SHADOW":continue
            for name,model in r["models"].items():
                inc={int(k):float(v) for k,v in model["starter_inclusion"].items()}
                if not starters[tid]<=set(inc):continue
                manager_rows.append({"team_id":tid,"model":name,"starter_brier":float(np.mean([(v-float(p in starters[tid]))**2 for p,v in inc.items()]))})
    return {"status":"STRICT_PREGAME_PROSPECTIVE_EVALUATION","model_version":VERSION,"week":week,"source":proof,
            "actual_exported_utc":snapshot["League"][0]["exported_utc"],"player_comparisons":comparisons,
            "core_all_model_cohort":metrics(values,CORE),
            "core_by_position":{p:metrics([r for r in values if r["position"]==p],CORE) for p in PRIOR},
            "lineup_comparisons":lineup_comparisons,"margin_comparisons":margin_pairs,
            "distribution_quantile_and_tail":dist,"conditional_matchup_probability_rows":probability_rows,
            "manager_starter_brier_rows":manager_rows,"player_rows":values,"lineup_rows":lineup_rows,"skipped":dict(skipped),
            "promotion_eligible":False,
            "limitations":["Final fantasy roster membership may differ; missing player scores excluded, not scored as zero.",
                           "Zero realized scores retained when archived eligible; no final ESPN projection filter.",
                           "ESPN optimizer comparison requires complete same frozen pool; no hindsight candidate changes.",
                           "Quantiles and tails scored; full CRPS unavailable without archived support/weights.",
                           "No counterfactual trade outcomes, season completion or unconditional matchup calibration claim."]}

def report(snapshot,repo,token,run_id=0,archive_loader=None,schedule_loader=None):
    week=int(snapshot["League"][0]["current_week"])-1
    if week<12:return {"status":"PENDING_FIRST_INTEGRATED_COMPLETED_WEEK","target_week":week,"first_integrated_week":12,"promotion_eligible":False}
    loader=schedule_loader or fetch
    schedule=loader(int(snapshot["League"][0]["season"]),week)
    if not schedule.get("complete") or not schedule.get("games") or not all(g.get("completed") is True and g.get("status_state")=="post" for g in schedule["games"]):
        return {"status":"PENDING_FINAL_NFL_GAMES","target_week":week,"promotion_eligible":False}
    first=min(date(x) for x in schedule["kickoffs"].values())
    from urllib.parse import quote
    window=quote((first-timedelta(days=7)).isoformat()+".."+first.isoformat(),safe="")
    data=github_json(f"https://api.github.com/repos/{repo}/actions/workflows/aaa-forecast.yml/runs?branch=main&status=success&per_page=100&created={window}",token)
    candidates=[r for r in data.get("workflow_runs",[]) if int(r["id"])!=run_id and r.get("head_branch")=="main"
                and r.get("event")!="pull_request" and r.get("conclusion")=="success" and r.get("status")=="completed"
                and r.get("updated_at") and date(r["updated_at"])<first]
    candidates.sort(key=lambda r:(date(r["updated_at"]),int(r["id"])),reverse=True)
    errors=[];load=archive_loader or load_archive
    for entry in candidates[:12]:
        try:
            a=load(repo,token,int(entry["id"]))
            verify_archive(a,entry,week,schedule)
        except Exception as e:
            errors.append({"run_id":entry["id"],"reason":str(e)[:200]});continue
        # Freeze selection before examining actual results. Do not choose
        # another archive when the chosen one has poor outcomes or coverage.
        out=evaluate(snapshot,a,entry,week,schedule)
        out["archive_selection"]="Latest verified completed pre-first-kickoff main run with ESPN and blend archives; independent of outcomes"
        out["rejected_earlier_candidates"]=errors
        return out
    return {"status":"PENDING_NO_VERIFIED_INTEGRATED_ARCHIVE","target_week":week,
            "candidates":len(candidates),"archive_errors":errors,"promotion_eligible":False}
