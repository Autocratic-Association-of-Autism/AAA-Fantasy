"""AAA v9 game-environment features from completed NFL play-by-play.

This is a source-backed matchup SCOUTING layer and an explicitly unvalidated
scenario scorer for every roster position. No self-reported film grades, fantasy
projections, betting lines, scheme labels or speculative injury status are
silently promoted to facts. No target-week games enter the feature aggregates.

Coverage man/zone, DB-on-WR assignments, true OL win rates, weather and
official gameday inactives are not inferred from standard nflverse PBP.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import io
import math
import urllib.request
from collections import defaultdict

from .engine import team_key

PBP_URL=("https://github.com/nflverse/nflverse-data/releases/download/"
         "pbp/play_by_play_{season}.csv.gz")
NEEDED={"season","week","posteam","defteam","pass_attempt","rush_attempt",
        "sack","epa"}
KEYS=("plays","passes","runs","dropbacks","sacks","qb_hits",
      "pass_epa","run_epa","redzone_plays","air_yards","air_count",
      "targets_short","targets_deep","third_down","third_converted",
      "fg_attempts","fg_made","turnovers","pass_tds","rush_tds",
      "yards_after_catch","yac_count")
CONTEXT_MIN_GAMES=3


def num(value):
    try:
        x=float(value)
        return x if math.isfinite(x) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _true(raw):
    return str(raw).strip().lower() in ("1","1.0","true","t","yes")


def parse_pbp(raw, season, cutoff):
    """Parse bounded, compressed nflverse play by play without game leakage.

    Return per-week team offense and defense aggregations rather than all rows.
    If source lacks an optional statistic, report missing rather than zero.
    """
    if isinstance(raw, bytes):
        if raw[:2]==b"\x1f\x8b":
            raw=gzip.decompress(raw)
        raw=raw.decode("utf-8-sig")
    table=csv.DictReader(io.StringIO(raw))
    fields=set(table.fieldnames or [])
    missing=NEEDED-fields
    if missing:
        raise ValueError("NFL PBP missing required columns: "+", ".join(sorted(missing)))
    offense=defaultdict(lambda:defaultdict(float))
    defense=defaultdict(lambda:defaultdict(float))
    opponents={}
    optional={
        "qb_hit":"qb_hit" in fields,
        "air_yards":"air_yards" in fields,
        "yards_after_catch":"yards_after_catch" in fields,
        "red_zone":"yardline_100" in fields,
        "fg_kicks":"field_goal_attempt" in fields or "field_goal_result" in fields,
        "interceptions":"interception" in fields,
        "passing_tds":"pass_touchdown" in fields,
        "rushing_tds":"rush_touchdown" in fields,
        "third_down":"down" in fields and "first_down" in fields,
        "true_coverage_man_zone":False,
        "true_offensive_line_win_rate":False,
        "verified_weather":False
    }
    total=0
    for r in table:
        if str(r.get("season")) != str(season):
            continue
        if r.get("season_type") and str(r["season_type"]).upper() not in ("REG","2"):
            continue
        try:w=int(r["week"])
        except (TypeError, ValueError):continue
        if w<1 or w>int(cutoff):
            continue
        off=team_key(r.get("posteam") or "")
        d=team_key(r.get("defteam") or "")
        if not off or not d or off==d or len(off)>4 or len(d)>4:
            continue
        previous=opponents.setdefault((w,off),d)
        if previous!=d:
            raise ValueError("Inconsistent NFL opponent in PBP source")
        fg=_true(r.get("field_goal_attempt")) or str(r.get("play_type")).lower()=="field_goal"
        if fg:
            for item in (offense[(w,off)],defense[(w,d)]):
                item["fg_attempts"]+=1
                if str(r.get("field_goal_result") or "").lower()=="made":
                    item["fg_made"]+=1
            continue
        pa=_true(r.get("pass_attempt"))
        ru=_true(r.get("rush_attempt"))
        sack=_true(r.get("sack"))
        if not (pa or ru or sack):
            continue
        epa=num(r.get("epa"))
        for agg in (offense[(w,off)],defense[(w,d)]):
            agg["plays"]+=1
            if pa or sack:
                agg["passes"]+=1
                agg["dropbacks"]+=1
                agg["pass_epa"]+=epa
            if ru and not sack:
                agg["runs"]+=1
                agg["run_epa"]+=epa
            if sack:
                agg["sacks"]+=1
            if optional["qb_hit"] and _true(r.get("qb_hit")):
                agg["qb_hits"]+=1
            if optional["red_zone"] and 0<num(r.get("yardline_100"))<=20:
                agg["redzone_plays"]+=1
            if optional["interceptions"] and _true(r.get("interception")):
                agg["turnovers"]+=1
            if optional["passing_tds"] and _true(r.get("pass_touchdown")):
                agg["pass_tds"]+=1
            if optional["rushing_tds"] and _true(r.get("rush_touchdown")):
                agg["rush_tds"]+=1
            if optional["third_down"] and str(r.get("down")) in ("3","3.0"):
                agg["third_down"]+=1
                if _true(r.get("first_down")) or _true(r.get("touchdown")):
                    agg["third_converted"]+=1
            if (pa or sack) and not sack:
                if optional["air_yards"] and r.get("air_yards") not in ("",None,"NA"):
                    air=num(r["air_yards"])
                    agg["air_yards"]+=air
                    agg["air_count"]+=1
                    if air>=15:agg["targets_deep"]+=1
                    else:agg["targets_short"]+=1
                if optional["yards_after_catch"] and r.get("yards_after_catch") not in ("",None,"NA"):
                    agg["yards_after_catch"]+=num(r["yards_after_catch"])
                    agg["yac_count"]+=1
        total+=1
    if total<200:
        raise ValueError("Too few completed-season play-by-play observations")
    def finalize(source):
        records={}
        for (week,team),x in source.items():
            values={key:round(float(x.get(key,0)),4) for key in KEYS}
            records[(week,team)]=values
        return records
    return {"offense":finalize(offense),
            "defense":finalize(defense),
            "opponents":opponents,
            "source_capabilities":optional,
            "included_through_week":int(cutoff),
            "eligible_scrimmage_plays":total,
            "season":int(season)}


def download_pbp(season,cutoff,as_of,timeout=60):
    url=PBP_URL.format(season=season)
    req=urllib.request.Request(url,headers={
        "User-Agent":"AAA-Game-Environment/1.0","Accept":"application/octet-stream"})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        raw=resp.read(48_000_001)
    if len(raw)>48_000_000:
        raise ValueError("PBP compressed source exceeds 48 MB")
    parsed=parse_pbp(raw,season,cutoff)
    source={"url":url,"sha256":hashlib.sha256(raw).hexdigest(),
            "retrieved_at_utc":as_of,"licence":"nflverse CC BY 4.0",
            "season":int(season),"included_through_week":int(cutoff),
            "eligible_scrimmage_plays":parsed["eligible_scrimmage_plays"]}
    return parsed,source


def summarize(team_records,cutoff):
    rows=[r for (w,_),r in team_records.items() if w<=cutoff]
    if not rows:
        return {}
    n=len(rows)
    total=lambda key:sum(r[key] for r in rows)
    count=lambda key:total(key)/n
    dropbacks=total("dropbacks")
    runs=total("runs")
    plays=total("plays")
    return {"games":n,
            "plays_per_game":round(count("plays"),2),
            "pass_rate":round(dropbacks/plays,4) if plays else None,
            "passes_per_game":round(count("passes"),2),
            "rushes_per_game":round(count("runs"),2),
            "pass_epa_per_dropback":round(total("pass_epa")/dropbacks,4) if dropbacks else None,
            "rush_epa_per_carry":round(total("run_epa")/runs,4) if runs else None,
            "sack_rate":round(total("sacks")/dropbacks,4) if dropbacks else None,
            "qb_hit_rate":round(total("qb_hits")/dropbacks,4) if dropbacks else None,
            "redzone_plays_per_game":round(count("redzone_plays"),2),
            "fg_attempts_per_game":round(count("fg_attempts"),2),
            "fg_made_per_game":round(count("fg_made"),2),
            "turnovers_per_game":round(count("turnovers"),2),
            "pass_tds_per_game":round(count("pass_tds"),2),
            "rush_tds_per_game":round(count("rush_tds"),2),
            "air_yards_per_attempt":round(total("air_yards")/total("air_count"),2)
                if total("air_count") else None,
            "deep_target_rate":round(total("targets_deep")/total("air_count"),4)
                if total("air_count") else None,
            "yac_per_recorded_play":round(total("yards_after_catch")/total("yac_count"),2)
                if total("yac_count") else None,
            "third_down_conversion":round(total("third_converted")/total("third_down"),4)
                if total("third_down") else None,
           }


def _team_stats(source,side,team,cutoff):
    relevant={(w,t):r for (w,t),r in source[side].items()
              if t==team_key(team) and w<=cutoff}
    return summarize(relevant,cutoff)


def _league_stats(source,side,cutoff):
    return summarize({k:v for k,v in source[side].items()
                      if k[0]<=cutoff},cutoff)


def _factor(value,reference,low=.85,high=1.15):
    if value is None or reference is None or reference<=0:
        return 1.
    return min(high,max(low,value/reference))


def preview(pbp, team, opponent, cutoff):
    """Record observable opposing units and a modest unvalidated game plan."""
    team=team_key(team)
    opponent=team_key(opponent)
    own=_team_stats(pbp,"offense",team,cutoff)
    defense=_team_stats(pbp,"defense",opponent,cutoff)
    rival=_team_stats(pbp,"offense",opponent,cutoff)
    defending=_team_stats(pbp,"defense",team,cutoff)
    league_off=_league_stats(pbp,"offense",cutoff)
    league_def=_league_stats(pbp,"defense",cutoff)
    if min(own.get("games",0),defense.get("games",0),
           rival.get("games",0),defending.get("games",0))<CONTEXT_MIN_GAMES:
        return {"status":"INSUFFICIENT_VERIFIED_GAMES",
                "own_games":own.get("games",0),
                "defense_games":defense.get("games",0),
                "applied_to_primary_model":False}
    # EPA is an observed offense-versus-opponent marker, NOT a calibrated
    # estimate of game total. Do not fabricate point totals or betting odds.
    expected_plays=(own["plays_per_game"]+defense["plays_per_game"])/2
    expected_dropbacks=(own["passes_per_game"]+defense["passes_per_game"])/2
    expected_runs=(own["rushes_per_game"]+defense["rushes_per_game"])/2
    pace=_factor(expected_plays,league_off.get("plays_per_game"),.86,1.14)
    passes=_factor(expected_dropbacks,league_off.get("passes_per_game"),.80,1.20)
    rushes=_factor(expected_runs,league_off.get("rushes_per_game"),.80,1.20)
    own_pressure=own.get("sack_rate")
    defense_pressure=defense.get("sack_rate")
    league_pressure=league_off.get("sack_rate")
    # Sacks are a multi-cause proxy, not offensive line win rate or a
    # separately identified defensive line talent grade.
    combined_pressure=(own_pressure+defense_pressure)/2 if (
        own_pressure is not None and defense_pressure is not None) else None
    sack_ratio=_factor(combined_pressure,league_pressure,.70,1.30)
    own_pass_epa=own.get("pass_epa_per_dropback")
    def_pass_epa=defense.get("pass_epa_per_dropback")
    own_run_epa=own.get("rush_epa_per_carry")
    def_run_epa=defense.get("rush_epa_per_carry")
    league_pass_epa=league_off.get("pass_epa_per_dropback")
    league_run_epa=league_off.get("rush_epa_per_carry")
    # Additive EPA deviations are bounded and uncalibrated; they are only
    # diagnostics. Do not promote without retrospective and prospective wins.
    pass_epa_edge=round(((own_pass_epa or 0)+(def_pass_epa or 0))/2
                        -(league_pass_epa or 0),3)
    run_epa_edge=round(((own_run_epa or 0)+(def_run_epa or 0))/2
                       -(league_run_epa or 0),3)
    rz=(own["redzone_plays_per_game"]+defense["redzone_plays_per_game"])/2
    kick=(own["fg_attempts_per_game"]+defense["fg_attempts_per_game"])/2
    # Rival offense drives scoring and expected defensive opportunity, but
    # these aggregate indicators cannot be mapped to a betting total.
    return {
        "status":"OBSERVED_MATCHUP_WITH_UNVALIDATED_VOLUME_SCENARIOS",
        "nfl_team":team,"opponent":opponent,
        "completed_through_week":cutoff,
        "offense":own,"opponent_defense":defense,
        "opponent_offense":rival,"own_defense":defending,
        "league_reference":league_off,
        "expected_offensive_plays_proxy":round(expected_plays,2),
        "expected_dropbacks_proxy":round(expected_dropbacks,2),
        "expected_rushes_proxy":round(expected_runs,2),
        "pass_volume_factor_shadow":round(passes,4),
        "rush_volume_factor_shadow":round(rushes,4),
        "pace_factor_shadow":round(pace,4),
        "sack_matchup_ratio":round(sack_ratio,4),
        "pass_epa_matchup_edge":pass_epa_edge,
        "rush_epa_matchup_edge":run_epa_edge,
        "redzone_plays_proxy":round(rz,2),
        "fg_attempts_proxy":round(kick,2),
        "game_script":{
            "opponent_offense_pass_epa":rival.get("pass_epa_per_dropback"),
            "own_defense_pass_epa_allowed":defending.get("pass_epa_per_dropback"),
            "opponent_pass_rate":rival.get("pass_rate"),
            "opponent_passes_per_game":rival.get("passes_per_game"),
            "score_or_spread":"NOT_MODELED_INDEPENDENTLY",
            "projected_game_total":"NOT_VERIFIED_OR_CALIBRATED"},
        "coverage":{"man_zone":"NOT_VERIFIED_IN_STANDARD_PBP",
                    "receiver_corner_assignments":"NOT_VERIFIED",
                    "safety_or_linebacker_assignments":"NOT_VERIFIED"},
        "trenches":{"offensive_line_vs_defensive_front":
                     "OBSERVED_SACK_RATE_PROXY_NOT_TRUE_BLOCKING_GRADE",
                    "offense_sacks_allowed_per_dropback":own_pressure,
                    "opponent_sack_rate_forced":defense_pressure,
                    "offense_qb_hit_rate":own.get("qb_hit_rate"),
                    "opponent_qb_hit_rate":defense.get("qb_hit_rate"),
                    "true_pass_block_win_rate":"NOT_VERIFIED"},
        "team_receiving_profile":{
            "avg_air_yards_per_attempt":own.get("air_yards_per_attempt"),
            "deep_target_rate":own.get("deep_target_rate"),
            "yac_per_recorded_play":own.get("yac_per_recorded_play"),
            "note":"Team trends only; not actual player-on-defender coverage"},
        "observed_injuries":"SEE_SEPARATELY_SOURCED_WEEKLY_INJURY_REPORT",
        "weather":"NO_VERIFIED_STADIUM_SPECIFIC_FORECAST",
        "rivalry_factor":"NOT_CALIBRATED",
        "applied_to_primary_model":False,
        "note":"All numerical factors below are candidate volume scenarios only, not point-forecast validation.",
    }


def scenario_points(position,base,workload,match):
    """Vary opportunities only; preserve original scoring for evaluation.

    This is transparent sensitivity, not a promoted forecast. K/DST use
    bounded illustrative scoring offsets rather than fictional usage models.
    """
    if match.get("status")!="OBSERVED_MATCHUP_WITH_UNVALIDATED_VOLUME_SCENARIOS":
        return {"status":"NO_VERIFIED_GAME_ENVIRONMENT","point_estimate":None,
                "applied_to_primary_model":False}
    p=position
    pass_factor=match["pass_volume_factor_shadow"]
    rush_factor=match["rush_volume_factor_shadow"]
    pressure=match["sack_matchup_ratio"]
    if p in ("QB","RB","WR","TE"):
        if not workload or workload.get("ppr_points") is None:
            return {"status":"NO_VERIFIED_PLAYER_OPPORTUNITY",
                    "point_estimate":None,"applied_to_primary_model":False}
        value=float(workload["ppr_points"])
        if p=="QB":
            # Attempts, passing yards, passing TDs, and interceptions move
            # together with volume. Sack proxy changes passing efficiency by
            # at most 4%; never infer guaranteed sacks or protection grades.
            pass_points=(workload["expected_passing_yards"]/25+
                        4*workload["expected_passing_tds"]-
                        2*workload["expected_interceptions"])
            value+=pass_points*(pass_factor-1)
            value-=max(0,pressure-1)*min(4.,pass_points*.12)
        else:
            carry_points=(workload["expected_rushing_yards"]/10+
                          6*workload["expected_rushing_tds"])
            receive_points=(workload["expected_receptions"]+
                            workload["expected_receiving_yards"]/10+
                            6*workload["expected_receiving_tds"])
            value+=carry_points*(rush_factor-1)
            value+=receive_points*(pass_factor-1)
        value=max(0.,value)
        return {"status":"HEURISTIC_VOLUME_SCENARIO_UNVALIDATED",
                "point_estimate":round(value,2),
                "original_workload":workload["ppr_points"],
                "position":p,
                "passing_opportunity_factor":pass_factor,
                "rushing_opportunity_factor":rush_factor,
                "applied_to_primary_model":False}
    if p=="D/ST":
        # No unsupported 'turnover prediction': a sensitivity centered on
        # defensive sack and opponent offensive efficiency indicators.
        opponent=match["opponent_offense"]
        defense=match["own_defense"]
        t=opponent.get("turnovers_per_game") or 0
        s=defense.get("sack_rate") or 0
        league_s=match["league_reference"].get("sack_rate") or .06
        delta=max(-2.5,min(2.5,2*(t-1.0)+10*(s-league_s)))
        return {"status":"ILLUSTRATIVE_DST_PRESSURE_TURNOVER_SCENARIO",
                "point_estimate":round(max(-5.,float(base)+delta),2),
                "baseline":float(base),"scenario_delta":round(delta,2),
                "applied_to_primary_model":False}
    if p=="K":
        # Historical opponent field-goal opportunities, not guaranteed kicker
        # attempts. Kickers' outcomes remain driven by drive finish rates.
        league_fg=match["league_reference"].get("fg_attempts_per_game") or 1.6
        delta=max(-2.,min(2.,(match["fg_attempts_proxy"]-league_fg)*2.))
        return {"status":"ILLUSTRATIVE_KICK_OPPORTUNITY_SCENARIO",
                "point_estimate":round(max(0.,float(base)+delta),2),
                "baseline":float(base),"scenario_delta":round(delta,2),
                "applied_to_primary_model":False}
    return {"status":"UNSUPPORTED_POSITION",
            "point_estimate":None,"applied_to_primary_model":False}


def build(report,pbp,schedule,snapshot,injuries=None):
    """All player position previews plus legal, locked, SHADOW lineup comparisons."""
    from .contextual import verified_opponents
    from .engine import current_players,locked_roster,optimize
    from .injury_context import team_injuries
    opponent=verified_opponents(schedule)
    cutoff=int(report["historical_cutoff_week"])
    cache={t:preview(pbp,t,opp,cutoff) for t,opp in opponent.items()}
    if injuries is not None:
        for team,opp in opponent.items():
            cache[team]["week_specific_injury_reports"]={
                "source":"nflverse weekly reports, not official inactive list",
                "own_team_all_positions":team_injuries(injuries,team,report["week"],report["as_of"]),
                "opponent_team_all_positions":team_injuries(injuries,opp,report["week"],report["as_of"]),
                "status":"OBSERVED_NOT_POSITION_CLASSIFIED_OR_POINTS_ADJUSTED",
                "note":"Injury feed includes players from both offensive and defensive units; no source-backed position classification."}
    else:
        for match in cache.values():
            match["week_specific_injury_reports"]={"status":"SOURCE_UNAVAILABLE"}
    observed_weeks={w for (w,t) in pbp["offense"]}
    if not observed_weeks or max(observed_weeks)!=cutoff:
        raise ValueError("PBP feed stale; required completed week "+str(cutoff))
    report["game_environment"]={
        "status":"SOURCE_BACKED_SCOUTING_AND_UNVALIDATED_SCENARIOS",
        "observed_through_week":cutoff,
        "source_capabilities":pbp["source_capabilities"],
        "position_coverage":["QB","RB","WR","TE","D/ST","K"],
        "matchups":cache,
        "primary_model_changed":False
    }
    for tid_text,team in report["all_rosters"].items():
        for player in team["player_projections"]:
            match=cache.get(player["nfl_team"],
                {"status":"BYE_OR_MATCHUP_UNAVAILABLE"})
            player["game_environment"]=match
            player["position_game_script_scenario"]=scenario_points(
                player["position"],player["baseline"],
                player.get("workload"),match)
        # Game-environment score changes are NEVER copied into the primary
        # forecast. Shadow optimization obeys the same locked roster positions
        # and original already-final scores.
        members=current_players(snapshot,int(tid_text),int(report["week"]))
        pool,locks,excluded=locked_roster(
            members,schedule["kickoffs"],report["as_of"],
            int(report["week"])==int(snapshot["League"][0]["current_week"]))
        scenario={p["id"]:float(p["position_game_script_scenario"].get("point_estimate")
                   if p["position_game_script_scenario"].get("point_estimate") is not None
                   else (p.get("workload") or {}).get("ppr_points",p["baseline"]))
                  for p in team["player_projections"]}
        for pid_text,points in team.get("locked_actual_scores",{}).items():
            scenario[int(pid_text)]=float(points)
        try:
            result=optimize(pool,scenario,locks)
            existing=team.get("best") or {}
            previous=set(existing.get("lineup",{}).values())
            proposed=set(result["lineup"].values())
            team["game_environment_shadow_best"]={
                "status":"UNVALIDATED_SCENARIO_ONLY_NOT_PRIMARY",
                **result,
                "changed_player_ids":sorted(proposed-previous),
                "replaced_player_ids":sorted(previous-proposed),
                "note":"Never auto-start players from this scenario until independent test improves decision regret"}
        except (ValueError,KeyError) as exc:
            team["game_environment_shadow_best"]={
                "status":"BLOCKED_NO_LEGAL_SCENARIO","reason":str(exc)}
    return report
