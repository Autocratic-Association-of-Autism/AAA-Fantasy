import unittest
from aaa_engine.prospective_integrated import verify_archive,metrics,report

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
    def test_pending_before_completed_week_12(self):
        r=report({"League":[{"current_week":12}]},"r","t")
        self.assertEqual(r["status"],"PENDING_FIRST_INTEGRATED_COMPLETED_WEEK")
        self.assertFalse(r["promotion_eligible"])
if __name__=="__main__":unittest.main()
