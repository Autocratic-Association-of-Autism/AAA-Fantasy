"""Shadow-only conditional one-for-one roster transaction research."""
from collections import defaultdict, Counter
import numpy as np
from .engine import (PRIOR, SLOTS, date, historical, history_index, predict,
                     current_players, position, team_key)
from .workload import lookup, expected, clean_name, POS
from .distributions import from_residuals, draw
from .fetch_kickoffs import fetch

VERSION="transaction-value-1.0-shadow"
TRIALS=100000
PROTECTED={"lutherburden","lutherburdeniii"}
UNAVAILABLE={"IR","INJURY_RESERVE","SUSPENSION","SUSPENDED"}

def optimal(pool,means):
    """Exact maximum-mean lineup for the fixed nine slots."""
    groups={p:sorted([r["pid"] for r in pool if r["pos"]==p and r["pid"] in means],
                     key=lambda i:(-means[i],i)) for p in PRIOR}
    if any(len(groups[p])<n for p,n in {"QB":1,"RB":2,"WR":2,"TE":1,"D/ST":1,"K":1}.items()):
        return None
    flex=groups["RB"][2:]+groups["WR"][2:]+groups["TE"][1:]
    if not flex:return None
    f=min(flex,key=lambda i:(-means[i],i))
    ids=(groups["QB"][0],*groups["RB"][:2],*groups["WR"][:2],groups["TE"][0],f,groups["D/ST"][0],groups["K"][0])
    if len(set(ids))!=9:raise ValueError("Duplicate starter IDs")
    return {"lineup":dict(zip(SLOTS,ids)),"points":float(sum(means[i] for i in ids))}

def player_mean(p,stats,idx,cutoff,shrink,recent):
    pid,pos=p["pid"],p["pos"]
    if pos in POS:
        obs,_=lookup(stats,p["name"],p["nfl_team"],pos,cutoff)
        if obs:
            val=expected(obs,pos,cutoff+1,cutoff)
            return {"mean":float(val["ppr_points"]),"method":"v6_opportunity",
                    "observations":len(obs),"last_week":max(r["week"] for r in obs)}
    h=[r for r in idx.get(pid,[]) if r["week"]<=cutoff]
    return {"mean":float(predict(pid,cutoff+1,pos,idx,shrink,recent)),
            "method":"league_score_baseline" if h else "positional_prior_only",
            "observations":len(h),"last_week":max((r["week"] for r in h),default=0)}

def eligible(p,w,first,s):
    return (p["nfl_team"] in s["kickoffs"] and p.get("slot")!="IR"
            and p.get("injury","") not in UNAVAILABLE
            and not (w==first and p.get("injury")=="OUT"))

def profile(pool,means,schedules,first):
    return {w:optimal([p for p in pool if eligible(p,w,first,s)],means) for w,s in schedules.items()}

def delta(before,after,weeks):
    matched=[w for w in weeks if before.get(w) is not None and after.get(w) is not None]
    return {"points_delta":round(sum(after[w]["points"]-before[w]["points"] for w in matched),4) if matched else None,
            "matched_weeks":matched,
            "restored_lineup_weeks":[w for w in weeks if before.get(w) is None and after.get(w) is not None],
            "lost_lineup_weeks":[w for w in weeks if before.get(w) is not None and after.get(w) is None],
            "unresolved_weeks":[w for w in weeks if before.get(w) is None and after.get(w) is None]}

def depth(pool,means,schedule,w,first):
    valid=[p for p in pool if eligible(p,w,first,schedule)]
    best=optimal(valid,means)
    if best is None:return None
    losses=[];blocked=[]
    for pid in best["lineup"].values():
        alt=optimal([p for p in valid if p["pid"]!=pid],means)
        if alt is None:blocked.append(pid)
        else:losses.append(best["points"]-alt["points"])
    return {"unreplaceable_starters":blocked,"unreplaceable_count":len(blocked),
            "mean_replaceable_loss":round(float(np.mean(losses)),4) if losses else None,
            "worst_replaceable_loss":round(max(losses),4) if losses else None}

