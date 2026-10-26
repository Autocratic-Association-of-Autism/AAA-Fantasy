"""AAA forecasting engine: chronological scoring, locked-lineup optimization, paired simulations.

No current injury field, NFL matchup, or ESPN projection is used to train past forecasts.
Historical scores are the user's league scoring, not a generic NFL points system.
"""
from __future__ import annotations
import itertools, math
from collections import defaultdict
from datetime import datetime
import numpy as np

PRIOR = {'QB': 18., 'RB': 10., 'WR': 10., 'TE': 8., 'D/ST': 6., 'K': 7.5}
SLOTS = ('QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX', 'D/ST', 'K')
ACTIVE = {'ACTIVE', 'NORMAL', 'QUESTIONABLE', 'DOUBTFUL', ''}
POSITION_ALIASES = {'DST': 'D/ST', 'DEF': 'D/ST', 'D/ST': 'D/ST'}
TEAM_ALIASES = {'JAC': 'JAX', 'LAR': 'LA', 'STL': 'LA', 'WSH': 'WSH', 'WAS': 'WSH',
                'OAK': 'LV', 'SD': 'LAC', 'ARZ': 'ARI', 'SF': 'SF'}


def team_key(s):
    s = str(s).upper()
    return TEAM_ALIASES.get(s, s)


def position(s):
    return POSITION_ALIASES.get(s, s)


def date(s):
    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('A timezone-aware as-of/kickoff timestamp is mandatory')
    return dt


def historical(snapshot, last_week):
    """A roster-sampled scoring series. Historical injury fields are deliberately ignored."""
    if last_week >= int(snapshot['League'][0]['current_week']):
        raise ValueError('Current ESPN week is not complete; it cannot be training data')
    out = []
    seen = set()
    for r in snapshot['Weekly_Lineups']:
        w = int(r['week'])
        if not (1 <= w <= last_week) or r['lineup_slot'] == 'IR':
            continue
        # Projection is used ONLY to exclude historical byes/no-game rows,
        # never as a model feature, forecast target, or injury probability.
        if float(r.get('projected_points') or 0) <= 0:
            continue
        pid = int(r['player_id'])
        key = (w, pid)
        if key in seen:
            raise ValueError(f'Duplicate player-week {key}')
        seen.add(key)
        pos = position(r['position'])
        if pos not in PRIOR:
            continue
        out.append({'week': w, 'pid': pid, 'name': r['player'], 'pos': pos,
                    'nfl_team': team_key(r['pro_team']), 'team_id': int(r['team_id']),
                    'slot': r['lineup_slot'], 'actual': float(r['points'])})
    return sorted(out, key=lambda r: (r['week'], r['pid']))


def history_index(rows):
    by = defaultdict(list)
    for r in rows:
        by[r['pid']].append(r)
    return by


def predict(pid, week, pos, indexed, shrink=5., recent=0.):
    if pos not in PRIOR:
        raise ValueError(f'Unknown position {pos}')
    previous = [float(r['actual']) for r in indexed.get(int(pid), []) if int(r['week']) < week]
    if not previous:
        return PRIOR[pos]
    avg = (1.-recent) * np.mean(previous) + recent * np.mean(previous[-3:])
    return float((len(previous) * avg + shrink * PRIOR[pos]) / (len(previous) + shrink))


def predictions(rows, shrink=5., recent=0., start=2, stop=6):
    idx = history_index(rows)
    out = []
    for r in rows:
        w = r['week']
        if start <= w <= stop:
            p = predict(r['pid'], w, r['pos'], idx, shrink, recent)
            out.append({**r, 'estimate': p, 'error': r['actual'] - p})
    return out


def fit_baseline(rows, train_weeks=(2, 3, 4)):
    trials = []
    for sh, re in itertools.product([.5, 1, 2, 3, 5, 8, 12], [0., .25, .5, 1.]):
        p = [r for r in predictions(rows, sh, re) if r['week'] in train_weeks]
        if not p:
            raise ValueError('No training player-weeks')
        mae = float(np.mean([abs(r['error']) for r in p]))
        trials.append((mae, sh, re))
    score, sh, re = min(trials)
    return {'shrink': sh, 'recent': re, 'training_mae': score, 'training_weeks': list(train_weeks)}


def train_residuals(rows):
    """Use only prior weeks to form a centered, heavy-tailed empirical error law."""
    by_pos = {}
    for pos in PRIOR:
        a = np.asarray([r['error'] for r in rows if r['pos'] == pos], dtype=float)
        if len(a) < 8:
            raise ValueError(f'Insufficient historical residuals for {pos}: {len(a)}')
        a = a - a.mean()
        by_pos[pos] = a
    return by_pos


