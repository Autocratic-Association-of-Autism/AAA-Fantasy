"""Conditional league season scenarios; no production or roster mutations."""
from collections import defaultdict
import numpy as np
from .engine import (PRIOR,SLOTS,date,historical,history_index,predict,predictions,
                     current_players,position,team_key)
from .distributions import from_residuals,draw
from .transaction_value import player_mean,residual_pool,eligible,swapped
from .manager_behavior import make_case,summarize_choice
from .fetch_kickoffs import fetch

VERSION="season-simulation-1.0-shadow"
TRIALS=100000

def completed_results(snapshot,cutoff):
    ids=sorted(int(t["team_id"]) for t in snapshot["Teams"])
    ix={t:i for i,t in enumerate(ids)}
    wins=np.zeros(len(ids));pf=np.zeros(len(ids),dtype=np.int64)
    games=np.zeros(len(ids),dtype=int);seen=set()
    for m in snapshot["Weekly_Matchups"]:
        w=int(m["week"])
        if not 1<=w<=cutoff:continue
        a,b=int(m["home_team_id"]),int(m["away_team_id"])
        if a==b or (w,a) in seen or (w,b) in seen:raise ValueError("Duplicate actual matchup")
        seen.update(((w,a),(w,b)))
        i,j=ix[a],ix[b];x,y=round(100*float(m["home_score"])),round(100*float(m["away_score"]))
        pf[i]+=x;pf[j]+=y;games[i]+=1;games[j]+=1
        wins[i]+=1. if x>y else .5 if x==y else 0.
        wins[j]+=1. if y>x else .5 if x==y else 0.
    if not np.all(games==cutoff):raise ValueError("Incomplete actual fantasy season")
    return ids,wins,pf

def verify_standings(snapshot,cutoff):
    ids,wins,pf=completed_results(snapshot,cutoff)
    by={int(t["team_id"]):t for t in snapshot["Teams"]}
    for i,tid in enumerate(ids):
        t=by[tid]
        if int(t["wins"])+int(t["losses"])+int(t["ties"])!=cutoff:
            raise ValueError("ESPN standings not advanced through completed cutoff")
        if abs(wins[i]-(int(t["wins"])+.5*int(t["ties"])))>1e-9 or abs(pf[i]-round(100*float(t["points_for"])))>2:
            raise ValueError("Completed matchups do not reconcile to ESPN standings")
    return ids,wins,pf

def seeds(wins,pf,divisions,division_priority=True):
    """Rows=teams, columns=trials. Equal record/PF uses team-ID order as explicit scenario."""
    n,trials=wins.shape
    ix=np.broadcast_to(np.arange(n)[:,None],wins.shape)
    general=np.lexsort((ix,-pf,-wins),axis=0)
    if not division_priority:return general
    leaders=np.zeros_like(wins,dtype=bool)
    div=np.asarray(divisions)
    for d in np.unique(div):
        group=np.where(div[general]==d,np.arange(n)[:,None],n)
        leader=general[group.min(axis=0),np.arange(trials)]
        leaders[leader,np.arange(trials)]=True
    return np.lexsort((ix,-pf,-wins,-leaders.astype(int)),axis=0)

def partial_lineup(pool,means):
    """Known roster cannot fill a slot: explicit frozen-roster empty-slot scenario."""
    g={p:sorted([x["pid"] for x in pool if x["pos"]==p and x["pid"] in means],
                key=lambda i:(-means[i],i)) for p in PRIOR}
    chosen={}
    for pos,slots in (("QB",["QB"]),("RB",["RB1","RB2"]),("WR",["WR1","WR2"]),("TE",["TE"]),("D/ST",["D/ST"]),("K",["K"])):
        chosen.update(dict(zip(slots,g[pos])))
    remaining=[i for pos in ("RB","WR","TE") for i in g[pos] if i not in chosen.values()]
    if remaining:chosen["FLEX"]=min(remaining,key=lambda i:(-means[i],i))
    return chosen,[s for s in SLOTS if s not in chosen]

def player_draws(pid,pos,mean,residuals,week,n):
    if len(residuals.get(pos,[]))<8:raise ValueError("Insufficient positional residuals: "+pos)
    d=from_residuals(residuals[pos],mean)
    rng=np.random.default_rng(np.random.SeedSequence([20261124,week,int(pid) & 0xffffffff,(int(pid) >> 32) & 0xffffffff]))
    return np.rint(draw(d,rng.random(n))*100).astype(np.int32)