def swapped(pool,outgoing,incoming):
    if sum(p["pid"]==outgoing for p in pool)!=1 or any(p["pid"]==incoming["pid"] for p in pool):
        raise ValueError("Invalid roster swap")
    return [p for p in pool if p["pid"]!=outgoing]+[{**incoming,"slot":"BE"}]

def rank_value(d):
    return (-len(d["lost_lineup_weeks"]),len(d["restored_lineup_weeks"]),
            d["points_delta"] if d["points_delta"] is not None else -float("inf"))

def residual_pool(hist,stats,idx,shrink,recent):
    result=defaultdict(list)
    for r in hist:
        w=r["week"]
        if w>=5:
            mean=player_mean(r,stats,idx,w-1,shrink,recent)["mean"]
            result[r["pos"]].append(r["actual"]-mean)
    return result

def paired_changes(before,after,opp_before,opp_after,means,meta,residuals,week,n=TRIALS):
    if any(x is None for x in (before,after,opp_before,opp_after)):return None
    ids=set().union(*(set(x["lineup"].values()) for x in (before,after,opp_before,opp_after)))
    samples={}
    for pid in sorted(ids):
        pos=meta[pid]["pos"]
        if len(residuals.get(pos,[]))<8:return None
        dist=from_residuals(residuals[pos],means[pid])
        rng=np.random.default_rng(np.random.SeedSequence([20261124,week,pid]))
        samples[pid]=draw(dist,rng.random(n))
    def total(x):return sum(samples[i] for i in x["lineup"].values())
    def credit(a,b):return (a>b).astype(float)+.5*(a==b)
    old=credit(total(before),total(opp_before));new=credit(total(after),total(opp_after))
    diff=new-old
    return {"before_win_fraction":round(float(old.mean()),6),"after_win_fraction":round(float(new.mean()),6),
            "win_fraction_delta":round(float(diff.mean()),6),
            "paired_mc_se":round(float(diff.std(ddof=1)/np.sqrt(n)),6),"trials":n}

