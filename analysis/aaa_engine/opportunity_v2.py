"""Opportunity Model v2: experimental team-volume -> player-share -> PPR model.

All features for target week W use NFL weeks strictly less than W. This module
does not change the v5 baseline or v6 workload forecasts. Parameters are
hypotheses to test on untouched future weeks, NOT calibrated coefficients.
"""
from __future__ import annotations

from collections import defaultdict
from .engine import (current_players, history_index, historical, locked_roster,
                     optimize, position, predict, PRIOR, team_key)
from .workload import expected, lookup

SKILL = {"QB", "RB", "WR", "TE"}
RECENCY = .73
PRIOR_GAMES = 3.


def _value(row, metric):
    if metric == "attempts":
        return max(0., row["passes"] - row["sacks"])
    return max(0., row[metric])


def _games(pbp, side, team, cutoff):
    return sorted(((w, r) for (w, t), r in pbp[side].items()
                   if t == team_key(team) and w <= cutoff), key=lambda x: x[0])


def _recent_mean(games, metric):
    if not games:
        return None
    latest = games[-5:]
    weights = [RECENCY ** (len(latest) - 1 - i) for i in range(len(latest))]
    return sum(_value(r, metric) * weight for (_, r), weight
               in zip(latest, weights)) / sum(weights)


def _league_mean(pbp, metric, cutoff):
    records = [(w, r) for (w, _), r in pbp["offense"].items() if w <= cutoff]
    return sum(_value(r, metric) for _, r in records) / len(records) if records else None


def team_volume(pbp, team, opponent, target_week):
    """Opponent-adjusted pass/rush counts, with small-history league shrinkage.

    PBP 'passes' includes sacks, so subtract sacks before estimating NFL pass
    attempts/receiver targets. This is a shadow estimate, not a betting total.
    """
    cutoff = target_week - 1
    if cutoff > int(pbp["included_through_week"]):
        return {"status": "BLOCKED_STALE_PBP"}
    own = _games(pbp, "offense", team, cutoff)
    allowed = _games(pbp, "defense", opponent, cutoff)
    if len(own) < 3 or len(allowed) < 3:
        return {"status": "INSUFFICIENT_PRIOR_TEAM_GAMES",
                "own_games": len(own), "opponent_defense_games": len(allowed)}
    output = {"status": "EXPERIMENTAL_TEAM_VOLUME",
              "team": team_key(team), "opponent": team_key(opponent),
              "historical_cutoff_week": cutoff,
              "own_games": len(own), "opponent_defense_games": len(allowed)}
    for metric, label in (("attempts", "pass_attempts"), ("runs", "rush_attempts"),
                          ("redzone_plays", "redzone_plays"),
                          ("pass_tds", "passing_tds"), ("rush_tds", "rushing_tds")):
        ref = _league_mean(pbp, metric, cutoff)
        if ref is None:
            return {"status": "BLOCKED_NO_LEAGUE_REFERENCE"}
        offense = _recent_mean(own, metric)
        defense = _recent_mean(allowed, metric)
        # Add three league-average pseudo games to either observed sample.
        o = (len(own) * offense + PRIOR_GAMES * ref) / (len(own) + PRIOR_GAMES)
        d = (len(allowed) * defense + PRIOR_GAMES * ref) / (len(allowed) + PRIOR_GAMES)
        estimate = .65 * o + .35 * d
        # Avoid overfitting to a defense's small sample of unusually fast games.
        output[label] = round(max(0., min(1.30 * ref, max(.70 * ref, estimate))), 3)
    output["method"] = "65/35 offense/opponent; recency .73; 3 pseudo-games; league bounds 70-130% (all uncalibrated)"
    return output


