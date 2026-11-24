"""Regression guards for game-first shadow forecasts."""
import unittest
import numpy as np

from aaa_engine.game_first import (analysis_snapshot, allocate_counts, completion_gate,
                                   FIELDS, I, game_blocks, model_week, normalize_shares,
                                   sample_scores, share, team_records, individual_means,
                                   efficiency_factor, EFFICIENCY_COMPONENTS)


def state(attempts=32, carries=26, sacks=2, yards=230):
    a = np.zeros(len(FIELDS))
    vals = {"attempts": attempts, "targets": attempts - 3, "receptions": 20,
            "receiving_yards": yards, "receiving_tds": 2, "passing_yards": yards,
            "passing_tds": 2, "interceptions": 1, "carries": carries,
            "rushing_yards": 100, "rushing_tds": 1, "fumbles": 1, "sacks": sacks,
            "plays": attempts + carries + sacks, "redzone": 6}
    for k, v in vals.items():
        a[I[k]] = v
    return a


def fixture():
    records, opponents = {}, {}
    for w in range(1, 7):
        for i in range(8):
            a, b = f"T{i}A", f"T{i}B"
            records[(w, a)] = state(attempts=30 + w, sacks=1 + i % 5, yards=240 - 15 * (i % 5))
            records[(w, b)] = state(attempts=32 + i % 4, sacks=2 + w % 3)
            opponents[(w, a)], opponents[(w, b)] = b, a
    return records, opponents


class GameFirstTests(unittest.TestCase):
    def test_budget_allocations_conserved_for_every_draw(self):
        rng = np.random.default_rng(14)
        totals = np.array([0, 1, 30, 60, 5, 12] * 100)
        for p in ([.2, .3], [.9, .9], [0, 0], [1, 0]):
            probs = normalize_shares(p)
            out = allocate_counts(rng, totals, probs)
            np.testing.assert_array_equal(out.sum(axis=1), totals)
            self.assertTrue((out >= 0).all())
            self.assertAlmostEqual(float(probs.sum()), 1.)

    def test_paired_blocks_exclude_target_week(self):
        records, opponents = fixture()
        a, b, w0, w1 = game_blocks(records, opponents, "T0A", "T0B", 5)
        for k in records:
            if k[0] == 6:
                records[k][I["attempts"]] = 9999
        aa, bb, ww0, ww1 = game_blocks(records, opponents, "T0A", "T0B", 5)
        for x, y in zip((a, b, w0, w1), (aa, bb, ww0, ww1)):
            np.testing.assert_array_equal(x, y)
        self.assertAlmostEqual(float(w1.sum()), 1.)
        self.assertFalse(np.allclose(w0, w1))
        self.assertTrue((a[:, I["attempts"]] < 100).all())

    def test_robust_share_reduces_single_breakout(self):
        records = {(w, "T"): state(attempts=33) for w in range(1, 7)}
        hist = [{"week": w, "targets": 4 if w < 6 else 18} for w in range(1, 7)]
        raw = share(hist, records, "targets", "T", 6, False)
        robust = share(hist, records, "targets", "T", 6, True)
        self.assertLess(robust, raw)
        self.assertEqual(share(hist, records, "targets", "T", 5, True),
                         share(hist[:-1], records, "targets", "T", 5, True))

    def test_joint_sample_points_conserve_aggregate_scoring(self):
        states = np.asarray([state()] * 1000)
        probs = np.asarray([[.5, .3, .2], [.2, .7, .1], [.7, .2, .1]])
        pts = sample_scores(states, probs, np.random.default_rng(12))
        s = state()
        total = (s[I["receptions"]] + .1 * s[I["receiving_yards"]] +
                 6 * s[I["receiving_tds"]] + .1 * s[I["rushing_yards"]] +
                 6 * s[I["rushing_tds"]] + .04 * s[I["passing_yards"]] +
                 4 * s[I["passing_tds"]] - 2 * s[I["interceptions"]] - 2 * s[I["fumbles"]])
        np.testing.assert_allclose(pts.sum(axis=1), total)

    def test_week_completion_requires_nfl_finals_and_reconciled_scores(self):
        snapshot = {"League": [{"current_week": 11, "exported_utc": "2026-11-24T08:00:00Z"}],
                    "Teams": [{"team_id": 1}, {"team_id": 2}],
                    "Weekly_Lineups": [{"week": 11, "team_id": t, "lineup_slot": "QB", "points": 10}
                                       for t in (1, 2) for _ in range(9)],
                    "Weekly_Matchups": [{"week": 11, "home_team_id": 1, "away_team_id": 2,
                                         "home_score": 90, "away_score": 90}]}
        schedule = {"week": 11, "complete": True, "games": [
            {"kickoff_utc": "2026-11-23T20:00:00Z", "completed": True, "status_state": "post"}]}
        g = completion_gate(snapshot, schedule)
        self.assertEqual(g["completed_through_week"], 11)
        self.assertEqual(analysis_snapshot(snapshot, g)["League"][0]["current_week"], 12)
        self.assertEqual(snapshot["League"][0]["current_week"], 11)
        schedule["games"][0]["completed"] = False
        self.assertEqual(completion_gate(snapshot, schedule)["completed_through_week"], 10)
        schedule["games"][0]["completed"] = True
        snapshot["Weekly_Matchups"][0]["home_score"] = 99
        self.assertEqual(completion_gate(snapshot, schedule)["completed_through_week"], 10)

    def test_individual_efficiency_preserves_component_totals_and_limits(self):
        s = state()
        shares = np.asarray([[.50, .25, .25], [.70, .15, .15], [.95, .0, .05]])
        factors = {k: np.array([3., .25, 1.]) for k, _, _ in EFFICIENCY_COMPONENTS}
        pts, components = individual_means(s, shares, factors)
        for k, v in components.items():
            self.assertAlmostEqual(float(v.sum()), s[I[k]], places=6)
        self.assertTrue((components["receptions"] <= components["targets"] + 1e-8).all())
        self.assertTrue((components["receiving_tds"] <= components["receptions"] + 1e-8).all())
        self.assertTrue((components["passing_tds"] + components["interceptions"] <=
                         components["attempts"] + 1e-8).all())
        self.assertTrue(np.isfinite(pts).all())

    def test_individual_efficiency_excludes_future_and_shrinks_small_samples(self):
        records = {(1, "KC"): state(), (2, "KC"): state()}
        first = {"week": 1, "targets": 2, "receiving_yards": 40}
        future = {"week": 2, "targets": 20, "receiving_yards": 999}
        f = efficiency_factor([first, future], records, "KC", 1,
                              "receiving_yards", "targets", 40)
        self.assertEqual(f, efficiency_factor([first], records, "KC", 1,
                                             "receiving_yards", "targets", 40))
        self.assertGreater(f, 1.)
        self.assertLess(f, 1.2)
        self.assertEqual(efficiency_factor([], records, "KC", 1,
                                          "receiving_yards", "targets", 40), 1.)

    def test_target_week_cutoff_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "leakage"):
            model_week([], [], {"included_through_week": 12}, {}, 12, 12)
        with self.assertRaisesRegex(ValueError, "stale"):
            model_week([], [], {"included_through_week": 10}, {}, 12, 11)


if __name__ == "__main__":
    unittest.main()