def report(snapshot,history_snapshot,baseline,schedule,stats,cutoff,shrink,recent):
    first=int(baseline["week"]);as_of=baseline["as_of"]
    if cutoff>=first:raise ValueError("Target-week leakage")
    league=snapshot["League"][0];reg_end=int(league["regular_season_weeks"])
    # Calendar only, not a verified playoff bracket or qualification forecast.
    last=min(18,reg_end+(int(league["playoff_team_count"])-1).bit_length()*int(league["playoff_matchup_period_length"]))
    regular=list(range(first,reg_end+1));playoffs=list(range(reg_end+1,last+1))
    schedules={};errors={}
    for w in range(first,last+1):
        try:
            s=schedule if w==first else fetch(int(league["season"]),w)
            if not s.get("complete") or int(s["week"])!=w or any(date(k)<=date(as_of) for k in s["kickoffs"].values()):
                raise ValueError("Unverified or already-started schedule")
            schedules[w]=s
        except Exception as exc:errors[w]=str(exc)
    if first not in schedules:return {"status":"BLOCKED_PREGAME_SCHEDULE","reason":errors.get(first),"promotion_eligible":False}
    hist=historical(history_snapshot,cutoff);idx=history_index(hist)
    pools={int(t["team_id"]):current_players(snapshot,int(t["team_id"]),first) for t in snapshot["Teams"]}
    all_owned=[p for pool in pools.values() for p in pool]
    if len({p["pid"] for p in all_owned})!=len(all_owned):raise ValueError("Duplicate current ownership")
    meta={p["pid"]:p for p in all_owned}
    fa=[]
    for r in snapshot["Free_Agents"]:
        pos=position(r["position"]);pid=int(r["player_id"])
        if pos not in PRIOR or pid in meta:continue
        p={"pid":pid,"name":r["player"],"pos":pos,"nfl_team":team_key(r["pro_team"]),
           "injury":str(r.get("injury_status","")).upper(),"slot":"BE"}
        if p["injury"] in UNAVAILABLE:continue
        meta[pid]=p;fa.append(p)
    projections={pid:player_mean(p,stats,idx,cutoff,shrink,recent) for pid,p in meta.items() if p["pos"] in PRIOR}
    means={pid:v["mean"] for pid,v in projections.items()}
    def supported(p):
        info=projections.get(p["pid"],{})
        return info.get("observations",0)>=3 and cutoff-info.get("last_week",0)<=3
    fa=[p for p in fa if supported(p)]
    tid=int(baseline.get("your_team_id",1));own=pools[tid]
    control={t:profile(pool,means,schedules,first) for t,pool in pools.items()}
    horizons={"week":[first],"regular":regular,"playoff_calendar":playoffs}
    moves=[]
    outgoing=[p for p in own if p["pos"] in PRIOR and p.get("slot")!="IR"
              and not (tid==1 and clean_name(p["name"]) in PROTECTED)]
    def make(kind,peer,inp,out):
        a=swapped(own,out["pid"],inp);pa=profile(a,means,schedules,first)
        pb=profile(swapped(pools[peer],inp["pid"],out),means,schedules,first) if peer is not None else None
        moves.append({"kind":kind,"counterparty_id":peer,"out":out["pid"],"in":inp["pid"],
                      "own":{k:delta(control[tid],pa,ws) for k,ws in horizons.items()},
                      "counterparty":{k:delta(control[peer],pb,ws) for k,ws in horizons.items()} if peer is not None else None,
                      "_a":pa,"_b":pb,"_pool":a})
    for out in outgoing:
        for inp in fa:make("one_add_one_drop",None,inp,out)
        for peer,pool in pools.items():
            if peer==tid:continue
            for inp in pool:
                if supported(inp) and inp.get("slot")!="IR" and inp.get("injury") not in UNAVAILABLE:
                    make("one_for_one_trade_hypothetical",peer,inp,out)
    groups={};selected={}
    for kind in ("one_add_one_drop","one_for_one_trade_hypothetical"):
        for horizon in horizons:
            options=sorted([x for x in moves if x["kind"]==kind],key=lambda x:rank_value(x["own"][horizon]),reverse=True)[:5]
            groups[kind+"_"+horizon]=[(x["out"],x["in"]) for x in options]
            for x in options:selected[(x["out"],x["in"])]=x
    residuals=residual_pool(hist,stats,idx,shrink,recent)
    opponents={}
    for m in snapshot["Season_Schedule"]:
        w=int(m["week"]);a,b=int(m["team_a_id"]),int(m["team_b_id"])
        opponents[w,a]=b;opponents[w,b]=a
    reports=[]
    for x in selected.values():
        peer=x["counterparty_id"];changes=[];peer_changes=[]
        for w in regular:
            other=opponents.get((w,tid))
            if other is None or w not in schedules:continue
            # For a trade with the actual opponent, change both lineups.
            before=control[other].get(w)
            after=x["_b"].get(w) if other==peer else before
            q=paired_changes(control[tid].get(w),x["_a"].get(w),before,after,means,meta,residuals,w)
            changes.append({"week":w,"opponent_id":other,"comparison":q})
            if peer is not None:
                rival=opponents.get((w,peer))
                if rival is not None:
                    b0=control[rival].get(w);b1=x["_a"].get(w) if rival==tid else b0
                    q2=paired_changes(control[peer].get(w),x["_b"].get(w),b0,b1,means,meta,residuals,w)
                    peer_changes.append({"week":w,"opponent_id":rival,"comparison":q2})
        def sum_wins(rows):
            valid=[r["comparison"] for r in rows if r["comparison"] is not None]
            return {"matched_weeks":len(valid),"sum_win_fraction_delta":round(sum(r["win_fraction_delta"] for r in valid),6) if valid else None}
        item={k:v for k,v in x.items() if not k.startswith("_")}
        item.update({"outgoing":meta[x["out"]]["name"],"incoming":meta[x["in"]]["name"],
                     "incoming_injury_status":meta[x["in"]].get("injury"),
                     "incoming_projection":projections[x["in"]],"outgoing_projection":projections[x["out"]],
                     "regular_weekly_win_sensitivity":changes,"regular_expected_wins_sensitivity":sum_wins(changes),
                     "counterparty_weekly_win_sensitivity":peer_changes,"counterparty_expected_wins_sensitivity":sum_wins(peer_changes),
                     "current_depth_after":depth(x["_pool"],means,schedules[first],first,first)})
        reports.append(item)
    return {"status":"UNVALIDATED_TRANSACTION_VALUE_SHADOW","model_version":VERSION,"week":first,"as_of":as_of,
            "completed_through_week":cutoff,"your_team_id":tid,"schedule_sources":{str(w):s["source"] for w,s in schedules.items()},
            "schedule_errors":errors,"regular_weeks":regular,"playoff_calendar_weeks":playoffs,
            "eligible_free_agents":len(fa),"screened_moves":dict(Counter(x["kind"] for x in moves)),
            "control":control[tid],"current_depth_control":depth(own,means,schedules[first],first,first),
            "shortlists":groups,"moves":reports,"promotion_eligible":False,"applied_to_primary_model":False,
            "limitations":["One-for-one hypothetical swaps; no actual transactions or verified deadline/waiver feasibility.",
                           "Team 1 Luther Burden protected; no acceptance probabilities.",
                           "Static v6 skill means and league-score baseline for K/DST, not future opponent-adjusted means.",
                           "Future injury/role unknown; IR excluded throughout, OUT excluded this week.",
                           "Independent positional residuals and optimal lineups; not calibrated win odds.",
                           "Playoff calendar points conditional on participation, no qualification or bracket odds.",
                           "Free agents require three observations, last within three weeks; speculative adds excluded."]}

