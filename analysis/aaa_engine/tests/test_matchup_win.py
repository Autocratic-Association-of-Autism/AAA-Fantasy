import unittest
import numpy as np
from aaa_engine.matchup_win import (fit_dependence,correlation_matrix,legal_lineups,
                                     sample_joint,select,win)
from aaa_engine.distributions import law

def player(pid,pos,team="KC"):
    return {"pid":pid,"pos":pos,"nfl_team":team}

class MatchupWinTests(unittest.TestCase):
    def test_signed_prior_fit_and_no_future(self):
        rows=[]
        for w in range(1,19):
            e=(-1)**w*4.
            rows.extend([{**player(1,"QB"),"week":w,"error":e},
                         {**player(2,"WR"),"week":w,"error":e},
                         {**player(3,"D/ST","DEN"),"week":w,"error":-e}])
        pbp={"opponents":{(w,t):o for w in range(1,19) for t,o in (("KC","DEN"),("DEN","KC"))}}
        f=fit_dependence(rows,pbp,17)
        self.assertGreater(f[("same_team","QB","WR")]["rho"],0)
        self.assertLess(f[("opposing_teams","D/ST","QB")]["rho"],0)
        self.assertEqual(f,fit_dependence([r for r in rows if r["week"]<17],pbp,17))

    def test_psd_and_common_marginals(self):
        players=[player(1,"QB"),player(2,"WR"),player(3,"D/ST","DEN")]
        fit={("same_team","QB","WR"):{"rho":.9},
             ("opposing_teams","D/ST","QB"):{"rho":-.9},
             ("opposing_teams","D/ST","WR"):{"rho":.9}}
        opp={"KC":"DEN","DEN":"KC"}
        c,d=correlation_matrix(players,opp,fit)
        self.assertGreater(np.linalg.eigvalsh(c).min(),0)
        np.testing.assert_allclose(np.diag(c),1.)
        self.assertGreater(d["max_psd_adjustment"],0.)
        laws={i:{"position":law([0.,20.])} for i in (1,2,3)}
        ix,a,b,_=sample_joint(players,laws,opp,fit,20000,17)
        np.testing.assert_allclose(a.mean(axis=1),10.,atol=.3)
        np.testing.assert_allclose(b.mean(axis=1),10.,atol=.3)
        _,a,b,_=sample_joint(players,laws,opp,{},2000,17)
        np.testing.assert_array_equal(a,b)

    def test_unique_legal_sets_and_win_objective(self):
        pool=[player(i,p) for i,p in enumerate(("QB","RB","RB","RB","WR","WR","WR","TE","D/ST","K"),1)]
        means={p["pid"]:float(p["pid"]) for p in pool}
        c=legal_lineups(pool,means)
        self.assertEqual(len(c),6)
        self.assertEqual(len({x["ids"] for x in c}),6)
        for x in c:
            self.assertEqual(len(x["lineup"]),9)
        # Higher mean can lose more often against a fixed threshold.
        mat=np.array([[0.,0.,30.],[9.,9.,9.],[8.,8.,8.]])
        ca=[{"ids":(1,),"mean":10.},{"ids":(2,),"mean":9.}]
        chosen=select(ca,[{"ids":(3,)}],{1:0,2:1,3:2},mat)
        self.assertEqual(chosen["ids"],(2,))
        self.assertEqual(win(np.array([1.,2.]),np.array([1.,3.])),.25)

if __name__=="__main__":
    unittest.main()