def week_scores(pools,means,residuals,schedule,first,w,n,ids,manager=None,idx=None,previous=None,selection_means=None,user_id=1):
    """Common random numbers by week/player, and distinct manager choice uniforms."""
    values=np.zeros((len(ids),n),dtype=np.int64);empty=[];choices={}
    for k,tid in enumerate(ids):
        valid=[p for p in pools[tid] if eligible(p,w,first,schedule)]
        starters,missing=partial_lineup(valid,means)
        if missing:empty.append({"week":w,"team_id":tid,"empty_slots":missing})
        scores={p["pid"]:player_draws(p["pid"],p["pos"],means[p["pid"]],residuals,w,n)
                for p in valid if p["pid"] in means}
        coeff=(manager or {}).get(tid)
        if coeff is not None and tid!=user_id and not missing:
            try:
                case=make_case(valid,w,tid,selection_means,idx,previous.get(tid,set()))
                p,order,_=summarize_choice(case,np.asarray(coeff,float))
                rng=np.random.default_rng(np.random.SeedSequence([20261125,w,tid]))
                selected=np.minimum(len(p)-1,np.searchsorted(np.cumsum(p),rng.random(n),side="left"))
                cols=np.asarray([c["ids"] for c in case["candidates"]],dtype=np.int64)[selected]
                # Sum selected scores without materializing all lineup/trial totals.
                player_ids=sorted(scores);index={pid:i for i,pid in enumerate(player_ids)}
                lookup=np.vectorize(index.__getitem__,otypes=[np.int64])(cols)
                matrix=np.stack([scores[pid] for pid in player_ids])
                values[k]=matrix[lookup,np.arange(n)[:,None]].sum(axis=1,dtype=np.int64)
                choices[str(tid)]="fixed_history_manager_choice_law"
                continue
            except ValueError:
                choices[str(tid)]="mean_fallback_choice_cap"
        for pid in starters.values():values[k]+=scores[pid]
    return values,empty,choices

def regular_schedule(snapshot,first,last,ids):
    out=defaultdict(list)
    for m in snapshot["Season_Schedule"]:
        w=int(m["week"])
        if first<=w<=last:out[w].append((int(m["team_a_id"]),int(m["team_b_id"])))
    for w in range(first,last+1):
        flat=[t for pair in out[w] for t in pair]
        if sorted(flat)!=ids:raise ValueError("Incomplete remaining fantasy schedule")
    return out

def simulate_regular(scores,fixtures,ids,start_wins,start_pf):
    n=next(iter(scores.values())).shape[1];ix={t:i for i,t in enumerate(ids)}
    wins=np.repeat(start_wins[:,None],n,axis=1);pf=np.repeat(start_pf[:,None],n,axis=1)
    weekly={}
    for w,pairs in sorted(fixtures.items()):
        x=scores[w];pf+=x
        for a,b in pairs:
            i,j=ix[a],ix[b]
            credit=(x[i]>x[j]).astype(float)+.5*(x[i]==x[j])
            wins[i]+=credit;wins[j]+=1-credit
            weekly.setdefault(str(w),[]).append({"a_id":a,"b_id":b,
                "a_win_fraction":float(credit.mean()),"a_mean":float(x[i].mean()/100),"b_mean":float(x[j].mean()/100)})
    return wins,pf,weekly

def postseason(order,scores,regular_end,reseeding=False):
    """Six-team single-week title bracket; four-team loser bracket.
    Hypothetical 2026 bracket based on documented past Sacko format.
    Title tie goes to higher seed; Sacko tie loses for lower seed.
    """
    n=order.shape[1];cols=np.arange(n)
    rank=np.empty_like(order)
    rank[order,cols]=np.arange(10)[:,None]
    def pick(a,b,w,low=False,second=None):
        x=scores[w][a,cols];y=scores[w][b,cols]
        if second is not None:x=x+scores[second][a,cols];y=y+scores[second][b,cols]
        win=np.where((x>y)|((x==y)&(rank[a,cols]<rank[b,cols])),a,b)
        return np.where(win==a,b,a) if low else win
    w1,w2,w3=regular_end+1,regular_end+2,regular_end+3
    q36=pick(order[2],order[5],w1);q45=pick(order[3],order[4],w1)
    if reseeding:
        low=np.where(rank[q36,cols]>rank[q45,cols],q36,q45)
        high=np.where(low==q36,q45,q36)
    else:low,high=q45,q36
    a=pick(order[0],low,w2);b=pick(order[1],high,w2)
    champ=pick(a,b,w3)
    s1=pick(order[6],order[9],w1,True);s2=pick(order[7],order[8],w1,True)
    sacko=pick(s1,s2,w2,True,w3)
    return champ,sacko

