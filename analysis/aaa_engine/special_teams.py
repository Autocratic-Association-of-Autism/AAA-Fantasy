"""Dedicated D/ST and kicker point shadows fitted to actual AAA league scoring.

Fixed ridge residual ablations, one model per position. Training examples
use lagged team/offense/defense features and the existing historical scoring
control. No generic ESPN scoring assumption, no use of target-week outcome.
These are mean estimates, not component-level scoring or calibrated odds.
"""
from __future__ import annotations
from collections import defaultdict
import numpy as np
from .engine import date, historical, history_index, predict, team_key, position
from .game_environment import preview, scenario_points, summarize

VERSION = "special-teams-1.0-shadow"
POSITIONS = ("D/ST", "K")
MIN_TRAIN = 24
MIN_TEAMS = 8
RIDGE = 30.
MODELS = ("baseline", "v9", "core", "expanded")


def _aggregate(pbp, side, team, cutoff):
    return summarize({(w,t):r for (w,t),r in pbp[side].items()
                      if t == team and w <= cutoff}, cutoff)


def matchup_features(pbp, pos, team, opponent, cutoff):
    """Feature groups are fixed before evaluation, with missing source gates."""
    if cutoff < 3 or int(pbp["included_through_week"]) < cutoff:
        return None
    team, opponent = team_key(team), team_key(opponent)
    if pos == "D/ST":
        off, defend = opponent, team
    elif pos == "K":
        off, defend = team, opponent
    else:
        raise ValueError("Unsupported special-teams position")
    a = _aggregate(pbp, "offense", off, cutoff)
    b = _aggregate(pbp, "defense", defend, cutoff)
    if min(a.get("games",0), b.get("games",0)) < 3:
        return None
    caps = pbp.get("source_capabilities",{})
    required = ("interceptions","passing_tds","rushing_tds") if pos == "D/ST" else (
        "fg_kicks","passing_tds","rushing_tds","red_zone")
    if not all(caps.get(k) is True for k in required):
        return None
    def avg(key):
        x,y=a.get(key),b.get(key)
        if x is None or y is None:
            raise ValueError("Missing metric "+key)
        return (float(x)+float(y))/2.
    def vals():
        if pos == "D/ST":
            db = avg("passes_per_game")
            return {"sacks_proxy":db*avg("sack_rate"),
                    "interceptions_proxy":avg("turnovers_per_game"),
                    "offensive_td_proxy":avg("pass_tds_per_game")+avg("rush_tds_per_game")}
        return {"fg_attempts_proxy":avg("fg_attempts_per_game"),
                "offensive_td_proxy":avg("pass_tds_per_game")+avg("rush_tds_per_game"),
                "redzone_plays_proxy":avg("redzone_plays_per_game")}
    try:
        core=vals()
        expanded={**core,"pass_epa_proxy":avg("pass_epa_per_dropback"),
                  "rush_epa_proxy":avg("rush_epa_per_carry"),
                  "plays_proxy":avg("plays_per_game")}
        if caps.get("third_down") is True:
            expanded["third_down_conversion_proxy"]=avg("third_down_conversion")
        if pos == "D/ST" and caps.get("qb_hit") is True:
            expanded["qb_hits_proxy"]=avg("passes_per_game")*avg("qb_hit_rate")
        if not all(np.isfinite(v) for v in expanded.values()):
            return None
        return {"core":core,"expanded":expanded,"games":[a["games"],b["games"]]}
    except (ValueError, TypeError):
        return None