def player_share(stats, pbp, name, team, pos, metric, target_week):
    """Target, rush, or QB-attempt share from whole-team completed game totals.

    Only observed player games enter conditional workload shares. Missing
    player weeks carry an explicit availability caveat rather than zero share.
    Sustained new roles receive more recent weight.
    No stats from the game being predicted may affect the share.
    """
    cutoff = target_week - 1
    if metric not in ("targets", "carries", "attempts"):
        raise ValueError("Unsupported share metric")
    if cutoff > int(pbp["included_through_week"]):
        return {"status": "BLOCKED_STALE_PBP"}
    player_rows, reason = lookup(stats, name, team, pos, cutoff)
    if not player_rows:
        return {"status": "NO_PLAYER_HISTORY", "reason": reason}
    team_games = _games(pbp, "offense", team, cutoff)
    if len(team_games) < 3:
        return {"status": "INSUFFICIENT_TEAM_HISTORY"}
    player_by_week = {int(r["week"]): r for r in player_rows}
    denominator_metric = "attempts" if metric in ("targets", "attempts") else "runs"
    rows = []
    # This is a conditional-on-participation workload forecast, not an
    # injury-risk forecast. Zeroes BEFORE debut and MISSING games after debut
    # must not silently dilute the player's share of team opportunities.
    # Missing current availability is reported separately for review.
    skipped_games = []
    for w, team_row in team_games:
        if w not in player_by_week:
            skipped_games.append(w)
            continue
        denom = _value(team_row, denominator_metric)
        if denom <= 0:
            continue
        numer = max(0., player_by_week[w].get(metric, 0.))
        rows.append((w, numer, denom))
    if len(rows) < 3:
        return {"status": "INSUFFICIENT_OBSERVED_PLAYER_GAMES",
                "player_games": len(rows)}
    share = lambda seq: (sum(x[1] for x in seq) / sum(x[2] for x in seq)
                         if seq and sum(x[2] for x in seq) else 0.)
    full = share(rows)
    recent = share(rows[-3:])
    old = share(rows[:-3]) if len(rows) > 3 else full
    recent_two = rows[-2:]
    strong_up = (len(rows) >= 5 and old > 0
                 and recent >= 1.35 * old
                 and all(x[1] / x[2] >= 1.15 * old for x in recent_two))
    strong_down = (len(rows) >= 5 and old > 0
                   and recent <= .65 * old
                   and all(x[1] / x[2] <= .85 * old for x in recent_two))
    # For short histories, avoid labeling one game as a confirmed role change.
    weight = .72 if (strong_up or strong_down) else (.45 if len(rows) >= 5 else .25)
    calculated = weight * recent + (1. - weight) * full
    ceiling = {"targets": .48, "carries": .90, "attempts": 1.}[metric]
    first_observed_week = min(player_by_week)
    before_debut = [w for w in skipped_games if w < first_observed_week]
    after_debut_gap = [w for w in skipped_games if w >= first_observed_week]
    result = {
        "status": "SHARE_ESTIMATED_UNVALIDATED",
        "share": round(min(ceiling, max(0., calculated)), 5),
        "season_share": round(full, 5),
        "recent_three_share": round(recent, 5),
        "recent_weight": weight,
        "role_change_detected": bool(strong_up or strong_down),
        "player_observed_weeks": [x["week"] for x in player_rows],
        "team_games_used": [x[0] for x in rows],
        "team_games_without_player_row": skipped_games,
        "pre_debut_team_games": before_debut,
        "missing_rows_since_debut": after_debut_gap,
        "conditional_on_participation": True,
        "historical_cutoff_week": cutoff,
    }
    if player_rows[-1]["week"] < cutoff:
        result["availability_caveat"] = "LAST_COMPLETED_GAME_MISSING_PLAYER_ROW"
    elif after_debut_gap:
        result["availability_caveat"] = "MISSED_PRIOR_TEAM_GAMES_ROLE_AND_HEALTH_REQUIRE_REVIEW"
    if before_debut:
        result["history_caveat"] = "RECENT_DEBUT_OR_NEW_ROLE_PREGAME_STATUS_UNVERIFIED"
    return result


