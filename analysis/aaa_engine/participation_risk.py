"""Participation-risk 1.0 shadow: empirical workload after observed disruptions.

A gap in offensive participation is NOT an injury diagnosis. Historical
injury labels without pregame publication timestamps are not training inputs.
Only earlier observed games determine risk classes and cohort factors.
The model estimates workload conditional on positive offensive participation,
not availability probabilities, and never changes production projections.
"""
from collections import defaultdict, Counter
import numpy as np
from .engine import date, position, team_key, optimize, current_players, locked_roster
from .workload import clean_name, expected, POS
from .injury_context import injury_match

VERSION = "participation-risk-1.0-shadow"
METRICS = {"targets": "expected_targets", "carries": "expected_carries",
           "attempts": "expected_pass_attempts"}
MIN_CASES = 12
MIN_PLAYERS = 6
PRIOR_CASES = 20


def build_index(stats, snaps, pbp, cutoff):
    """Use only completed team games with actual snap-feed observations."""
    if not snaps or not stats:
        raise ValueError("Missing snap or player stat feed")
    if int(pbp["included_through_week"]) < cutoff:
        raise ValueError("PBP source cutoff is stale")
    scheduled = defaultdict(set)
    for (w, t) in pbp["offense"]:
        if w <= cutoff:
            scheduled[team_key(t)].add(w)
    covered = defaultdict(set)
    snap_index = defaultdict(dict)
    ambiguous = set()
    for r in snaps:
        w, t = int(r["week"]), team_key(r["team"])
        if w > cutoff or w not in scheduled[t]:
            continue
        f = float(r["offensive_snap_fraction"])
        if not 0 <= f <= 1:
            continue
        key = (t, r["name_key"])
        if w in snap_index[key]:
            ambiguous.add(key)
        snap_index[key][w] = f
        covered[(t, w)].add(r["name_key"])
    # A missing player row is interpretable as no observed offensive
    # participation only when the team's snap feed has substantial coverage.
    games = {t: sorted(w for w in weeks if len(covered[(t, w)]) >= 20)
             for t, weeks in scheduled.items()}
    histories = defaultdict(dict)
    for r in stats:
        w, t, pos = int(r["week"]), team_key(r["team"]), r["pos"]
        if w > cutoff or pos not in POS:
            continue
        key = (t, r["name_key"], pos)
        if w in histories[key]:
            ambiguous.add((t, r["name_key"]))
        histories[key][w] = r
    histories = {k: v for k, v in histories.items() if k[:2] not in ambiguous}
    snap_index = {k: v for k, v in snap_index.items() if k not in ambiguous}
    return {"games": games, "scheduled": dict(scheduled), "snaps": snap_index,
            "histories": histories, "cutoff": cutoff, "ambiguous_names": len(ambiguous)}


def risk_state(index, key, target):
    """Classify using only earlier team games; byes never count as missed."""
    t, name, pos = key
    prior = [w for w in index["games"].get(t, []) if w < target]
    scheduled = [w for w in index["scheduled"].get(t, []) if w < target]
    if len(prior) < 3 or not scheduled or max(scheduled) != prior[-1]:
        return {"class": "UNKNOWN", "reason": "Incomplete recent team snap coverage"}
    series = index["snaps"].get((t, name), {})
    # Positive snap observations establish a prior offensive role. A player
    # with no matched snap history is unknown, not inactive.
    observed = [(w, series[w]) for w in prior if series.get(w, 0.) > 0.]
    if len(observed) < 3:
        return {"class": "UNKNOWN", "reason": "Fewer than three observed positive-snap games"}
    last_week, last_fraction = observed[-1]
    missed = [w for w in prior if w > last_week]
    # Do not infer an absence across a team game with incomplete feed coverage.
    if any(w not in prior for w in scheduled if w > last_week):
        return {"class": "UNKNOWN", "reason": "Coverage gap since last observed participation"}
    previous = [f for _, f in observed[-4:-1]]
    reference = float(np.median(previous))
    if reference < .25:
        return {"class": "UNKNOWN", "reason": "No established prior offensive role"}
    if missed:
        category = "GAP_2_PLUS" if len(missed) >= 2 else "GAP_1"
    elif last_fraction <= .6 * reference:
        category = "RECENT_SNAP_DROP"
    else:
        category = "NORMAL_OBSERVED"
    return {"class": category, "last_observed_game": last_week,
            "missed_team_games": missed, "last_snap_fraction": round(last_fraction, 3),
            "reference_snap_fraction": round(reference, 3),
            "interpretation": "Observed participation proxy; cause unknown"}


