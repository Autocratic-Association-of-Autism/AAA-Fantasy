"""NFLverse injury reports and strictly sourced route observations.

This module annotates the workload shadow output. Neither player/team injury
reports nor route counts receive unvalidated scoring multipliers. Missing rows
do not imply HEALTHY, and source publication timestamps are preserved.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import urllib.request
from collections import defaultdict

from .engine import date, team_key
from .workload import clean_name, number

INJURY_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
              "injuries/injuries_{season}.csv.gz")
# The published 2026 release currently omits 'date_modified', despite the
# documented historical dictionary containing it. Missing record timestamps
# must be exposed as UNVERIFIED, never filled with guessed times.
REQUIRED = {"season", "season_type", "week", "team", "full_name",
            "report_status", "practice_status"}
STATUS = {"out": "OUT", "doubtful": "DOUBTFUL",
          "questionable": "QUESTIONABLE", "probable": "PROBABLE"}


def _read_csv(raw):
    if isinstance(raw, bytes):
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        raw = raw.decode("utf-8-sig")
    return csv.DictReader(io.StringIO(raw))


def parse_injuries(raw, season):
    reader = _read_csv(raw)
    missing = REQUIRED - set(reader.fieldnames or [])
    if missing:
        raise ValueError("Missing injury columns: " + ", ".join(sorted(missing)))
    rows = []
    for row in reader:
        if str(row["season"]) != str(season):
            continue
        if str(row["season_type"]).upper() not in ("REG", "2"):
            continue
        try:
            week = int(row["week"])
        except (TypeError, ValueError):
            continue
        if not (1 <= week <= 18):
            continue
        if not row.get("full_name") or not row.get("team"):
            continue
        label = (row.get("report_status") or "").strip()
        # Blank means no designation *on a filed report*, not clearance.
        rows.append({
            "week": week, "name": row["full_name"],
            "name_key": clean_name(row["full_name"]),
            "team": team_key(row["team"]),
            "report_status": STATUS.get(label.lower(), label.upper() or "NO_GAME_DESIGNATION_REPORTED"),
            "practice_status": (row.get("practice_status") or "NOT_REPORTED").strip(),
            "primary_injury": (row.get("report_primary_injury") or "").strip(),
            "date_modified": (row.get("date_modified") or "").strip(),
        })
    if not rows:
        raise ValueError("No current-season regular-season injury observations")
    return rows


def download_injuries(season, fetched_at, timeout=25):
    url = INJURY_URL.format(season=season)
    req = urllib.request.Request(url, headers={
        "User-Agent":"AAA-Forecast/1.0", "Accept":"application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(6_000_001)
    if len(raw) > 6_000_000:
        raise ValueError("NFL injury feed exceeds 6 MB compressed")
    return parse_injuries(raw,season),{
        "uri":url,"fetched_at_utc":fetched_at,
        "sha256":hashlib.sha256(raw).hexdigest(),
        "license":"nflverse CC BY 4.0",
        "kind":"reported weekly NFL injury/practice designation; not official inactive list"
    }


def _safe_modified(raw):
    """Recognize only unambiguous timezone-aware timestamps."""
    if not raw:
        return None
    try:
        return date(raw)
    except (TypeError, ValueError, AttributeError):
        return None


def injury_match(rows, name, team, week, as_of):
    """Status is UNKNOWN unless a current-week, nonfuture report matches."""
    target = clean_name(name)
    now = date(as_of)
    all_matches = [r for r in rows
                   if r["week"] == int(week)
                   and r["team"] == team_key(team)
                   and r["name_key"] == target]
    valid = []
    for r in all_matches:
        parsed = _safe_modified(r["date_modified"])
        if parsed and parsed > now:
            continue
        valid.append((parsed, r))
    if not valid:
        return {"status":"NOT_ON_CURRENT_WEEK_REPORT",
                "reported":False,"not_necessarily_healthy":True}
    # Prefer most recently modified, preserving an uncertain timestamp label.
    valid.sort(key=lambda pair: (pair[0] is not None,
                                 pair[0].isoformat() if pair[0] else ""))
    modified, r = valid[-1]
    return {
        "status":"CURRENT_WEEK_REPORT",
        "reported":True,
        "game_status":r["report_status"],
        "practice_status":r["practice_status"],
        "primary_injury":r["primary_injury"],
        "record_updated":r["date_modified"] or None,
        "record_timestamp_verified":modified is not None,
        "not_an_official_inactive_confirmation":True,
    }


def team_injuries(rows, team, week, as_of):
    latest={}
    for r in rows:
        if r["week"] != int(week) or team_key(team) != r["team"]:
            continue
        modified=_safe_modified(r["date_modified"])
        if modified and modified > date(as_of):
            continue
        key=r["name_key"]
        before=latest.get(key)
        if before is None or ((modified is not None,modified.isoformat() if modified else "")
                              > before[0]):
            latest[key]=((modified is not None,modified.isoformat() if modified else ""),r)
    result=[]
    for _,r in latest.values():
        if r["report_status"] in ("OUT","DOUBTFUL","QUESTIONABLE"):
            result.append({"name":r["name"],"game_status":r["report_status"],
                           "position_not_verified":True,"primary_injury":r["primary_injury"]})
    return sorted(result,key=lambda v:v["name"])


def route_report(context, player, team, cutoff, as_of):
    """No route count without a dated licensed/sourced observation.

    Supports manually supplied charting exported from a licensed service.
    Every report is informational only, never a fabricated opportunity change.
    """
    candidates=[]
    for item in context.get("verified_route_reports",[]):
        required={"name","nfl_team","week","routes_run","team_dropbacks",
                  "source_url","as_of"}
        if not required.issubset(item):
            raise ValueError("Route report must contain: "+", ".join(sorted(required)))
        if not str(item["source_url"]).startswith("https://"):
            raise ValueError("Route report requires an HTTPS source URL")
        observed=date(item["as_of"])
        if observed > date(as_of):
            raise ValueError("Route report comes from the future")
        week=int(item["week"])
        routes=float(item["routes_run"])
        total=float(item["team_dropbacks"])
        if week >= int(cutoff)+1 or week < 1:
            raise ValueError("Route report must cover only prior completed weeks")
        if not (total > 0 and 0 <= routes <= total):
            raise ValueError("Invalid routes run or team dropbacks")
        if (clean_name(item["name"])==clean_name(player)
                and team_key(item["nfl_team"]) == team_key(team)):
            candidates.append((week,observed,item,routes,total))
    if not candidates:
        return {"status":"NO_VERIFIED_IN_SEASON_ROUTE_FEED",
                "applied_to_mean":False,
                "note":"nflverse participation data is not released during the current season."}
    week,observed,item,routes,total=max(candidates,key=lambda x:(x[0],x[1]))
    return {"status":"SOURCED_HISTORICAL_ROUTE_COUNT",
            "week":week,"routes_run":int(routes),
            "team_dropbacks":int(total),
            "routes_per_team_dropback":round(routes/total,3),
            "source_url":item["source_url"],
            "as_of":item["as_of"],"applied_to_mean":False,
            "note":"Charted participation is informational and not a calibrated multiplier."}


def enrich(report, injury_rows, source, context=None):
    """Enrich all 10 rosters without altering score or lineup decisions."""
    context=context or {}
    week=int(report["week"])
    as_of=report["as_of"]
    cutoff=int(report["historical_cutoff_week"])
    for team in report["all_rosters"].values():
        for player in team["player_projections"]:
            nfl_team=player["nfl_team"]
            injury=injury_match(injury_rows,player["name"],nfl_team,week,as_of)
            player.setdefault("matchup_context",{})["injury_report"]=injury
            player["matchup_context"]["route_participation"]=route_report(
                context,player["name"],nfl_team,cutoff,as_of)
            espn_status=player.get("injury_status_from_espn")
            if (injury.get("game_status") == "OUT"
                and espn_status not in ("OUT","IR","INJURY_RESERVE")):
                player["injury_status_conflict"]=True
                team["requires_official_inactive_review"]=True
            player["matchup_context"]["same_team_reported_injuries"]=team_injuries(
                injury_rows,nfl_team,week,as_of)
    report["injury_source"]=source
    report["injury_context_status"]="OBSERVED_WEEKLY_REPORTS_NO_SCORE_MULTIPLIERS"
    report["your_team"]=report["all_rosters"][str(report["your_team_id"])]
    return report