def player_projection(stats, pbp, name, team, opponent, pos, target_week, volume=None):
    """Explicit PPR component conversion, preserving the existing v6 rates."""
    if pos not in SKILL:
        return {"status": "POSITION_NOT_SUPPORTED"}
    volume = volume or team_volume(pbp, team, opponent, target_week)
    if volume.get("status") != "EXPERIMENTAL_TEAM_VOLUME":
        return {"status": "BLOCKED_TEAM_VOLUME", "reason": volume.get("status")}
    cutoff = target_week - 1
    hist, reason = lookup(stats, name, team, pos, cutoff)
    if not hist:
        return {"status": "NO_PLAYER_HISTORY", "reason": reason}
    legacy = expected(hist, pos, target_week, cutoff)
    needed = ("targets", "carries", "attempts") if pos == "QB" else ("targets", "carries")
    shares = {k: player_share(stats, pbp, name, team, pos, k, target_week) for k in needed}
    if any(s["status"] != "SHARE_ESTIMATED_UNVALIDATED" for s in shares.values()):
        return {"status": "BLOCKED_PLAYER_SHARE", "shares": shares}
    targets = volume["pass_attempts"] * shares["targets"]["share"]
    carries = volume["rush_attempts"] * shares["carries"]["share"]
    attempts = (volume["pass_attempts"] * shares["attempts"]["share"]
                if pos == "QB" else 0.)
    old_t = legacy["expected_targets"]
    old_c = legacy["expected_carries"]
    old_a = legacy["expected_pass_attempts"]
    # The v6 Bayesian-smoothed conditional rates form this phase's conversion
    # baseline. New per-route, red-zone-player rates require separate evidence.
    rate = lambda outcome, denominator: (legacy[outcome] / denominator if denominator > 0 else 0.)
    rec = targets * rate("expected_receptions", old_t)
    r_yards = targets * rate("expected_receiving_yards", old_t)
    u_yards = carries * rate("expected_rushing_yards", old_c)
    rec_td = targets * rate("expected_receiving_tds", old_t)
    rush_td = carries * rate("expected_rushing_tds", old_c)
    pass_yards = attempts * rate("expected_passing_yards", old_a)
    pass_tds = attempts * rate("expected_passing_tds", old_a)
    ints = attempts * rate("expected_interceptions", old_a)
    exposure = targets + carries + attempts
    total_opps = sum(r["targets"] + r["carries"] + r["attempts"] for r in hist)
    lost = sum(r["rushing_fumbles_lost"] + r["receiving_fumbles_lost"] +
               r["sack_fumbles_lost"] for r in hist)
    fumble_rate = (lost + .007 * 75) / (total_opps + 75)
    fumbles = exposure * fumble_rate
    points = max(0., rec + .1 * (r_yards + u_yards) +
                  6. * (rec_td + rush_td) + pass_yards / 25 +
                  4. * pass_tds - 2. * (ints + fumbles))
    return {
        "status": "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED",
        "ppr_points": round(points, 3),
        "expected_targets": round(targets, 2),
        "expected_carries": round(carries, 2),
        "expected_pass_attempts": round(attempts, 2),
        "expected_receptions": round(rec, 2),
        "expected_receiving_yards": round(r_yards, 2),
        "expected_rushing_yards": round(u_yards, 2),
        "expected_receiving_tds": round(rec_td, 3),
        "expected_rushing_tds": round(rush_td, 3),
        "expected_passing_yards": round(pass_yards, 2),
        "expected_passing_tds": round(pass_tds, 3),
        "expected_interceptions": round(ints, 3),
        "expected_lost_fumbles": round(fumbles, 3),
        "shares": shares,
        "team_volume": volume,
        "underlying_v6_ppr": legacy["ppr_points"],
        "model_note": "New team opportunity/share estimate; existing v6 smoothed conversion rates; player-specific red-zone data not yet verified",
    }


def forecast_feature_cutoff(week, workload, pbp):
    """Use the explicitly available completed-week cutoff, never fake freshness."""
    cutoff = min(int(week)-1, int(workload["historical_cutoff_week"]),
                 int(pbp["included_through_week"]))
    if cutoff < 1 or not any(w == cutoff for w, _ in pbp["offense"]):
        raise ValueError("No verified PBP observations at v2 feature cutoff")
    return cutoff


