"""Game-first v1 shadow: empirically paired game blocks and finite opportunities.

Uses only games before the requested target and within an explicit completion
cutoff. Historical entire-game records are resampled jointly, not independent
player multipliers. This is NOT a drive simulator or calibrated win model.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from math import isfinite
import numpy as np

from .engine import (PRIOR, date, historical, history_index, optimize, position,
                     predict, team_key, current_players, locked_roster)
from .workload import expected, lookup, clean_name
from .opportunity_v2 import player_projection
from .game_environment import preview, scenario_points

VERSION = "game-first-1.1-shadow"
SKILL = {"QB", "RB", "WR", "TE"}
MODELS = ("baseline", "v6", "v2", "v9", "game_volume", "game_robust", "game_pressure", "game_individual")
# All counts represent aggregate team opportunities. Integer-valued counts
# support multinomial allocations; yards remain signed real-valued totals.
FIELDS = ("attempts", "targets", "receptions", "receiving_yards", "receiving_tds",
          "passing_yards", "passing_tds", "interceptions", "carries",
          "rushing_yards", "rushing_tds", "fumbles", "sacks", "plays", "redzone")
I = {k: i for i, k in enumerate(FIELDS)}


def completion_gate(snapshot, nfl_schedule):
    """Advance only a SHADOW analysis view, never alter raw ESPN data.

    Require official final markers, export after the last kickoff, and every
    fantasy team's nine starter scores reconciling to its matchup score.
    NFL finals do not independently confirm ESPN stat corrections or standings.
    """
    current = int(snapshot["League"][0]["current_week"])
    result = {"status": "ESPN_WEEK_UNADVANCED", "espn_current_week": current,
              "completed_through_week": current - 1,
              "standings_advanced": False}
    games = nfl_schedule.get("games", [])
    if (int(nfl_schedule.get("week", -1)) != current
            or not nfl_schedule.get("complete") or not games
            or not all(g.get("completed") is True and g.get("status_state") == "post"
                       for g in games)):
        return {**result, "reason": "NFL scoreboard does not confirm every current-week game final"}
    try:
        exported = date(snapshot["League"][0]["exported_utc"])
        if any(date(g["kickoff_utc"]) >= exported for g in games):
            return {**result, "reason": "Export predates a current-week NFL kickoff"}
        tids = {int(t["team_id"]) for t in snapshot["Teams"]}
        points = defaultdict(list)
        for r in snapshot["Weekly_Lineups"]:
            if int(r["week"]) == current and r["lineup_slot"] not in ("BE", "IR"):
                if r.get("points") in ("", None):
                    raise ValueError("Missing starter score")
                points[int(r["team_id"])].append(float(r["points"]))
        scores = {}
        for m in snapshot["Weekly_Matchups"]:
            if int(m["week"]) != current:
                continue
            for side in ("home", "away"):
                tid = int(m[side + "_team_id"])
                if tid in scores:
                    raise ValueError("Duplicate matchup team")
                scores[tid] = float(m[side + "_score"])
        if set(scores) != tids or set(points) != tids or any(
                len(points[t]) != 9 or abs(sum(points[t]) - scores[t]) > .02 for t in tids):
            raise ValueError("Starter totals do not reconcile for every fantasy team")
    except (KeyError, ValueError, TypeError) as exc:
        return {**result, "reason": str(exc)}
    return {**result, "status": "NFL_FINAL_AND_FANTASY_TOTALS_RECONCILED",
            "completed_through_week": current, "source": nfl_schedule.get("source"),
            "exported_utc": snapshot["League"][0]["exported_utc"],
            "reason": "Shadow analysis may include reconciled current-week scores; ESPN standings remain unadvanced and stat corrections possible."}


def analysis_snapshot(snapshot, gate):
    """Private in-memory view only, allowing existing lagged replay methods."""
    result = deepcopy(snapshot)
    result["League"][0]["current_week"] = int(gate["completed_through_week"]) + 1
    return result


def team_records(stats, pbp, cutoff):
    """Join completed, paired NFL team-game blocks from the existing feeds."""
    aggregate = defaultdict(lambda: np.zeros(len(FIELDS)))
    for r in stats:
        w = int(r["week"])
        if not 1 <= w <= cutoff:
            continue
        a = aggregate[(w, team_key(r["team"]))]
        for k in FIELDS[:11]:
            a[I[k]] += float(r.get(k, 0.))
        a[I["fumbles"]] += sum(float(r.get(k, 0.)) for k in (
            "rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost"))
    records = {}
    for key, a in aggregate.items():
        row = pbp["offense"].get(key)
        if row is None or not np.all(np.isfinite(a)):
            continue
        for k, pbk in (("sacks", "sacks"), ("plays", "plays"), ("redzone", "redzone_plays")):
            a[I[k]] = float(row.get(pbk, 0.))
        if a[I["attempts"]] <= 0 or a[I["carries"]] <= 0:
            continue
        # Refuse materially inconsistent aggregate data instead of inventing
        # receiving opportunities beyond pass attempts.
        if (a[I["targets"]] > a[I["attempts"]] + .001
                or a[I["receptions"]] > a[I["targets"]] + .001
                or a[I["receiving_tds"]] > a[I["receptions"]] + .001
                or a[I["rushing_tds"]] > a[I["carries"]] + .001):
            continue
        records[key] = a
    return records


def _metrics(a):
    return np.column_stack((a[:, I["attempts"]], a[:, I["carries"]],
                            a[:, I["sacks"]] / np.maximum(1., a[:, I["attempts"]] + a[:, I["sacks"]])))


def game_blocks(records, opponents, team_a, team_b, cutoff):
    """Both orientations of real prior games, with prospective matchup weights.

    Kernel weights use expected attempt/carry counts and, in the pressure
    ablation, sack-rate matchup. The outcomes of the target game are absent.
    """
    a, b = [], []
    for (w, t), r in sorted(records.items()):
        if w > cutoff:
            continue
        opp = opponents.get((w, t))
        other = records.get((w, opp))
        if other is not None and opp != t:
            a.append(r)
            b.append(other)
    if len(a) < 30:
        raise ValueError("Too few verified paired NFL game blocks")
    a, b = np.asarray(a), np.asarray(b)
    ma, mb = _metrics(a), _metrics(b)
    def matchup(team, opponent):
        own = [r for (w, t), r in records.items() if w <= cutoff and t == team]
        allowed = [r for (w, t), r in records.items()
                   if w <= cutoff and opponents.get((w, t)) == opponent]
        ref = ma.mean(axis=0)
        def shrink(rows):
            if not rows:
                return ref
            m = _metrics(np.asarray(rows))
            return (m.sum(axis=0) + 3 * ref) / (len(m) + 3)
        return .65 * shrink(own) + .35 * shrink(allowed)
    target_a, target_b = matchup(team_a, team_b), matchup(team_b, team_a)
    scale = np.maximum(ma.std(axis=0), np.array([3., 3., .02]))
    za = (ma - target_a) / scale
    zb = (mb - target_b) / scale
    def weights(k):
        # Broad empirical kernel; not trained on Week 11 or claimed calibrated.
        logw = -.5 * ((za[:, :k] ** 2).sum(axis=1) + (zb[:, :k] ** 2).sum(axis=1))
        w = np.exp(logw - logw.max())
        return w / w.sum()
    return a, b, weights(2), weights(3)


def share(history, records, metric, team, cutoff, robust):
    rows = []
    for r in history:
        w = int(r["week"])
        if w > cutoff:
            continue
        a = records.get((w, team))
        if a is not None and a[I[metric]] > 0:
            rows.append((w, float(r.get(metric, 0.)) / a[I[metric]]))
    rows.sort()
    if len(rows) < 2:
        return None
    x = np.clip([p[1] for p in rows], 0., 1.)
    season = float(np.mean(x))
    recent = float(np.mean(x[-3:]))
    weight = .55 if len(x) >= 4 else .35
    if robust:
        old = float(np.mean(x[:-3])) if len(x) >= 5 else season
        sustained = (len(x) >= 5 and old > 0 and
                     ((recent >= 1.35 * old and np.min(x[-2:]) >= 1.15 * old)
                      or (recent <= .65 * old and np.max(x[-2:]) <= .85 * old)))
        recent = float(np.median(x[-3:]))
        weight = .72 if sustained else (.45 if len(x) >= 5 else .25)
    return max(0., min(1., weight * recent + (1 - weight) * season))


def normalize_shares(values):
    """Add explicit unmodeled-player bucket, even for a fantasy-only pool."""
    a = np.maximum(0., np.asarray(values, dtype=float))
    total = float(a.sum())
    if total > 1:
        a = a / total
    return np.append(a, max(0., 1. - float(a.sum())))


def _score_per_share(state, shares):
    t, c, q = shares
    return (t * (state[..., I["receptions"]] + .1 * state[..., I["receiving_yards"]]
                 + 6 * state[..., I["receiving_tds"]])
            + c * (.1 * state[..., I["rushing_yards"]] + 6 * state[..., I["rushing_tds"]])
            + q * (.04 * state[..., I["passing_yards"]] + 4 * state[..., I["passing_tds"]]
                   - 2 * state[..., I["interceptions"]])
            - 2 * state[..., I["fumbles"]] * (
                t * state[..., I["targets"]] + c * state[..., I["carries"]]
                + q * state[..., I["attempts"]]) / np.maximum(
                    1., state[..., I["targets"]] + state[..., I["carries"]] + state[..., I["attempts"]]))


def allocate_counts(rng, totals, probs):
    """Integer multinomial with vector-valued team budgets, residual last."""
    remaining = np.rint(totals).astype(np.int64).copy()
    remaining_prob = 1.
    out = []
    for p in probs[:-1]:
        chance = min(1., max(0., float(p) / max(remaining_prob, 1e-12)))
        x = rng.binomial(remaining, chance)
        out.append(x)
        remaining -= x
        remaining_prob -= float(p)
    return np.column_stack([*out, remaining])


def sample_scores(states, shares, rng):
    """Allocate finite target, carry and QB attempt counts in every draw.

    Conditional team efficiency is common; receiving/rushing TD scoring uses
    team rates per allocated opportunity, not discrete individual TD outcomes.
    Hence these draws are a partial distribution, NOT calibrated player tails.
    """
    score = np.zeros((len(states), shares.shape[1]))
    for j, (opps, components) in enumerate((
        ("targets", (("receptions", 1.), ("receiving_yards", .1), ("receiving_tds", 6.))),
        ("carries", (("rushing_yards", .1), ("rushing_tds", 6.))),
        ("attempts", (("passing_yards", .04), ("passing_tds", 4.), ("interceptions", -2.))),
    )):
        total = states[:, I[opps]]
        allocation = allocate_counts(rng, total, shares[j])
        rate = sum(states[:, I[k]] * v for k, v in components) / np.maximum(1., total)
        rate -= 2 * states[:, I["fumbles"]] / np.maximum(
            1., states[:, I["targets"]] + states[:, I["carries"]] + states[:, I["attempts"]])
        score += allocation * rate[:, None]
    return score


# Mean-only ablation, with the same game_volume weights and opportunity budget.
# Pseudo-opportunity counts are provisional, not fitted to Week 11.
EFFICIENCY_COMPONENTS = (
    ("receptions", "targets", 25.),
    ("receiving_yards", "targets", 40.),
    ("receiving_tds", "targets", 80.),
    ("rushing_yards", "carries", 40.),
    ("rushing_tds", "carries", 80.),
    ("passing_yards", "attempts", 80.),
    ("passing_tds", "attempts", 100.),
    ("interceptions", "attempts", 120.),
)


def efficiency_factor(history, records, team, cutoff, outcome, opportunity, strength):
    """Shrink a player/team per-opportunity ratio toward one, strictly lagged."""
    n = observed = reference = 0.
    for row in history:
        week = int(row["week"])
        state = records.get((week, team))
        if week > cutoff or state is None:
            continue
        team_n = state[I[opportunity]]
        exposure = float(row.get(opportunity, 0.))
        if team_n <= 0 or exposure <= 0:
            continue
        n += exposure
        observed += float(row.get(outcome, 0.))
        reference += exposure * float(state[I[outcome]]) / team_n
    if n <= 0 or reference <= 0:
        return 1.
    prior = strength * reference / n
    return float(np.clip((observed + prior) / (reference + prior), .25, 3.))


def expected_allocation(total, weights, caps=None):
    """Conserve expected component totals, with capacity for count outcomes."""
    w = np.maximum(0., np.asarray(weights, dtype=float))
    if w.sum() <= 0:
        w = np.ones_like(w)
    if caps is None:
        return float(total) * w / w.sum()
    c = np.maximum(0., np.asarray(caps, dtype=float))
    if total < -1e-8 or total > c.sum() + 1e-7:
        raise ValueError("Inconsistent scoring component budget")
    left = max(0., float(total))
    result = np.zeros_like(w)
    for _ in range(len(w) + 1):
        if left <= 1e-9:
            break
        room = np.maximum(0., c - result)
        x = w * (room > 1e-10)
        if x.sum() <= 0:
            x = room
        if x.sum() <= 0:
            break
        add = np.minimum(room, left * x / x.sum())
        result += add
        left = max(0., float(total) - float(result.sum()))
    if left > 1e-7:
        raise ValueError("Scoring allocation did not reconcile")
    return result


def individual_means(state, shares, factors):
    """Allocate mean scoring totals using lagged individual efficiency.

    Opportunities remain unchanged. Receptions cannot exceed targets,
    receiving TDs cannot exceed receptions, and pass TDs plus interceptions
    cannot exceed attempts. This is a mean-only candidate, not a new
    calibrated player distribution.
    """
    budgets = {"targets": state[I["targets"]] * shares[0],
               "carries": state[I["carries"]] * shares[1],
               "attempts": state[I["attempts"]] * shares[2]}
    out = dict(budgets)
    for outcome, opportunity, _ in EFFICIENCY_COMPONENTS:
        weight = shares[("targets", "carries", "attempts").index(opportunity)] * factors[outcome]
        caps = {
            "receptions": budgets["targets"],
            "receiving_tds": out.get("receptions"),
            "rushing_tds": budgets["carries"],
            "passing_tds": budgets["attempts"],
            "interceptions": budgets["attempts"] - out.get("passing_tds", 0.),
        }.get(outcome)
        out[outcome] = expected_allocation(state[I[outcome]], weight, caps)
    opps = budgets["targets"] + budgets["carries"] + budgets["attempts"]
    out["fumbles"] = expected_allocation(state[I["fumbles"]], opps)
    points = (out["receptions"] + .1 * (out["receiving_yards"] + out["rushing_yards"])
              + 6 * (out["receiving_tds"] + out["rushing_tds"])
              + .04 * out["passing_yards"] + 4 * out["passing_tds"]
              - 2 * (out["interceptions"] + out["fumbles"]))
    return points, out


def model_week(members, stats, pbp, opponents, target_week, cutoff, draws=0, seed=20261124):
    """Compute identical candidate variants on the same finite NFL budgets."""
    if cutoff >= target_week:
        raise ValueError("Target-week leakage")
    if int(pbp["included_through_week"]) < cutoff:
        raise ValueError("PBP cutoff stale")
    records = team_records(stats, pbp, cutoff)
    if not records or max(k[0] for k in records) != cutoff:
        raise ValueError("Completed-week team-game source stale")
    # All modeled players across all fantasy rosters share one budget per NFL team.
    groups = defaultdict(list)
    for p in members:
        if p["pos"] in SKILL:
            groups[team_key(p["nfl_team"])].append(p)
    projections, samples, teams = {}, {}, {}
    rng = np.random.default_rng(seed)
    seen = set()
    for team, opp in sorted(opponents.items()):
        if team in seen:
            continue
        seen.update((team, opp))
        if opponents.get(opp) != team:
            raise ValueError("Non-reciprocal schedule")
        if not groups.get(team) and not groups.get(opp):
            continue
        a, b, w0, w1 = game_blocks(records, pbp["opponents"], team, opp, cutoff)
        index = rng.choice(len(a), size=draws, p=w1) if draws else None
        for t, other, block in ((team, opp, a), (opp, team, b)):
            modeled, raw, robust, histories = [], [], [], []
            for p in sorted(groups.get(t, []), key=lambda x: x["pid"]):
                hist, _ = lookup(stats, p["name"], t, p["pos"], cutoff)
                if not hist:
                    continue
                metrics = ("targets", "carries", "attempts")
                sh0 = [share(hist, records, k, t, cutoff, False) for k in metrics]
                sh1 = [share(hist, records, k, t, cutoff, True) for k in metrics]
                if any(x is None for x in sh0 + sh1):
                    continue
                if p["pos"] != "QB":
                    sh0[2] = sh1[2] = 0.
                modeled.append(p)
                raw.append(sh0)
                robust.append(sh1)
                histories.append(hist)
            if not modeled:
                continue
            p0 = np.asarray([normalize_shares(np.asarray(raw)[:, j]) for j in range(3)])
            p1 = np.asarray([normalize_shares(np.asarray(robust)[:, j]) for j in range(3)])
            m0, m1 = w0 @ block, w1 @ block
            factors = {outcome: np.asarray([
                efficiency_factor(hist, records, t, cutoff, outcome, opportunity, strength)
                for hist in histories] + [1.])
                for outcome, opportunity, strength in EFFICIENCY_COMPONENTS}
            # Average the per-state allocations to preserve the common
            # game_volume control, including nonlinear fumble allocation.
            individual = np.zeros(len(modeled) + 1)
            individual_status = "OK"
            try:
                for state, weight in zip(block, w0):
                    pts, _ = individual_means(state, p0, factors)
                    individual += weight * pts
            except ValueError as exc:
                # Explicit fail-closed fallback for inconsistent source totals.
                individual_status = "BLOCKED_COMPONENT_BUDGET: " + str(exc)
                individual = np.asarray([w0 @ _score_per_share(block, p0[:, k])
                                         for k in range(p0.shape[1])])
            sims = sample_scores(block[index], p1, rng) if draws else None
            teams[t] = {"opponent": other, "historical_oriented_blocks": len(block),
                        "effective_sample_size": round(float(1 / (w1 @ w1)), 2),
                        "mean_attempts": round(float(m1[I["attempts"]]), 3),
                        "mean_targets": round(float(m1[I["targets"]]), 3),
                        "mean_carries": round(float(m1[I["carries"]]), 3),
                        "mean_sacks": round(float(m1[I["sacks"]]), 3),
                        "mean_plays": round(float(m1[I["plays"]]), 3),
                        "mean_redzone_plays": round(float(m1[I["redzone"]]), 3),
                        "other_target_share": round(float(p1[0, -1]), 6),
                        "other_carry_share": round(float(p1[1, -1]), 6),
                        "other_attempt_share": round(float(p1[2, -1]), 6),
                        "source_cutoff": cutoff}
            for k, p in enumerate(modeled):
                pid = p["pid"]
                # Fumble term is linear in shares but nonlinear in game states.
                # Average scores across actual weighted states, not rounded means.
                projections[pid] = {
                    "game_volume": float(w0 @ _score_per_share(block, p0[:, k])),
                    "game_robust": float(w0 @ _score_per_share(block, p1[:, k])),
                    "game_pressure": float(w1 @ _score_per_share(block, p1[:, k])),
                    "game_individual": float(individual[k]),
                    "individual_status": individual_status,
                    "targets": float(m1[I["targets"]] * p1[0, k]),
                    "carries": float(m1[I["carries"]] * p1[1, k]),
                    "attempts": float(m1[I["attempts"]] * p1[2, k]),
                    "availability": "CONDITIONAL_ON_PARTICIPATION",
                    "model_version": VERSION,
                }
                if draws:
                    samples[pid] = sims[:, k]
    return projections, samples, teams


def _metrics_report(rows, models):
    out = {}
    for name in models:
        e = np.asarray([r[name] - r["actual"] for r in rows], dtype=float)
        out[name] = {"n": len(e), "mae": round(float(np.abs(e).mean()), 4) if len(e) else None,
                     "rmse": round(float(np.sqrt(np.mean(e ** 2))), 4) if len(e) else None,
                     "bias": round(float(e.mean()), 4) if len(e) else None}
    return out


def backtest(snapshot, stats, pbp, cutoff, shrink, recent):
    """Retrospective, same paired player sample; Week 11 is diagnostic."""
    idx = history_index(historical(snapshot, cutoff))
    result, decisions, excluded, match_rows = [], [], [], []
    special_teams, opportunity_rows = [], []
    for week in range(5, cutoff + 1):
        roster = [r for r in snapshot["Weekly_Lineups"] if int(r["week"]) == week
                  and r["lineup_slot"] != "IR" and position(r["position"]) in PRIOR
                  and float(r.get("projected_points") or 0) > 0]
        members = [{"pid": int(r["player_id"]), "name": r["player"],
                    "pos": position(r["position"]), "nfl_team": team_key(r["pro_team"])}
                   for r in roster]
        opponents = {t: o for (w, t), o in pbp["opponents"].items() if w == week}
        try:
            candidate, _, _ = model_week(members, stats, pbp, opponents, week, week - 1)
        except ValueError as e:
            excluded.append({"week": week, "reason": str(e)})
            continue
        by_team = defaultdict(list)
        means = {}
        actual = {}
        # Recorded ESPN scores can overwrite projections after kickoff.
        matchups = [m for m in snapshot["Weekly_Matchups"] if int(m["week"]) == week]
        overwritten = bool(matchups) and all(
            abs(float(m[s + "_projected"]) - float(m[s + "_score"])) < .001
            for m in matchups for s in ("home", "away"))
        for r, p in zip(roster, members):
            pid, pos, t = p["pid"], p["pos"], p["nfl_team"]
            base = predict(pid, week, pos, idx, shrink, recent)
            v6 = base
            work = None
            v2 = base
            q = None
            if pos in SKILL:
                hist, _ = lookup(stats, p["name"], t, pos, week - 1)
                if hist:
                    work = expected(hist, pos, week, week - 1)
                    v6 = float(work["ppr_points"])
                    v2 = v6
                    opp = opponents.get(t)
                    if opp:
                        q = player_projection(stats, pbp, p["name"], t, opp, pos, week)
                        if q["status"] == "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED":
                            v2 = float(q["ppr_points"])
            opp = opponents.get(t)
            v9 = v6
            if opp:
                v = scenario_points(pos, base, work, preview(pbp, t, opp, week - 1)).get("point_estimate")
                if v is not None:
                    v9 = float(v)
            a = float(r["points"])
            values = {"baseline": float(base), "v6": float(v6), "v2": float(v2), "v9": float(v9)}
            for name in MODELS[4:]:
                values[name] = candidate.get(pid, {}).get(name, v6)
            if pid in candidate and work is not None:
                result.append({"week": week, "position": pos, "actual": a,
                               "espn_recorded": None if overwritten else float(r["projected_points"]),
                               **values})
                observed = [x for x in stats if int(x["week"]) == week
                            and x["name_key"] == clean_name(p["name"])
                            and team_key(x["team"]) == t and x["pos"] == pos]
                if len(observed) == 1:
                    for metric, old_key in (("targets", "expected_targets"),
                                             ("carries", "expected_carries"),
                                             ("attempts", "expected_pass_attempts")):
                        if metric == "attempts" and pos != "QB":
                            continue
                        opportunity_rows.append({"week": week, "position": pos, "metric": metric,
                            "actual": float(observed[0][metric]), "v6": float(work[old_key]),
                            "game_pressure": float(candidate[pid][metric]),
                            "v2": float(q[old_key]) if q and q["status"] == "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED"
                                  else float(work[old_key])})
            elif pos in ("D/ST", "K"):
                special_teams.append({"week": week, "position": pos, "actual": a,
                                      "espn_recorded": None if overwritten else float(r["projected_points"]),
                                      "baseline": float(base), "v9": float(v9)})
            by_team[int(r["team_id"])].append((p, r["lineup_slot"]))
            means[pid], actual[pid] = values, a
        for tid, items in by_team.items():
            pool = [p for p, _ in items]
            try:
                ideal = optimize(pool, actual)["expected_points"]
                choices = {name: optimize(pool, {p["pid"]: means[p["pid"]][name] for p in pool})
                           for name in MODELS}
                observed = {name: sum(actual[pid] for pid in choice["lineup"].values())
                            for name, choice in choices.items()}
                other = next((m for m in matchups if tid in (int(m["home_team_id"]), int(m["away_team_id"]))), None)
                opp_score = None if other is None else float(other["away_score"] if int(other["home_team_id"]) == tid else other["home_score"])
                decisions.append({"week": week, "team_id": tid,
                                  **{name + "_regret": round(ideal - value, 3) for name, value in observed.items()},
                                  **{name + "_win_vs_actual": int(value > opp_score) if opp_score is not None else None
                                     for name, value in observed.items()}})
                starters = [p["pid"] for p, slot in items if slot != "BE"]
                if len(starters) == 9:
                    match_rows.append({"week": week, "team_id": tid,
                                       "actual": sum(actual[pid] for pid in starters),
                                       "espn_recorded": None if overwritten else sum(
                                           float(r["projected_points"]) for r in roster if int(r["player_id"]) in starters),
                                       **{name: sum(means[pid][name] for pid in starters) for name in MODELS}})
            except ValueError as exc:
                excluded.append({"week": week, "team_id": tid, "reason": str(exc)})
    match_index = {(r["week"], r["team_id"]): r for r in match_rows}
    margins = []
    for m in snapshot["Weekly_Matchups"]:
        w = int(m["week"])
        a = match_index.get((w, int(m["home_team_id"])))
        b = match_index.get((w, int(m["away_team_id"])))
        if not a or not b:
            continue
        margin = {"actual": a["actual"] - b["actual"],
                  **{name: a[name] - b[name] for name in MODELS}}
        if a["espn_recorded"] is not None and b["espn_recorded"] is not None:
            margin["espn_recorded"] = a["espn_recorded"] - b["espn_recorded"]
        margins.append(margin)
    margin_comparable = [r for r in margins if "espn_recorded" in r]
    summarize = lambda rows: {
        "paired_skill_player_weeks": len(rows),
        "point_error": _metrics_report(rows, MODELS),
        "espn_comparable_unverified": _metrics_report(
            [r for r in rows if r["espn_recorded"] is not None], (*MODELS, "espn_recorded")),
    }
    return {"status": "EXPLORATORY_RETROSPECTIVE_NOT_PROMOTION", "model_version": VERSION,
            "weeks_tested": sorted({r["week"] for r in result}),
            "week_11_diagnostic_only": True,
            "all": summarize(result),
            "pre_week_11": summarize([r for r in result if r["week"] < 11]),
            "week_11": summarize([r for r in result if r["week"] == 11]),
            "by_position": {p: summarize([r for r in result if r["position"] == p]) for p in sorted(SKILL)},
            "by_week": {str(w): summarize([r for r in result if r["week"] == w])
                        for w in sorted({r["week"] for r in result})},
            "opportunity_error": {metric: _metrics_report([r for r in opportunity_rows if r["metric"] == metric],
                                                          ("v6", "v2", "game_pressure"))
                                  for metric in ("targets", "carries", "attempts")},
            "special_teams_control_audit": {
                p: {"all": _metrics_report([r for r in special_teams if r["position"] == p], ("baseline", "v9")),
                    "espn_comparable_unverified": _metrics_report(
                        [r for r in special_teams if r["position"] == p and r["espn_recorded"] is not None],
                        ("baseline", "v9", "espn_recorded"))} for p in ("D/ST", "K")},
            "team_score_error_as_played": _metrics_report(match_rows, MODELS),
            "team_score_error_vs_espn_unverified": _metrics_report(
                [r for r in match_rows if r["espn_recorded"] is not None], (*MODELS, "espn_recorded")),
            "matchup_margin_error": _metrics_report(margins, MODELS),
            "matchup_margin_vs_espn_unverified": _metrics_report(margin_comparable, (*MODELS, "espn_recorded")),
            "winner_accuracy": {name: round(float(np.mean([np.sign(r[name]) == np.sign(r["actual"]) for r in margins])), 4)
                                if margins else None for name in MODELS},
            "winner_accuracy_vs_espn_unverified": {
                name: round(float(np.mean([np.sign(r[name]) == np.sign(r["actual"]) for r in margin_comparable])), 4)
                      if margin_comparable else None for name in (*MODELS, "espn_recorded")},
            "legal_team_weeks": len(decisions),
            "mean_lineup_regret": {name: round(float(np.mean([r[name + "_regret"] for r in decisions])), 4)
                                    if decisions else None for name in MODELS},
            "wins_vs_actual_opponent": {name: sum(r[name + "_win_vs_actual"] or 0 for r in decisions)
                                        for name in MODELS},
            "per_team_week": decisions,
            "excluded": excluded,
            "promotion_eligible": False,
            "limitations": ["Week 1 no within-season priors; Weeks 2-4 baseline training window, not scored.",
                            "Final ESPN rosters and recorded projections are not timestamped pregame.",
                            "Week 11 diagnostics may not be used as independent holdout.",
                            "v2/v9 fallbacks included; K/DST use baseline for game-first models.",
                            "Win totals compare each candidate to actual opponent scores, not paired counterfactual opponents."]}


def forecast_report(snapshot, baseline, workload, stats, pbp, schedule, cutoff, gate, draws=100000):
    week = int(baseline["week"])
    as_of = baseline["as_of"]
    opponents = {}
    for game in schedule["games"]:
        a, b = game["teams"]
        opponents[team_key(a)] = team_key(b)
        opponents[team_key(b)] = team_key(a)
    pools, locks = {}, {}
    for t in snapshot["Teams"]:
        tid = int(t["team_id"])
        pool, lock, _ = locked_roster(current_players(snapshot, tid, week), schedule["kickoffs"],
                                     as_of, week == int(snapshot["League"][0]["current_week"]))
        pools[tid], locks[tid] = pool, lock
    # Do not make a future-game simulation for already-started players. The
    # production report remains available and uses its existing lock rules.
    fully_pregame = all(date(v) > date(as_of) for v in schedule["kickoffs"].values())
    use_draws = draws if fully_pregame else 0
    cand, samples, team_env = model_week([p for pool in pools.values() for p in pool],
                                          stats, pbp, opponents, week, cutoff, use_draws)
    rosters = {}
    for tid, pool in pools.items():
        base = baseline["all_rosters"].get(str(tid)) or baseline["all_rosters"][tid]
        old = {int(k): float(v) for k, v in base["player_means"].items()}
        workteam = workload.get("all_rosters", {}).get(str(tid), {})
        fallback = {int(p["id"]): float((p.get("workload") or {}).get("ppr_points", p["baseline"]))
                    for p in workteam.get("player_projections", [])}
        rows, values = [], {}
        for p in pool:
            pid = p["pid"]
            item = cand.get(pid)
            value = float(item["game_pressure"]) if item else fallback.get(pid, old[pid])
            if pid in locks[tid].values():
                actual = workteam.get("locked_actual_scores", {}).get(str(pid))
                if actual is not None:
                    value = float(actual)
            values[pid] = value
            rows.append({"pid": pid, "name": p["name"], "position": p["pos"], "nfl_team": p["nfl_team"],
                         "baseline": old[pid], "shadow_mean": round(value, 3),
                         "method": VERSION if item else "V6_OR_BASELINE_FALLBACK",
                         "injury_status_unverified_for_target_week": p["injury"],
                         "components": item})
        try:
            best = optimize(pool, values, locks[tid])
        except ValueError:
            best = None
        sensitivity = []
        # Explicit what-if cases only: neither NFL injury labels nor arbitrary
        # percentages are treated as calibrated probabilities.
        if tid == int(baseline["your_team_id"]) and fully_pregame:
            for p in pool:
                if p["injury"] not in ("QUESTIONABLE", "DOUBTFUL", "OUT", "IR", "INJURY_RESERVE"):
                    continue
                for factor in (.5, 0.):
                    revised = dict(values)
                    revised[p["pid"]] *= factor
                    reduced_pool = [x for x in pool if factor != 0 or x["pid"] != p["pid"]]
                    try:
                        alternative = optimize(reduced_pool, revised, locks[tid])
                    except ValueError:
                        alternative = None
                    sensitivity.append({"player_id":p["pid"],"name":p["name"],
                                        "unweighted_assumed_workload_factor":factor,
                                        "best_shadow_if_assumption_true":alternative,
                                        "caution":"Illustrative reduced-score or removal case, not medical probability or reallocated teammate workload"})
        rosters[str(tid)] = {"best_shadow": best, "baseline_best": base.get("best"),
                             "players": rows,"unweighted_injury_sensitivities":sensitivity}
    comparison = {"status": "NO_COMPLETE_PREGAME_MATCHUP"}
    opp_info = baseline.get("opponent") or {}
    tid, oid = int(baseline["your_team_id"]), opp_info.get("opponent_id")
    if use_draws and oid is not None:
        a, b = rosters.get(str(tid), {}), rosters.get(str(oid), {})
        if a.get("best_shadow") and a.get("baseline_best") and b.get("baseline_best"):
            fixed = {}
            for group in (a, b):
                for p in group["players"]:
                    if p["pid"] not in samples:
                        fixed[p["pid"]] = p["shadow_mean"]
            def total(line):
                return sum(samples.get(pid, fixed.get(pid, 0.)) for pid in line["lineup"].values())
            enemy = total(b["baseline_best"])
            def summary(line):
                scores = total(line)
                margin = scores - enemy
                return {"mean": round(float(np.mean(scores)), 3),
                        "median": round(float(np.median(scores)), 3),
                        "p10": round(float(np.quantile(scores, .1)), 3),
                        "p90": round(float(np.quantile(scores, .9)), 3),
                        "conditional_win_fraction": round(float(np.mean(margin > 0) + .5 * np.mean(margin == 0)), 5)}
            comparison = {"status": "UNCALIBRATED_PARTIAL_GAME_SCENARIO_NOT_WIN_FORECAST",
                          "trials": draws, "opponent_id": oid,
                          "opponent_lineup": "Baseline optimized, not verified submitted Week 12 lineup",
                          "fixed_fallback_player_ids": sorted(fixed),
                          "baseline_lineup_under_shared_model": summary(a["baseline_best"]),
                          "shadow_lineup_under_shared_model": summary(a["best_shadow"])}
    return {"status": "UNVALIDATED_GAME_FIRST_SHADOW", "model_version": VERSION,
            "week": week, "as_of": as_of, "completed_through_week": cutoff,
            "completion_gate": gate, "source_snapshot_sha256": baseline.get("snapshot_sha256"),
            "modeled_players": len(cand), "team_environments": team_env, "all_rosters": rosters,
            "matchup_sensitivity": comparison, "promotion_eligible": False,
            "limitations": ["Paired historical game blocks, not possessions or score-by-score simulation.",
                            "Current roster slots may be absent in next-week ESPN exports; verify IR and actual submitted lineup before any transaction or start decision.",
                            "Pressure is historical sack proxy, not verified line injuries or blitz schemes.",
                            "Common team efficiency; player-specific efficiency and discrete TD distributions not modeled.",
                            "Targets/carries/attempts conserved including unmodeled residual bucket.",
                            "Unresolved injuries conditional on participation; no medical probabilities.",
                            "DST/K fixed fallback scores, not modeled distributions; no calibrated win or playoff odds."]}
