"""Integrated audit: matched objectives and frozen comparison inputs.

No automatic promotion. Blend weights are fixed before future outcomes,
but designed after Week 11, so prior replays remain exploratory.
"""
from collections import defaultdict
from .engine import date, position, team_key, optimize, PRIOR

VERSION="integrated-audit-1.0-shadow"
BLENDS=("blend_baseline_v2","blend_baseline_volume")

def capture_espn(snapshot,forecast,schedule):
    """Archive target-week recorded projections only while game unstarted.
    Never treat future-week roster projection as target-week ESPN projection.
    """
    league=snapshot["League"][0];w=int(forecast["week"])
    ts=date(league["exported_utc"]);now=date(forecast["as_of"])
    if int(league["current_week"])!=w or int(league["scoring_period_id"])!=w:
        return {"status":"BLOCKED_ESPN_TARGET_WEEK_MISMATCH","week":w}
    if ts>now or int(schedule["week"])!=w or not schedule.get("complete"):
        return {"status":"BLOCKED_ESPN_TIMESTAMP_OR_SCHEDULE","week":w}
    rows=[];seen=set()
    for r in snapshot["Weekly_Lineups"]:
        if int(r["week"])!=w or position(r["position"]) not in PRIOR or r["lineup_slot"]=="IR":
            continue
        nfl=team_key(r["pro_team"]);kick=schedule["kickoffs"].get(nfl)
        if not kick or ts>=date(kick) or now>=date(kick):continue
        try:
            p=float(r["projected_points"])
        except (ValueError,TypeError):continue
        if p<=0:continue
        key=(int(r["team_id"]),int(r["player_id"]))
        if key in seen:raise ValueError("Duplicate archived ESPN player")
        seen.add(key)
        rows.append({"team_id":key[0],"player_id":key[1],"position":position(r["position"]),
                     "nfl_team":nfl,"projected_points":p,"kickoff_utc":kick,
                     "slot":r["lineup_slot"]})
    return {"status":"PREGAME_EXPORT_PROJECTIONS_CAPTURED" if rows else "NO_ELIGIBLE_PREGAME_PROJECTIONS",
            "week":w,"exported_utc":league["exported_utc"],"forecast_as_of":forecast["as_of"],
            "snapshot_sha256":forecast.get("snapshot_sha256"),"schedule_sha256":forecast.get("schedule_sha256"),
            "players":rows,"limitations":["Export timestamp is observation time, not ESPN internal projection issuance timestamp.",
                                            "For prospective comparison verify artifact/run completion before kickoff."]}

def blend_forecast(forecast,v2,gf,schedule):
    w=int(forecast["week"]);ts=date(forecast["as_of"])
    if any(date(v)<=ts for v in schedule["kickoffs"].values()):
        return {"status":"BLOCKED_BLEND_AFTER_KICKOFF","week":w}
    if (v2.get("status")!="UNVALIDATED_OPPORTUNITY_V2_SHADOW" or
        gf.get("status")!="UNVALIDATED_GAME_FIRST_SHADOW" or
        v2.get("week")!=w or gf.get("week")!=w or
        v2.get("as_of")!=forecast["as_of"] or gf.get("as_of")!=forecast["as_of"] or
        int(v2.get("historical_cutoff_week",-1))!=w-1 or
        int(gf.get("completed_through_week",-1))!=w-1):
        return {"status":"BLOCKED_BLEND_SOURCE_MISMATCH","week":w}
    result={}
    for tid,r in forecast["all_rosters"].items():
        key=str(tid)
        a=v2["all_rosters"].get(key,{})
        b=gf["all_rosters"].get(key,{})
        v={int(p["id"]):p for p in a.get("players",[])}
        g={int(p["pid"]):p for p in b.get("players",[])}
        base={int(pid):float(x) for pid,x in r["player_means"].items()}
        if set(base)!=set(v) or set(base)!=set(g):
            result[key]={"status":"BLOCKED_BLEND_POOL_MISMATCH"};continue
        rows=[];pool=[]
        for pid,x in base.items():
            p=v[pid];q=g[pid];components=q.get("components") or {}
            if p["position"]!=q["position"] or p["nfl_team"]!=q["nfl_team"]:
                raise ValueError("Inconsistent shadow player identity")
            pool.append({"pid":pid,"pos":p["position"]})
            a_val=float(p["v2_ppr_or_fallback"])
            b_val=float(components.get("game_volume",p["workload_v6_ppr"]))
            rows.append({"pid":pid,"name":p["name"],"position":p["position"],
                         "nfl_team":p["nfl_team"],"baseline":x,
                         "blend_baseline_v2":.5*(x+a_val),"blend_baseline_volume":.5*(x+b_val),
                         "v2_genuine":(p.get("v2") or {}).get("status")=="EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED",
                         "volume_genuine":"game_volume" in components})
        choices={}
        for m in BLENDS:
            try:choices[m]=optimize(pool,{p["pid"]:p[m] for p in rows})
            except ValueError:choices[m]=None
        result[key]={"status":"PREGAME_BLEND_SHADOW","players":rows,"choices":choices}
    return {"status":"UNVALIDATED_FIXED_BLEND_SHADOW","week":w,"as_of":forecast["as_of"],
            "all_rosters":result,"weights":{"baseline":.5,"challenger":.5},
            "promotion_eligible":False,"note":"Equal-weight fixed blends; all historical comparisons exploratory."}

