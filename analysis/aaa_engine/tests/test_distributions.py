import unittest
import numpy as np
from aaa_engine.distributions import (law, from_residuals, player_laws, score, quantile,
                                     matchup_draws, MODELS, describe)

class DistributionTests(unittest.TestCase):
    def test_discrete_crps_and_quantiles(self):
        d=law([0.,2.])
        self.assertAlmostEqual(score(d,1.,2.)["crps"],.5)
        self.assertAlmostEqual(score(d,2.,2.)["tail_brier"],.25)
        self.assertEqual(quantile(d,.5),0.)
        self.assertEqual(quantile(d,.9),2.)

    def test_weighted_distribution_preserves_mean_and_signed_scores(self):
        d=from_residuals([-10.,2.,8.],4.,[.2,.3,.5])
        self.assertAlmostEqual(float(d[0]@d[1]),4.)
        self.assertGreater(describe(d,20.)["negative_score_probability"],0.)

    def test_chronological_personalization_and_fallback(self):
        rows=[{"week":w,"pid":pid,"pos":"WR","estimate":10.+pid,
               "error":float((-1)**w*(pid+1))}
              for w in range(2,6) for pid in range(1,10)]
        p={"pid":1,"pos":"WR"}
        laws,meta=player_laws(rows,p,11.,5)
        self.assertEqual(meta["own_observations"],3)
        self.assertEqual(meta["status"],"PERSONAL_BLEND")
        self.assertEqual(meta["through_week"],4)
        early,_=player_laws([r for r in rows if r["week"]<5],p,11.,5)
        for m in MODELS:
            np.testing.assert_array_equal(laws[m][0],early[m][0])
            self.assertAlmostEqual(float(laws[m][0]@laws[m][1]),11.)
        new,meta=player_laws(rows,{"pid":999,"pos":"WR"},11.,5)
        self.assertEqual(meta["status"],"CONDITIONAL_FALLBACK")
        np.testing.assert_array_equal(new["personal"][0],new["conditional"][0])

    def test_common_random_numbers_for_identical_models(self):
        d=law([1.,20.])
        by={pid:{m:d for m in MODELS} for pid in (1,2)}
        result=matchup_draws(by,[1],[2],1000,7)
        for m in MODELS:
            np.testing.assert_array_equal(result[m][0],result["position"][0])
            np.testing.assert_array_equal(result[m][1],result["position"][1])
        with self.assertRaises(ValueError):
            matchup_draws(by,[1],[1],1000,7)

if __name__=="__main__":
    unittest.main()
