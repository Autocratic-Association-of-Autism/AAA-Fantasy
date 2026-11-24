"""Manager behavior shadow: chronological lineup-choice and activity models.

Models team IDs, not personalities. Roster snapshots are final, not verified
pregame. Transaction records are observed actions, not complete negotiations.
No actual roster actions, production scoring changes or calibrated odds.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import math
import numpy as np
from .engine import (PRIOR, historical, history_index, predict, position, team_key,
                     current_players, locked_roster, date)
from .matchup_win import legal_lineups

VERSION = "manager-behavior-1.0-shadow"
FEATURES = ("projected_points_per_10", "prior_week_starter_count",
            "prior_game_surprise_per_10")
BASE = np.array([1.25, 0., 0.])
MODELS = ("uniform", "points", "league", "manager")
ACTIONS = ("FA ADDED", "WAIVER ADDED", "DROPPED", "TRADE_RECEIVED", "TRADE_SENT")
MIN_LEAGUE = 12
MIN_MANAGER = 3


def softmax(x):
    z = np.asarray(x, float)
    e = np.exp(z - z.max())
    return e / e.sum()


def prior_features(history, pid, week, prior_start, mean):
    h = [r for r in history.get(pid, []) if r["week"] < week]
    surprise = h[-1]["actual"] - mean if h else 0.
    return np.array([mean / 10., float(pid in prior_start), np.clip(surprise / 10., -4., 4.)])


def make_case(pool, week, tid, means, idx, previous, observed=None):
    candidates = legal_lineups(pool, means)
    f = {p["pid"]: prior_features(idx, p["pid"], week, previous, means[p["pid"]]) for p in pool}
    X = np.asarray([sum((f[i] for i in c["ids"]), np.zeros(len(FEATURES))) for c in candidates])
    X -= X.mean(axis=0)  # choice-set centering preserves probabilities
    actual_index = None
    if observed is not None:
        hits = [i for i,c in enumerate(candidates) if set(c["ids"]) == set(observed)]
        if len(hits) != 1:
            raise ValueError("Submitted starters not in legal candidate pool")
        actual_index = hits[0]
    return {"week":week, "team_id":tid, "candidates":candidates,
            "X":X, "actual_index":actual_index}


def historical_cases(snapshot, cutoff, shrink, recent):
    hist = historical(snapshot, cutoff)
    idx = history_index(hist)
    pools = defaultdict(list)
    for r in hist:
        pools[(r["week"],r["team_id"])].append(r)
    scores = {}
    for m in snapshot["Weekly_Matchups"]:
        for side in ("home","away"):
            scores[(int(m["week"]),int(m[side+"_team_id"]))] = float(m[side+"_score"])
    previous = {}
    cases, excluded = [], []
    for (w,tid), pool in sorted(pools.items()):
        starts = [r["pid"] for r in pool if r["slot"] not in ("BE","IR")]
        last = previous.get((w-1,tid), set())
        if len(starts)==9:
            previous[(w,tid)] = set(starts)
        if w < 5:
            continue
        if len(starts)!=9 or abs(sum(r["actual"] for r in pool if r["pid"] in starts)
                                 -scores.get((w,tid),float("inf")))>.02:
            excluded.append({"week":w,"team_id":tid,"reason":"Incomplete or unreconciled starters"})
            continue
        means = {p["pid"]:predict(p["pid"],w,p["pos"],idx,shrink,recent) for p in pool}
        try:
            cases.append(make_case(pool,w,tid,means,idx,last,starts))
        except ValueError as exc:
            excluded.append({"week":w,"team_id":tid,"reason":str(exc)})
    return cases,idx,previous,excluded


def fit_coeff(cases, prior, penalty):
    """Penalized conditional logit; fixed regularization and bounded fit.

    Newton steps with backtracking monotonically reduce the objective.
    Case-level weighting avoids large rosters dominating the fit.
    """
    beta = np.asarray(prior,float).copy()
    def objective(b):
        loss=.5*penalty*float((b-prior)@(b-prior))
        for c in cases:
            z=c["X"]@b
            loss+=float(np.log(np.exp(z-z.max()).sum())+z.max()-z[c["actual_index"]])
        return loss
    for _ in range(40):
        grad=penalty*(beta-prior)
        hess=penalty*np.eye(len(beta))
        for c in cases:
            X=c["X"]; p=softmax(X@beta)
            mu=p@X
            grad+=mu-X[c["actual_index"]]
            d=X-mu
            hess+=d.T@(p[:,None]*d)
        step=np.linalg.solve(hess,grad)
        if np.linalg.norm(step)<1e-7:
            break
        old=objective(beta)
        for k in range(12):
            candidate=beta-step*(.5**k)
            if objective(candidate)<=old+1e-10:
                beta=candidate
                break
        else:
            break
    return beta


def fit(cases, week, tid):
    prior=[c for c in cases if c["week"]<week]
    # Leave the target manager out of the league coefficient fit. The
    # manager fit is then shrunk toward an independently pooled prior.
    other=[c for c in prior if c["team_id"]!=tid]
    own=[c for c in prior if c["team_id"]==tid]
    league=fit_coeff(other,BASE,8.) if len(other)>=MIN_LEAGUE else BASE.copy()
    personal=fit_coeff(own,league,8.) if len(own)>=MIN_MANAGER else league.copy()
    return {"uniform":np.zeros(len(BASE)),"points":BASE.copy(),"league":league,"manager":personal}, {
        "league_cases":len(other),"manager_cases":len(own),
        "manager_genuine":len(own)>=MIN_MANAGER,
        "league_genuine":len(other)>=MIN_LEAGUE}


def summarize_choice(case, beta):
    p=softmax(case["X"]@beta)
    candidates=case["candidates"]
    order=sorted(range(len(p)),key=lambda i:(-p[i],candidates[i]["ids"]))
    inclusion=defaultdict(float)
    for prob,c in zip(p,candidates):
        for pid in c["ids"]:
            inclusion[pid]+=float(prob)
    # Preserve the full finite law for later simulations, not only top three.
    return p,order,inclusion


def evaluate_choice(case, beta):
    p,order,inclusion=summarize_choice(case,beta)
    candidates=case["candidates"]; observed=case["actual_index"]
    actual=set(candidates[observed]["ids"])
    predicted=set(candidates[order[0]]["ids"])
    return {"log_loss":-math.log(max(1e-15,float(p[observed]))),
            "exact_lineup":float(order[0]==observed),
            "overlap":len(actual&predicted)/9.,
            "top3_hit":float(observed in order[:3]),
            "inclusion_brier":float(np.mean([(v-float(pid in actual))**2 for pid,v in inclusion.items()]))}


def lineup_backtest(cases, excluded):
    results=[]
    for c in cases:
        betas,meta=fit(cases,c["week"],c["team_id"])
        results.append({"week":c["week"],"team_id":c["team_id"],"fit":meta,
                        "results":{m:evaluate_choice(c,betas[m]) for m in MODELS}})
    def summary(rows):
        return {m:{"n":len(rows),**{k:round(float(np.mean([r["results"][m][k] for r in rows])),6)
                       for k in ("log_loss","exact_lineup","overlap","top3_hit","inclusion_brier")}}
                if rows else {"n":0} for m in MODELS}
    return {"all":summary(results),
            "genuine_manager":summary([r for r in results if r["fit"]["manager_genuine"] and r["fit"]["league_genuine"]]),
            "pre_week_11":summary([r for r in results if r["week"]<11]),
            "by_manager":{str(t):summary([r for r in results if r["team_id"]==t]) for t in sorted({r["team_id"] for r in results})},
            "rows":results,"excluded":excluded}


def monday(d):
    return (d-timedelta(days=d.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)


def activity_bins(snapshot, as_of):
    """Calendar UTC weeks, not NFL scoring weeks. Exclude boundary weeks.

    Earliest event is not a guarantee of feed coverage. Counts describe only
    observed records, even if activity counters reconcile.
    """
    now=date(as_of)
    team_ids={int(t["team_id"]) for t in snapshot["Teams"]}
    events=[]; seen=set(); unknown=Counter()
    for r in snapshot.get("Transactions",[]):
        try:
            ts=datetime.fromtimestamp(int(r["date_epoch_ms"])/1000,tz=timezone.utc)
            tid=int(r["team_id"]); pid=int(r["player_id"]); action=str(r["action"])
        except (KeyError,ValueError,TypeError,OverflowError,OSError):
            continue
        if ts>now or tid not in team_ids:
            continue
        if action not in ACTIONS:
            unknown[action]+=1
            continue
        key=(ts,tid,pid,action)
        if key in seen:
            continue
        seen.add(key)
        events.append((ts,tid,pid,action,position(r.get("position",""))))
    if not events:
        return [],events,{"status":"NO_OBSERVED_ACTIONS"}
    first=min(e[0] for e in events)
    start=monday(first)+timedelta(days=7)
    stop=monday(now)
    bins=[]
    while start<stop:
        end=start+timedelta(days=7)
        c=Counter((e[1],e[3]) for e in events if start<=e[0]<end)
        for tid in sorted(team_ids):
            bins.append({"start":start.isoformat(),"end":end.isoformat(),"team_id":tid,
                         "counts":{a:c[tid,a] for a in ACTIONS}})
        start=end
    return bins,events,{"status":"OBSERVED_ACTIONS_NOT_COMPLETENESS_VERIFIED",
                        "first_event_utc":first.isoformat(),"observed_rows":len(events),
                        "unknown_actions":dict(unknown),"complete_calendar_weeks":len(bins)//len(team_ids),
                        "partial_current_week_excluded":True}


def rates(bins, target_start, tid):
    before=[r for r in bins if r["start"]<target_start]
    peer=[r for r in before if r["team_id"]!=tid]
    own=[r for r in before if r["team_id"]==tid]
    out={}
    for a in ACTIONS:
        pooled=(sum(r["counts"][a] for r in peer)+.5)/(len(peer)+1.)
        manager=(sum(r["counts"][a] for r in own)+4.*pooled)/(len(own)+4.)
        out[a]={"pooled":pooled,"manager":manager,"prior_manager_weeks":len(own)}
    return out


def activity_report(snapshot, as_of):
    bins,events,coverage=activity_bins(snapshot,as_of)
    scored=[]
    for b in bins:
        fit_r=rates(bins,b["start"],b["team_id"])
        if fit_r[ACTIONS[0]]["prior_manager_weeks"]<3:
            continue
        for a in ACTIONS:
            y=b["counts"][a]
            scored.append({"action":a,"actual":y,**{m:fit_r[a][m] for m in ("pooled","manager")}})
    def score(rows):
        return {m:{"n":len(rows),"mae":round(float(np.mean([abs(r[m]-r["actual"]) for r in rows])),6),
                   "poisson_nll":round(float(np.mean([r[m]-r["actual"]*math.log(max(r[m],1e-12))+math.lgamma(r["actual"]+1) for r in rows])),6)}
                if rows else {"n":0} for m in ("pooled","manager")}
    target=monday(date(as_of)).isoformat()
    profiles={}
    for t in snapshot["Teams"]:
        tid=int(t["team_id"])
        own=[e for e in events if e[1]==tid]
        adds=[e for e in own if e[3] in ("FA ADDED","WAIVER ADDED")]
        acq=Counter(e[4] for e in adds)
        total=len(adds)
        counts=Counter(e[3] for e in own)
        profiles[str(tid)]={"name":t["team_name"],"observed_action_counts":dict(counts),
                            "acquisition_positions":dict(acq),
                            "waiver_fraction_observed":counts["WAIVER ADDED"]/total if total else None,
                            "weekly_action_rate_shadow":rates(bins,target,tid),
                            "exported_acquisitions":t.get("acquisitions"),
                            "exported_drops":t.get("drops"),
                            "trade_counter":t.get("trades"),
                            "acquisition_counter_difference":total-int(t["acquisitions"]) if str(t.get("acquisitions","")).isdigit() else None}
    return {"coverage":coverage,"profiles":profiles,
            "walk_forward":{a:score([r for r in scored if r["action"]==a]) for a in ACTIONS},
            "note":"Rates predict observed action counts in a full UTC calendar week; no candidate-player choices, completed trade counts or acceptance probabilities."}


def forecast(snapshot, history_snapshot, baseline, schedule, cases, idx, previous, cutoff, shrink, recent):
    week=int(baseline["week"]); as_of=baseline["as_of"]
    if cutoff>=week:
        raise ValueError("Target-week leakage")
    if any(date(v)<=date(as_of) for v in schedule["kickoffs"].values()):
        return {"status":"BLOCKED_AFTER_KICKOFF","model_version":VERSION,"promotion_eligible":False}
    reports={}
    for t in snapshot["Teams"]:
        tid=int(t["team_id"])
        try:
            pool,locks,excluded=locked_roster(current_players(snapshot,tid,week),schedule["kickoffs"],as_of,
                                    week==int(snapshot["League"][0]["current_week"]))
            means={p["pid"]:predict(p["pid"],week,p["pos"],idx,shrink,recent) for p in pool}
            c=make_case(pool,week,tid,means,idx,previous.get((week-1,tid),set()))
            beta,meta=fit(cases,week,tid)
            result={}
            for m in MODELS:
                p,order,inc=summarize_choice(c,beta[m])
                result[m]={"top_lineups":[{"lineup":c["candidates"][i]["lineup"],"probability":float(p[i]),
                                            "mean":c["candidates"][i]["mean"]} for i in order[:5]],
                           "starter_inclusion":{str(k):round(v,6) for k,v in inc.items()},
                           "coefficients":beta[m].tolist()}
                if m=="manager":
                    result[m]["full_lineup_law"]=[{"lineup":x["lineup"],"probability":float(q)}
                                                  for x,q in zip(c["candidates"],p)]
            reports[str(tid)]={"name":t["team_name"],"status":"CONDITIONAL_ROSTER_SHADOW",
                              "fit":meta,"legal_unique_lineups":len(c["candidates"]),
                              "models":result,"excluded":excluded}
        except ValueError as exc:
            reports[str(tid)]={"name":t["team_name"],"status":"BLOCKED_POOL","reason":str(exc)}
    return {"status":"UNVALIDATED_MANAGER_BEHAVIOR_SHADOW","model_version":VERSION,
            "week":week,"as_of":as_of,"completed_through_week":cutoff,"features":list(FEATURES),
            "all_rosters":reports,"activity":activity_report(snapshot,as_of),
            "promotion_eligible":False,"applied_to_primary_model":False,
            "limitations":["Conditional on current eligible roster and fixed lagged point model.",
                           "No candidate injury probabilities, future acquisitions or inferred trade acceptance.",
                           "Historical final roster choices are not pregame availability snapshots.",
                           "Behavior probabilities are uncalibrated, not used for production lineup or season odds."]}


def run_backtest(snapshot, cutoff, shrink, recent, as_of):
    cases,idx,previous,excluded=historical_cases(snapshot,cutoff,shrink,recent)
    return {"status":"EXPLORATORY_MANAGER_BEHAVIOR_BACKTEST_NOT_PROMOTION","model_version":VERSION,
            "lineups":lineup_backtest(cases,excluded),"activity":activity_report(snapshot,as_of),
            "promotion_eligible":False,
            "limitations":["All feature histories precede each evaluated scoring week.",
                           "Historical end-week roster and projection>0 eligibility filter may bias choice sets.",
                           "No independent prospective evaluation; Week 11 is diagnostic.",
                           "Action count backtest uses full observed UTC calendar weeks, not NFL weeks.",
                           "No verified history of rejected trade offers or waiver alternatives."]},cases,idx,previous