def summarize(ids,wins,pf,order,post=None):
    n=order.shape[1]
    result={}
    for i,tid in enumerate(ids):
        seed_probs=[float(np.mean(order[k]==i)) for k in range(len(ids))]
        result[str(tid)]={"expected_final_win_credits":float(wins[i].mean()),
            "expected_final_points_for":float(pf[i].mean()/100),
            "seed_probabilities":seed_probs,"top6_fraction":sum(seed_probs[:6]),
            "top2_fraction":sum(seed_probs[:2]),"regular_last_seed_fraction":seed_probs[-1]}
        if post is not None:
            c,s=post;result[str(tid)].update({"championship_scenario_fraction":float(np.mean(c==i)),
                                             "sacko_scenario_fraction":float(np.mean(s==i))})
    return result

def scenario(pools,means,residuals,schedules,fixtures,ids,initial_wins,initial_pf,divisions,
             first,last,n,manager=None,idx=None,previous=None,selection_means=None,user_id=1,post_allowed=False):
    scores={};empty=[];choices={}
    for w,s in sorted(schedules.items()):
        x,holes,selected=week_scores(pools,means,residuals,s,first,w,n,ids,manager,idx,previous,selection_means,user_id)
        scores[w]=x;empty.extend(holes);choices[str(w)]=selected
    wins,pf,weekly=simulate_regular({w:scores[w] for w in fixtures},fixtures,ids,initial_wins,initial_pf)
    order=seeds(wins,pf,divisions)
    pure=seeds(wins,pf,divisions,False)
    fixed=postseason(order,scores,last) if post_allowed else None
    reseed=postseason(order,scores,last,True) if post_allowed else None
    return {"teams":summarize(ids,wins,pf,order,fixed),"record_points_only":summarize(ids,wins,pf,pure),
            "reseeded_title_sensitivity":summarize(ids,wins,pf,order,reseed) if reseed is not None else None,
            "weekly_matchups":weekly,"frozen_roster_empty_slots":empty,"manager_choice_status":choices}

