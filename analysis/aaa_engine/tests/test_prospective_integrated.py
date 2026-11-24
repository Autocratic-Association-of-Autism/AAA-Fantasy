import unittest
from aaa_engine.prospective_integrated import verify_archive,metrics,report,evaluate

class StrictProspectiveTests(unittest.TestCase):
    def fixture(self):
        ts="2026-11-25T12:00:00Z";kick="2026-11-26T18:00:00Z"
        f={"week":12,"as_of":ts,"snapshot_sha256":"a","schedule_sha256":"b"}
        s={"week":12,"complete":True,"kickoffs":{"KC":kick}}
        e={"week":12,"status":"PREGAME_EXPORT_PROJECTIONS_CAPTURED","forecast_as_of":ts,
           "exported_utc":ts,"snapshot_sha256":"a","schedule_sha256":"b"}
        b={"week":12,"as_of":ts,"status":"UNVALIDATED_FIXED_BLEND_SHADOW"}
        r={"id":3,"status":"completed","conclusion":"success","head_branch":"main","event":"push",
           "created_at":ts,"updated_at":"2026-11-25T12:05:00Z"}
        return {"forecast":f,"nfl_kickoffs":s,"espn_pregame":e,"blend_forecast":b},r,s
    def test_completed_before_kickoff(self):
        a,r,s=self.fixture()
        self.assertEqual(verify_archive(a,r,12,s)["run_id"],3)
        r["updated_at"]="2026-11-26T18:01:00Z"
        with self.assertRaises(ValueError):verify_archive(a,r,12,s)
    def test_reject_pr_hash_and_moved_kickoff(self):
        a,r,s=self.fixture();r["event"]="pull_request"
        with self.assertRaises(ValueError):verify_archive(a,r,12,s)
        r["event"]="push";a["espn_pregame"]["snapshot_sha256"]="bad"
        with self.assertRaises(ValueError):verify_archive(a,r,12,s)
        a["espn_pregame"]["snapshot_sha256"]="a"
        with self.assertRaises(ValueError):verify_archive(a,r,12,{**s,"kickoffs":{"KC":"2026-11-25T11:00:00Z"}})
    def test_matched_zero_actual_and_missing_model(self):
        rows=[{"actual":0.,"baseline":8.,"espn":10.},{"actual":20.,"baseline":18.}]
        x=metrics(rows,("baseline","espn"))
        self.assertEqual(x["n"],1);self.assertEqual(x["models"]["baseline"]["mae"],8.)
    def test_full_two_team_final_score_and_lineup_reconciliation(self):
        a,entry,schedule=self.fixture()
        schedule["games"]=[{"completed":True,"status_state":"post"}]
        snap={"League":[{"current_week":13,"exported_utc":"2026-12-01T12:00:00Z"}],
              "Teams":[{"team_id":1},{"team_id":2}],"Weekly_Lineups":[],"Weekly_Matchups":[]}
        a["forecast"]["all_rosters"]={}
        a["blend_forecast"]["all_rosters"]={}
        a["espn_pregame"]["players"]=[]
        slots=("QB","RB1","RB2","WR1","WR2","TE","FLEX","D/ST","K")
        pos=("QB","RB","RB","WR","WR","TE","RB","D/ST","K","WR")
        totals={}
        for tid in (1,2):
            ids=[tid*100+i for i in range(10)]
            ids[7]=-16000-tid
            vals=[float(i+tid) for i in range(10)]
            vals[0]=0.
            totals[tid]=sum(vals[:9])
            line={"lineup":dict(zip(slots,ids[:9]))}
            players=[]
            for i,(pid,p,v) in enumerate(zip(ids,pos,vals)):
                snap["Weekly_Lineups"].append({"week":12,"team_id":tid,"player_id":pid,
                    "position":p,"pro_team":"KC","lineup_slot":slots[i] if i<9 else "BE",
                    "points":v,"projected_points":0})
                players.append({"pid":pid,"position":p,"nfl_team":"KC","baseline":v+2,
                    "blend_baseline_v2":v+1,"blend_baseline_volume":v+3})
                a["espn_pregame"]["players"].append({"team_id":tid,"player_id":pid,"position":p,
                    "nfl_team":"KC","kickoff_utc":schedule["kickoffs"]["KC"],"projected_points":v+4})
            a["forecast"]["all_rosters"][str(tid)]={"player_means":{str(i):v+2 for i,v in zip(ids,vals)},
                "best":line}
            a["blend_forecast"]["all_rosters"][str(tid)]={"players":players,
                "choices":{"blend_baseline_v2":line,"blend_baseline_volume":line}}
        snap["Weekly_Matchups"]=[{"week":12,"home_team_id":1,"away_team_id":2,
                                  "home_score":totals[1],"away_score":totals[2]}]
        result=evaluate(snap,a,entry,12,schedule)
        self.assertEqual(result["status"],"STRICT_PREGAME_PROSPECTIVE_EVALUATION")
        m=result["player_comparisons"]["blend_baseline_v2"]
        self.assertEqual(m["n"],20)
        self.assertAlmostEqual(m["models"]["baseline"]["mae"],2.)
        self.assertAlmostEqual(m["models"]["espn"]["mae"],4.)
        self.assertAlmostEqual(m["models"]["blend_baseline_v2"]["mae"],1.)
        self.assertEqual(result["lineup_comparisons"]["blend_baseline_v2"]["n"],2)
        self.assertEqual(result["margin_comparisons"]["blend_baseline_v2"]["n"],1)
        snap["Weekly_Matchups"][0]["home_score"]+=1.
        with self.assertRaisesRegex(ValueError,"reconcile"):
            evaluate(snap,a,entry,12,schedule)
    def test_pending_before_completed_week_12(self):
        r=report({"League":[{"current_week":12}]},"r","t")
        self.assertEqual(r["status"],"PENDING_FIRST_INTEGRATED_COMPLETED_WEEK")
        self.assertFalse(r["promotion_eligible"])
if __name__=="__main__":unittest.main()