def control(index, key, target):
    h = [r for w, r in sorted(index["histories"].get(key, {}).items()) if w < target]
    return expected(h, key[2], target, target - 1) if h else None


def cases(index):
    """Build historical conditional workload cases from observed positive snaps.

    A missing stat row is excluded, not silently interpreted as zero.
    Each case is labeled from information strictly before its own game.
    """
    rows = []
    for key, history in index["histories"].items():
        t, name, pos = key
        for w, r in sorted(history.items()):
            if w not in index["games"].get(t, []) or index["snaps"].get((t, name), {}).get(w, 0.) <= 0:
                continue
            risk = risk_state(index, key, w)
            if risk["class"] not in ("GAP_1", "GAP_2_PLUS", "RECENT_SNAP_DROP"):
                continue
            base = control(index, key, w)
            if base is None:
                continue
            rows.append({"key": key, "week": w, "class": risk["class"],
                         "position": pos,
                         "actual": {k: float(r[k]) for k in METRICS},
                         "control": {k: float(base[v]) for k, v in METRICS.items()}})
    return rows


def cohort_factors(rows, risk_class, pos, target, exclude_key=None):
    """Prior-only conditional estimates; shrink exposure-weighted ratios to 1."""
    selected = [r for r in rows if r["week"] < target and r["class"] == risk_class
                and r["position"] == pos and r["key"] != exclude_key]
    n, players = len(selected), len({r["key"] for r in selected})
    result = {"cases": n, "distinct_player_team_keys": players, "factors": {},
              "conditional_on_positive_offensive_snaps": True}
    if n < MIN_CASES or players < MIN_PLAYERS:
        return {**result, "status": "INSUFFICIENT_PRIOR_COHORT"}
    for k in METRICS:
        if k == "attempts" and pos != "QB":
            continue
        informative = [r for r in selected if r["control"][k] >= 1.]
        if len(informative) < MIN_CASES or len({r["key"] for r in informative}) < MIN_PLAYERS:
            continue
        exposure = sum(r["control"][k] for r in informative)
        actual = sum(r["actual"][k] for r in informative)
        prior = PRIOR_CASES * exposure / len(informative)
        raw = actual / exposure
        ratio = (actual + prior) / (exposure + prior)
        observed = [r["actual"][k] / r["control"][k] for r in informative]
        result["factors"][k] = {"factor": round(ratio, 4),
            "raw_ratio": round(raw, 4), "cases": len(informative),
            "observed_ratio_p20_p80": [round(float(x), 4) for x in np.quantile(observed, [.2, .8])]}
    return {**result, "status": "EXPERIMENTAL_CONDITIONAL_FACTOR" if result["factors"]
            else "INSUFFICIENT_METRIC_COHORT"}


def adjusted(base, cohort):
    """Change opportunities only; retain the identical v6 conversion rates."""
    f = {k: float(cohort.get("factors", {}).get(k, {}).get("factor", 1.)) for k in METRICS}
    receiving = (base["expected_receptions"] + .1 * base["expected_receiving_yards"]
                 + 6 * base["expected_receiving_tds"])
    rushing = .1 * base["expected_rushing_yards"] + 6 * base["expected_rushing_tds"]
    passing = .04 * base["expected_passing_yards"] + 4 * base["expected_passing_tds"] - 2 * base["expected_interceptions"]
    # v6's reported point estimate includes a fumble penalty and rounding.
    # Keep that residual unchanged to isolate the opportunity ablation.
    points = max(0., float(base["ppr_points"]) + receiving * (f["targets"] - 1.)
                 + rushing * (f["carries"] - 1.) + passing * (f["attempts"] - 1.))
    return {"ppr_points": round(points, 4),
            **{v: round(float(base[v]) * f[k], 4) for k, v in METRICS.items()}}