def forecast_report(snapshot, baseline, workload, stats, pbp, schedule):
    """New standalone artifact; existing baseline/v6 outputs remain unchanged."""
    from .contextual import verified_opponents
    week = int(workload["week"])
    current = int(snapshot["League"][0]["current_week"])
    cutoff = forecast_feature_cutoff(week, workload, pbp)
    feature_week = cutoff + 1
    opponents = verified_opponents(schedule)
    groups = {}
    projected = 0
    team_cache = {team: team_volume(pbp, team, opp, feature_week)
                  for team, opp in opponents.items()}
    for tid_text, old in workload["all_rosters"].items():
        tid = int(tid_text)
        pool, locks, excluded = locked_roster(
            current_players(snapshot, tid, week),
            schedule["kickoffs"], workload["as_of"], week == current)
        previous = {int(p["id"]): p for p in old["player_projections"]}
        means = {}
        details = []
        for member in pool:
            pid = member["pid"]
            row = previous.get(pid)
            if not row:
                raise ValueError("v2 roster and v6 pool disagree: " + str(pid))
            old_score = (row.get("workload") or {}).get("ppr_points", row["baseline"])
            projected_score = float(old_score)
            projection = None
            if row["position"] in SKILL:
                opp = opponents.get(row["nfl_team"])
                if opp:
                    projection = player_projection(
                        stats, pbp, row["name"], row["nfl_team"], opp,
                        row["position"], feature_week, team_cache[row["nfl_team"]])
                else:
                    projection = {"status": "NO_VERIFIED_MATCHUP"}
                if projection["status"] == "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED":
                    projected_score = projection["ppr_points"]
                    projected += 1
            if str(pid) in old.get("locked_actual_scores", {}):
                projected_score = float(old["locked_actual_scores"][str(pid)])
            means[pid] = projected_score
            details.append({
                "id": pid, "name": row["name"], "position": row["position"],
                "nfl_team": row["nfl_team"], "baseline_ppr": row["baseline"],
                "workload_v6_ppr": old_score,
                "v2_ppr_or_fallback": round(projected_score, 3),
                "v2": projection,
                "locked_actual": str(pid) in old.get("locked_actual_scores", {}),
            })
        try:
            line = optimize(pool, means, locks)
            status = "UNVALIDATED_V2_LINEUP_SHADOW"
        except ValueError as e:
            line = None
            status = "BLOCKED_INCOMPLETE_LINEUP: " + str(e)
        groups[str(tid)] = {
            "name": old["name"], "status": status, "best_shadow": line,
            "players": details, "excluded": excluded,
        }
    return {
        "status": "UNVALIDATED_OPPORTUNITY_V2_SHADOW",
        "week": week, "as_of": workload["as_of"],
        "historical_cutoff_week": cutoff,
        "forecast_cutoff_lag_weeks": week - 1 - cutoff,
        "model_version": "opportunity-v2-cutoff-explicit",
        "modeled_players": projected,
        "applied_to_primary_model": False,
        "source_provenance": {"player_stats": workload.get("source"),
                              "pbp": workload.get("game_environment", {}).get("source")},
        "team_volumes": team_cache,
        "your_team_id": baseline["your_team_id"],
        "all_rosters": groups,
        "methodology": "Opponent-aware play count + dynamic target/carry/attempt shares + v6 efficiency/TD smoothing. Unvalidated.",
        "known_gaps": ["No player-level red-zone opportunities", "No verified routes or pass-block win rates",
                       "No official gameday inactive probabilities", "No separately calibrated win distributions"],
    }


