"""Reproducible AAA Week 8 QB rental comparison against the user's opponent.

The same non-QB outcomes and the SAME sampled QB error vector are used
for every streamer. No ESPN QB point projections enter our model, only the
list of likely starters eligible for a waiver claim.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from .download_export import download_export
from .fetch_kickoffs import fetch
from .engine import (historical, history_index, fit_baseline, predict,
                     predictions, train_residuals, current_players, locked_roster,
                     optimize, date, team_key)
from .workload import download, lookup, expected
from .contextual import allowed_context, snap_summary, download_snaps
from .injury_context import download_injuries, injury_match

N=100000
WEEK=8
SEED=17382
SLOTS=('QB','RB1','RB2','WR1','WR2','TE','FLEX','D/ST','K')


def nfl_qb_score(r):
    return (r['passing_yards']/25. + 4*r['passing_tds'] - 2*r['interceptions']
            + (r['rushing_yards']+r['receiving_yards'])/10
            + r['receptions'] + 6*(r['rushing_tds']+r['receiving_tds'])
            -2*(r['rushing_fumbles_lost']+r['receiving_fumbles_lost']
                +r['sack_fumbles_lost']))


def sources_ok(snapshot, schedule, now):
    if int(snapshot['League'][0]['current_week'])!=WEEK:
        raise ValueError('Export is not Week 8, stop to avoid wrong-week advice')
    if int(schedule['week']) != WEEK or not schedule['complete']:
        raise ValueError('Kickoff schedule not verified')
    if date(now) >= date('2026-11-01T18:00:00Z'):
        raise ValueError('Week 8 Sunday games started; re-run with live scores')
    user_roster=[r for r in snapshot['Current_Rosters'] if int(r['team_id'])==1]
    if not any(r['player']=='Patrick Mahomes' for r in user_roster):
        raise ValueError('Patrick Mahomes no longer on your team')


def baseline(pid,week,pos,idx,cfg,hist=None):
    # The original validated AAA historical projection is used whenever the
    # league has observed this player >= 2 previous weeks.
    league_history=[r for r in idx.get(int(pid),[]) if int(r['week'])<week]
    if len(league_history)>=2 or not hist:
        return round(predict(pid,week,pos,idx,cfg['shrink'],cfg['recent']),3), (
            'AAA_LEAGUE_BASELINE' if len(league_history)>=2 else 'AAA_POSITION_PRIOR')
    # For free-agent QBs never rostered for long in AAA, apply the same AAA
    # shrinkage to independent observed NFL weekly scores instead.
    obs=[nfl_qb_score(r) for r in hist]
    n=len(obs)
    p=(sum(obs)+cfg['shrink']*18.)/(n+cfg['shrink'])
    return round(p,3),'AAA_SHRINKAGE_USING_NFL_PLAYER_HISTORY'


def projected_player(p, stats, idx, cfg, cutoff):
    hist,reason=lookup(stats,p['name'],p['nfl_team'],p['pos'],cutoff)
    base,origin=baseline(p['pid'],WEEK,p['pos'],idx,cfg,hist)
    w=expected(hist,p['pos'],WEEK,cutoff)['ppr_points'] if hist and p['pos'] in ('QB','RB','WR','TE') else None
    model=round(.7*base+.3*w,3) if w is not None else base
    return {'base':base,'origin':origin,'workload':w,'blend':model,
            'history_weeks':[r['week'] for r in hist],'reason':reason}


def week_roster(snapshot,stats,schedule,idx,cfg,team_id,now):
    members=current_players(snapshot,team_id,WEEK)
    pool,locked,excluded=locked_roster(members,schedule['kickoffs'],now,True)
    if any(x['pos']=='QB' for x in pool)==False:
        raise ValueError(f'Team {team_id} missing QB')
    methods={}
    means={}
    completed={}
    actual={(int(r['team_id']),int(r['player_id'])):r
            for r in snapshot['Weekly_Lineups']
            if int(r['week'])==WEEK}
    for p in pool:
        item=projected_player(p,stats,idx,cfg,7)
        methods[p['pid']]=item
        means[p['pid']]=item['blend']
    for slot,pid in locked.items():
        p=next(x for x in pool if x['pid']==pid)
        kickoff=date(schedule['kickoffs'][team_key(p['nfl_team'])])
        if date(now)-kickoff >= timedelta(hours=8):
            rr=actual.get((team_id,pid))
            if not rr or rr.get('points') in ('',None):
                raise ValueError(f'Completed score unavailable for {p["name"]}')
            score=float(rr['points'])
            means[pid]=score
            completed[pid]=score
    selected=optimize(pool,means,locked)
    meta={p['pid']:{'pos':p['pos'],'nfl_team':p['nfl_team'],
                    'name':p['name']} for p in pool}
    return {'means':means,'methods':methods,'completed':completed,
            'selected':selected,'meta':meta,'locked':locked,
            'excluded':excluded}


def candidates(snapshot, stats, idx, cfg, schedule, injuries, snaps, now):
    listq=[]
    source=list(snapshot['Free_Agents'])+[
        r for r in snapshot['Current_Rosters'] if int(r['team_id'])==1 and r['position']=='QB']
    seen=set()
    for r in source:
        if r['position']!='QB':
            continue
        name=r['player']
        if name in seen:
            continue
        seen.add(name)
        is_rostered=int(r.get('team_id',0) or 0)==1
        if not is_rostered and float(r.get('projected_points') or 0)<=0:
            # The projection is only used as an eligibility filter; never
            # as a point estimate or a weight in the ranking.
            continue
        team=team_key(r['pro_team'])
        if team not in schedule['kickoffs']:
            continue
        injury=str(r['injury_status']).upper()
        if injury in ('OUT','INJURY_RESERVE','IR'):
            continue
        hist,reason=lookup(stats,name,team,'QB',7)
        if len(hist)<3 or max(x['week'] for x in hist)<6:
            continue
        score,origin=baseline(int(r['player_id']),WEEK,'QB',idx,cfg,hist)
        workload=expected(hist,'QB',WEEK,7)
        forecast=.7*score+.3*workload['ppr_points']
        opponent=next((other for g in schedule['games']
                      if team in g['teams']
                      for other in g['teams'] if other!=team),None)
        matchup=allowed_context(stats,team,opponent,'QB',7)
        injury_live=injury_match(injuries,name,team,WEEK,now) if injuries else {'status':'INJURY_FEED_UNAVAILABLE'}
        if injury_live.get('game_status')=='OUT':
            continue
        rec={
            'name':name,'team':team,'opponent':opponent,
            'status':'ROSTERED' if is_rostered else 'FREE_AGENT',
            'espn_reference_only':float(r.get('projected_points') or 0),
            'baseline':score,'baseline_source':origin,
            'workload':workload['ppr_points'],
            'blended':round(forecast,3),
            'workload_details':workload,
            'observed_nfl_weeks':[x['week'] for x in hist],
            'matchup':matchup,
            'injury':injury_live,
            'snap_share':snap_summary(snaps,name,team,7) if snaps is not None else {'status':'SNAP_SOURCE_UNAVAILABLE'},
            'risk_flags':[],
        }
        if hist[-1]['week']<7:
            rec['risk_flags'].append('DID_NOT_PLAY_IN_WEEK7_CHECK_STARTER_STATUS')
        if injury_live.get('game_status') in ('QUESTIONABLE','DOUBTFUL'):
            rec['risk_flags'].append('OFFICIAL_GAME_STATUS_CONFIRM_BEFORE_ADD')
        if len(hist)<5:
            rec['risk_flags'].append('SMALL_NFL_HISTORY_SAMPLE')
        if workload['expected_carries']>=5:
            rec['risk_flags'].append('RUSHING_UPSIDE_AND_VARIANCE')
        listq.append(rec)
    return sorted(listq,key=lambda r:-r['blended'])


def safe_realize(mean,err,pos):
    values=np.asarray(mean+err,dtype=float)
    return values if pos=='D/ST' else np.maximum(0.,values)


def run_sim(qbs,user,opp,errs,n=N,seed=SEED):
    rng=np.random.default_rng(seed)
    us=user['selected']['lineup']
    them=opp['selected']['lineup']
    user_qb=us['QB']
    base=np.zeros(n)
    opponent=np.zeros(n)
    for side,lineup,out in [('user',us,base),('opponent',them,opponent)]:
        sample_team=user if side=='user' else opp
        for slot,pid in lineup.items():
            if side=='user' and slot=='QB':
                continue
            if pid in sample_team['completed']:
                values=float(sample_team['completed'][pid])
            else:
                pos=sample_team['meta'][pid]['pos']
                sample=errs[pos]
                # The same residual distribution is used in the official
                # baseline simulator. Zero-centering avoids systematic drift.
                residual=rng.choice(sample,size=n,replace=True)
                residual=residual-residual.mean()
                values=safe_realize(sample_team['means'][pid],residual,pos)
            out+=values
    qb_errors=rng.choice(errs['QB'],size=n,replace=True)
    qb_errors=qb_errors-qb_errors.mean()
    outputs=[]
    for qb in qbs:
        value=safe_realize(qb['blended'],qb_errors,'QB')
        score=base+value
        qb['simulation']={
            'qb_p10':round(float(np.quantile(value,.1)),1),
            'qb_p50':round(float(np.quantile(value,.5)),1),
            'qb_p90':round(float(np.quantile(value,.9)),1),
            'qb_mean':round(float(value.mean()),2),
            'qb_20plus_chance':round(float(np.mean(value>=20)),4),
            'team_mean':round(float(score.mean()),2),
            'opponent_team_mean':round(float(opponent.mean()),2),
            'win_chance':round(float(np.mean(score>opponent)+.5*np.mean(score==opponent)),4),
            'model_mean_minus_zero':round(qb['blended'],2),
        }
        for label,wgt in [('baseline_only',1.),('half_workload',.5),('workload_only',0.)]:
            trial=wgt*qb['baseline']+(1-wgt)*qb['workload']
            trial_score=base+safe_realize(trial,qb_errors,'QB')
            qb['simulation'][label+'_win_chance']=round(
                float(np.mean(trial_score>opponent)+.5*np.mean(trial_score==opponent)),4)
        # Hypothetical defense adjustment, NOT a calibrated predictive change.
        for label,change in [('downside_10pct',-.10),('upside_10pct',.10)]:
            trial_score=base+safe_realize(qb['blended']*(1+change),qb_errors,'QB')
            qb['simulation'][label+'_win_chance']=round(
                float(np.mean(trial_score>opponent)),4)
        outputs.append(qb)
    outputs.sort(key=lambda q:-q['simulation']['win_chance'])
    reference=next((q for q in outputs if q['name']=='Patrick Mahomes'),None)
    if reference:
        for q in outputs:
            q['simulation']['win_probability_change_vs_mahomes_pp']=round(
                100*(q['simulation']['win_chance']-reference['simulation']['win_chance']),2)
            q['simulation']['blended_points_change_vs_mahomes']=round(
                q['blended']-reference['blended'],2)
    return outputs


def main():
    repo=os.environ.get('GITHUB_REPOSITORY','Autocratic-Association-of-Autism/AAA-Fantasy')
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:raise ValueError('GitHub token required')
    output=Path('qb_comparison_output')
    output.mkdir(exist_ok=True)
    exported=download_export(repo,0,token,str(output/'snapshot.json'))
    snapshot=json.loads((output/'snapshot.json').read_text())
    now=datetime.now(timezone.utc).isoformat()
    schedule=fetch(2026,WEEK)
    sources_ok(snapshot,schedule,now)
    stats,stat_src=download(2026,now)
    inj,inj_src=download_injuries(2026,now)
    try:snaps,snap_src=download_snaps(2026,now)
    except Exception as exc:snaps=None;snap_src={'status':'SOURCE_UNAVAILABLE','reason':str(exc)}
    hist=historical(snapshot,7)
    cfg=fit_baseline(hist,(2,3,4))
    idx=history_index(hist)
    residuals=train_residuals(predictions(hist,cfg['shrink'],cfg['recent'],2,7))
    user=week_roster(snapshot,stats,schedule,idx,cfg,1,now)
    opp=week_roster(snapshot,stats,schedule,idx,cfg,3,now)
    options=candidates(snapshot,stats,idx,cfg,schedule,inj,snaps,now)
    if not any(q['name']=='Patrick Mahomes' for q in options):
        raise ValueError('Mahomes missing from comparison')
    if not any(q['name']=='Jacoby Brissett' for q in options):
        raise ValueError('Brissett missing or unsupported by observed NFL stats')
    options=run_sim(options,user,opp,residuals)
    ours=user['selected']['lineup']
    theirs=opp['selected']['lineup']
    report={
        'status':'QB_RENTAL_WEEK8_SIMULATED_NOT_CALIBRATED',
        'as_of_utc':now,'league_id':1438350867,'week':WEEK,'draws':N,
        'espn_export_run_id':exported['workflow_run'],
        'baseline_validation':'historical Weeks 2-4 selection; Weeks 5-6 heldout QB distribution',
        'model':'70% AAA scoring baseline + 30% independent nflverse opportunity model. 100k common-random-number paired games; positional historical empirical scoring errors, no NFL-team correlation (shadow correlation not promoted).',
        'sources':{'nflverse_player_stats':stat_src,'nflverse_injuries':inj_src,
                   'nflverse_snap_counts':snap_src,'nfl_schedule':schedule['source']},
        'league_roster_as_of_utc':snapshot['League'][0]['exported_utc'],
        'locked_actuals_user':{user['meta'][pid]['name']:v for pid,v in user['completed'].items()},
        'locked_actuals_opponent':{opp['meta'][pid]['name']:v for pid,v in opp['completed'].items()},
        'user_nonqb_lineup':{slot:user['meta'][pid]['name'] for slot,pid in ours.items() if slot!='QB'},
        'opponent_lineup':{slot:opp['meta'][pid]['name'] for slot,pid in theirs.items()},
        'qb_options':options,
        'limitations':[
            'NFL starters and inactive status require official Sunday confirmation; ESPN positive projection is an eligibility filter only.',
            'Free agents not previously rostered in AAA use the same baseline shrinkage against nflverse NFL stats; not the exact league-only baseline.',
            'NFL matchup fantasy points allowed are contextual only; unvalidated 10% changes appear solely as sensitivity cases.',
            'QB scoring distributions share league QB historical error law; do not claim individual calibrated tails.',
            'The other positions use optimized 70/30 projections rather than the manager’s current unoptimized lineup, to avoid including an opponent player ruled OUT.',
            'No waiver claim is executed. The roster slot is contingent on A.J. Brown remaining IR eligible.',
            'No future games, week 8 player stats, ESPN projected scores, or results of Sunday games entered the player forecasts.'
        ]
    }
    (output/'AAA_Week8_QB_Streamer_Simulation.json').write_text(json.dumps(report,indent=2))
    lines=['# AAA Week 8 quarterback stream comparison',
        '',f'As of {now}. {N:,} paired simulations.','',
        '| Player | Matchup | Baseline | Workload | Blended | QB 10–90% | 20+ chance | Matchup win chance | Δ vs Mahomes |',
        '|---|---|---:|---:|---:|---|---:|---:|---:|']
    for q in options:
        v=q['simulation']
        lines.append(f"| {q['name']} | {q['team']} vs {q['opponent']} | {q['baseline']:.1f} | {q['workload']:.1f} | {q['blended']:.1f} | {v['qb_p10']:.1f}–{v['qb_p90']:.1f} | {100*v['qb_20plus_chance']:.1f}% | {100*v['win_chance']:.1f}% | {v['win_probability_change_vs_mahomes_pp']:+.1f} pp |")
    lines+=['','## Identical simulation assumptions','',
            f"User locked scores: {report['locked_actuals_user']}",
            f"Opponent locked scores: {report['locked_actuals_opponent']}",
            '','QB risk flags:']
    for q in options:
        lines.append(f"- {q['name']}: {', '.join(q['risk_flags']) or 'none'}; "
                     f"injury: {q['injury'].get('game_status',q['injury']['status'])}")
    lines+=['','## Important limitations']+[f'- {x}' for x in report['limitations']]
    (output/'AAA_Week8_QB_Streamer_Report.md').write_text('\n'.join(lines))
    print(json.dumps({'status':report['status'],'qbs':len(options),
                      'top':[(q['name'],q['blended'],q['simulation']['win_chance']) for q in options[:6]],
                      'export':report['espn_export_run_id']}))


if __name__=='__main__':main()
