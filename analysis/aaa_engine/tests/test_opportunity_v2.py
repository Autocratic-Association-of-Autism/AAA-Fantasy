"""Synthetic, leakage-safe regression checks for opportunity v2."""
import copy
import unittest

from aaa_engine.opportunity_v2 import (team_volume, player_share, player_projection,
                                        retrospective)
from aaa_engine.workload import clean_name, METRICS


def game(week, team, opponent, attempts, runs, sacks=2, redzone=6):
    return (week, team), {
        "passes": attempts + sacks, "sacks": sacks, "runs": runs,
        "redzone_plays": redzone, "pass_tds": 2, "rush_tds": 1,
    }


def pbp_fixture(weeks=6, future=None):
    off, defense, opponents = {}, {}, {}
    for w in range(1, weeks + 1):
        attempts = 40 if w < 6 else 50
        a, ra = game(w, "KC", "DEN", attempts, 25)
        b, rb = game(w, "DEN", "KC", 32, 27, sacks=1)
        off[a] = ra
        off[b] = rb
        defense[(w, "DEN")] = dict(ra)
        defense[(w, "KC")] = dict(rb)
        opponents[(w, "KC")] = "DEN"
        opponents[(w, "DEN")] = "KC"
    data = {"offense": off, "defense": defense, "opponents": opponents,
            "included_through_week": weeks}
    if future:
        for key, value in future["offense"].items():
            data["offense"][key] = value
        for key, value in future["defense"].items():
            data["defense"][key] = value
        data["opponents"].update(future["opponents"])
        data["included_through_week"] = max(x[0] for x in off)
    return data


def player(week, targets=6, carries=1, pos="WR", name="Receiver Test"):
    row = dict.fromkeys(METRICS, 0.)
    row.update({
        "name": name, "name_key": clean_name(name), "team": "KC",
        "pos": pos, "week": week,
        "targets": float(targets), "carries": float(carries),
        "receptions": targets * .65,
        "receiving_yards": targets * 7.0,
        "rushing_yards": carries * 4.2,
        "receiving_tds": targets * .04,
        "rushing_tds": carries * .02,
    })
    return row


class OpportunityV2Tests(unittest.TestCase):
    def test_team_pass_attempts_exclude_sacks(self):
        data = pbp_fixture(5)
        out = team_volume(data, "KC", "DEN", 6)
        self.assertEqual(out["status"], "EXPERIMENTAL_TEAM_VOLUME")
        self.assertGreater(out["pass_attempts"], 30)
        self.assertLess(out["pass_attempts"], 45)
        self.assertEqual(out["historical_cutoff_week"], 5)

    def test_strict_lag_excludes_future_stats_and_team_plays(self):
        baseline = pbp_fixture(5)
        future = pbp_fixture(6)
        future["offense"][(6, "KC")]["passes"] = 5000
        future["defense"][(6, "DEN")]["passes"] = 5000
        old = team_volume(baseline, "KC", "DEN", 6)
        new = team_volume(future, "KC", "DEN", 6)
        self.assertEqual(old, new)
        history = [player(w, targets=5 + w) for w in range(1, 6)]
        extra = history + [player(6, targets=1000)]
        self.assertEqual(
            player_share(history, baseline, "Receiver Test", "KC", "WR", "targets", 6),
            player_share(extra, future, "Receiver Test", "KC", "WR", "targets", 6),
        )

    def test_adaptive_share_detects_sustained_role_change(self):
        data = pbp_fixture(6)
        stats = [player(w, targets=(2 if w <= 3 else 12)) for w in range(1, 7)]
        out = player_share(stats, data, "Receiver Test", "KC", "WR", "targets", 7)
        self.assertTrue(out["role_change_detected"])
        self.assertEqual(out["recent_weight"], .72)
        self.assertGreater(out["share"], out["season_share"])

    def test_no_single_week_change_point_and_injury_warning(self):
        data = pbp_fixture(6)
        stats = [player(w, targets=5) for w in (1, 2, 3, 4, 5)]
        out = player_share(stats, data, "Receiver Test", "KC", "WR", "targets", 7)
        self.assertFalse(out["role_change_detected"])
        self.assertEqual(out["availability_caveat"],
                         "LAST_COMPLETED_GAME_MISSING_PLAYER_ROW")

    def test_late_debut_does_not_count_prior_team_games_as_zero_share(self):
        data = pbp_fixture(6)
        stats = [player(w, targets=8) for w in (4, 5, 6)]
        out = player_share(stats, data, "Receiver Test", "KC", "WR", "targets", 7)
        self.assertEqual(out["team_games_used"], [4, 5, 6])
        self.assertEqual(out["team_games_without_player_row"], [1, 2, 3])
        self.assertTrue(out["conditional_on_participation"])
        self.assertEqual(out["pre_debut_team_games"], [1, 2, 3])
        self.assertEqual(out["missing_rows_since_debut"], [])
        self.assertEqual(out["history_caveat"], "RECENT_DEBUT_OR_NEW_ROLE_PREGAME_STATUS_UNVERIFIED")
        self.assertNotIn("availability_caveat", out)
        self.assertGreater(out["share"], .15)

    def test_missing_intermittent_games_flagged_not_zeroed(self):
        data = pbp_fixture(6)
        stats = [player(w, targets=6) for w in (1, 2, 4, 5, 6)]
        out = player_share(stats, data, "Receiver Test", "KC", "WR", "targets", 7)
        self.assertEqual(out["team_games_used"], [1, 2, 4, 5, 6])
        self.assertEqual(out["team_games_without_player_row"], [3])
        self.assertEqual(out["missing_rows_since_debut"], [3])
        self.assertEqual(out["pre_debut_team_games"], [])
        self.assertEqual(out["availability_caveat"],
                         "MISSED_PRIOR_TEAM_GAMES_ROLE_AND_HEALTH_REQUIRE_REVIEW")

    def test_points_rebuilt_from_team_opportunities(self):
        data = pbp_fixture(5)
        stats = [player(w) for w in range(1, 6)]
        forecast = player_projection(stats, data, "Receiver Test", "KC",
                                     "DEN", "WR", 6)
        self.assertEqual(forecast["status"],
                         "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED")
        self.assertGreater(forecast["expected_targets"], 0)
        self.assertGreater(forecast["expected_receptions"], 0)
        self.assertGreater(forecast["ppr_points"], 0)
        self.assertLess(forecast["ppr_points"], 100)
        self.assertEqual(forecast["shares"]["targets"]["historical_cutoff_week"], 5)

    def test_missing_and_stale_inputs_fail_closed(self):
        data = pbp_fixture(3)
        self.assertEqual(team_volume(data, "KC", "DEN", 7)["status"],
                         "BLOCKED_STALE_PBP")
        self.assertEqual(
            player_projection([], data, "Nobody", "KC", "DEN", "WR", 4)["status"],
            "NO_PLAYER_HISTORY")

    def test_backtest_rejects_training_window_and_marks_small_season_pending(self):
        snapshot = {"League": [{"current_week": 4}]}
        data = pbp_fixture(3)
        with self.assertRaisesRegex(ValueError, "starts after"):
            retrospective(snapshot, [], data, 5, 0, first_week=4)
        self.assertEqual(retrospective(snapshot, [], data, 5, 0)["status"],
                         "PENDING_NOT_ENOUGH_COMPLETED_WEEKS")


if __name__ == "__main__":
    unittest.main()
