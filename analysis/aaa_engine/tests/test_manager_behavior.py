import unittest
import numpy as np
from aaa_engine.manager_behavior import (make_case, fit, summarize_choice, evaluate_choice,
                                         activity_bins, rates, FEATURES)

class ManagerBehaviorTests(unittest.TestCase):
    def test_choice_law_normalizes_and_preserves_nine_starters(self):
        pool=[{"pid":i,"pos":p} for i,p in enumerate(("QB","RB","RB","RB","WR","WR","WR","TE","D/ST","K"),1)]
        means={p["pid"]:float(p["pid"]) for p in pool}
        c=make_case(pool,5,1,means,{},set(),None)
        c["actual_index"]=0
        p,order,inc=summarize_choice(c,np.zeros(len(FEATURES)))
        self.assertAlmostEqual(float(p.sum()),1.)
        self.assertAlmostEqual(sum(inc.values()),9.)
        self.assertAlmostEqual(evaluate_choice(c,np.zeros(len(FEATURES)))["log_loss"],np.log(len(p)))
        betas,meta=fit([c],5,1)
        self.assertEqual(meta["manager_cases"],0)
        np.testing.assert_array_equal(betas["manager"],betas["league"])

    def test_fit_excludes_future_cases(self):
        rows=[]
        for w in range(5,10):
            for tid in range(1,5):
                rows.append({"week":w,"team_id":tid,"X":np.array([[-1.,0.,0.],[1.,1.,0.]]),"actual_index":1})
        before,meta=fit(rows,9,1)
        after,_=fit([r for r in rows if r["week"]<9],9,1)
        for m in before:
            np.testing.assert_array_equal(before[m],after[m])
        self.assertTrue(meta["manager_genuine"])
        self.assertTrue(meta["league_genuine"])

    def test_activity_full_calendar_bins_and_future_exclusion(self):
        from datetime import datetime,timezone
        def row(d,pid):
            return {"team_id":1,"player_id":pid,"action":"FA ADDED","position":"RB",
                    "date_epoch_ms":int(datetime.fromisoformat(d).timestamp()*1000)}
        events=[row("2026-09-07T12:00:00+00:00",1),row("2026-09-14T12:00:00+00:00",2),
                row("2026-09-21T12:00:00+00:00",3),row("2026-10-01T12:00:00+00:00",4)]
        s={"Teams":[{"team_id":1},{"team_id":2}],"Transactions":events+[events[1]]}
        bins,e,meta=activity_bins(s,"2026-09-23T12:00:00+00:00")
        self.assertEqual(len(e),3)
        self.assertEqual(meta["complete_calendar_weeks"],1)
        self.assertEqual(len(bins),2)
        self.assertEqual(bins[0]["counts"]["FA ADDED"],1)
        r=rates(bins,"2026-09-14T00:00:00+00:00",1)
        self.assertEqual(r["FA ADDED"]["prior_manager_weeks"],0)

if __name__=="__main__":
    unittest.main()
