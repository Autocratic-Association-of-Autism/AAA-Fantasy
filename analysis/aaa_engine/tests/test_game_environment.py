"""v9: scenario provenance, all-position coverage and strict completed-week cutoff."""
import csv
import io
import unittest

from aaa_engine.game_environment import (parse_pbp,preview,scenario_points)


def fixture(with_future=False):
    output=io.StringIO()
    fields=["season","season_type","week","posteam","defteam",
            "pass_attempt","rush_attempt","sack","epa","qb_hit",
            "air_yards","yards_after_catch","yardline_100",
            "interception","pass_touchdown","rush_touchdown",
            "play_type","field_goal_result","down","first_down"]
    writer=csv.DictWriter(output,fieldnames=fields)
    writer.writeheader()
    weeks=(1,2,3,4) if with_future else (1,2,3)
    for week in weeks:
        for off,defense in (("KC","DEN"),("DEN","KC")):
            for i in range(80):
                passed=i%2==0
                writer.writerow({
                    "season":2026,"season_type":"REG","week":week,
                    "posteam":off,"defteam":defense,
                    "pass_attempt":int(passed),"rush_attempt":int(not passed),
                    "sack":int(passed and i%17==0),
                    "epa":(100 if week==4 else .12),
                    "qb_hit":int(passed and i%7==0),
                    "air_yards":8 if passed else "",
                    "yards_after_catch":5 if passed else "",
                    "yardline_100":15 if i%11==0 else 60,
                    "interception":int(passed and i%37==0),
                    "pass_touchdown":int(passed and i%31==0),
                    "rush_touchdown":int(not passed and i%29==0),
                    "play_type":"pass" if passed else "run",
                    "field_goal_result":"",
                    "down":3 if i%4==0 else 1,
                    "first_down":int(i%7==0)
                })
    return output.getvalue()


class GameEnvironmentTests(unittest.TestCase):
    def test_cutoff_excludes_future_and_keeps_position_features(self):
        a=parse_pbp(fixture(False),2026,3)
        b=parse_pbp(fixture(True),2026,3)
        self.assertEqual(a["offense"],b["offense"])
        self.assertEqual(a["defense"],b["defense"])
        self.assertNotIn((4,"KC"),b["offense"])
        out=preview(b,"KC","DEN",3)
        self.assertEqual(out["status"],
           "OBSERVED_MATCHUP_WITH_UNVALIDATED_VOLUME_SCENARIOS")
        self.assertEqual(out["offense"]["games"],3)
        self.assertEqual(out["opponent_defense"]["games"],3)
        self.assertEqual(out["coverage"]["man_zone"],
                         "NOT_VERIFIED_IN_STANDARD_PBP")
        self.assertFalse(out["applied_to_primary_model"])

    def test_coverage_and_trenches_not_fabricated(self):
        a=parse_pbp(fixture(),2026,3)
        out=preview(a,"KC","DEN",3)
        self.assertEqual(out["trenches"]["true_pass_block_win_rate"],
                         "NOT_VERIFIED")
        self.assertIsInstance(out["trenches"]["opponent_sack_rate_forced"],float)
        self.assertEqual(out["weather"],"NO_VERIFIED_STADIUM_SPECIFIC_FORECAST")
        self.assertEqual(out["game_script"]["score_or_spread"],
                         "NOT_MODELED_INDEPENDENTLY")

    def test_all_positions_have_explicit_scenarios_no_promotion(self):
        out=preview(parse_pbp(fixture(),2026,3),"KC","DEN",3)
        player={"ppr_points":15.0,"expected_passing_yards":200,
                "expected_passing_tds":1.5,"expected_interceptions":.5,
                "expected_rushing_yards":40,"expected_rushing_tds":.3,
                "expected_receptions":4.5,
                "expected_receiving_yards":55,
                "expected_receiving_tds":.4}
        for pos in ("QB","RB","WR","TE","D/ST","K"):
            with self.subTest(position=pos):
                result=scenario_points(pos,10.,player,out)
                self.assertIsInstance(result["point_estimate"],float)
                self.assertFalse(result["applied_to_primary_model"])

    def test_missing_game_features_must_not_force_adjustment(self):
        out=scenario_points("QB",12,
                    {"ppr_points":15.0}, {"status":"NO_MATCH"})
        self.assertIsNone(out["point_estimate"])

    def test_invalid_source_blocks(self):
        with self.assertRaisesRegex(ValueError,"required columns"):
            parse_pbp("season,week\n2026,1\n",2026,3)


if __name__=="__main__":
    unittest.main()
