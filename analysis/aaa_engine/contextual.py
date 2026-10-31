"""Source-checked matchup context for AAA shadow forecasts (never calibrated).

No implied current-week data: only records with week < target week are used.
Opponent and offensive-line features are informational or explicitly experimental;
missing sources are reported, not filled with fabricated values.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import io
import json
import math
import urllib.request
from collections import defaultdict
from .engine import team_key
from .workload import clean_name, number, POS

SNAP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
            "snap_counts/snap_counts_{season}.csv.gz")


def _find(columns, options, required=True):
    choice = next((key for key in options if key in columns), None)
    if required and choice is None:
        raise ValueError("Required source column absent: " + "/".join(options))
    return choice


def parse_snaps(raw, season):
    if isinstance(raw, bytes):
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    columns = set(reader.fieldnames or [])
    name = _find(columns, ("player", "player_name", "player_display_name"))
    team = _find(columns, ("team", "recent_team"))
    week = _find(columns, ("week",))
    pct = _find(columns, ("offense_pct", "offense_snap_pct", "offense_percentage"))
    year = _find(columns, ("season",))
    result = []
    for r in reader:
        if str(r[year]) != str(season):
            continue
        try:
            w = int(r[week])
        except (TypeError, ValueError):
            continue
        value = number(str(r[pct]).strip().rstrip("%"))
        if not (0 <= value <= 100):
            continue
        if value > 1:
            value /= 100
        if not (1 <= w <= 18 and r[name]):
            continue
        result.append({"name_key": clean_name(r[name]), "name": r[name],
                       "team": team_key(r[team]), "week": w,
                       "offensive_snap_fraction": value})
    if not result:
        raise ValueError("No valid NFL offensive snap observations")
    return result


def download_snaps(season, as_of, timeout=35):
    url = SNAP_URL.format(season=season)
    req = urllib.request.Request(url, headers={"User-Agent": "AAA-Forecast/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(9_000_001)
    if len(raw) > 9_000_000:
        raise ValueError("Snap feed exceeded size limit")
    return parse_snaps(raw, season), {
        "uri": url, "retrieved_at_utc": as_of,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "licence": "nflverse CC BY 4.0"
    }


def snap_summary(snaps, player_name, nfl_team, cutoff):
    series = sorted([r for r in snaps if r["name_key"] == clean_name(player_name)
                     and r["team"] == team_key(nfl_team)
                     and r["week"] <= cutoff], key=lambda r:r["week"])
    if not series:
        return {"status": "NO_MATCH", "applied_to_mean": False}
    tail = series[-3:]
    season_avg = sum(r["offensive_snap_fraction"] for r in series)/len(series)
    recent_avg = sum(r["offensive_snap_fraction"] for r in tail)/len(tail)
    delta = recent_avg-season_avg
    return {
        "status":"OBSERVED_SNAP_SHARE", "weeks":[r["week"] for r in series],
        "season_average_pct":round(100*season_avg,1),
        "recent_three_game_pct":round(100*recent_avg,1),
        "change_percentage_points":round(100*delta,1),
        "applied_to_mean": False,
        "note":"Snap-share trend only; do not double-count volume changes already reflected in carries and targets."
    }


def allowed_context(stats, player_team, opponent, pos, cutoff):
    """Historical fantasy points allowed to each opponent's whole position group.

    An opponent value is provided only with >=3 distinct completed opponents.
    This is NOT opponent-adjusted forecast accuracy or a DVOA equivalent.
    """
    if not opponent:
        return {"status":"OPPONENT_NOT_IN_VERIFIED_SCHEDULE"}
    pts = defaultdict(float)
    for r in stats:
        if r["week"] > cutoff or r["pos"] != pos or not r.get("opponent"):
            continue
        if r["team"] == r["opponent"]:
            continue
        ppr = (r["receptions"] + (r["rushing_yards"]+r["receiving_yards"])/10
               + 6*(r["rushing_tds"]+r["receiving_tds"])
               + r["passing_yards"]/25 + 4*r["passing_tds"]
               - 2*r["interceptions"])
        pts[(r["opponent"],r["week"])] += max(0,ppr)
    by_defense = defaultdict(list)
    for (defense,week), total in pts.items():
        by_defense[defense].append(total)
    values = by_defense.get(team_key(opponent),[])
    if len(values) < 3:
        return {"status":"INSUFFICIENT_OPPONENT_GAMES",
                "games_observed":len(values)}
    league = [v for scores in by_defense.values() for v in scores]
    opponent_mean = sum(values)/len(values)
    league_mean = sum(league)/len(league) if league else 0
    return {"status":"HISTORICAL_POSITION_ALLOWED",
            "opponent":team_key(opponent),"position":pos,
            "games_observed":len(values),
            "position_group_ppr_allowed":round(opponent_mean,2),
            "league_group_ppr_average":round(league_mean,2),
            "applied_to_mean":False,
            "note":"Opponent fantasy points allowed are descriptive, noisy and not adjusted for opposing skill."}


def verified_opponents(schedule):
    mapping = {}
    for game in schedule.get("games",[]):
        pair = [team_key(x) for x in game.get("teams",[])]
        if len(pair) != 2 or pair[0] == pair[1]:
            raise ValueError("Invalid verified NFL matchup")
        if pair[0] in mapping or pair[1] in mapping:
            raise ValueError("Duplicate verified NFL opponent")
        mapping[pair[0]] = pair[1]
        mapping[pair[1]] = pair[0]
    if len(mapping) != len(schedule.get("kickoffs",{})):
        raise ValueError("Incomplete NFL opponent schedule")
    return mapping


def teammate_context(context, player_team, as_of):
    """Accept strictly sourced manual reports, but do not infer availability."""
    result = []
    for r in context.get("verified_teammate_updates",[]):
        if team_key(r.get("nfl_team","")) != team_key(player_team):
            continue
        if (not r.get("name") or not r.get("status") or not r.get("source_url")
                or not str(r["source_url"]).startswith("https://")
                or not r.get("as_of")):
            raise ValueError("Every teammate update needs name, status, HTTPS source and as_of")
        from .engine import date
        if date(r["as_of"]) > date(as_of):
            raise ValueError("Teammate update comes from the future")
        result.append({"name":r["name"], "status":r["status"],
                       "source_url":r["source_url"],"as_of":r["as_of"],
                       "applied_to_mean":False})
    return result


def contextualize(report, stats, snaps, schedule, source, context=None):
    """Enrich v6 report without changing underlying projected points or lineup."""
    context = context or {}
    cutoff = int(report["historical_cutoff_week"])
    opponents = verified_opponents(schedule)
    for team in report["all_rosters"].values():
        for r in team["player_projections"]:
            nfl_team = r["nfl_team"]
            r["matchup_context"] = {
                "snap_share":(snap_summary(snaps,r["name"],nfl_team,cutoff)
                              if snaps is not None else {"status":"SNAP_SOURCE_UNAVAILABLE"}),
                "opponent":allowed_context(stats,nfl_team,opponents.get(nfl_team),
                                            r["position"],cutoff)
                            if r["position"] in POS else {"status":"NOT_MODELED_POSITION"},
                "verified_teammate_updates":teammate_context(context,nfl_team,report["as_of"]),
                "routes_run":{"status":"NO_VERIFIED_ROUTE_FEED"},
                "offensive_line":{"status":"NO_VERIFIED_LINE_METRIC"},
                "official_gameday_inactives":{"status":"NOT_YET_VERIFIED"}
            }
    report["your_team"] = report["all_rosters"][str(report.get("your_team_id",1))]
    report["context_source"] = source
    report["context_status"] = "OBSERVED_ONLY_NO_UNVALIDATED_CONTEXT_MULTIPLIERS"
    report["context_note"] = (
        "Updated snap shares, opposing positional allowance and manually sourced teammate "
        "reports are visible, but do not automatically override expected points. "
        "Route, OL and inactive data remain missing rather than guessed.")
    return report
