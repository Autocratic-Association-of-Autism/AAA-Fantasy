import unittest
from datetime import datetime,timezone,timedelta
from aaa_engine.refresh_guard import decide,snapshot_freshness,has_artifact,EXPORT,FORECAST
NOW=datetime(2026,11,24,20,0,tzinfo=timezone.utc)
def run(i,minutes,status="completed",conclusion="success",branch="main",duration=2):
    end=NOW-timedelta(minutes=minutes)
    return {"id":i,"status":status,"conclusion":conclusion,"head_branch":branch,
            "event":"schedule","updated_at":end.isoformat(),"created_at":(end-timedelta(minutes=duration)).isoformat()}
class RefreshGuardTests(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(decide(NOW,[run(1,45)],[run(2,35)],True,True)["status"],"REFRESH_HEALTHY")
    def test_stale_missing_failed_and_pr_export(self):
        self.assertEqual(decide(NOW,[run(1,196)],[],True,False)["dispatch"],EXPORT)
        self.assertEqual(decide(NOW,[run(1,10)],[],False,False)["dispatch"],EXPORT)
        self.assertEqual(decide(NOW,[run(1,10,conclusion="failure"),run(2,1,branch="pr")],[],True,False)["dispatch"],EXPORT)
    def test_active_suppresses_duplicate(self):
        self.assertIsNone(decide(NOW,[run(1,250),run(2,1,status="queued",conclusion=None)],[],True,False)["dispatch"])
        self.assertIsNone(decide(NOW,[run(1,20)],[run(2,1,status="in_progress",conclusion=None)],True,False)["dispatch"])
    def test_forecast_not_fresh_for_latest_export(self):
        self.assertEqual(decide(NOW,[run(1,20)],[run(2,25)],True,True)["dispatch"],FORECAST)
        self.assertEqual(decide(NOW,[run(1,20)],[run(2,10)],True,False)["dispatch"],FORECAST)
    def test_freshness_boundaries(self):
        for age,status,ok in [(0,"FRESH_WITHIN_THREE_HOURS",True),(181,"DELAYED_BUT_WITHIN_LIMIT",True),
                              (241,"BLOCKED_STALE_EXPORT",False),(-1,"BLOCKED_FUTURE_EXPORT",False)]:
            x=snapshot_freshness((NOW-timedelta(minutes=age)).isoformat(),NOW,10)
            self.assertEqual(x["status"],status);self.assertEqual(x["actionable"],ok)
    def test_artifact_expiration(self):
        self.assertFalse(has_artifact([{"name":"x","expired":True,"size_in_bytes":100}],"x"))
        self.assertTrue(has_artifact([{"name":"x","expired":False,"size_in_bytes":100}],"x"))
if __name__=="__main__":unittest.main()
