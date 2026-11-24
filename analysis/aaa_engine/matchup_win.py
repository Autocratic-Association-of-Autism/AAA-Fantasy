"""Signed matchup dependence and legal lineup win optimization, shadow only."""
from __future__ import annotations
from collections import defaultdict
from itertools import combinations, product
import numpy as np
from .engine import (PRIOR,SLOTS,date,historical,history_index,predict,predictions,
                     current_players,locked_roster,team_key)
from .distributions import player_laws, draw

VERSION="matchup-win-1.0-shadow"
MIN_PAIRS=12
PAIR_PRIOR=80.
MAX_LINEUPS=3000
OPPONENT_SCENARIOS=3


def pair_key(a,b,opponents):
    ta,tb=a["nfl_team"],b["nfl_team"]
    if ta==tb:
        relation="same_team"
    elif opponents.get(ta)==tb and opponents.get(tb)==ta:
        relation="opposing_teams"
    else:
        return None
    return (relation,*sorted((a["pos"],b["pos"])))


def fit_dependence(rows,pbp,week):
    """Fit signed standardized residual products on strictly earlier games."""
    past=[r for r in rows if r["week"]<week]
    scales={}
    for p in PRIOR:
        a=np.asarray([r["error"] for r in past if r["pos"]==p],float)
        if len(a)>=8:
            scales[p]=(float(a.mean()),max(1.,float(a.std())))
    groups=defaultdict(list)
    for r in past:
        if r["pos"] in scales:
            groups[r["week"]].append(r)
    pairs=defaultdict(list)
    for w,group in groups.items():
        opponents={t:o for (v,t),o in pbp["opponents"].items() if v==w}
        for a,b in combinations(group,2):
            key=pair_key(a,b,opponents)
            if key is None or a["pid"]==b["pid"]:
                continue
            def standard(r):
                mu,sd=scales[r["pos"]]
                return float(np.clip((r["error"]-mu)/sd,-3.,3.))
            pairs[key].append(standard(a)*standard(b))
    return {k:{"n":len(v),"raw":float(np.mean(v)),
               "rho":float(np.clip(np.mean(v)*len(v)/(len(v)+PAIR_PRIOR),-.45,.45))
                     if len(v)>=MIN_PAIRS else 0.}
            for k,v in pairs.items()}


def correlation_matrix(players,opponents,fit):
    """Repair pairwise latent matrix to positive semidefinite, unit diagonal."""
    n=len(players)
    raw=np.eye(n)
    for i,j in combinations(range(n),2):
        raw[i,j]=raw[j,i]=fit.get(pair_key(players[i],players[j],opponents),{}).get("rho",0.)
    values,vectors=np.linalg.eigh(raw)
    fixed=(vectors*np.maximum(values,1e-6))@vectors.T
    sd=np.sqrt(np.diag(fixed))
    fixed=fixed/sd[:,None]/sd[None,:]
    # Preserve independence across games after numerical eigensolver noise.
    return fixed,{"minimum_raw_eigenvalue":float(values.min()),
                  "max_psd_adjustment":float(np.max(np.abs(fixed-raw)))}


def normal_cdf(x):
    # Vectorized standard normal CDF approximation (absolute error < 8e-8).
    z=np.abs(x)
    t=1./(1.+.2316419*z)
    q=np.exp(-z*z/2.)/np.sqrt(2*np.pi)*t*(.31938153+t*(-.356563782+t*(1.781477937+t*(-1.821255978+t*1.330274429))))
    return np.clip(np.where(x>=0,1.-q,q),0.,1.)


def sample_joint(players,laws,opponents,fit,n,seed):
    """Same normals for independent and signed Gaussian-copula ablations."""
    if n<1000:
        raise ValueError("Insufficient simulation draws")
    p=sorted(players,key=lambda a:a["pid"])
    ids=[a["pid"] for a in p]
    if len(ids)!=len(set(ids)) or not ids:
        raise ValueError("Duplicate or empty matchup pool")
    corr,diagnostics=correlation_matrix(p,opponents,fit)
    rng=np.random.default_rng(seed)
    z=rng.standard_normal((len(ids),n))
    u=normal_cdf(z)
    v=normal_cdf(np.linalg.cholesky(corr)@z)
    # Retain identical positional marginals in both dependence ablations.
    independent=np.asarray([draw(laws[pid]["position"],u[i]) for i,pid in enumerate(ids)],dtype=np.float32)
    correlated=np.asarray([draw(laws[pid]["position"],v[i]) for i,pid in enumerate(ids)],dtype=np.float32)
    return {pid:i for i,pid in enumerate(ids)},independent,correlated,diagnostics


