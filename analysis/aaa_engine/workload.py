"""AAA v6: transparent, opportunity-based *shadow* projections.

Independent nflverse weekly stats are used for opportunity, not ESPN fantasy
projections. These outputs are unvalidated and never replace the v5 baseline.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import re
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from .engine import (current_players, date, historical, history_index, locked_roster,
                     optimize, predict, PRIOR, team_key)

URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv.gz"
METRICS = ("carries", "targets", "receptions", "rushing_yards", "receiving_yards",
           "rushing_tds", "receiving_tds", "attempts", "passing_yards",
           "passing_tds", "interceptions", "rushing_fumbles_lost",
           "receiving_fumbles_lost", "sack_fumbles_lost")
NEEDED = {"player_display_name", "recent_team", "position", "week", "season",
          "season_type", *METRICS}
POS = {"QB", "RB", "WR", "TE"}


def clean_name(value):
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return s


def number(v):
    try:
        z = float(v)
        return z if math.isfinite(z) else 0.
    except (ValueError, TypeError):
        return 0.


def parse_feed(raw, season):
    if isinstance(raw, bytes):
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    missing = NEEDED - set(reader.fieldnames or ())
    if missing:
        raise ValueError("Missing required nflverse columns: " + ", ".join(sorted(missing)))
    result = []
    for r in reader:
        if str(r["season"]) != str(season) or r["season_type"] not in ("REG", "2"):
            continue
        if not (1 <= int(r["week"]) <= 18):
            continue
        pos = r["position"].upper()
        if pos not in POS:
            continue
        result.append({
            "name": r["player_display_name"], "name_key": clean_name(r["player_display_name"]),
            "team": team_key(r["recent_team"]), "pos": pos, "week": int(r["week"]),
            **{k: number(r[k]) for k in METRICS},
        })
    if not result:
        raise ValueError("No regular-season NFL player observations from nflverse")
    return result


def download(season, as_of, timeout=35):
    uri = URL.format(season=season)
    req = urllib.request.Request(uri, headers={
        "User-Agent": "AAA-Fantasy-Workload/1.0", "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = res.read(12_000_000 + 1)
    if len(data) > 12_000_000:
        raise ValueError("nflverse feed exceeds allowed size")
    return parse_feed(data, season), {
        "url": uri, "fetched_at_utc": as_of,
        "sha256": hashlib.sha256(data).hexdigest(),
        "licence": "nflverse CC BY 4.0",
    }


def lookup(rows, name, team, pos, through_week):
    matches = [r for r in rows if r["name_key"] == clean_name(name)
               and r["pos"] == pos and r["week"] <= through_week]
    if not matches:
        return [], "no_verified_name_match"
    teams = {r["team"] for r in matches}
    if team_key(team) in teams:
        selected = [r for r in matches if r["team"] == team_key(team)]
        return sorted(selected, key=lambda x: x["week"]), None
    # A single team mismatch might be an NFL trade or altered ESPN abbreviation.
    # Never silently join records for a different team.
    return [], "nfl_team_not_matched"


def expected(rows, pos, current_week, through_week):
    """Lagged opportunities and smoothed per-opportunity efficiencies.

    The 55/45 recent/season blend and prior rates are provisional assumptions,
    not trained or validated coefficients.
    """
    rows = sorted(rows, key=lambda r: r["week"])
    latest = rows[-3:]
    recent_weight = .55 if len(rows) >= 4 else .35

    def volume(key):
        all_avg = sum(x[key] for x in rows) / len(rows)
        last_avg = sum(x[key] for x in latest) / len(latest)
        return recent_weight * last_avg + (1 - recent_weight) * all_avg

    def rate(success, denom, prior, strength):
        x = sum(r[success] for r in rows)
        n = sum(r[denom] for r in rows)
        return (x + prior * strength) / (n + strength)

    carries = max(0., volume("carries"))
    targets = max(0., volume("targets"))
    attempts = max(0., volume("attempts")) if pos == "QB" else 0.
    catch_rate = rate("receptions", "targets", {"RB": .75, "WR": .63, "TE": .68, "QB": .65}[pos], 12)
    receptions = targets * min(1., catch_rate)
    yards_per_carry = max(0., rate("rushing_yards", "carries", 4.2, 30))
    yards_per_target = max(0., rate("receiving_yards", "targets", 7.0, 25))
    rush_yards = carries * yards_per_carry
    rec_yards = targets * yards_per_target
    rush_tds = carries * max(0., rate("rushing_tds", "carries", .025, 40))
    rec_tds = targets * max(0., rate("receiving_tds", "targets", .045, 35))
    pass_yards = attempts * max(0., rate("passing_yards", "attempts", 6.9, 80))
    pass_tds = attempts * max(0., rate("passing_tds", "attempts", .042, 100))
    ints = attempts * max(0., rate("interceptions", "attempts", .022, 120))
    fumbles = (carries + targets + attempts) * max(0., (
        sum(r["rushing_fumbles_lost"] + r["receiving_fumbles_lost"] +
            r["sack_fumbles_lost"] for r in rows) + .007 * 75) /
        (sum(r["carries"] + r["targets"] + r["attempts"] for r in rows) + 75))
    points = (receptions + (rush_yards + rec_yards) / 10 +
              6 * (rush_tds + rec_tds) + pass_yards / 25 +
              4 * pass_tds - 2 * (ints + fumbles))
    flags = []
    if len(rows) < 3:
        flags.append("less_than_three_observed_games")
    if rows[-1]["week"] < through_week:
        flags.append("missed_most_recent_completed_week_role_unverified")
    if rows[-1]["week"] < through_week - 1:
        flags.append("long_absence_role_unverified")
    # These intervals are explicitly heuristics; no calibrated coverage claims.
    sd = {"QB": 8., "RB": 7., "WR": 7., "TE": 5.}[pos]
    if len(rows) > 1:
        actual_points = [r["receptions"] + (r["rushing_yards"] +
                         r["receiving_yards"]) / 10 +
                         6 * (r["rushing_tds"] + r["receiving_tds"]) +
                         r["passing_yards"] / 25 + 4 * r["passing_tds"] -
                         2 * r["interceptions"] for r in rows]
        mu = sum(actual_points) / len(actual_points)
        sd = max(sd, math.sqrt(sum((v-mu)**2 for v in actual_points)/len(actual_points)))
    return {
        "ppr_points": round(max(0., points), 2),
        "expected_carries": round(carries, 1), "expected_targets": round(targets, 1),
        "expected_receptions": round(receptions, 1),
        "expected_rushing_yards": round(rush_yards, 1),
        "expected_receiving_yards": round(rec_yards, 1),
        "expected_rushing_tds": round(rush_tds, 2),
        "expected_receiving_tds": round(rec_tds, 2),
        "expected_pass_attempts": round(attempts, 1),
        "expected_passing_yards": round(pass_yards, 1),
        "expected_passing_tds": round(pass_tds, 2),
        "expected_interceptions": round(ints, 2),
        "interval_80_heuristic": [round(max(0, points - 1.28*sd), 1),
                                  round(max(0, points + 1.28*sd), 1)],
        "observed_weeks": [r["week"] for r in rows],
        "latest_observed_week": rows[-1]["week"],
        "role_flags": flags,
        "method": "UNVALIDATED_nflverse_opportunity_rate_shrinkage",
    }


def evaluate(snapshot, stats, cfg, cutoff):
    """Paired, time-ordered diagnostics. No in-sample coefficient fitting."""
    comparisons = []
    by_week = defaultdict(dict)
    for r in snapshot["Weekly_Lineups"]:
        week = int(r["week"])
        pid = int(r["player_id"])
        if 5 <= week <= cutoff:
            by_week[(week, pid)] = r
    for (week, pid), r in by_week.items():
        pos = str(r["position"]).upper()
        if pos not in POS or number(r.get("projected_points")) <= 0:
            continue
        series, why = lookup(stats, r["player"], r["pro_team"], pos, week-1)
        if not series:
            continue
        pred = expected(series, pos, week, week-1)["ppr_points"]
        from .engine import predict
        # Official engine's fixed shrinkage, on preceding completed ESPN weeks.
        idx = history_index(historical(snapshot, week-1))
        baseline = predict(pid, week, pos, idx, cfg["shrink"], cfg["recent"])
        actual = number(r["points"])
        comparisons.append((abs(pred-actual), abs(baseline-actual), week))
    n = len(comparisons)
    return {
        "weeks": list(range(5, cutoff+1)),
        "paired_observations": n,
        "workload_mae": round(sum(x[0] for x in comparisons)/n, 4) if n else None,
        "baseline_mae_same_players": round(sum(x[1] for x in comparisons)/n, 4) if n else None,
        "caveat": "Exploratory retrospective check, not a sealed independent holdout. "
                  "The 55/45 blend and rates have not been calibrated. "
                  "Roster-sampled games exclude undrafted players.",
    }


def make_report(snapshot, baseline, schedule, stats, provenance):
    week = int(baseline["week"])
    current_week = int(snapshot["League"][0]["current_week"])
    cutoff = min(current_week-1, week-1)
    as_of = baseline["as_of"]
    if cutoff < 1:
        raise ValueError("No completed weeks for opportunity forecast")
    unique_weeks = sorted({r["week"] for r in stats if r["week"] <= cutoff})
    if len(unique_weeks) < 3 or unique_weeks[-1] != cutoff:
        raise ValueError(f"nflverse feed stale/incomplete: latest={unique_weeks[-1] if unique_weeks else None}, requires week {cutoff}")
    teams = {}
    for t in snapshot["Teams"]:
        tid = int(t["team_id"])
        players = current_players(snapshot, tid, week)
        pool, locks, excluded = locked_roster(players, schedule["kickoffs"], as_of, week==current_week)
        old = baseline["all_rosters"][str(tid)] if str(tid) in baseline["all_rosters"] else baseline["all_rosters"][tid]
        means = {int(pid):float(score) for pid,score in old["player_means"].items()}
        player_rows = []
        workload_count = 0
        for p in pool:
            entry = {"id":p["pid"],"name":p["name"],"position":p["pos"],
                     "nfl_team":p["nfl_team"],"baseline":round(means[p["pid"]],2)}
            if p["pos"] in POS:
                observations, reason = lookup(stats,p["name"],p["nfl_team"],p["pos"],cutoff)
                if observations:
                    proj = expected(observations,p["pos"],week,cutoff)
                    means[p["pid"]] = proj["ppr_points"]
                    entry["workload"] = proj
                    entry["method"] = "OPPORTUNITY"
                    workload_count += 1
                else:
                    entry["method"] = "BASELINE_FALLBACK_MISSING_OPPORTUNITY_DATA"
                    entry["reason"] = reason
            else:
                entry["method"] = "BASELINE_ONLY_NO_WORKLOAD_MODEL"
            player_rows.append(entry)

        # A player whose game is finished is immutable. Use the ESPN points, not
        # another predicted value, whenever the kickoff is at least 8 hours past.
        completed_scores = {}
        if week == current_week:
            lineups = {(int(r["team_id"]),int(r["player_id"])):r
                       for r in snapshot["Weekly_Lineups"] if int(r["week"])==week}
            for slot,pid in locks.items():
                p = next(x for x in pool if x["pid"]==pid)
                kickoff=date(schedule["kickoffs"][p["nfl_team"]])
                if date(as_of) - kickoff >= timedelta(hours=8):
                    score = lineups.get((tid,pid),{}).get("points")
                    if score in (None,""):
                        raise ValueError(f"Missing completed game score for {p['name']}")
                    means[pid] = number(score)
                    completed_scores[str(pid)] = means[pid]
        try:
            optimal=optimize(pool,means,locks)
            status="UNVALIDATED_WORKLOAD_SHADOW"
        except ValueError as error:
            optimal=None
            status="BLOCKED_INCOMPLETE_LINEUP: "+str(error)
        teams[str(tid)]={
            "name":t["team_name"],"status":status,"best":optimal,
            "locked_actual_scores":completed_scores,
            "workload_players":workload_count,"eligible_players":len(pool),
            "baseline_fallbacks":[r["name"] for r in player_rows if r["method"].startswith("BASELINE_FALLBACK")],
            "player_projections":player_rows,"excluded":excluded
        }
    return {
        "status":"UNVALIDATED_SHADOW__NOT_PRIMARY_CALIBRATED_FORECAST",
        "week":week,"as_of":as_of,"historical_cutoff_week":cutoff,
        "source":provenance,"source_weeks":unique_weeks,
        "baseline_snapshot_sha256":baseline.get("snapshot_sha256"),
        "methodology":"55% recent 3-game / 45% season opportunity average (35/65 with under 4 games); "
                      "Bayesian-smoothed yards, catches and TD rates. Missing roles use labelled baseline. "
                      "Injuries, snaps, routes, OL, opponent and weather NOT modelled.",
        "uncertainty":"80% intervals are heuristic, not calibrated. Do not treat shadow rank as certain. "
                      "No teammate-availability or workload-share override is made without sourced input.",
        "backtest":evaluate(snapshot,stats,baseline["calibration"],cutoff),
        "all_rosters":teams,"your_team":teams[str(baseline["your_team_id"])],
    }
