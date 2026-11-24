"""Mean-preserving empirical fantasy scoring distribution experiments.

No model promotion. All models have the SAME conditional expected points.
Marginal residual uncertainty is estimated only from completed earlier weeks.
Neither player injury probabilities nor cross-player covariance are inferred.
"""
from __future__ import annotations
from collections import defaultdict
import numpy as np
from .engine import (PRIOR, date, historical, history_index, predict,
                     predictions, current_players, locked_roster, team_key)

VERSION = "player-distributions-1.0-shadow"
MODELS = ("position", "conditional", "personal")
MIN_POSITION = 8
NEIGHBORS = 32
MIN_PERSONAL = 3
PERSONAL_PRIOR = 8.
TAIL = {"QB": 25., "RB": 20., "WR": 20., "TE": 15., "D/ST": 12., "K": 12.}
QUANTILES = (.05, .10, .25, .50, .75, .90, .95)


def law(values, weights=None):
    """Return sorted finite discrete law with normalized positive weights."""
    x = np.asarray(values, dtype=float)
    w = np.ones(len(x), dtype=float) if weights is None else np.asarray(weights, dtype=float)
    if x.ndim != 1 or w.shape != x.shape or not len(x):
        raise ValueError("Empty or malformed scoring distribution")
    if not np.isfinite(x).all() or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError("Invalid scoring distribution")
    order = np.argsort(x, kind="stable")
    x, w = x[order], w[order]
    positive = w > 0
    x, w = x[positive], w[positive]
    return x, w / w.sum()


def centered(values):
    x = np.asarray(values, float)
    return x - x.mean()


def from_residuals(errors, mean, weights=None):
    x, w = law(errors, weights)
    # Do not clip negative scores: even skill players can lose points.
    # Clipping would change the mean, confounding the distribution ablation.
    return law(x - float(x @ w) + float(mean), w)


def player_laws(prior, player, mean, target_week):
    pos, pid = player["pos"], int(player["pid"])
    eligible = [r for r in prior if r["week"] < target_week and r["pos"] == pos]
    if len(eligible) < MIN_POSITION:
        return None, {"status": "INSUFFICIENT_POSITION_RESIDUALS", "n": len(eligible)}
    position_law = from_residuals([r["error"] for r in eligible], mean)
    # Exclude the target player from peer selection when possible so personal
    # history is an identifiable, separately controlled contribution.
    peers = [r for r in eligible if r["pid"] != pid]
    if len(peers) < MIN_POSITION:
        peers = eligible
    # Include all ties at the neighborhood boundary; stable across row order.
    d = np.asarray([abs(float(r["estimate"]) - mean) for r in peers])
    radius = float(np.sort(d)[min(NEIGHBORS, len(d))-1])
    near = [r for r, delta in zip(peers, d) if delta <= radius + 1e-10]
    peer_errors = centered([r["error"] for r in near])
    conditional_law = from_residuals(peer_errors, mean)
    own = [r["error"] for r in eligible if r["pid"] == pid]
    weight = len(own) / (len(own) + PERSONAL_PRIOR) if len(own) >= MIN_PERSONAL else 0.
    if weight:
        own_errors = centered(own)
        personal_law = from_residuals(
            np.r_[peer_errors, own_errors], mean,
            np.r_[np.full(len(peer_errors), (1-weight)/len(peer_errors)),
                  np.full(len(own_errors), weight/len(own_errors))])
    else:
        personal_law = conditional_law
    return {"position": position_law, "conditional": conditional_law, "personal": personal_law}, {
        "status": "PERSONAL_BLEND" if weight else "CONDITIONAL_FALLBACK",
        "position_observations": len(eligible), "peer_observations": len(near),
        "own_observations": len(own), "own_weight": round(weight, 4),
        "through_week": max(r["week"] for r in eligible)}