def legal_lineups(pool,means,locks=None):
    """Enumerate unique legal 9-player sets; canonical assignments pregame."""
    locks=locks or {}
    if locks:
        raise ValueError("Live locks unsupported by matchup shadow")
    groups={p:sorted(x["pid"] for x in pool if x["pos"]==p) for p in PRIOR}
    unique={}
    for qb,te,dst,k in product(groups["QB"],groups["TE"],groups["D/ST"],groups["K"]):
        for rb,wr in product(combinations(groups["RB"],2),combinations(groups["WR"],2)):
            used={qb,te,dst,k,*rb,*wr}
            for flex in sorted(set(groups["RB"]+groups["WR"]+groups["TE"])-used):
                ids=(qb,*rb,*wr,te,flex,dst,k)
                if len(set(ids))!=9:
                    continue
                key=tuple(sorted(ids))
                unique.setdefault(key,dict(zip(SLOTS,ids)))
                if len(unique)>MAX_LINEUPS:
                    raise ValueError("Legal lineup cap exceeded; no approximate optimum claimed")
    if not unique:
        raise ValueError("No complete legal lineup")
    return sorted([{"ids":k,"lineup":v,"mean":sum(means[i] for i in k)}
                   for k,v in unique.items()],key=lambda r:(-r["mean"],r["ids"]))


def totals(matrix,index,ids):
    return matrix[[index[i] for i in ids]].sum(axis=0,dtype=np.float64)


def win(a,b):
    return float(np.mean(a>b)+.5*np.mean(a==b))


def select(candidates,opponents,index,matrix):
    """Compare every candidate against each fixed scenario, equal weighting.

    Equal weighting is a robustness convention, not manager probabilities.
    Exact enumeration under these finite draws, deterministic tie-break.
    """
    enemy=np.asarray([totals(matrix,index,x["ids"]) for x in opponents])
    best=None
    for c in candidates:
        a=totals(matrix,index,c["ids"])
        w=float(np.mean(a[None,:]>enemy)+.5*np.mean(a[None,:]==enemy))
        if best is None or w>best[0]+1e-12:
            best=(w,c)
    return best[1]


def evaluate_choice(c,opps,index,matrix):
    a=totals(matrix,index,c["ids"])
    outcomes=[win(a,totals(matrix,index,o["ids"])) for o in opps]
    return {"lineup":c["lineup"],"mean":round(c["mean"],4),
            "simulated_mean":round(float(a.mean()),4),
            "p10":round(float(np.quantile(a,.1)),4),"p90":round(float(np.quantile(a,.9)),4),
            "vs_top_mean_opponent":round(outcomes[0],6),
            "equal_weight_scenario_fraction":round(float(np.mean(outcomes)),6),
            "scenario_win_fractions":[round(x,6) for x in outcomes]}


def optimize_match(a,b,means,laws,opponents,fit,selection_n,evaluation_n,seed):
    ca,cb=legal_lineups(a,means),legal_lineups(b,means)
    ix,ind,corr,diag=sample_joint(a+b,laws,opponents,fit,selection_n,seed)
    # Select on one batch. Evaluate the selected decisions on a separate seed.
    picks=[]
    for own,enemy in ((ca,cb),(cb,ca)):
        scenarios=enemy[:OPPONENT_SCENARIOS]
        picks.append({"mean":own[0],"independent_win":select(own,scenarios[:1],ix,ind),
                      "correlated_win":select(own,scenarios[:1],ix,corr),
                      "robust_win":select(own,scenarios,ix,corr)})
    ei,ind_eval,corr_eval,_=sample_joint(a+b,laws,opponents,fit,evaluation_n,seed+1000003)
    results=[]
    for own,enemy,choices in ((ca,cb,picks[0]),(cb,ca,picks[1])):
        scenarios=enemy[:OPPONENT_SCENARIOS]
        out={"legal_unique_lineups":len(own),"opponent_scenarios":[x["lineup"] for x in scenarios],
             "choices":{}}
        for name,c in choices.items():
            out["choices"][name]={
                "independent":evaluate_choice(c,scenarios,ei,ind_eval),
                "correlated":evaluate_choice(c,scenarios,ei,corr_eval)}
        results.append(out)
    return results,diag,(ei,ind_eval,corr_eval)