def train_team_correlation(rows, residuals):
    """Estimate intra-NFL-team-week residual covariance, shrunk toward independence."""
    sd = {p: max(float(np.std(x, ddof=1)), 1.) for p, x in residuals.items()}
    groups = defaultdict(list)
    for r in rows:
        groups[(r['week'], r['nfl_team'])].append(r)
    products = []
    for group in groups.values():
        # Exclude redundant same-player observations by construction.
        for a, b in itertools.combinations(group, 2):
            products.append((a['error'] / sd[a['pos']]) * (b['error'] / sd[b['pos']]))
    if len(products) < 10:
        return {'rho_team': 0., 'same_team_pairs': len(products), 'status': 'insufficient_pairs'}
    raw = float(np.mean(products))
    rho = float(np.clip(max(0., raw) * len(products)/(len(products)+80), 0., .35))
    return {'rho_team': rho, 'same_team_pairs': len(products),
            'raw_covariance_proxy': raw, 'status': 'estimated_on_training_weeks'}


def score_intervals(calibration_rows, tested_rows, level=.8):
    by_pos = defaultdict(list)
    for r in calibration_rows:
        by_pos[r['pos']].append(abs(r['error']))
    if not tested_rows:
        raise ValueError('Empty holdout')
    flags = []
    for r in tested_rows:
        q = float(np.quantile(by_pos[r['pos']], level))
        flags.append(abs(r['error']) <= q)
    return float(np.mean(flags))


def current_players(snapshot, team_id, week):
    """Return all current roster members with currently assigned ESPN slots, if recorded."""
    team_id = int(team_id)
    lineup = [r for r in snapshot['Weekly_Lineups'] if int(r['week']) == week
              and int(r['team_id']) == team_id]
    slot_by_id = {int(r['player_id']): r['lineup_slot'] for r in lineup}
    out = []
    for r in snapshot['Current_Rosters']:
        if int(r['team_id']) != team_id:
            continue
        pid = int(r['player_id'])
        out.append({'pid': pid, 'name': r['player'], 'pos': position(r['position']),
                    'nfl_team': team_key(r['pro_team']), 'injury': str(r['injury_status']).upper(),
                    'slot': slot_by_id.get(pid, 'BE'), 'team_id': team_id})
    return out


def locked_roster(players, kickoffs, as_of, week_is_current):
    """Resolve all locked starter slots BEFORE optimization; no missing kickoff guessing."""
    now = date(as_of)
    if len({p['pid'] for p in players}) != len(players):
        raise ValueError('Duplicate current roster players')
    if not kickoffs:
        raise ValueError('BLOCKED: No verified NFL kickoff schedule provided')
    kickoffs = {team_key(k): v for k, v in kickoffs.items()}
    pool, locked, gone = [], {}, []
    rb_lock, wr_lock = 0, 0
    for p in players:
        pro = p['nfl_team']
        # No scheduled game = bye, provided the schedule has been verified complete.
        if pro not in kickoffs:
            gone.append((p['name'], 'bye'))
            continue
        started = date(kickoffs[pro]) <= now
        slot = p['slot'] if week_is_current else 'BE'
        if slot == 'IR':
            gone.append((p['name'], 'IR'))
            continue
        if week_is_current and not started and p['injury'] in ('OUT','INJURY_RESERVE','IR'):
            gone.append((p['name'], 'confirmed_out_current_week'))
            continue
        if started:
            if slot == 'BE':
                gone.append((p['name'], 'benched_game_started'))
                continue
            canonical = {'RB/WR/TE':'FLEX'}.get(slot,slot)
            if canonical == 'RB':
                rb_lock += 1; canonical = f'RB{rb_lock}'
            if canonical == 'WR':
                wr_lock += 1; canonical = f'WR{wr_lock}'
            if canonical not in SLOTS:
                raise ValueError(f'Invalid locked slot {canonical} for {p["name"]}')
            if canonical in locked:
                raise ValueError('Multiple players locked to same slot')
            locked[canonical] = p['pid']
        pool.append(p)
    return pool, locked, gone