def quantile(dist, p):
    x, w = dist
    i = np.searchsorted(np.cumsum(w), p, side="left")
    return float(x[min(len(x)-1, int(i))])


def draw(dist, u):
    x, w = dist
    return x[np.minimum(len(x)-1, np.searchsorted(np.cumsum(w), u, side="left"))]


def describe(dist, threshold):
    x,w = dist
    mean = float(x@w)
    return {"mean": round(mean,4), "sd": round(float(np.sqrt(((x-mean)**2)@w)),4),
            **{f"p{int(p*100):02d}":round(quantile(dist,p),4) for p in QUANTILES},
            "tail_threshold":threshold, "tail_probability":round(float(w[x>=threshold].sum()),6),
            "negative_score_probability":round(float(w[x<0].sum()),6)}


def score(dist, y, threshold):
    """Exact discrete CRPS, central interval coverage, and tail Brier score."""
    x,w = dist
    cw = np.cumsum(w)-w
    cwx = np.cumsum(w*x)-w*x
    crps = float(np.abs(x-y)@w - w@(x*cw-cwx))
    p = float(w[x>=threshold].sum())
    p10,p90 = quantile(dist,.1),quantile(dist,.9)
    p05,p95 = quantile(dist,.05),quantile(dist,.95)
    pinball = lambda q,t: max(t*(y-q),(t-1)*(y-q))
    return {"crps":max(0.,crps),"coverage80":float(p10<=y<=p90),
            "coverage90":float(p05<=y<=p95),"width80":p90-p10,"width90":p95-p05,
            "p90_pinball":pinball(p90,.9),"upper90_exceedance":float(y>p90),
            "tail_brier":(p-float(y>=threshold))**2,
            "tail_probability":p,"tail_observed":float(y>=threshold)}


def aggregate(rows):
    return {"n":len(rows), **{
        k:round(float(np.mean([r[k] for r in rows])),6)
        for k in ("crps","coverage80","coverage90","width80","width90","p90_pinball",
                  "upper90_exceedance","tail_brier","tail_probability","tail_observed")
    }} if rows else {"n":0}


def matchup_draws(laws_by_pid, a, b, n, seed):
    """Same uniform per player across models and lineup alternatives.

    This intentionally isolates marginal distributions using independent
    player draws. Shared-game covariance is a separate future ablation.
    """
    if n < 1000 or set(a)&set(b) or len(set(a))!=len(a) or len(set(b))!=len(b):
        raise ValueError("Invalid paired matchup trial specification")
    rng=np.random.default_rng(seed)
    sums={m:[np.zeros(n),np.zeros(n)] for m in MODELS}
    for pid in sorted(set(a)|set(b)):
        u=rng.random(n)
        side=0 if pid in a else 1
        for m in MODELS:
            sums[m][side]+=draw(laws_by_pid[pid][m],u)
    return sums


def matchup_metrics(sums, actual_a=None, actual_b=None):
    report={}
    for m,(a,b) in sums.items():
        margin=a-b
        prob=float(np.mean(a>b)+.5*np.mean(a==b))
        row={"a_mean":round(float(a.mean()),4),"b_mean":round(float(b.mean()),4),
             "a_median":round(float(np.median(a)),4),"b_median":round(float(np.median(b)),4),
             "a_p10":round(float(np.quantile(a,.1)),4),"a_p90":round(float(np.quantile(a,.9)),4),
             "b_p10":round(float(np.quantile(b,.1)),4),"b_p90":round(float(np.quantile(b,.9)),4),
             "margin_p10":round(float(np.quantile(margin,.1)),4),
             "margin_p90":round(float(np.quantile(margin,.9)),4),
             "a_win_fraction":round(prob,6)}
        if actual_a is not None and actual_b is not None:
            outcome=1. if actual_a>actual_b else 0. if actual_a<actual_b else .5
            row.update({"brier":(prob-outcome)**2,"observed_outcome":outcome,
                        "winner_credit":float((prob>.5)==(outcome>.5)) if prob!=.5 and outcome!=.5 else .5,
                        "margin_coverage80":float(row["margin_p10"]<=actual_a-actual_b<=row["margin_p90"])})
        report[m]=row
    return report


