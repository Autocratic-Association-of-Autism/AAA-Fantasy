"""Run the validated AAA baseline and guard-railed prospective lineup optimization.

Example: python -m aaa_engine.cli --snapshot export/snapshot.json --week 8 \
  --kickoffs export/nfl_week8.json --team-id 1 --output forecast.json
"""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
from .engine import (date,historical,history_index,fit_baseline,predict,train_residuals,
                     train_team_correlation,predictions,current_players,locked_roster,
                     optimize,scenario_sensitivity,simulate_pair,team_key)
from .validate import validate


def summarize(snapshot, week, team_id, as_of, schedule, context=None, sims=30000):
    context=context or {}
    if context:
        if not context.get('as_of') or date(context['as_of']) > date(as_of):
            raise ValueError('BLOCKED: contextual news is missing an as-of timestamp or comes from the future')
        if not context.get('sources'):
            raise ValueError('BLOCKED: injury/role/opponent input requires documented source references')
        if any('weight' in s for s in context.get('external_scenarios',[])):
            raise ValueError('Unvalidated context scenarios cannot receive probability weights')
    team_id=int(team_id)
    league=snapshot['League'][0]
    current_week=int(league['current_week'])
    if week < current_week:
        raise ValueError('Past-week optimizer is not a prospective forecast')
    if week>int(league['regular_season_weeks']):
        raise ValueError('Playoff weeks require separately verified bracket and rosters')
    if int(schedule.get('week',-1))!=week:
        raise ValueError('BLOCKED: NFL schedule week does not match requested week')
    kickoff=schedule['kickoffs']
    if not schedule.get('complete') or len(kickoff)<26:
        raise ValueError('BLOCKED: insufficient NFL kickoff coverage: no legal start/sit output')
    for k,v in kickoff.items():
        date(v)
    last_week=current_week-1 # train only on fully completed weeks, never partial current-week results
    rows=historical(snapshot,last_week)
    cfg=fit_baseline(rows)
    idx=history_index(rows)
    scores=predictions(rows,cfg['shrink'],cfg['recent'],2,last_week)
    calibrated=[r for r in scores if r['week']>=2]
    err=train_residuals(calibrated)
    # More data may estimate the team covariance, but it may NOT promote
    # correlated win probabilities without a separate later held-out validation.
    corr=train_team_correlation(calibrated,err)
    baseline_validation=validate(snapshot)
    rho=baseline_validation['probability']['used_rho']
    rosters={}
    for t in snapshot['Teams']:
        tid=int(t['team_id'])
        members=current_players(snapshot,tid,week)
        pool,locked,excluded=locked_roster(members,kickoff,as_of,week_is_current=(week==current_week))
        means={p['pid']:predict(p['pid'],week,p['pos'],idx,cfg['shrink'],cfg['recent']) for p in pool}
        risk=[]
        for p in pool:
            seen=len([r for r in idx.get(p['pid'],[]) if r['week']<week])
            flags=[]
            if seen<=3:flags.append('limited_history_or_recent_promotion')
            if p['injury'] in ('QUESTIONABLE','DOUBTFUL'):
                flags.append('current_injury_designation_must_reverify_for_target_week')
            if p['nfl_team'] in {team_key(x) for x in schedule.get('international_teams',[])}:
                flags.append('international_travel_uncertainty')
            manual=context.get('player_flags',{}).get(str(p['pid']),[])
            if manual:flags.extend(str(x) for x in manual)
            if flags:risk.append({'player':p['name'],'player_id':p['pid'],'flags':sorted(set(flags))})
        try:
            best=optimize(pool,means,locked)
            # Conservative what-if tests: ranges, not assumed scenario probabilities.
            fragile={x['player_id'] for x in risk if 'limited_history_or_recent_promotion' in x['flags']}
            intl={p['pid'] for p in pool if p['nfl_team'] in {team_key(x) for x in schedule.get('international_teams',[])}}
            quarterbacks_and_kickers={p['pid'] for p in pool if p['pos'] in ('QB','K')}
            dst={p['pid'] for p in pool if p['pos']=='D/ST'}
            hypothetical=[
              {'name':'low_volume_short_history_illustration','player_multipliers':{str(x):.60 for x in fragile}},
              {'name':'higher_volume_short_history_illustration','player_multipliers':{str(x):1.30 for x in fragile}},
              {'name':'international_travel_illustration','player_multipliers':{str(x):.80 for x in intl}},
              {'name':'offense_stalls_illustration','player_multipliers':{str(x):.60 for x in quarterbacks_and_kickers}},
            ]
            hypothetical += [
                {'name':f'dst_negative_tail_for_{x}','player_overrides':{str(x):-3}}
                for x in dst]
            if context:
                for scenario in context.get('external_scenarios',[]):
                    if not scenario.get('source'):
                        raise ValueError('Every externally supplied stress scenario needs a source')
                    # A scenario may mention other managers; restrict its application to this roster.
                    ids=set(means)
                    hyp={**scenario}
                    hyp['player_multipliers']={str(pid):v for pid,v in scenario.get('player_multipliers',{}).items() if int(pid) in ids}
                    hyp['player_overrides']={str(pid):v for pid,v in scenario.get('player_overrides',{}).items() if int(pid) in ids}
                    hypothetical.append(hyp)
            sensitivity=scenario_sensitivity(pool,means,locked,hypothetical)
            status='READY_WITH_UNVALIDATED_CONTEXT_RISKS'
        except ValueError as e:
            best=None;sensitivity=None;status='BLOCKED_INCOMPLETE_LEGAL_LINEUP: '+str(e)
        rosters[tid]={'team':t['team_name'],'status':status,'players':len(members),
                      'locked':locked,'excluded':excluded,'risk_flags':risk,'best':best,
                      'sensitivity':sensitivity,'player_means':{str(k):round(v,2) for k,v in means.items()},
                      '_means':means,'_pool':pool}
    target=next((s for s in snapshot['Season_Schedule'] if s['week']==week and team_id in (s['team_a_id'],s['team_b_id'])),None)
    if target is None: raise ValueError('No scheduled regular season matchup')
    opponent=target['team_b_id'] if target['team_a_id']==team_id else target['team_a_id']
    matchup=None
    a,b=rosters[team_id],rosters[opponent]
    if a['best'] and b['best']:
        both=a['_pool']+b['_pool']; meta={p['pid']:p for p in both}; means={**a['_means'],**b['_means']}
        matchup={'opponent_id':opponent,'opponent':b['team'],
                 'model':simulate_pair(a['best']['lineup'],b['best']['lineup'],means,meta,err,rho,sims),
                 'correlated_shadow':simulate_pair(a['best']['lineup'],b['best']['lineup'],means,meta,err,corr['rho_team'],sims),
                 'uncertainty':'Point predictions use lagged scoring only. Matchup adjustments and injury probabilities are NOT calibrated.'}
    for r in rosters.values():
        del r['_means'],r['_pool']
    return {'status':'MODEL_BASELINE_PARTIALLY_VALIDATED__LINEUP_DECISIONS_NOT_YET_PROSPECTIVELY_VALIDATED',
            'as_of':as_of,'espn_exported_utc':league['exported_utc'], 'week':week,
            'snapshot_source':'ESPN GitHub artifact','schedule_source':schedule.get('source','unspecified'),
            'context_sources':context.get('sources',[]),
            'calibration':{'shrink':cfg['shrink'],'recent':cfg['recent'],
                           'heldout_MAE':baseline_validation['accuracy']['holdout']['mae'],
                           'heldout_Brier':baseline_validation['probability']['independent_brier'],
                           'team_rho_scenario_estimate':corr['rho_team'],
                           'team_rho_promoted':rho},
            'data_gaps':['No archived full NFL target/route logs; do not claim target-share model was tested.',
                         'No timestamped historical pregame lineups; prospective lineup regret cannot yet be measured.',
                         'Current ESPN injury labels may not be valid for future weeks; official inactive checks are required.',
                         'Sensitivity cases are explicitly hypothetical, not weighted predictive scenarios.',
                         'Weather and opponent DVOA are NOT independently obtained or validated.'],
            'all_rosters':rosters, 'your_team_id':team_id,'opponent':matchup}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--snapshot',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--validate-only',action='store_true')
    ap.add_argument('--week',type=int)
    ap.add_argument('--team-id',type=int,default=1)
    ap.add_argument('--kickoffs')
    ap.add_argument('--context',help='Optional timestamped sourced injury/route/travel/OL what-if scenarios')
    ap.add_argument('--as-of',default=datetime.now(timezone.utc).isoformat())
    ap.add_argument('--sims',type=int,default=30000)
    a=ap.parse_args()
    snapshot=Path(a.snapshot).read_bytes()
    league=json.loads(snapshot)
    if a.validate_only:
        result=validate(league)
    else:
        if a.week is None or not a.kickoffs:
            raise SystemExit('BLOCKED: --week and verified --kickoffs are mandatory for actionable lineup recommendations')
        schedule=json.loads(Path(a.kickoffs).read_text())
        context=json.loads(Path(a.context).read_text()) if a.context else {}
        result=summarize(league,a.week,a.team_id,a.as_of,schedule,context=context,sims=a.sims)
    result['snapshot_sha256']=hashlib.sha256(snapshot).hexdigest()
    dest=Path(a.output);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2))
    print(f'Wrote {dest}: {result["status"]}')

if __name__=='__main__':main()