def report(snapshot,history_snapshot,baseline,schedule,stats,cutoff,shrink,recent,manager_report,transactions,n=TRIALS):
    first=int(baseline["week"]);as_of=baseline["as_of"];league=snapshot["League"][0];last=int(league["regular_season_weeks"])
    if cutoff!=first-1 or cutoff>=first:raise ValueError("Season simulation requires reconciled immediately preceding week")
    ids,initial_wins,initial_pf=verify_standings(snapshot,cutoff)
    teams={int(t["team_id"]):t for t in snapshot["Teams"]};div=[int(teams[t]["division_id"]) for t in ids]
    if len(ids)!=10 or len(set(div))!=2 or int(league["playoff_team_count"])!=6:
        raise ValueError("Unexpected league structure; bracket assumptions blocked")
    if league.get("playoff_seed_tie_rule")!="TOTAL_POINTS_SCORED":raise ValueError("Unsupported seeding tiebreaker")
    initial_order=seeds(initial_wins[:,None],initial_pf[:,None],div)[:,0]
    observed_order=sorted(ids,key=lambda t:int(teams[t]["standing"]))
    replay_order=[ids[i] for i in initial_order]
    if replay_order!=observed_order:raise ValueError("Division leader seeding does not reproduce current standings")
    fixtures=regular_schedule(snapshot,first,last,ids)
    schedules={};errors={}
    for w in range(first,min(18,last+3)+1):
        try:
            s=schedule if w==first else fetch(int(league["season"]),w)
            if int(s["week"])!=w or not s.get("complete") or any(date(k)<=date(as_of) for k in s["kickoffs"].values()):
                raise ValueError("Unverified or started NFL schedule")
            schedules[w]=s
        except Exception as e:errors[w]=str(e)
    if any(w not in schedules for w in fixtures):raise ValueError("Missing remaining regular season NFL schedule: "+str(errors))
    post_allowed=int(league["playoff_matchup_period_length"])==1 and all(w in schedules for w in range(last+1,last+4))
    if not post_allowed:schedules={w:s for w,s in schedules.items() if w<=last}
    hist=historical(history_snapshot,cutoff);idx=history_index(hist)
    pools={tid:[p for p in current_players(snapshot,tid,first) if p["pos"] in PRIOR] for tid in ids}
    all_players=[p for pool in pools.values() for p in pool]
    if len({p["pid"] for p in all_players})!=len(all_players):raise ValueError("Duplicate roster ownership")
    means={p["pid"]:predict(p["pid"],first,p["pos"],idx,shrink,recent) for p in all_players}
    residuals=defaultdict(list)
    for r in predictions(hist,shrink,recent,start=2,stop=cutoff):residuals[r["pos"]].append(r["error"])
    user_id=int(baseline.get("your_team_id",1))
    common=(schedules,fixtures,ids,initial_wins,initial_pf,div,first,last,n)
    scenarios={"frozen_mean_control":scenario(pools,means,residuals,*common,post_allowed=post_allowed)}
    coeff={};previous=defaultdict(set)
    for r in hist:
        if r["week"]==cutoff and r["slot"] not in ("BE","IR"):previous[r["team_id"]].add(r["pid"])
    for tid,r in manager_report.get("all_rosters",{}).items():
        if r.get("status")=="CONDITIONAL_ROSTER_SHADOW":
            coeff[int(tid)]=r["models"]["manager"]["coefficients"]
    if coeff:
        scenarios["manager_choice_sensitivity"]=scenario(pools,means,residuals,*common,
            manager=coeff,idx=idx,previous=previous,selection_means=means,user_id=user_id,post_allowed=post_allowed)
    # Use separate matched v6 control for transaction proposals selected by v6.
    # No acceptance probability; two explicit single-move scenarios only.
    if transactions.get("status")=="UNVALIDATED_TRANSACTION_VALUE_SHADOW":
        moves=transactions.get("moves",[])
        chosen=[]
        for kind in ("one_add_one_drop","one_for_one_trade_hypothetical"):
            keys=transactions.get("shortlists",{}).get(kind+"_regular",[])
            for out,inc in keys[:1]:
                move=next((m for m in moves if m["out"]==out and m["in"]==inc),None)
                if move:chosen.append(move)
        if chosen:
            v6means={p["pid"]:player_mean(p,stats,idx,cutoff,shrink,recent)["mean"] for p in all_players}
            v6res=residual_pool(hist,stats,idx,shrink,recent)
            scenarios["transaction_matched_v6_control"]=scenario(pools,v6means,v6res,*common,post_allowed=post_allowed)
            meta={p["pid"]:p for p in all_players}
            for r in snapshot["Free_Agents"]:
                pid=int(r["player_id"]);pos=position(r["position"])
                if pid not in meta and pos in PRIOR:
                    meta[pid]={"pid":pid,"name":r["player"],"pos":pos,"nfl_team":team_key(r["pro_team"]),
                               "slot":"BE","injury":str(r.get("injury_status","")).upper()}
            for move in chosen:
                out,inc=move["out"],move["in"];peer=move["counterparty_id"]
                if inc not in meta or out not in meta:continue
                alt=dict(pools);alt[user_id]=swapped(pools[user_id],out,meta[inc])
                if peer is not None:alt[peer]=swapped(pools[peer],inc,meta[out])
                mm=dict(v6means);mm[inc]=player_mean(meta[inc],stats,idx,cutoff,shrink,recent)["mean"]
                key="hypothetical_"+move["kind"]
                scenarios[key]=scenario(alt,mm,v6res,*common,post_allowed=post_allowed)
                scenarios[key]["transaction"]={"outgoing":move["outgoing"],"incoming":move["incoming"],"counterparty_id":peer}
    return {"status":"UNVALIDATED_SEASON_SCENARIOS_NOT_CALIBRATED_ODDS","model_version":VERSION,
            "week":first,"as_of":as_of,"completed_through_week":cutoff,"trials_per_scenario":n,
            "standings_reconciled":True,"observed_seed_order":observed_order,"division_priority_reproduced":True,
            "schedule_sources":{str(w):s["source"] for w,s in schedules.items()},"schedule_errors":errors,
            "postseason_status":"HYPOTHETICAL_BRACKET_UNVERIFIED_2026" if post_allowed else "BLOCKED_POSTSEASON_SCHEDULE_OR_PERIOD",
            "scenarios":scenarios,"promotion_eligible":False,"applied_to_primary_model":False,
            "limitations":["Division leaders get first two seeds; current standings reproduced, future rule not independently confirmed.",
                           "Points-for tiebreaker from ESPN; exact equal record and points resolved by team ID as scenario.",
                           "Title #3 vs #6, #4 vs #5, top two byes; fixed and reseeded semifinals are illustrations.",
                           "Sacko #7 vs #10, #8 vs #9 losers advance to two-week aggregate final; historical format assumption, current rules unverified.",
                           "Frozen roster with empty eligible slots explicitly scoring zero; no simulated injury probabilities or automatic transactions.",
                           "Static lagged means, independent player/week residuals, no joint NFL game-budget coupling.",
                           "Manager coefficients fixed to observed history; no evolving manager choices or acceptance probability.",
                           "Transaction scenario uses matched v6 scoring control; no deadline, waiver or trade feasibility verified.",
                           "No independent completed-season probability calibration."]}