def backtest(snapshot, cutoff, shrink, recent, n=10000):
    hist=historical(snapshot,cutoff)
    rows=predictions(hist,shrink,recent,start=2,stop=cutoff)
    grouped=defaultdict(list)
    law_index={}
    skips=[]
    for r in rows:
        w=r["week"]
        if w<5:
            continue
        laws,meta=player_laws(rows,r,r["estimate"],w)
        if laws is None:
            skips.append({"week":w,"pid":r["pid"],"reason":meta["status"]})
            continue
        law_index[(w,r["pid"])]=laws
        grouped[w].append({"position":r["pos"],"pid":r["pid"],"personal":meta["status"]=="PERSONAL_BLEND",
                           "results":{m:score(laws[m],r["actual"],TAIL[r["pos"]]) for m in MODELS}})
    all_rows=[r for rs in grouped.values() for r in rs]
    def summarize(rs):
        return {m:aggregate([r["results"][m] for r in rs]) for m in MODELS}
    starts=defaultdict(list)
    for r in rows:
        if r["slot"] not in ("BE","IR"):
            starts[(r["week"],r["team_id"])].append(r)
    matches=[]
    match_skips=[]
    for m in snapshot["Weekly_Matchups"]:
        w=int(m["week"])
        if not 5<=w<=cutoff:
            continue
        home,away=int(m["home_team_id"]),int(m["away_team_id"])
        aa,bb=starts[(w,home)],starts[(w,away)]
        a,b=[r["pid"] for r in aa],[r["pid"] for r in bb]
        y,z=float(m["home_score"]),float(m["away_score"])
        if (len(a)!=9 or len(b)!=9 or set(a)&set(b) or
            any((w,p) not in law_index for p in a+b) or
            abs(sum(r["actual"] for r in aa)-y)>.02 or abs(sum(r["actual"] for r in bb)-z)>.02):
            match_skips.append({"week":w,"home_id":home,"away_id":away,"reason":"Incomplete or unreconciled starters or laws"})
            continue
        sums=matchup_draws({p:law_index[(w,p)] for p in a+b},a,b,n,20261124+w*100+home)
        matches.append({"week":w,"home_id":home,"away_id":away,"results":matchup_metrics(sums,y,z)})
    def match_summary(ms):
        return {m:{"n":len(ms), **{k:round(float(np.mean([r["results"][m][k] for r in ms])),6)
                                  for k in ("brier","winner_credit","margin_coverage80")}} if ms else {"n":0}
                for m in MODELS}
    return {"status":"EXPLORATORY_DISTRIBUTION_BACKTEST_NOT_PROMOTION","model_version":VERSION,
            "evaluated_weeks":sorted(grouped),"player_results":summarize(all_rows),
            "genuine_personal_results":summarize([r for r in all_rows if r["personal"]]),
            "by_position":{p:summarize([r for r in all_rows if r["position"]==p]) for p in PRIOR},
            "by_week":{str(w):summarize(rs) for w,rs in grouped.items()},
            "pre_week_11":summarize([r for w,rs in grouped.items() if w<11 for r in rs]),
            "week_11_diagnostic":summarize(grouped.get(11,[])),
            "matchups":match_summary(matches),"matchup_trials":n,"matchup_rows":matches,
            "excluded_players":skips,"excluded_matchups":match_skips,
            "promotion_eligible":False,
            "limitations":["Final historical fantasy rosters and starters; not frozen pregame decisions.",
                           "Baseline hyperparameters fixed using Weeks 2-4; calibration residuals start Week 2.",
                           "Week 11 is a development diagnostic; no independent prospective evidence.",
                           "Independent player draws isolate marginal effects; no shared-game covariance.",
                           "Position-specific fixed tail thresholds; no injury-conditioned distributions."]}


