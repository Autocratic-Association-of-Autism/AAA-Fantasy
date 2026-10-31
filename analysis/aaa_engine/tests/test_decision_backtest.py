"""Regression tests for strict walk-forward and decision-regret semantics."""
import unittest
from aaa_engine.decision_backtest import backtest


class DecisionTests(unittest.TestCase):
    def fixture(self):
        slots=[("QB","QB"),("RB","RB"),("RB","RB"),("WR","WR"),
               ("WR","WR"),("TE","TE"),("RB","RB/WR/TE"),
               ("D/ST","D/ST"),("K","K"),("WR","BE")]
        names=["QB1","RB1","RB2","WR1","WR2","TE1","RB3","D1","K1","WR3"]
        rows=[]
        for wk in range(1,6):
            for i,(pos,slot) in enumerate(slots):
                rows.append({"week":wk,"team_id":1,"player_id":i+1,
                             "player":names[i],"position":pos,
                             "pro_team":"KC","lineup_slot":slot,
                             "points":float(5+i+wk),"projected_points":10.})
        return {"League":[{"current_week":6}],
                "Teams":[{"team_id":1,"team_name":"One"}],
                "Weekly_Lineups":rows,
                "Weekly_Matchups":[]}

    def test_baseline_fallback_unchanged_and_regret_nonnegative(self):
        test=backtest(self.fixture(),[],shrink=5,recent=0)
        self.assertEqual(test["summary"]["legal_team_weeks"],1)
        week=test["your_weeks"][0]
        self.assertEqual(week["workload_actual"],week["baseline_actual"])
        self.assertEqual(week["baseline_regret"],week["workload_regret"])
        self.assertGreaterEqual(week["baseline_regret"],0)

    def test_no_future_stats_can_enter_week_five(self):
        example={"name":"WR3","name_key":"wr3","team":"KC","pos":"WR",
                 "week":5,"targets":100.}
        # A Week 5 data row cannot influence the Week 5 prediction.
        test=backtest(self.fixture(),[example],shrink=5,recent=0)
        self.assertEqual(test["summary"]["paired_skill_player_weeks"],0)
        self.assertEqual(test["summary"]["lineups_with_different_starters"],0)

    def test_untrained_period_blocked(self):
        with self.assertRaisesRegex(ValueError,"starts week 5"):
            backtest(self.fixture(),[],first_week=4)

    def test_no_completed_week_pending(self):
        fixture=self.fixture()
        fixture["League"][0]["current_week"]=5
        result=backtest(fixture,[],first_week=5)
        self.assertEqual(result["status"],"PENDING_NOT_ENOUGH_COMPLETED_WEEKS")


if __name__=="__main__":
    unittest.main()