def backtest(snapshot,stats,cutoff,shrink,recent):
    """Observed roster differences, NOT verified transaction timing or choice sets."""
    hist=historical(snapshot,cutoff);idx=history_index(hist)
    by=defaultdict(dict);actual=defaultdict(dict)
    for r in hist:
        by[r["week"],r["team_id"]][r["pid"]]=r
        actual[r["week"]][r["pid"]]=r
    rows=[];skipped=Counter()
    for (w,tid),now in sorted(by.items()):
        if w<5:continue
        old=by.get((w-1,tid),{})
        if not old:continue
        added=set(now)-set(old);dropped=set(old)-set(now)
        if len(added)!=1 or len(dropped)!=1:
            skipped["not_single_roster_difference"]+=1;continue
        outgoing=next(iter(dropped));incoming=next(iter(added))
        if outgoing not in actual[w]:
            skipped["outgoing_actual_unobserved"]+=1;continue
        new_pool=list(now.values())
        old_pool=swapped(new_pool,incoming,actual[w][outgoing])
        union={p["pid"]:p for p in old_pool+new_pool}
        means={i:player_mean(p,stats,idx,w-1,shrink,recent)["mean"] for i,p in union.items()}
        b=optimal(old_pool,means);a=optimal(new_pool,means)
        if b is None or a is None:
            skipped["incomplete_lineup"]+=1;continue
        obs=lambda lineup:sum(actual[w][i]["actual"] for i in lineup["lineup"].values())
        rows.append({"week":w,"team_id":tid,"out":outgoing,"in":incoming,
                     "predicted_delta":a["points"]-b["points"],"observed_delta":obs(a)-obs(b)})
    summary={"n":len(rows)}
    if rows:
        e=np.asarray([r["predicted_delta"]-r["observed_delta"] for r in rows])
        summary.update({"delta_mae":float(np.abs(e).mean()),"delta_bias":float(e.mean()),
                        "same_sign_fraction":float(np.mean([np.sign(r["predicted_delta"])==np.sign(r["observed_delta"]) for r in rows]))})
    return {"status":"EXPLORATORY_ROSTER_DIFFERENCE_REPLAY_NOT_PROMOTION","model_version":VERSION,
            "summary":summary,"rows":rows,"excluded":dict(skipped),"promotion_eligible":False,
            "limitations":["Final roster differences are not confirmed transactions or pregame choice sets.",
                           "Historical positive-projection filter can confuse bye/injury with roster change.",
                           "Unobserved outgoing actuals excluded; selective sample cannot validate the waiver market."]}
