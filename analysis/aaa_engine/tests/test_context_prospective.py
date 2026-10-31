"""v7: no-leakage tests for observational context and saved pregame scoring."""
import csv
import io
import unittest
from aaa_engine.contextual import (parse_snaps,snap_summary,allowed_context,
                                   teammate_context,verified_opponents,
                                   pass_protection_context)
from aaa_engine.prospective import evaluate_archive


class ContextTests(unittest.TestCase):
    def test_snap_pct_and_cutoff(self):
        data="season,week,player,team,offense_pct\n2026,6,Rachaad White,WSH,45%\n2026,7,Rachaad White,WSH,69%\n2026,8,Rachaad White,WSH,99%\n"
        snaps=parse_snaps(data,2026)
        r=snap_summary(snaps,"Rachaad White","WAS",7)
        self.assertEqual(r["weeks"],[6,7])
        self.assertAlmostEqual(r["recent_three_game_pct"],57.)
        self.assertFalse(r["applied_to_mean"])

    def test_verified_opponents(self):
        obj={"games":[{"teams":["KC","DEN"]}],"kickoffs":{"KC":"t","DEN":"t"}}
        self.assertEqual(verified_opponents(obj)["KC"],"DEN")

    def test_observed_defense_only_completed_weeks(self):
        base=dict(pos="RB",opponent="DEN",team="KC",receptions=2.,
                  rushing_yards=40.,receiving_yards=20.,
                  rushing_tds=0.,receiving_tds=0.,passing_yards=0.,
                  passing_tds=0.,interceptions=0.)
        rows=[{**base,"week":w} for w in (1,2,3)]
        rows.append({**base,"week":8,"rushing_yards":4000.})
        context=allowed_context(rows,"KC","DEN","RB",7)
        self.assertEqual(context["status"],"HISTORICAL_POSITION_ALLOWED")
        self.assertAlmostEqual(context["position_group_ppr_allowed"],8.)
        self.assertFalse(context["applied_to_mean"])

    def test_sack_rate_proxy_requires_verified_source(self):
        data=[{"week":w,"team":"KC","pos":"QB","attempts":30,
               "sacks_suffered":2,"has_sacks_source":True}
              for w in (1,2,3)]
        good=pass_protection_context(data,"KC",3)
        self.assertEqual(good["status"],"OBSERVED_TEAM_QB_SACK_RATE_PROXY")
        self.assertAlmostEqual(good["team_sacks_per_dropback"],.0625)
        # Explicit source absence must not be silently interpreted as zero sacks.
        data[0]["has_sacks_source"]=False
        self.assertEqual(pass_protection_context(data,"KC",3)["status"],
                         "SACKS_SOURCE_UNAVAILABLE")

    def test_teammate_report_requires_source(self):
        context={"verified_teammate_updates":[{"nfl_team":"ARI",
                  "name":"Test Player","status":"OUT",
                  "source_url":"https://example.org/report",
                  "as_of":"2026-10-29T12:00:00Z"}]}
        self.assertEqual(len(teammate_context(context,"ARI","2026-10-30T12:00:00Z")),1)
        with self.assertRaisesRegex(ValueError,"future"):
            teammate_context(context,"ARI","2026-10-28T12:00:00Z")
        context["verified_teammate_updates"][0]["source_url"]="rumor"
        with self.assertRaisesRegex(ValueError,"HTTPS"):
            teammate_context(context,"ARI","2026-10-30T12:00:00Z")


class ProspectiveTests(unittest.TestCase):
    def fixtures(self,as_of="2026-10-27T14:00:00Z",week=8):
        rows=[]
        pos=["QB","RB","RB","RB","WR","WR","WR","TE","D/ST","K"]
        team=[{"id":i+1,"name":f"Player {i+1}","position":p,
               "nfl_team":"ARI","baseline":8,
               "workload":{"ppr_points":9}} for i,p in enumerate(pos)]
        for p in team:
            rows.append({"week":week,"team_id":1,"player_id":p["id"],
                         "projected_points":7,
                         "points":10+(p["id"]%2)})
        snapshot={"League":[{"current_week":week+1,
                   "exported_utc":"2026-11-03T12:00:00Z"}],
                   "Weekly_Lineups":rows}
        starters={"QB":1,"RB1":2,"RB2":3,"WR1":5,
                  "WR2":6,"FLEX":4,"TE":8,"D/ST":9,"K":10}
        forecast={"week":week,"as_of":as_of,
                  "all_rosters":{"1":{"best":{"lineup":starters}}}}
        workload={"week":week,"as_of":as_of,
                  "status":"UNVALIDATED_SHADOW__NOT_PRIMARY_CALIBRATED_FORECAST",
                  "all_rosters":{"1":{"best":{"lineup":starters},
                     "player_projections":team}}}
        schedule={"week":week,"kickoffs":{"ARI":"2026-11-01T17:00:00Z"}}
        return snapshot,forecast,workload,schedule

    def test_only_finished_week_scored(self):
        a,b,c,d=self.fixtures()
        a["League"][0]["current_week"]=8
        self.assertEqual(evaluate_archive(a,b,c,d)["status"],"PENDING_UNFINISHED_WEEK")

    def test_complete_frozen_pregame_forecast_scored(self):
        a,b,c,d=self.fixtures()
        r=evaluate_archive(a,b,c,d)
        self.assertEqual(r["paired_players"],10)
        self.assertEqual(r["status"],"PROSPECTIVE_EVALUATION")
        self.assertEqual(r["team_lineup_results"]["1"]["lineup"]["status"],
                         "FULL_PREGAME_LINEUP_SCORED")
        self.assertFalse(r["promotion_eligible"])

    def test_friday_forecast_never_hindsight_scores_thursday(self):
        a,b,c,d=self.fixtures(as_of="2026-11-01T18:00:00Z")
        r=evaluate_archive(a,b,c,d)
        self.assertEqual(r["paired_players"],0)
        self.assertEqual(r["team_lineup_results"]["1"]["lineup"]["status"],
                         "NO_COMPLETE_PREGAME_LINEUP")


if __name__=="__main__":
    unittest.main()