def forecast(snapshot, baseline, schedule, cutoff, shrink, recent, n=100000):
    w=int(baseline["week"])
    if cutoff>=w:
        raise ValueError("Target-week leakage")
    hist=historical(snapshot,cutoff)
    prior=predictions(hist,shrink,recent,start=2,stop=cutoff)
    idx=history_index(hist)
    laws_by_pid={}
    rosters={}
    pools={}
    any_started=any(date(k)<=date(baseline["as_of"]) for k in schedule["kickoffs"].values())
    for t in snapshot["Teams"]:
        tid=int(t["team_id"])
        pool,locks,excluded=locked_roster(current_players(snapshot,tid,w),schedule["kickoffs"],
                                         baseline["as_of"],w==int(snapshot["League"][0]["current_week"]))
        pools[tid]=pool
        entries=[]
        for p in pool:
            if date(schedule["kickoffs"][p["nfl_team"]])<=date(baseline["as_of"]):
                continue
            mean=predict(p["pid"],w,p["pos"],idx,shrink,recent)
            laws,meta=player_laws(prior,p,mean,w)
            if laws is not None:
                laws_by_pid[p["pid"]]=laws
            entries.append({"player_id":p["pid"],"name":p["name"],"position":p["pos"],
                            "nfl_team":p["nfl_team"],"mean_control_same_cutoff":round(mean,4),
                            "injury_status_unverified_for_target_week":p["injury"],"history":meta,
                            "distributions":{m:describe(laws[m],TAIL[p["pos"]]) for m in MODELS}
                            if laws is not None else None})
        rosters[str(tid)]={"players":entries,"excluded":excluded,"locked":locks}
    comparisons=[]
    # The existing optimizer's selected lineups are fixed; this stage does
    # NOT claim to optimize all legal lineups or predict manager behavior.
    if not any_started:
        for m in snapshot["Season_Schedule"]:
            if int(m["week"])!=w:
                continue
            a,b=int(m["team_a_id"]),int(m["team_b_id"])
            entries=[]
            for tid in (a,b):
                r=baseline["all_rosters"].get(str(tid)) or baseline["all_rosters"].get(tid,{})
                best=r.get("best")
                entries.append(list(best["lineup"].values()) if best else [])
            aa,bb=entries
            if len(aa)!=9 or len(bb)!=9 or any(p not in laws_by_pid for p in aa+bb):
                comparisons.append({"a_id":a,"b_id":b,"status":"BLOCKED_INCOMPLETE_FIXED_LINEUPS"})
                continue
            sums=matchup_draws(laws_by_pid,aa,bb,n,20261124+w*100+a)
            comparisons.append({"a_id":a,"b_id":b,"status":"INDEPENDENT_SHADOW_NOT_CALIBRATED",
                                "a_lineup":aa,"b_lineup":bb,"trials":n,"results":matchup_metrics(sums)})
    return {"status":"UNVALIDATED_PLAYER_DISTRIBUTIONS_SHADOW","model_version":VERSION,
            "week":w,"as_of":baseline["as_of"],"completed_through_week":cutoff,
            "source_snapshot_sha256":baseline.get("snapshot_sha256"),"all_rosters":rosters,
            "matchup_status":"BLOCKED_AFTER_ANY_NFL_KICKOFF" if any_started else "FIXED_BASELINE_LINEUPS_ONLY",
            "matchups":comparisons,"promotion_eligible":False,"applied_to_primary_model":False,
            "limitations":["All marginal distributions use a common lagged baseline mean at the verified cutoff.",
                           "Negative fantasy scores retained to preserve means.",
                           "No medical or availability probabilities; next-week IR/roles require confirmation.",
                           "Independent players, no joint-game effects; no calibrated matchup odds.",
                           "No current-week simulation after kickoff; avoid inventing locked final scores."]}