def audit(forecast,gf,prospective,participation,special,distribution,win,manager,transaction,season):
    """Preserve metric cohorts; avoid comparing incompatible samples."""
    methods={}
    for m,e in gf.get("all",{}).get("point_error",{}).items():
        methods[m]={"point":e,"matchup_margin":gf.get("matchup_margin_error",{}).get(m),
                    "lineup_regret":gf.get("mean_lineup_regret",{}).get(m),
                    "wins_vs_actual":gf.get("wins_vs_actual_opponent",{}).get(m)}
    reports={"game_first":gf,"prospective":prospective,"participation":participation,"special_teams":special,
             "distribution":distribution,"win":win,"manager":manager,"transaction":transaction,"season":season}
    return {"status":"INTEGRATED_AUDIT_NO_AUTOMATIC_PROMOTION","model_version":VERSION,
            "week":forecast["week"],"as_of":forecast["as_of"],"snapshot_sha256":forecast.get("snapshot_sha256"),
            "production_model":"v5-lagged-ppr-control","promotion_eligible":False,
            "report_status":{k:r.get("status","MISSING") for k,r in reports.items()},
            "matched_game_first_methods":methods,"matched_game_first_weeks":gf.get("weeks_tested"),
            "legal_team_weeks":gf.get("legal_team_weeks"),
            "espn_recorded_unverified":gf.get("all",{}).get("espn_comparable_unverified"),
            "prospective":{k:prospective.get(k) for k in ("status","week","source_run_id","paired_players","baseline_mae","workload_mae","v2_paired_players","v2_paired_baseline_mae","v2_mae")},
            "genuine_participation":participation.get("genuine_adjustment_comparison"),
            "special_teams_genuine":{p:v.get("matched_genuine") for p,v in special.get("positions",{}).items()},
            "distribution":distribution.get("player_results"),
            "fixed_matchup_brier":win.get("fixed_submitted_lineup_brier"),
            "win_objectives":win.get("decision_summary"),
            "manager_genuine":manager.get("lineups",{}).get("genuine_manager"),
            "transaction_replay":transaction.get("summary"),"season_replay":{k:season.get(k) for k in ("n","wins_mae","points_mae")},
            "policy":{"production":"retain baseline","lineup_challenger":"v2","matchup_challenger":"game_volume",
                      "distribution_control":"position","kicker_challenger":"expanded",
                      "promotion_requires":"Frozen pregame evidence across future weeks and comparable cohorts; no post-hoc retrospective winner promotion."},
            "limitations":["Different objectives and cohorts must not be combined into a single rank.",
                           "Historical ESPN projections remain unverified unless archived before kickoff.",
                           "Retrospective roster choice sets and fallback estimates may bias results.",
                           "New blends are fixed 50/50 and will be scored prospectively only after archival." ]}