def errors(rows, key, actual):
    if not rows:
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    e = np.asarray([r[key] - r[actual] for r in rows])
    return {"n": len(rows), "mae": round(float(np.abs(e).mean()), 4),
            "rmse": round(float(np.sqrt(np.mean(e ** 2))), 4),
            "bias": round(float(e.mean()), 4)}


def retrospective(snapshot, index, training_cases, cutoff):
    """Walk-forward comparison, conditional on observed offensive participation.

    Final ESPN rosters are retrospective. This does not estimate injury
    occurrence, return probability, or pregame lineup improvement.
    """
    paired, opportunities = [], []
    classifications = Counter()
    seen = set()
    for r in snapshot["Weekly_Lineups"]:
        w, pos = int(r["week"]), position(r["position"])
        if not 5 <= w <= cutoff or pos not in POS or r["lineup_slot"] == "IR":
            continue
        if r.get("points") in (None, ""):
            continue
        unique = (w, int(r["player_id"]))
        if unique in seen:
            continue
        seen.add(unique)
        key = (team_key(r["pro_team"]), clean_name(r["player"]), pos)
        risk = risk_state(index, key, w)
        classifications[risk["class"]] += 1
        if risk["class"] in ("UNKNOWN", "NORMAL_OBSERVED"):
            continue
        # Outcome conditions define the evaluation sample, not the risk flag.
        if index["snaps"].get(key[:2], {}).get(w, 0.) <= 0:
            continue
        actual = index["histories"].get(key, {}).get(w)
        base = control(index, key, w)
        if actual is None or base is None:
            continue
        fit = cohort_factors(training_cases, risk["class"], pos, w, key)
        new = adjusted(base, fit)
        genuine = fit["status"] == "EXPERIMENTAL_CONDITIONAL_FACTOR"
        paired.append({"week": w, "position": pos, "class": risk["class"],
                       "genuine": genuine, "actual": float(r["points"]),
                       "control": float(base["ppr_points"]), "candidate": new["ppr_points"]})
        for k, v in METRICS.items():
            if k == "attempts" and pos != "QB":
                continue
            opportunities.append({"metric": k, "actual": float(actual[k]),
                                  "control": float(base[v]), "candidate": new[v],
                                  "genuine": k in fit["factors"]})
    def summary(rows):
        return {m: errors(rows, m, "actual") for m in ("control", "candidate")}
    return {"status": "EXPLORATORY_CONDITIONAL_RETROSPECTIVE_NOT_PROMOTION",
            "model_version": VERSION, "weeks": list(range(5, cutoff + 1)),
            "training_case_count": len(training_cases), "risk_classifications": dict(classifications),
            "conditional_point_comparison": summary(paired),
            "genuine_adjustment_comparison": summary([r for r in paired if r["genuine"]]),
            "by_position": {p: summary([r for r in paired if r["position"] == p]) for p in sorted(POS)},
            "by_risk_class": {k: summary([r for r in paired if r["class"] == k])
                              for k in ("GAP_1", "GAP_2_PLUS", "RECENT_SNAP_DROP")},
            "opportunity_comparison": {k: {"all": summary([r for r in opportunities if r["metric"] == k]),
                "genuine": summary([r for r in opportunities if r["metric"] == k and r["genuine"]])}
                for k in METRICS},
            "week_11_diagnostic_only": summary([r for r in paired if r["week"] == 11]),
            "promotion_eligible": False,
            "limitations": ["Conditional on positive offensive snaps and matched stat rows.",
                            "Missing snap rows with team coverage are not diagnosed injuries.",
                            "No timestamped practice histories or injury-specific severity/recurrence probabilities.",
                            "Small position/class cohorts use unchanged v6 control; no imputed probability.",
                            "Historical roster selection is retrospective. No independent future holdout."]}