def retrospective(snapshot, stats, pbp, shrink, recent, first_week=5, last_week=None):
    """Paired, strictly lagged exploratory point and lineup comparisons."""
    end = min(int(snapshot["League"][0]["current_week"]) - 1,
              int(pbp["included_through_week"]), int(last_week or 99))
    if first_week < 5:
        raise ValueError("Backtest starts after baseline hyperparameter selection Weeks 2-4")
    if end < first_week:
        return {"status": "PENDING_NOT_ENOUGH_COMPLETED_WEEKS"}
    idx = history_index(historical(snapshot, end))
    grouped = defaultdict(list)
    for row in snapshot["Weekly_Lineups"]:
        w = int(row["week"])
        if first_week <= w <= end:
            grouped[(w, int(row["team_id"]))].append(row)
    paired = []
    lineups = []
    excluded = []
    positions = defaultdict(list)
    cache = {}
    for (week, fantasy_team), rows in sorted(grouped.items()):
        means = {"baseline": {}, "v6": {}, "v2": {}, "actual": {}}
        pool = []
        for row in rows:
            if row["lineup_slot"] == "IR" or float(row.get("projected_points") or 0) <= 0:
                continue
            pos = position(row["position"])
            if pos not in PRIOR:
                continue
            pid = int(row["player_id"])
            nfl_team = team_key(row["pro_team"])
            base = float(predict(pid, week, pos, idx, shrink, recent))
            v6 = base
            v2 = None
            if pos in SKILL:
                history, _ = lookup(stats, row["player"], nfl_team, pos, week - 1)
                if history:
                    v6 = expected(history, pos, week, week - 1)["ppr_points"]
                    opp = pbp["opponents"].get((week, nfl_team))
                    if opp:
                        key = (week, nfl_team, opp)
                        if key not in cache:
                            cache[key] = team_volume(pbp, nfl_team, opp, week)
                        pred = player_projection(stats, pbp, row["player"],
                                                 nfl_team, opp, pos, week, cache[key])
                        if pred["status"] == "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED":
                            v2 = pred["ppr_points"]
            actual = float(row["points"])
            means["actual"][pid] = actual
            means["baseline"][pid] = base
            means["v6"][pid] = v6
            means["v2"][pid] = v2 if v2 is not None else v6
            pool.append({"pid": pid, "pos": pos})
            if v2 is not None:
                result = {"week": week, "team": fantasy_team, "position": pos,
                          "baseline_abs_error": abs(base - actual),
                          "v6_abs_error": abs(v6 - actual),
                          "v2_abs_error": abs(v2 - actual)}
                paired.append(result)
                positions[pos].append(result)
        try:
            choices = {name: optimize(pool, values) for name, values in means.items()}
        except ValueError as e:
            excluded.append({"week": week, "team": fantasy_team, "reason": str(e)})
            continue
        score = lambda model: sum(means["actual"][pid] for pid in choices[model]["lineup"].values())
        ideal = score("actual")
        lineups.append({
            "week": week, "team": fantasy_team,
            **{name + "_regret": round(ideal - score(name), 3)
               for name in ("baseline", "v6", "v2")},
            "v2_minus_v6_actual_points": round(score("v2") - score("v6"), 3),
            "different_v2_starters": sorted(
                set(choices["v2"]["lineup"].values()) - set(choices["v6"]["lineup"].values())),
        })
    avg = lambda values: round(sum(values) / len(values), 4) if values else None
    bypos = lambda rows: {
        "observations": len(rows),
        **{name + "_mae": avg([r[name + "_abs_error"] for r in rows])
           for name in ("baseline", "v6", "v2")}}
    return {
        "status": "EXPLORATORY_WALK_FORWARD_NOT_PROSPECTIVE",
        "promotion_eligible": False, "weeks": list(range(first_week, end + 1)),
        "summary": {
            "paired_player_weeks": len(paired),
            "paired_all_positions": bypos(paired),
            "by_position": {p: bypos(items) for p, items in sorted(positions.items())},
            "legal_lineup_team_weeks": len(lineups),
            **{name + "_mean_lineup_regret": avg([r[name + "_regret"] for r in lineups])
               for name in ("baseline", "v6", "v2")},
            "v2_better_than_v6_lineup": sum(x["v2_minus_v6_actual_points"] > .001 for x in lineups),
            "v2_worse_than_v6_lineup": sum(x["v2_minus_v6_actual_points"] < -.001 for x in lineups),
            "v2_tied_v6_lineup": sum(abs(x["v2_minus_v6_actual_points"]) <= .001 for x in lineups),
        },
        "per_team_week": lineups, "excluded": excluded,
        "limitations": [
            "Final ESPN weekly rosters are not verified pre-kickoff availability.",
            "The v2 coefficients are proposed after completed games, not a sealed holdout.",
            "PBP week W is used for opponent identity only; every volume/share feature uses weeks < W.",
            "The conversion rates are reused from v6; red-zone scoring is not independently calibrated.",
            "All test lineups are hindsight roster optimizations, not genuine pregame decisions.",
        ],
    }
