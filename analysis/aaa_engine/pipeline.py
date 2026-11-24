"""Automated forecast: download validated snapshot, backtest, schedule gate, optimization."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json,sys,hashlib,os
from .download_export import download_export
from .fetch_kickoffs import fetch
from .validate import validate
from .cli import summarize
from .workload import download, make_report
from .contextual import download_snaps, contextualize
from .prospective import prospective_report
from .decision_backtest import backtest as decision_backtest
from .injury_context import download_injuries, enrich as enrich_injury_context
from .game_environment import download_pbp, build as build_game_environment
from .game_environment_backtest import evaluate as evaluate_game_environment
from .waiver_scout import scan as scan_waiver_context
from .opportunity_v2 import forecast_report as opportunity_v2_report, retrospective as opportunity_v2_backtest
from .game_first import (VERSION as GAME_FIRST_VERSION, completion_gate, analysis_snapshot,
                         team_records, forecast_report as game_first_report, backtest as game_first_backtest)


def run(repo, token, export_run_id=0, output_dir='forecast_output', week=None):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    info=download_export(repo,export_run_id,token,str(out/'current_export.json'))
    snapshot=json.loads((out/'current_export.json').read_text())
    validation=validate(snapshot)
    (out/'validation.json').write_text(json.dumps(validation,indent=2))
    current=int(snapshot['League'][0]['current_week'])
    year=int(snapshot['League'][0]['season'])
    now=datetime.now(timezone.utc)
    current_schedule=None
    if week is None:
        schedule=fetch(year,current)
        current_schedule=schedule
        remaining=sum(datetime.fromisoformat(t.replace('Z','+00:00'))>now
                      for t in schedule['kickoffs'].values())//2
        if remaining<2 and current<int(snapshot['League'][0]['regular_season_weeks']):
            week=current+1;schedule=fetch(year,week)
        else:week=current
    else:schedule=fetch(year,week)
    try:
        current_schedule=current_schedule or (schedule if week==current else fetch(year,current))
        gate=completion_gate(snapshot,current_schedule)
    except Exception as exc:
        gate={'status':'BLOCKED_CURRENT_WEEK_COMPLETION_CHECK','espn_current_week':current,
              'completed_through_week':current-1,'reason':str(exc),'standings_advanced':False}
    (out/'week_completion.json').write_text(json.dumps(gate,indent=2))
    (out/'nfl_kickoffs.json').write_text(json.dumps(schedule,indent=2))
    context_file=os.environ.get('FORECAST_CONTEXT_FILE')
    context=json.loads(Path(context_file).read_text()) if context_file else {}
    forecast=summarize(snapshot,week,1,now.isoformat(),schedule,context=context)
    forecast['source_run_id']=info['workflow_run']
    forecast['snapshot_sha256']=hashlib.sha256((out/'current_export.json').read_bytes()).hexdigest()
    forecast['schedule_sha256']=hashlib.sha256((out/'nfl_kickoffs.json').read_bytes()).hexdigest()
    # Workload forecast is a separately identified experimental track. Never
    # label the validated baseline run failed merely because a public data
    # provider is temporarily unavailable; report an explicit blocked state.
    try:
        stats, provenance=download(year,now.isoformat())
        workload=make_report(snapshot,forecast,schedule,stats,provenance)
        try:
            snaps, snap_source=download_snaps(year,now.isoformat())
        except Exception as snap_exc:
            snaps=None
            snap_source={"status":"SNAP_SOURCE_UNAVAILABLE",
                         "reason":str(snap_exc)}
        try:
            workload=contextualize(workload,stats,snaps,schedule,
                                   {"snap_counts":snap_source,
                                    "player_stats":provenance},context)
        except Exception as context_exc:
            workload["context_status"]="CONTEXT_BLOCKED"
            workload["context_reason"]=str(context_exc)
        # nflverse weekly report is sourced, but it does not confirm game-day
        # inactives. Injury reports inform a review flag, not a fabricated
        # snap-limit multiplier or an automatic replacement of the base model.
        injuries=None
        try:
            injuries, injury_source=download_injuries(year,now.isoformat())
            workload=enrich_injury_context(workload,injuries,injury_source,context)
        except Exception as injury_exc:
            workload["injury_context_status"]="BLOCKED_OR_UNAVAILABLE"
            workload["injury_context_reason"]=str(injury_exc)
            workload["injury_source"]=None
        # Play-level game environment: both sides' pace, drive opportunities,
        # opponent pass rush, position-specific volume and red zone. Observed
        # evidence and experimental lineup candidates are separate from the
        # primary AAA lineup and cannot silently alter it.
        try:
            pbp,game_source=download_pbp(year,workload["historical_cutoff_week"],
                                         now.isoformat())
            workload=build_game_environment(workload,pbp,schedule,snapshot,injuries)
            workload["game_environment"]["source"]=game_source
        except Exception as environment_exc:
            workload["game_environment"]={
                "status":"BLOCKED_SOURCE_OR_SCHEMA_UNAVAILABLE",
                "reason":str(environment_exc),
                "primary_model_changed":False,
                "note":"Existing baseline and workload remain unchanged."}
    except Exception as exc:
        workload={'status':'BLOCKED_WORKLOAD_DATA_UNAVAILABLE',
                  'reason':str(exc),
                  'fallback':'Use original baseline; do not invent workload inputs'}
    workload["model_version"]="v6-smoothed-opportunities"
    if isinstance(workload.get("game_environment"),dict):
        workload["game_environment"]["model_version"]="v9-context-shadow"
    (out/'workload_forecast.json').write_text(json.dumps(workload,indent=2))
    try:
        waiver_preview=scan_waiver_context(
            snapshot,stats,workload.get("game_environment",{}),schedule)
    except Exception as error:
        waiver_preview={"status":"BLOCKED_WAIVER_MATCHUP_SCOUTING",
                        "reason":str(error),
                        "note":"No claim or points recommendation made."}
    (out/'waiver_game_environment.json').write_text(
        json.dumps(waiver_preview,indent=2))
    try:
        env_validation=evaluate_game_environment(
            snapshot,stats,pbp,
            forecast["calibration"]["shrink"],
            forecast["calibration"]["recent"])
    except Exception as error:
        env_validation={
            "status":"BLOCKED_OR_UNAVAILABLE",
            "reason":str(error),
            "promotion_eligible":False}
    (out/'game_environment_backtest.json').write_text(
        json.dumps(env_validation,indent=2))
    # v2 is a separate shadow artifact. Never overwrite the production v5
    # forecasts or the existing v6 and v9 comparison reports.
    try:
        v2 = opportunity_v2_report(snapshot,forecast,workload,stats,pbp,schedule)
        v2_validation = opportunity_v2_backtest(
            snapshot,stats,pbp,
            forecast["calibration"]["shrink"],
            forecast["calibration"]["recent"])
    except Exception as error:
        v2={"status":"BLOCKED_V2_INPUT_OR_MODEL","reason":str(error),
            "applied_to_primary_model":False}
        v2_validation={"status":"BLOCKED_V2_BACKTEST",
                       "reason":str(error),"promotion_eligible":False}
    (out/'opportunity_v2_forecast.json').write_text(json.dumps(v2,indent=2))
    (out/'opportunity_v2_backtest.json').write_text(json.dumps(v2_validation,indent=2))
    # Independent shadow-only game-first experiment; never change v5 means.
    # The ESPN scoring period may lag NFL finals. Extend ONLY the shadow
    # input cutoff after final-status and full fantasy-score reconciliation.
    shadow_cutoff=current-1
    shadow_source=None
    try:
        shadow_pbp=pbp
        shadow_source=workload.get("game_environment",{}).get("source")
        requested_cutoff=int(gate["completed_through_week"])
        if requested_cutoff>shadow_cutoff:
            try:
                more_pbp,more_source=download_pbp(year,requested_cutoff,now.isoformat())
                rec=team_records(stats,more_pbp,requested_cutoff)
                from .engine import team_key
                scheduled={team_key(t) for g in current_schedule["games"] for t in g["teams"]}
                observed={t for (w,t) in rec if w==requested_cutoff}
                if not scheduled or scheduled!=observed:
                    raise ValueError("Completed week NFL stats/PBP incomplete: expected "+str(len(scheduled))+
                                     ", reconciled paired team records "+str(len(observed)))
                for g in current_schedule["games"]:
                    a,b=(team_key(t) for t in g["teams"])
                    if (more_pbp["opponents"].get((requested_cutoff,a))!=b or
                            more_pbp["opponents"].get((requested_cutoff,b))!=a):
                        raise ValueError("PBP opponent mismatch in verified completed week")
                shadow_pbp,shadow_source=more_pbp,more_source
                shadow_cutoff=requested_cutoff
            except Exception as error:
                gate["shadow_feed_warning"]=str(error)
        gate["game_first_actual_source_cutoff"]=shadow_cutoff
        (out/'week_completion.json').write_text(json.dumps(gate,indent=2))
        shadow_snapshot=analysis_snapshot(snapshot,{"completed_through_week":shadow_cutoff})
        # v2 can now use the later verified source cutoff without changing v6
        # or production baseline estimates. Retain provenance for both.
        if shadow_cutoff > int(workload["historical_cutoff_week"]) and week > shadow_cutoff:
            try:
                v2_input={**workload,"historical_cutoff_week":shadow_cutoff,
                          "game_environment":{**workload.get("game_environment",{}),"source":shadow_source}}
                v2_new=opportunity_v2_report(snapshot,forecast,v2_input,stats,shadow_pbp,schedule)
                v2_new["control_v6_cutoff_week"]=workload["historical_cutoff_week"]
                v2_validation_new=opportunity_v2_backtest(
                    shadow_snapshot,stats,shadow_pbp,
                    forecast["calibration"]["shrink"],forecast["calibration"]["recent"])
                v2,v2_validation=v2_new,v2_validation_new
                (out/'opportunity_v2_forecast.json').write_text(json.dumps(v2,indent=2))
                (out/'opportunity_v2_backtest.json').write_text(json.dumps(v2_validation,indent=2))
            except Exception as error:
                gate["v2_extended_cutoff_warning"]=str(error)
                (out/'week_completion.json').write_text(json.dumps(gate,indent=2))
        gf_validation=game_first_backtest(shadow_snapshot,stats,shadow_pbp,shadow_cutoff,
                                         forecast["calibration"]["shrink"],forecast["calibration"]["recent"])
        gf_validation["source_provenance"]={"player_stats":provenance,"pbp":shadow_source}
    except Exception as error:
        gf_validation={"status":"BLOCKED_GAME_FIRST_BACKTEST","reason":str(error),
                       "model_version":GAME_FIRST_VERSION,"promotion_eligible":False}
    try:
        gf=game_first_report(snapshot,forecast,workload,stats,shadow_pbp,schedule,
                             min(shadow_cutoff,week-1),gate)
        gf["source_provenance"]={"player_stats":provenance,"pbp":shadow_source}
        gf["forecast_cutoff_lag_weeks"]=max(0,week-1-min(shadow_cutoff,week-1))
    except Exception as error:
        gf={"status":"BLOCKED_GAME_FIRST_FORECAST","reason":str(error),
            "model_version":GAME_FIRST_VERSION,"promotion_eligible":False}
    (out/'game_first_forecast.json').write_text(json.dumps(gf,indent=2))
    (out/'game_first_backtest.json').write_text(json.dumps(gf_validation,indent=2))
    # Separate retrospective decision replay from genuine prospective
    # validation. Never let this exploratory result promote a model.
    try:
        decision=decision_backtest(snapshot,stats,
                                   forecast['calibration']['shrink'],
                                   forecast['calibration']['recent'])
    except Exception as exc:
        decision={'status':'BLOCKED_RETROSPECTIVE_TEST',
                  'reason':str(exc),
                  'caution':'No retrospective improvement claim warranted'}
    (out/'decision_backtest.json').write_text(json.dumps(decision,indent=2))
    # Historical evaluation MUST use archived, immutable pregame forecasts.
    # If Actions artifacts are temporarily inaccessible, report pending
    # rather than retroactively fabricating a scorecard.
    try:
        prospective=prospective_report(analysis_snapshot(snapshot,gate),repo,token,
                                      int(os.getenv('GITHUB_RUN_ID') or 0))
        prospective['week_completion_gate']=gate
        prospective['raw_espn_current_week']=current
        prospective['fantasy_scores_provisional_until_espn_advances']=(
            int(gate["completed_through_week"])>=current)
    except Exception as exc:
        prospective={"status":"BLOCKED_ARCHIVE_ACCESS",
                     "reason":str(exc),
                     "note":"Prospective validation not available, no model promoted."}
    (out/'prospective_scorecard.json').write_text(json.dumps(prospective,indent=2))
    forecast['waiver_scouting']={
        'status':waiver_preview['status'],
        'report_file':'waiver_game_environment.json',
        'waiver_actions_taken':False}
    forecast['game_environment_backtest']={
        'status':env_validation["status"],
        'summary':env_validation.get("summary"),
        'report_file':'game_environment_backtest.json',
        'promotion_eligible':False}
    forecast['retrospective_lineup_test']={
        'status':decision["status"],'summary':decision.get('summary'),
        'report_file':'decision_backtest.json'}
    forecast['prospective_scorecard']={"status":prospective["status"],
                                     "report_file":"prospective_scorecard.json",
                                     "paired_players":prospective.get("paired_players"),
                                     "v2_paired_players":prospective.get("v2_paired_players"),
                                     "v2_mae":prospective.get("v2_mae"),
                                     "source_run_id":prospective.get("source_run_id")}
    forecast['opportunity_v2_shadow']={
        'status':v2['status'],
        'backtest_status':v2_validation['status'],
        'backtest_summary':v2_validation.get('summary'),
        'report_files':['opportunity_v2_forecast.json','opportunity_v2_backtest.json'],
        'applied_to_primary_model':False}
    forecast['game_first_shadow']={'status':gf['status'],'model_version':GAME_FIRST_VERSION,
                                    'backtest_status':gf_validation['status'],
                                    'completed_through_week':shadow_cutoff,
                                    'report_files':['game_first_forecast.json','game_first_backtest.json','week_completion.json'],
                                    'promotion_eligible':False}
    forecast['production_model_version']='v5-lagged-ppr-control'
    forecast['workload_shadow']={
        'status':workload['status'],
        'backtest':workload.get('backtest'),
        'your_lineup':(workload.get('your_team') or {}).get('best'),
        'data_source':(workload.get('source') or {}).get('url'),
        'reason':workload.get('reason'),
        'game_environment':(workload.get('game_environment') or {}).get('status'),
        'report_file':'workload_forecast.json'}
    (out/'forecast.json').write_text(json.dumps(forecast,indent=2))
    return {'run_id':info['workflow_run'],'week':week,
            'result':forecast['status'],'validation':validation['status'],
            'workload':workload['status'],
            'prospective':prospective['status'],
            'decision_backtest':decision['status'],
            'game_environment':(workload.get('game_environment') or {}).get('status'),
            'game_environment_backtest':env_validation['status'],
            'opportunity_v2':v2['status'],
            'opportunity_v2_backtest':v2_validation['status'],
            'game_first':gf['status'],'game_first_backtest':gf_validation['status'],
            'week_completion':gate['status'],'game_first_cutoff':shadow_cutoff,
            'waiver_scouting':waiver_preview['status'],
            'user_lineup_status':forecast['all_rosters'][1]['status']}


def main():
    import os,argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--week',type=int);parser.add_argument('--output-dir',default='forecast_output')
    args=parser.parse_args()
    token=os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if not token:raise SystemExit('GH_TOKEN or GITHUB_TOKEN required')
    try:
        result=run(os.getenv('GITHUB_REPOSITORY','Autocratic-Association-of-Autism/AAA-Fantasy'),
                   token,int(os.getenv('EXPORT_RUN_ID') or 0),args.output_dir,args.week)
        print(json.dumps(result))
    except Exception as e:
        Path(args.output_dir).mkdir(exist_ok=True,parents=True)
        reason={'status':'BLOCKED_INPUT_OR_DATA_ERROR','error':str(e),
                'caution':'No legal lineup recommendation should be issued from this run.'}
        (Path(args.output_dir)/'blocked.json').write_text(json.dumps(reason,indent=2))
        print(json.dumps(reason),file=sys.stderr)
        raise

if __name__=='__main__':main()
