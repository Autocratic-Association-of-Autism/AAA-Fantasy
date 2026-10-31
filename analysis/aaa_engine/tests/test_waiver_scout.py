"""v9 waiver scouting is source-backed and does not import ESPN scoring projections."""
import unittest

from aaa_engine.waiver_scout import scan


def fixtures():
    teams={
        "KC":{"status":"OBSERVED_MATCHUP_WITH_UNVALIDATED_VOLUME_SCENARIOS",
              "opponent":"DEN","expected_dropbacks_proxy":34.,
              "expected_rushes_proxy":26.,"sack_matchup_ratio":1.,
              "pass_epa_matchup_edge":0.1,"rush_epa_matchup_edge":0.,
              "pass_volume_factor_shadow":1.04,
              "rush_volume_factor_shadow":1.02,
              "opponent_offense":{"turnovers_per_game":1.2},
              "own_defense":{"sack_rate":.08},
              "league_reference":{"sack_rate":.06,"fg_attempts_per_game":2.},
              "fg_attempts_proxy":2.1},
    }
    context={"status":"SOURCE_BACKED_SCOUTING_AND_UNVALIDATED_SCENARIOS",
             "observed_through_week":7,"matchups":teams}
    snapshot={"League":[{"exported_utc":"2026-10-31T12:00:00Z"}],
              "Current_Rosters":[],
              "Free_Agents":[{"player_id":100,"player":"Unrostered K",
                             "position":"K","pro_team":"KC",
                             "projected_points":9.3,"injury_status":"ACTIVE"},
                            {"player_id":101,"player":"Unrostered QB",
                             "position":"QB","pro_team":"KC",
                             "projected_points":9.3,"injury_status":"ACTIVE"},
                            {"player_id":102,"player":"Out WR",
                             "position":"WR","pro_team":"KC",
                             "projected_points":8.,"injury_status":"OUT"}]}
    schedule={"kickoffs":{"KC":"2026-11-01T20:00:00Z",
                          "DEN":"2026-11-01T20:00:00Z"}}
    return snapshot,[],context,schedule


class WaiverScoutingTests(unittest.TestCase):
    def test_kicker_has_context_but_no_invented_points(self):
        data=scan(*fixtures())
        self.assertEqual(data["status"],
            "SOURCE_BACKED_WAIVER_SCOUTING_NO_AUTOMATIC_ADD")
        k=data["by_position"]["K"][0]
        self.assertEqual(k["opponent"],"DEN")
        self.assertIsNone(k["score_scenario"])
        self.assertFalse(k["applied_to_primary_model"])
        self.assertEqual(data["by_position"]["WR"],[])

    def test_positive_espn_projection_does_not_change_estimates(self):
        a=fixtures()
        one=scan(*a)
        a[0]["Free_Agents"][1]["projected_points"]=42
        two=scan(*a)
        self.assertEqual(one["by_position"]["QB"],two["by_position"]["QB"])
        self.assertEqual(two["by_position"]["QB"][0]["opportunity_status"],
                         "NO_VERIFIED_PLAYER_HISTORY")

    def test_league_rostered_player_is_not_free_agent(self):
        a=fixtures()
        a[0]["Current_Rosters"]=[{"player_id":101,"position":"QB"}]
        report=scan(*a)
        self.assertEqual(report["by_position"]["QB"],[])


if __name__=="__main__":
    unittest.main()