def mean_laws(rows,players,week,means):
    out={}
    for p in players:
        d,_=player_laws(rows,p,means[p["pid"]],week)
        if d is None:
            raise ValueError("Missing positional distribution")
        out[p["pid"]]=d
    return out


def backtest(snapshot,pbp,cutoff,shrink,recent,selection_n=4000,evaluation_n=6000):
    hist=historical(snapshot,cutoff)
    rows=predictions(hist,shrink,recent,start=2,stop=cutoff)
    pools=defaultdict(list)
    for r in rows:
        if r["week"]>=5:
            pools[(r["week"],r["team_id"])].append(r)
    matches,decisions,skipped=[],[],[]
    fits={}
    for m in snapshot["Weekly_Matchups"]:
        w=int(m["week"])
        if not 5<=w<=cutoff:
            continue
        home,away=int(m["home_team_id"]),int(m["away_team_id"])
        a,b=pools[(w,home)],pools[(w,away)]
        aa=[r["pid"] for r in a if r["slot"] not in ("BE","IR")]
        bb=[r["pid"] for r in b if r["slot"] not in ("BE","IR")]
        actual={r["pid"]:r["actual"] for r in a+b}
        y,z=float(m["home_score"]),float(m["away_score"])
        if (len(aa)!=9 or len(bb)!=9 or abs(sum(actual[i] for i in aa)-y)>.02 or
                abs(sum(actual[i] for i in bb)-z)>.02):
            skipped.append({"week":w,"home":home,"reason":"Incomplete or unreconciled starters"})
            continue
        means={r["pid"]:r["estimate"] for r in a+b}
        opp={t:o for (v,t),o in pbp["opponents"].items() if v==w}
        if w not in fits:
            fits[w]=fit_dependence(rows,pbp,w)
        try:
            if any(r["nfl_team"] not in opp for r in a+b):
                raise ValueError("Missing historical NFL opponent")
            laws=mean_laws(rows,a+b,w,means)
            results,diag,(ix,ind,corr)=optimize_match(a,b,means,laws,opp,fits[w],selection_n,evaluation_n,20261124+w*100+home)
        except ValueError as e:
            skipped.append({"week":w,"home":home,"reason":str(e)})
            continue
        outcome=1. if y>z else 0. if y<z else .5
        probs={name:win(totals(mat,ix,aa),totals(mat,ix,bb)) for name,mat in (("independent",ind),("correlated",corr))}
        matches.append({"week":w,"home":home,"away":away,"actual_home_outcome":outcome,
                        "probabilities":probs,"psd":diag})
        for tid,enemy,out,pool in ((home,z,results[0],a),(away,y,results[1],b)):
            oracle=legal_lineups(pool,actual)[0]["mean"]
            result={}
            for name,choice in out["choices"].items():
                selected=choice["correlated"]["lineup"]
                observed=sum(actual[i] for i in selected.values())
                result[name]={"points":observed,"regret":oracle-observed,
                              "win_vs_actual":1. if observed>enemy else 0. if observed<enemy else .5,
                              "lineup":selected,
                              "fresh_draw_correlated_fraction":choice["correlated"]["vs_top_mean_opponent"]}
            decisions.append({"week":w,"team_id":tid,"choices":result})
    def summary(ds):
        return {name:{"n":len(ds),"mean_regret":float(np.mean([r["choices"][name]["regret"] for r in ds])),
                      "wins_vs_actual_opponents":sum(r["choices"][name]["win_vs_actual"] for r in ds)}
                for name in ("mean","independent_win","correlated_win","robust_win")} if ds else {}
    return {"status":"EXPLORATORY_WIN_OPTIMIZATION_NOT_PROMOTION","model_version":VERSION,
            "selection_trials":selection_n,"independent_evaluation_trials":evaluation_n,
            "fixed_submitted_lineup_brier":{name:float(np.mean([(m["probabilities"][name]-m["actual_home_outcome"])**2 for m in matches]))
                                           if matches else None for name in ("independent","correlated")},
            "matchup_count":len(matches),"team_week_count":len(decisions),
            "decision_summary":summary(decisions),"pre_week_11":summary([r for r in decisions if r["week"]<11]),
            "week_11_diagnostic":summary([r for r in decisions if r["week"]==11]),
            "matchups":matches,"decisions":decisions,"excluded":skipped,
            "promotion_eligible":False,
            "limitations":["Historical end-week rosters and submitted starters are retrospective, not frozen pregame.",
                           "All models use same lagged baseline means and positional marginal law.",
                           "Signed standardized residual products are latent correlation proxies, not fitted copula parameters.",
                           "Gaussian copula preserves marginal laws but does not enforce finite game-first opportunity budgets.",
                           "Top three mean opponent lineups equally weighted only as a sensitivity; no manager probability.",
                           "Selection and evaluation use separate simulation seeds, not an independent real-world holdout."]}