def optimize(players, means, locked=None):
    """Enumerate every legal 9-player combination and honor exact locks."""
    locked = locked or {}
    pp = {p['pid']: p for p in players}
    if set(locked.values()) - set(pp):
        raise ValueError('A locked player is absent from the eligible pool')
    groups = {pos: [p['pid'] for p in players if p['pos'] == pos]
              for pos in PRIOR}
    combos = []
    for qb, te, dst, k in itertools.product(groups['QB'], groups['TE'], groups['D/ST'], groups['K']):
        for rbs in itertools.combinations(groups['RB'], 2):
            for wrs in itertools.combinations(groups['WR'], 2):
                used = {qb, te, dst, k, *rbs, *wrs}
                if len(used) != 8:
                    continue
                for flex in [p['pid'] for p in players if p['pos'] in ('RB','WR','TE') and p['pid'] not in used]:
                    for ra, rb in (rbs, rbs[::-1]):
                        for wa, wb in (wrs, wrs[::-1]):
                            lineup = dict(zip(SLOTS, (qb, ra, rb, wa, wb, te, flex, dst, k)))
                            if any(lineup[s] != pid for s, pid in locked.items()):
                                continue
                            score = float(sum(means[p] for p in lineup.values()))
                            combos.append((score, lineup))
    if not combos:
        missing = [p for p, n in [('QB',1),('RB',2),('WR',2),('TE',1),('D/ST',1),('K',1)]
                   if len(groups[p]) < n]
        raise ValueError(f'BLOCKED: no complete legal lineup. Missing positional coverage: {missing}')
    combos.sort(key=lambda r:r[0], reverse=True)
    best = combos[0]
    runner = next(((s,x) for s,x in combos[1:] if set(x.values()) != set(best[1].values())), None)
    return {'expected_points': round(best[0],2), 'lineup': best[1],
            'runner_up_gap': round(best[0]-runner[0],2) if runner else None,
            'runner_up': runner[1] if runner else None,
            'num_legal_slot_assignments': len(combos)}


def scenario_sensitivity(players, means, locks, scenarios):
    """Unweighted 'what if' scenarios: do not pretend to know injury/travel probabilities."""
    base = optimize(players, means, locks)
    chosen = set(base['lineup'].values())
    results = []
    for s in scenarios:
        multipliers = {int(k): float(v) for k,v in s.get('player_multipliers',{}).items()}
        by_team = {team_key(k):float(v) for k,v in s.get('team_multipliers',{}).items()}
        overrides = {int(k):float(v) for k,v in s.get('player_overrides',{}).items()}
        m = {p['pid']: overrides.get(p['pid'], max(0., means[p['pid']] *
              multipliers.get(p['pid'],1.) * by_team.get(p['nfl_team'],1.))) for p in players}
        alt = optimize(players, m, locks)
        chosen_pts = sum(m[p] for p in chosen)
        results.append({'name':s['name'],'optimal_points':alt['expected_points'],
                        'chosen_points':round(chosen_pts,2),
                        'regret':round(alt['expected_points']-chosen_pts,2),
                        'would_change_starters':set(alt['lineup'].values())!=chosen})
    return {'baseline':base,'unweighted_sensitivities':results}


def simulate_pair(starter_a, starter_b, means, meta, residuals, rho, n=100000, seed=2026):
    """One shared NFL-team latent factor for BOTH teams; empirical heavy-tail residuals."""
    if n < 1000:
        raise ValueError('At least 1000 paired draws for interval reporting')
    rng = np.random.default_rng(seed)
    ids = sorted(set(starter_a.values()) | set(starter_b.values()))
    teams = {i:meta[i]['nfl_team'] for i in ids}
    latent = {k:rng.standard_normal(n) for k in set(teams.values())}
    rho = float(np.clip(rho,0.,.35))
    samples = {}
    for i in ids:
        pos = meta[i]['pos']
        e = residuals[pos]
        sigma = max(float(np.std(e,ddof=1)),1.)
        errors = rng.choice(e, size=n, replace=True)
        values = (means[i] + math.sqrt(1-rho)*errors +
                  math.sqrt(rho)*sigma*latent[teams[i]])
        if pos != 'D/ST':
            values = np.maximum(values,0.)
        samples[i] = values
    a = sum(samples[i] for i in starter_a.values())
    b = sum(samples[i] for i in starter_b.values())
    return {'a_expected':round(float(a.mean()),2),'b_expected':round(float(b.mean()),2),
            'a_win_rate':round(float(np.mean(a>b)+.5*np.mean(a==b)),5),
            'margin_p10':round(float(np.quantile(a-b,.1)),2),
            'margin_p90':round(float(np.quantile(a-b,.9)),2),
            'rho_team':round(rho,5), 'samples':n,
            'source':'empirical historical errors + estimated same-NFL-team correlation; matchup adjustments NOT validated'}


def evaluate_accuracy(rows):
    x = np.asarray([r['error'] for r in rows],dtype=float)
    if not len(x):raise ValueError('Empty evaluation sample')
    return {'n':len(x),'mae':round(float(np.mean(abs(x))),4),
            'rmse':round(float(np.sqrt(np.mean(x*x))),4),
            'forecast_bias':round(float(np.mean(-x)),4)}
