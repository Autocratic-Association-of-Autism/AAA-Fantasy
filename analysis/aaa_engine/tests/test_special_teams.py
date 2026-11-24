"""Chronological special-teams model tests."""
import unittest
from aaa_engine.special_teams import fit, predict_shadow, backtest, matchup_features
from aaa_engine.game_environment import parse_pbp
from test_game_environment import fixture

class SpecialTeamsTests(unittest.TestCase):
    def test_position_specific_prior_only_fit(self):
        rows=[]
        for i in range(32):
            x=float(i%8)
            rows.append({"week":5+i//16,"position":"D/ST","nfl_team":str(i%16),
                         "actual":6+2*x,"baseline":6.,
                         "features":{"core":{"sacks":x},"expanded":{"sacks":x,"epa":-x}},
                         "v9":6.,"espn_recorded":7.})
        m=fit(rows,"D/ST",7,"core")
        self.assertEqual(m["status"],"FIT_SHADOW")
        self.assertEqual(m["n"],32)
        rows.append({**rows[0],"week":7,"actual":9999.})
        rows.append({**rows[0],"position":"K","actual":9999.})
        self.assertEqual(m,fit(rows,"D/ST",7,"core"))
        self.assertEqual(fit(rows,"K",7,"core")["status"],"INSUFFICIENT_PRIOR_TRAINING")
        lo,ok=predict_shadow(6,m,{"core":{"sacks":0.}},"core")
        hi,ok2=predict_shadow(6,m,{"core":{"sacks":7.}},"core")
        self.assertTrue(ok and ok2)
        self.assertGreater(hi,lo)
        self.assertEqual(predict_shadow(6,m,None,"core"),(6.,False))

    def test_matchup_features_are_lagged_and_capability_gated(self):
        a=parse_pbp(fixture(False),2026,3)
        b=parse_pbp(fixture(True),2026,4)
        for pos in ("D/ST","K"):
            x=matchup_features(a,pos,"KC","DEN",3)
            self.assertIsNotNone(x)
            self.assertEqual(x,matchup_features(b,pos,"KC","DEN",3))
        self.assertIsNone(matchup_features(a,"D/ST","KC","DEN",4))
        b["source_capabilities"]["interceptions"]=False
        self.assertIsNone(matchup_features(b,"D/ST","KC","DEN",3))
        b["source_capabilities"]["fg_kicks"]=False
        self.assertIsNone(matchup_features(b,"K","KC","DEN",3))

    def test_early_fallback_not_mislabeled_as_genuine(self):
        r={"week":5,"position":"K","nfl_team":"KC","actual":5.,
           "baseline":7.,"v9":8.,"espn_recorded":6.,
           "features":{"core":{"fg":1.},"expanded":{"fg":1.}}}
        report=backtest([r])["positions"]["K"]
        self.assertEqual(report["all_with_fallbacks"]["core"]["mae"],2.)
        self.assertEqual(report["matched_genuine"]["core"]["n"],0)
        self.assertEqual(report["excluded_from_genuine"],1)

if __name__=="__main__":
    unittest.main()
