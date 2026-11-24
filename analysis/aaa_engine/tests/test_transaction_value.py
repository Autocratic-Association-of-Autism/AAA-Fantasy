import unittest
from aaa_engine.transaction_value import optimal,delta,swapped,paired_changes,depth

def pool():
    return [{"pid":i,"pos":p,"nfl_team":"KC","injury":"ACTIVE","slot":"BE"}
            for i,p in enumerate(("QB","RB","RB","RB","WR","WR","WR","TE","D/ST","K"),1)]

class TransactionTests(unittest.TestCase):
    def test_exact_lineup(self):
        from aaa_engine.engine import optimize
        p=pool();m={r["pid"]:float(r["pid"]) for r in p}
        a=optimal(p,m);b=optimize(p,m)
        self.assertEqual(a["points"],b["expected_points"])
        self.assertEqual(set(a["lineup"].values()),set(b["lineup"].values()))
        self.assertIsNone(optimal([r for r in p if r["pos"]!="K"],m))
    def test_missing_weeks_and_swap(self):
        p=pool();q=swapped(p,2,{"pid":99,"pos":"RB"})
        self.assertEqual(len(p),len(q))
        self.assertTrue(any(r["pid"]==2 for r in p))
        self.assertFalse(any(r["pid"]==2 for r in q))
        d=delta({12:{"points":100},13:None,14:{"points":90}},
                {12:{"points":105},13:{"points":95},14:None},[12,13,14,15])
        self.assertEqual(d["points_delta"],5)
        self.assertEqual(d["restored_lineup_weeks"],[13])
        self.assertEqual(d["lost_lineup_weeks"],[14])
        self.assertEqual(d["unresolved_weeks"],[15])
    def test_common_draws_zero_change(self):
        p=pool();m={r["pid"]:float(r["pid"]) for r in p}
        a=optimal(p,m)
        other=[{**r,"pid":r["pid"]+100} for r in p]
        m.update({r["pid"]:float(r["pid"]-100) for r in other})
        b=optimal(other,m);meta={r["pid"]:r for r in p+other}
        residuals={r["pos"]:[-2.,0.,2.,4.,-4.,1.,-1.,0.] for r in p}
        q=paired_changes(a,a,b,b,m,meta,residuals,12,1000)
        self.assertEqual(q["win_fraction_delta"],0.)
        self.assertEqual(q["paired_mc_se"],0.)
        self.assertIsNone(paired_changes(a,None,b,b,m,meta,residuals,12,1000))
    def test_depth(self):
        p=pool();m={r["pid"]:float(r["pid"]) for r in p}
        self.assertGreater(depth(p,m,{"kickoffs":{"KC":"x"}},12,12)["unreplaceable_count"],0)
if __name__=="__main__":
    unittest.main()