def fit(rows, pos, week, group):
    """Standardization and ridge fit use only earlier labeled observations.

    Fixed penalty and features; no hyperparameter search on Week 11.
    No intercept: the residual mean is anchored at the baseline control.
    """
    train=[r for r in rows if r["week"]<week and r["position"]==pos]
    if len(train)<MIN_TRAIN or len({r["nfl_team"] for r in train})<MIN_TEAMS:
        return {"status":"INSUFFICIENT_PRIOR_TRAINING","n":len(train)}
    keys=sorted(set.intersection(*(set(r["features"][group]) for r in train)))
    if not keys:
        return {"status":"MISSING_FEATURES","n":len(train)}
    X=np.asarray([[r["features"][group][k] for k in keys] for r in train],float)
    y=np.asarray([r["actual"]-r["baseline"] for r in train],float)
    center=X.mean(axis=0)
    scale=X.std(axis=0)
    scale=np.where(scale>1e-8,scale,1.)
    z=(X-center)/scale
    coeff=np.linalg.solve(z.T@z+RIDGE*np.eye(len(keys)),z.T@y)
    return {"status":"FIT_SHADOW","n":len(train),"features":keys,
            "center":center.tolist(),"scale":scale.tolist(),"coeff":coeff.tolist(),
            "through_week":max(r["week"] for r in train),"ridge_penalty":RIDGE}


def predict_shadow(base, model, features, group):
    if model["status"]!="FIT_SHADOW":
        return float(base),False
    if not features or any(k not in features[group] for k in model["features"]):
        return float(base),False
    x=np.asarray([features[group][k] for k in model["features"]],float)
    # Restrict extrapolation to within three standardized training units.
    z=np.clip((x-np.asarray(model["center"]))/np.asarray(model["scale"]),-3.,3.)
    return float(base+z@np.asarray(model["coeff"])),True


def training_rows(snapshot,pbp,cutoff,shrink,recent):
    if int(pbp["included_through_week"])<cutoff:
        raise ValueError("Stale PBP source")
    hist=historical(snapshot,cutoff)
    idx=history_index(hist)
    rows=[]
    raw={(int(r["week"]),int(r["player_id"])):r for r in snapshot["Weekly_Lineups"]}
    # Baseline coefficients are trained on Weeks 2-4; start residual
    # examples in Week 5, not in that fitted training window.
    overwritten={}
    for m in snapshot["Weekly_Matchups"]:
        w=int(m["week"])
        try:
            equal=all(abs(float(m[s+"_projected"])-float(m[s+"_score"]))<.001 for s in ("home","away"))
        except (KeyError,ValueError,TypeError):
            equal=True
        overwritten[w]=overwritten.get(w,True) and equal
    for r in hist:
        w,pos,t=r["week"],r["pos"],r["nfl_team"]
        if w<5 or pos not in POSITIONS:
            continue
        opp=pbp["opponents"].get((w,t))
        if not opp:
            continue
        f=matchup_features(pbp,pos,t,opp,w-1)
        if f is None:
            continue
        base=predict(r["pid"],w,pos,idx,shrink,recent)
        scenario=scenario_points(pos,base,None,preview(pbp,t,opp,w-1))
        v9=scenario.get("point_estimate")
        record=raw[(w,r["pid"])]
        espn=None if overwritten.get(w,True) else float(record["projected_points"])
        rows.append({"week":w,"position":pos,"nfl_team":t,"opponent":opp,
                     "player_id":r["pid"],"name":r["name"],"actual":float(r["actual"]),
                     "baseline":float(base),"v9":float(v9) if v9 is not None else float(base),
                     "features":f,"espn_recorded":espn})
    return rows,idx


def metrics(rows, names):
    out={}
    for name in names:
        errors=np.asarray([r[name]-r["actual"] for r in rows],float)
        out[name]={"n":len(errors),"mae":round(float(np.abs(errors).mean()),4) if len(errors) else None,
                   "rmse":round(float(np.sqrt(np.mean(errors**2))),4) if len(errors) else None,
                   "bias":round(float(errors.mean()),4) if len(errors) else None}
    return out


