import unittest
import numpy as np
from aaa_engine.season_simulation import seeds,postseason,simulate_regular,partial_lineup

class SeasonTests(unittest.TestCase):
    def test_division_leader_priority_and_ties(self):
        w=np.array([[9],[8],[7],[6],[5],[5],[4],[3],[2],[1]],float)
        pf=np.array([[100],[100],[110],[90],[100],[101],[100],[100],[100],[100]])
        d=[0,0,1,1,0,1,0,1,0,1]
        self.assertEqual(seeds(w,pf,d)[:,0].tolist()[:4],[0,2,1,3])
        self.assertEqual(seeds(w,pf,d,False)[:,0].tolist()[:3],[0,1,2])
        self.assertLess(seeds(w,pf,d)[:,0].tolist().index(5),seeds(w,pf,d)[:,0].tolist().index(4))
    def test_sacko_two_week_aggregate_not_regular_last(self):
        order=np.arange(10)[:,None]
        a=np.array([[100],[90],[80],[70],[60],[50],[40],[30],[20],[10]])
        b=a.copy();c=a.copy()
        # Week 15 losers: seed 10 and seed 9. Seed 10 wins aggregate.
        b[9]=100;c[9]=100
        champion,sacko=postseason(order,{15:a,16:b,17:c},14)
        self.assertEqual(champion[0],0)
        self.assertEqual(sacko[0],8)
    def test_regular_win_credit_conservation(self):
        x=np.array([[100,90],[90,90]])
        w,p,_=simulate_regular({12:x},{12:[(1,2)]},[1,2],np.array([4.,5.]),np.array([1000,1100]))
        np.testing.assert_allclose(w.sum(axis=0),10.)
        np.testing.assert_array_equal(p,np.array([[1100,1090],[1190,1190]]))
    def test_empty_slot_is_explicit(self):
        pool=[{"pid":1,"pos":"QB"}]
        chosen,missing=partial_lineup(pool,{1:10.})
        self.assertEqual(chosen,{"QB":1})
        self.assertEqual(len(missing),8)
if __name__=="__main__":
    unittest.main()
