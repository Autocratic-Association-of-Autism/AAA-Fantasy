"""Chronological, leakage-guarded validation. Never call a ten-matchup holdout 'fully calibrated'."""
from __future__ import annotations
from collections import defaultdict
import json
import numpy as np
from .engine import (historical, fit_baseline, predictions, train_residuals,
                     train_team_correlation, score_intervals, evaluate_accuracy,
                     simulate_pair, PRIOR)


def validate(snapshot, seed=421):
    complete = min(6, int(snapshot['League'][0]['current_week'])-1)
    if complete < 6:
        raise ValueError('Validation requires at least six completed NFL weeks')
    rows = historical(snapshot, 6)
    hyper = fit_baseline(rows, (2,3,4))
    p = predictions(rows,hyper['shrink'],hyper['recent'],start=2,stop=6)
    train = [r for r in p if r['week'] in (2,3,4)]
    hold = [r for r in p if r['week'] in (5,6)]
    residuals = train_residuals(train)
    corr = train_team_correlation(train,residuals)
    by_pos = {pos:evaluate_accuracy([r for r in hold if r['pos']==pos]) for pos in PRIOR}
    results = []
    starts = defaultdict(dict)
    for r in hold:
        if r['slot'] not in ('BE','IR'):
            starts[(r['week'],r['team_id'])][r['pid']] = r
    for m in snapshot['Weekly_Matchups']:
        w = int(m['week'])
        if w not in (5,6):continue
        home,away = int(m['home_team_id']),int(m['away_team_id'])
        a=starts.get((w,home),{});b=starts.get((w,away),{})
        if len(a)!=9 or len(b)!=9:
            results.append({'week':w,'home_id':home,'away_id':away,
                            'status':'excluded_incomplete_lineup','home_starters':len(a),'away_starters':len(b)})
            continue
        means={x['pid']:x['estimate'] for x in list(a.values())+list(b.values())}
        meta={x['pid']:x for x in list(a.values())+list(b.values())}
        # Dummy keys are used here only to add nine independently selected players.
        aa={str(i):x['pid'] for i,x in enumerate(a.values())}
        bb={str(i):x['pid'] for i,x in enumerate(b.values())}
        independent=simulate_pair(aa,bb,means,meta,residuals,0.,n=12000,seed=seed+w*100+home)
        adjusted=simulate_pair(aa,bb,means,meta,residuals,corr['rho_team'],n=12000,seed=seed+w*100+home)
        observed=float(m['home_score'])>float(m['away_score'])
        results.append({'week':w,'home_id':home,'away_id':away,'status':'evaluated',
                        'home_win':int(observed), 'independent_win_prob':independent['a_win_rate'],
                        'correlated_win_prob':adjusted['a_win_rate'],
                        'home_actual':m['home_score'],'away_actual':m['away_score']})
    eval_matches=[m for m in results if m['status']=='evaluated']
    if not eval_matches: raise ValueError('No complete held-out matchup records')
    def brier(key):return float(np.mean([(r[key]-r['home_win'])**2 for r in eval_matches]))
    b0,b1=brier('independent_win_prob'),brier('correlated_win_prob')
    # Do not promote added complexity when the holdout fails to improve over the simple model.
    correlated_approved = b1 < b0 - 0.002 and len(eval_matches)>=30
    # For fewer than 30 matchups, include paired correlation only as sensitivity range.
    return {'status':'PARTIAL_OUT_OF_TIME_VALIDATION_NOT_FULL_SEASON',
            'source':'AAA ESPN 2026 snapshot, weeks 1-6 complete',
            'sampling_warning':'History includes league-rostered players, not every free agent; as-played starters are retrospective and cannot validate lock-time decisions.',
            'training_weeks':[2,3,4], 'sealed_test_weeks':[5,6],
            'fit':hyper,'observations':{'training_players':len(train),'heldout_players':len(hold),
              'heldout_matchups':len(eval_matches),'excluded_matchups':len(results)-len(eval_matches)},
            'accuracy':{'train':evaluate_accuracy(train),'holdout':evaluate_accuracy(hold),
              'holdout_by_position':by_pos,
              'empirical_80pct_coverage':round(score_intervals(train,hold,.8),4),
              'empirical_90pct_coverage':round(score_intervals(train,hold,.9),4)},
            'probability':{'independent_brier':round(b0,5),'correlated_brier':round(b1,5),
              'team_rho_estimated':corr,'correlation_promoted':correlated_approved,
              'used_rho':corr['rho_team'] if correlated_approved else 0.,
              'caution':'10 games is insufficient for calibrated matchup odds; 30-game promotion threshold is a minimum screen, not proof.'},
            'heldout_matchup_rows':results,
            'unvalidated_components':['individual injury adjustments','rookie route/target distributions',
                'international-game travel effects','opponent defensive matchup multipliers',
                'future injuries','playoff/last-place simulations','pregame lineup selection'],
            'policy':'Fail closed on kickoff/roster ambiguity; do not present unvalidated scenario weights as measured win probabilities.'}


if __name__=='__main__':
    import sys
    with open(sys.argv[1]) as f: s=json.load(f)
    print(json.dumps(validate(s),indent=2))