def report(snapshot, baseline, schedule, index, training_cases, injuries, cutoff):
    week, as_of = int(baseline["week"]), baseline["as_of"]
    if cutoff >= week:
        raise ValueError("Target-week leakage")
    rosters = {}
    for t in snapshot["Teams"]:
        tid = int(t["team_id"])
        pool, locks, _ = locked_roster(current_players(snapshot, tid, week), schedule["kickoffs"],
                                       as_of, week == int(snapshot["League"][0]["current_week"]))
        b = baseline["all_rosters"].get(str(tid)) or baseline["all_rosters"][tid]
        means = {int(k): float(v) for k, v in b["player_means"].items()}
        rows, normal, conditional = [], dict(means), dict(means)
        for p in pool:
            pid, pos = p["pid"], p["pos"]
            if pos not in POS:
                continue
            key = (team_key(p["nfl_team"]), clean_name(p["name"]), pos)
            risk = risk_state(index, key, week) if cutoff == week - 1 else {
                "class": "UNKNOWN", "reason": "Completed-source cutoff lags target week"}
            base = control(index, key, cutoff + 1)
            if base is None:
                continue
            current_report = injury_match(injuries or [], p["name"], p["nfl_team"], week, as_of)
            fit = cohort_factors(training_cases, risk["class"], pos, week, key)
            candidate = adjusted(base, fit)
            locked = pid in locks.values()
            if not locked:
                normal[pid] = base["ppr_points"]
                conditional[pid] = candidate["ppr_points"]
            injury_flag = (p["injury"] in ("OUT", "DOUBTFUL", "QUESTIONABLE", "IR", "INJURY_RESERVE")
                           or current_report.get("game_status") in ("OUT", "DOUBTFUL", "QUESTIONABLE"))
            # Illustrative half workload and unavailable cases are not
            # probabilities; no teammate redistribution is assumed here.
            sensitivities = []
            if not locked and (injury_flag or risk["class"] not in ("NORMAL_OBSERVED", "UNKNOWN")):
                for factor in (.5, 0.):
                    sensitivities.append({"assumed_workload_fraction": factor,
                                          "ppr_if_assumption_true": round(float(base["ppr_points"]) * factor, 3)})
            rows.append({"id": pid, "name": p["name"], "position": pos,
                         "nfl_team": p["nfl_team"], "risk": risk,
                         "espn_designation_not_verified_for_target_week": p["injury"],
                         "current_injury_report": current_report,
                         "normal_v6": base, "conditional_candidate": candidate,
                         "cohort": fit, "unweighted_scenarios": sensitivities, "locked": locked})
        # This ablation does not simulate a live NFL game or confirm final
        # locked actuals. Suppress lineup comparison after any kickoff lock.
        def best(values):
            if locks:
                return None
            try:
                return optimize(pool, values, locks)
            except ValueError:
                return None
        rosters[str(tid)] = {"players": rows, "normal_control_lineup": best(normal),
                             "conditional_shadow_lineup": best(conditional),
                             "lineup_status": "BLOCKED_LOCKED_GAMES" if locks else "MEAN_ONLY_SHADOW"}
    return {"status": "UNVALIDATED_PARTICIPATION_RISK_SHADOW", "model_version": VERSION,
            "week": week, "as_of": as_of, "completed_through_week": cutoff,
            "training_cases": len(training_cases), "all_rosters": rosters,
            "source_snapshot_sha256": baseline.get("snapshot_sha256"),
            "applied_to_primary_model": False, "promotion_eligible": False,
            "limitations": ["Conditional workload only; no probability of being active.",
                            "Current reports are informational and may lack publication timestamps.",
                            "No teammate workload redistribution, medical severity, or official inactive inference.",
                            "Shadow lineups not recommendations; locked scores remain production control."]}