def replay(snapshot,pbp,cutoff,shrink,recent,n=5000):
    """Frozen observed rosters from before each three-week historical window."""
    hist=historical(snapshot,cutoff);idx=history_index(hist)
    ids=sorted(int(t["team_id"]) for t in snapshot["Teams"])
    actual_rows=defaultdict(list)
    for r in hist:actual_rows[r["week"]].append(r)
    out=[]
    for first in range(5,cutoff-1):
        last=first+2;_,start_wins,start_pf=completed_results(snapshot,first-1)
        _,end_wins,end_pf=completed_results(snapshot,last)
        prior=[r for r in hist if r["week"]<first]
        residuals=defaultdict(list)
        for r in predictions(prior,shrink,recent,start=2,stop=first-1):residuals[r["pos"]].append(r["error"])
        if any(len(residuals[p])<8 for p in PRIOR):continue
        pools={tid:[r for r in actual_rows[first-1] if r["team_id"]==tid] for tid in ids}
        means={p["pid"]:predict(p["pid"],first,p["pos"],idx,shrink,recent) for pool in pools.values() for p in pool}
        fixtures=regular_schedule(snapshot,first,last,ids);scores={};empty=[]
        for w in fixtures:
            schedule={"kickoffs":{t:"historical_game" for (v,t) in pbp["opponents"] if v==w}}
            if len(schedule["kickoffs"])<26:raise ValueError("Historical NFL schedule incomplete")
            scores[w],holes,_=week_scores(pools,means,residuals,schedule,first,w,n,ids);empty.extend(holes)
        wins,pf,_=simulate_regular(scores,fixtures,ids,start_wins,start_pf)
        for i,tid in enumerate(ids):
            out.append({"first_week":first,"last_week":last,"team_id":tid,
                        "predicted_wins":float(wins[i].mean()-start_wins[i]),
                        "actual_wins":float(end_wins[i]-start_wins[i]),
                        "predicted_points":float((pf[i].mean()-start_pf[i])/100),
                        "actual_points":float((end_pf[i]-start_pf[i])/100),
                        "empty_slot_count":sum(len(x["empty_slots"]) for x in empty if x["team_id"]==tid)})
    return {"status":"EXPLORATORY_OVERLAPPING_THREE_WEEK_REPLAY","model_version":VERSION,
            "n":len(out),"trials":n,"wins_mae":float(np.mean([abs(r["predicted_wins"]-r["actual_wins"]) for r in out])) if out else None,
            "points_mae":float(np.mean([abs(r["predicted_points"]-r["actual_points"]) for r in out])) if out else None,
            "rows":out,"promotion_eligible":False,
            "limitations":["Overlapping historical windows are dependent; no independent season calibration.",
                           "Prior-week observed final rosters filtered by ESPN projection-positive history.",
                           "Actual managers made subsequent roster moves; frozen roster replay is not transaction-aware.",
                           "No completed-season championship or Sacko validation."]}