def backtest(rows):
    evaluated=[]
    fits={}
    for r in rows:
        pos,w=r["position"],r["week"]
        out=dict(r)
        for group in ("core","expanded"):
            key=(pos,w,group)
            if key not in fits:
                fits[key]=fit(rows,pos,w,group)
            out[group],out[group+"_genuine"]=predict_shadow(r["baseline"],fits[key],r["features"],group)
        evaluated.append(out)
    results={}
    for pos in POSITIONS:
        subset=[r for r in evaluated if r["position"]==pos]
        genuine=[r for r in subset if r["core_genuine"] and r["expanded_genuine"]]
        # Use identical cohort for all methods; show fallback-inclusive separately.
        espn=[r for r in genuine if r["espn_recorded"] is not None]
        results[pos]={"all_with_fallbacks":metrics(subset,MODELS),
                      "matched_genuine":metrics(genuine,MODELS),
                      "matched_espn_unverified":metrics(espn,(*MODELS,"espn_recorded")),
                      "week_11_diagnostic":metrics([r for r in genuine if r["week"]==11],MODELS),
                      "pre_week_11":metrics([r for r in genuine if r["week"]<11],MODELS),
                      "excluded_from_genuine":len(subset)-len(genuine),
                      "per_week":{str(w):metrics([r for r in genuine if r["week"]==w],MODELS)
                                  for w in sorted({r["week"] for r in subset})}}
    return {"status":"EXPLORATORY_SPECIAL_TEAMS_RETROSPECTIVE_NOT_PROMOTION",
            "model_version":VERSION,"positions":results,
            "promotion_eligible":False,
            "limitations":["Roster-sampled fantasy scores; ESPN recorded projections not verified pregame.",
                           "Early weeks lack sufficient residual training; explicitly labeled baseline fallback.",
                           "Weeks 5-11 exploratory; Week 11 diagnostic, not an independent holdout.",
                           "Exact league fantasy scores as response; no scoring-rule reconstruction.",
                           "Turnover proxy is interceptions only; no fumble/return TD probability, weather or individual kick distance.",
                           "Fixed ridge penalty, not optimized on test results."]}


def forecast(snapshot, baseline, schedule, pbp, rows, idx, cutoff, shrink, recent):
    w=int(baseline["week"])
    if cutoff>=w:
        raise ValueError("Target-week leakage")
    opponents={}
    for g in schedule["games"]:
        a,b=(team_key(t) for t in g["teams"])
        opponents[a]=b
        opponents[b]=a
    fits={(p,g):fit(rows,p,w,g) for p in POSITIONS for g in ("core","expanded")}
    entries=[]
    # Include roster and available free-agent streamers; deduplicate by ID.
    seen=set()
    for source in ("Current_Rosters","Free_Agents"):
        for r in snapshot[source]:
            p=position(r["position"])
            if p not in POSITIONS:
                continue
            pid=int(r["player_id"])
            if pid in seen:
                continue
            seen.add(pid)
            team=team_key(r["pro_team"])
            opp=opponents.get(team)
            kickoff=schedule["kickoffs"].get(team)
            if not opp or not kickoff or date(kickoff)<=date(baseline["as_of"]):
                continue
            base=predict(pid,w,p,idx,shrink,recent)
            f=matchup_features(pbp,p,team,opp,cutoff)
            v9=scenario_points(p,base,None,preview(pbp,team,opp,cutoff)).get("point_estimate")
            a={"player_id":pid,"name":r["player"],"position":p,"nfl_team":team,
               "opponent":opp,"fantasy_team_id":r.get("team_id"),"pool":source,
               "injury_status_unverified":r.get("injury_status"),
               "baseline_same_cutoff":round(base,3),"v9_same_cutoff":v9,"features":f}
            for group in ("core","expanded"):
                value,genuine=predict_shadow(base,fits[(p,group)],f,group)
                a[group]=round(value,3)
                a[group+"_genuine"]=genuine
            entries.append(a)
    return {"status":"UNVALIDATED_SPECIAL_TEAMS_SHADOW","model_version":VERSION,
            "week":w,"as_of":baseline["as_of"],"completed_through_week":cutoff,
            "forecast_cutoff_lag_weeks":w-1-cutoff,
            "models":{p:{g:fits[(p,g)] for g in ("core","expanded")} for p in POSITIONS},
            "players":sorted(entries,key=lambda r:(r["position"],-r["core"],r["player_id"])),
            "scoring_rules_exported":bool(snapshot.get("Scoring_Rules")),
            "promotion_eligible":False,"applied_to_primary_model":False,
            "limitations":["Mean-only candidate; no transaction or lineup recommendation.",
                           "Uses exact observed fantasy points, not verified component scoring reconstruction.",
                           "Free-agent kickers may lack own scoring history; roles and availability unverified.",
                           "No verified weather, personnel, fumble or return-TD probability."]}
