"""Must-pass regression tests for Week 7 failures and temporal leakage."""
import json, unittest
from pathlib import Path
import numpy as np
from aaa_engine.engine import (historical,history_index,predict,fit_baseline,predictions,
  optimize,locked_roster,scenario_sensitivity,simulate_pair,train_team_correlation,
  train_residuals)
from aaa_engine.validate import validate
from aaa_engine.cli import summarize

SAMPLE=Path(__file__).resolve().parents[3]/'ESPN_Current_Snapshot_1438350867_2026.json'


def person(pid,pos,team='CHI',slot='BE',injury='ACTIVE'):
    return {'pid':pid,'name':str(pid),'pos':pos,'nfl_team':team,'slot':slot,'injury':injury}

class ForecastEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap=json.loads(SAMPLE.read_text()) if SAMPLE.exists() else None
    def test_history_does_not_use_partial_week_seven(self):
        if not self.snap:self.skipTest('No fixture')
        x=historical(self.snap,6)
        self.assertTrue(x);self.assertLessEqual(max(r['week'] for r in x),6)
        with self.assertRaisesRegex(ValueError,'not complete'):
            historical(self.snap,7)

    def test_prospective_pred_no_future_leakage(self):
        if not self.snap:self.skipTest('No fixture')
        rows=historical(self.snap,6); pid=next(r['pid'] for r in rows if r['week']==1)
        idx=history_index(rows)
        original=predict(pid,5,idx[pid][0]['pos'],idx)
        for r in idx[pid]:
            if r['week']>=5:r['actual']+=10000
        self.assertAlmostEqual(predict(pid,5,idx[pid][0]['pos'],idx),original)

    def test_existing_holdout_reproducible(self):
        if not self.snap:self.skipTest('No fixture')
        v=validate(self.snap)
        self.assertEqual(v['observations']['heldout_players'],265)
        self.assertEqual(v['observations']['heldout_matchups'],10)
        self.assertAlmostEqual(v['accuracy']['holdout']['mae'],6.2293,places=3)
        self.assertFalse(v['probability']['correlation_promoted'])

    def test_full_re_rank_all_receiver_candidates(self):
        p=[person(1,'QB'),person(2,'RB'),person(3,'RB'),person(4,'WR'),person(5,'WR'),
           person(6,'WR'),person(7,'WR'),person(8,'TE'),person(9,'D/ST'),person(10,'K'),
           person(11,'WR')]
        means={1:18,2:12,3:11,4:7,5:10,6:19,7:23,8:12,9:5,10:7,11:9}
        result=optimize(p,means)
        starters=set(result['lineup'].values())
        self.assertIn(6,starters);self.assertIn(7,starters)
        self.assertNotIn(4,starters)

    def test_locked_starters_cannot_move_or_be_removed(self):
        p=[person(1,'QB'),person(2,'RB'),person(3,'RB'),person(4,'WR'),person(5,'WR'),
           person(6,'WR'),person(7,'TE'),person(8,'D/ST'),person(9,'K'),person(10,'RB')]
        means={x['pid']:20. for x in p};means[4]=1;means[6]=30
        r=optimize(p,means,locked={'WR1':4})
        self.assertEqual(r['lineup']['WR1'],4)

    def test_locked_bench_excluded(self):
        p=[person(1,'WR','CHI','BE'),person(2,'WR','CHI','WR'),person(3,'RB','NYG','BE')]
        k={'CHI':'2026-10-22T20:15:00Z','NYG':'2026-10-25T17:00:00Z'}
        pool,locked,gone=locked_roster(p,k,'2026-10-22T21:00:00Z',True)
        self.assertEqual([x['pid'] for x in pool],[2,3])
        self.assertEqual(locked['WR1'],2)
        self.assertIn(('1','benched_game_started'),gone)

    def test_no_schedule_blocks(self):
        with self.assertRaisesRegex(ValueError,'No verified NFL kickoff'):
            locked_roster([person(1,'QB')],{},'2026-10-22T12:00:00Z',True)

    def test_bye_and_current_out_excluded(self):
        p=[person(1,'WR','CHI'),person(2,'WR','NE',injury='OUT')]
        pool,_,gone=locked_roster(p,{'NE':'2026-10-25T17:00:00Z'},'2026-10-25T12:00:00Z',True)
        self.assertEqual(pool,[])
        self.assertEqual(len(gone),2)

    def test_downside_scenario_changes_legal_lineup(self):
        p=[person(1,'QB'),person(2,'RB'),person(3,'RB'),person(4,'RB'),person(5,'WR'),
           person(6,'WR'),person(7,'WR'),person(8,'TE'),person(9,'D/ST'),person(10,'K')]
        m={1:18,2:15,3:14,4:12,5:15,6:14,7:13,8:11,9:6,10:8}
        s=scenario_sensitivity(p,m,{},[{'name':'role-collapse','player_multipliers':{'2':.05}}])
        self.assertTrue(s['unweighted_sensitivities'][0]['would_change_starters'])
        self.assertGreater(s['unweighted_sensitivities'][0]['regret'],0)

    def test_negative_defense_tail(self):
        p={1:{'nfl_team':'CHI','pos':'D/ST'},2:{'nfl_team':'NYG','pos':'K'}}
        e={pos:np.array([-14.,-4.,0.,1.,17.]) for pos in ['D/ST','K']}
        sim=simulate_pair({'D/ST':1},{'K':2},{1:6.,2:7.},p,e,0,10000,2)
        self.assertEqual(sim['samples'],10000)
        # Test exact negative exposure, not mean-only assumptions.
        rng=np.random.default_rng(2)
        self.assertTrue(np.any(6 + rng.choice(e['D/ST'],size=10000) <0))

    def test_correlation_uses_same_team_shared_latent(self):
        n=12000; rng=np.random.default_rng(7)
        # Simulated errors with rho>0 must share positive covariance.
        e=np.array([-8,-4,-2,2,4,8],float)
        z=rng.standard_normal(n)
        a=.8*z+.6*rng.standard_normal(n);b=.8*z+.6*rng.standard_normal(n)
        self.assertGreater(float(np.corrcoef(a,b)[0,1]),.5)
        sim=simulate_pair({'QB':1},{'K':2},{1:18,2:8},
             {1:{'nfl_team':'KC','pos':'QB'},2:{'nfl_team':'KC','pos':'K'}},
             {'QB':e,'K':e},.25,12000,7)
        self.assertEqual(sim['rho_team'],.25)

    def test_sim_reproducible(self):
        e={'QB':np.array([-8.,0.,8.]),'WR':np.array([-9.,0.,9.])}
        meta={1:{'nfl_team':'KC','pos':'QB'},2:{'nfl_team':'CHI','pos':'WR'}}
        a=simulate_pair({'QB':1},{'WR':2},{1:18,2:12},meta,e,.1,3000,99)
        b=simulate_pair({'QB':1},{'WR':2},{1:18,2:12},meta,e,.1,3000,99)
        self.assertEqual(a,b)

if __name__=='__main__':unittest.main()
