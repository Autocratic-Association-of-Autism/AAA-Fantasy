import unittest
from aaa_engine.integrated_audit import capture_espn, audit, blend_forecast

class IntegratedAuditTests(unittest.TestCase):
    def test_espn_capture_target_week_and_kickoff(self):
        snap={"League":[{"current_week":12,"scoring_period_id":12,"exported_utc":"2026-11-24T16:00:00Z"}],
              "Weekly_Lineups":[{"week":12,"position":"QB","lineup_slot":"QB","pro_team":"KC","team_id":1,"player_id":3,"projected_points":20},
                                {"week":12,"position":"WR","lineup_slot":"WR","pro_team":"DEN","team_id":1,"player_id":4,"projected_points":10}]}
        f={"week":12,"as_of":"2026-11-24T17:00:00Z"}
        s={"week":12,"complete":True,"kickoffs":{"KC":"2026-11-26T17:00:00Z","DEN":"2026-11-24T16:30:00Z"}}
        out=capture_espn(snap,f,s)
        self.assertEqual([p["player_id"] for p in out["players"]],[3])
        f["week"]=13
        self.assertEqual(capture_espn(snap,f,s)["status"],"BLOCKED_ESPN_TARGET_WEEK_MISMATCH")

    def test_blend_refuses_started_week(self):
        f={"week":12,"as_of":"2026-11-26T18:00:00Z"}
        s={"kickoffs":{"KC":"2026-11-26T17:00:00Z"}}
        self.assertEqual(blend_forecast(f,{}, {},s)["status"],"BLOCKED_BLEND_AFTER_KICKOFF")

    def test_audit_does_not_promote_on_missing_reports(self):
        result=audit({"week":12,"as_of":"2026-11-24T17:00:00Z"},*([{}]*9))
        self.assertFalse(result["promotion_eligible"])
        self.assertEqual(result["production_model"],"v5-lagged-ppr-control")
if __name__=="__main__":unittest.main()