def forecast(snapshot,history_snapshot,baseline,schedule,pbp,cutoff,shrink,recent,selection_n=20000,evaluation_n=100000):
    w=int(baseline["week"])
    if cutoff>=w:
        raise ValueError("Target-week leakage")
    if any(date(v)<=date(baseline["as_of"]) for v in schedule["kickoffs"].values()):
        return {"status":"BLOCKED_AFTER_KICKOFF","model_version":VERSION,"promotion_eligible":False}
    hist=historical(history_snapshot,cutoff)
    idx=history_index(hist)
    rows=predictions(hist,shrink,recent,start=2,stop=cutoff)
    fit=fit_dependence(rows,pbp,w)
    opponents={}
    for g in schedule["games"]:
        a,b=(team_key(t) for t in g["teams"])
        opponents[a]=b
        opponents[b]=a
    pools={}
    raw_ir={int(r["player_id"]) for r in snapshot["Current_Rosters"] if r.get("lineup_slot")=="IR"}
    for t in snapshot["Teams"]:
        tid=int(t["team_id"])
        pool,locks,excluded=locked_roster(current_players(snapshot,tid,w),schedule["kickoffs"],
                                         baseline["as_of"],w==int(snapshot["League"][0]["current_week"]))
        pools[tid]=[p for p in pool if p["pid"] not in raw_ir]
    reports=[]
    for m in snapshot["Season_Schedule"]:
        if int(m["week"])!=w:
            continue
        a,b=int(m["team_a_id"]),int(m["team_b_id"])
        aa,bb=pools[a],pools[b]
        means={p["pid"]:predict(p["pid"],w,p["pos"],idx,shrink,recent) for p in aa+bb}
        try:
            laws=mean_laws(rows,aa+bb,w,means)
            result,diag,_=optimize_match(aa,bb,means,laws,opponents,fit,selection_n,evaluation_n,20261124+w*100+a)
            reports.append({"a_id":a,"b_id":b,"status":"UNVALIDATED_PREGAME_SHADOW",
                            "a":result[0],"b":result[1],"psd":diag})
        except ValueError as e:
            reports.append({"a_id":a,"b_id":b,"status":"BLOCKED_MATCHUP","reason":str(e)})
    return {"status":"UNVALIDATED_WIN_OPTIMIZATION_SHADOW","model_version":VERSION,"week":w,
            "as_of":baseline["as_of"],"completed_through_week":cutoff,
            "selection_trials":selection_n,"fresh_evaluation_trials":evaluation_n,
            "dependence_fit":[{"relationship":k[0],"positions":list(k[1:]),**v} for k,v in sorted(fit.items())],
            "matchups":reports,"promotion_eligible":False,"applied_to_primary_model":False,
            "limitations":["Not calibrated win odds or primary lineup recommendations.",
                           "Fixed baseline means; signed copula dependence, not finite-budget joint game simulation.",
                           "Top-three opposing lineups are hypothetical equally weighted sensitivities.",
                           "Target-week IR, injury, starter roles and availability must be independently confirmed.",
                           "No mid-game simulation. No transactions."]}
