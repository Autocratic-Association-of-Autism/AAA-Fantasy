"""v7: no-leakage tests for observational context and saved pregame scoring."""
import csv
import io
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from aaa_engine.contextual import (parse_snaps,snap_summary,allowed_context,
                                   teammate_context,verified_opponents,
                                   pass_protection_context)
from aaa_engine.prospective import (evaluate_archive, prospective_report,
                                   eligible_report_from_directory)


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

    def v2_fixture(self, workload, as_of=None):
        roster = workload["all_rosters"]["1"]
        return {
            "status": "UNVALIDATED_OPPORTUNITY_V2_SHADOW",
            "week": workload["week"],
            "as_of": as_of or workload["as_of"],
            "all_rosters": {"1": {
                "best_shadow": roster["best"],
                "players": [
                    {"id": p["id"], "nfl_team": p["nfl_team"],
                     "position": p["position"], "locked_actual": False,
                     "v2": {"status": "EXPERIMENTAL_OPPORTUNITY_V2_NOT_CALIBRATED",
                            "ppr_points": 10.0}}
                    for p in roster["player_projections"]
                ],
            }},
        }

    def test_genuine_v2_scored_only_on_identical_pregame_players(self):
        snap, base, work, kickoff = self.fixtures()
        v2 = self.v2_fixture(work)
        result = evaluate_archive(snap, base, work, kickoff, 123, v2)
        self.assertEqual(result["paired_players"], 10)
        self.assertEqual(result["v2_paired_players"], 10)
        self.assertEqual(result["v2_archive_status"], "AVAILABLE_FROZEN_SHADOW")
        self.assertIsNotNone(result["v2_mae"])
        self.assertLess(result["v2_mae"], result["v2_paired_workload_mae"])
        lineup = result["team_lineup_results"]["1"]["lineup"]
        self.assertEqual(lineup["v2_hybrid_shadow_actual"], lineup["workload_actual"])
        self.assertFalse(result["promotion_eligible"])

    def test_v2_fallbacks_not_labeled_genuine_and_bad_timestamp_excluded(self):
        snap, base, work, kickoff = self.fixtures()
        v2 = self.v2_fixture(work)
        v2["all_rosters"]["1"]["players"][0]["v2"] = None
        result = evaluate_archive(snap, base, work, kickoff, v2=v2)
        self.assertEqual(result["v2_paired_players"], 9)
        self.assertEqual(result["skipped"]["no_genuine_v2_projection"], 1)
        v2["as_of"] = "2026-11-04T14:00:00Z"
        rejected = evaluate_archive(snap, base, work, kickoff, v2=v2)
        self.assertEqual(rejected["v2_archive_status"], "BLOCKED_INVALID_V2_ARCHIVE")
        self.assertEqual(rejected["v2_paired_players"], 0)
        self.assertNotIn("v2_hybrid_shadow_actual",
                         rejected["team_lineup_results"]["1"]["lineup"])

    def test_week_8_archive_can_omit_new_v2_file(self):
        snap, base, work, kickoff = self.fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            for name, obj in (("forecast.json", base),
                              ("workload_forecast.json", work),
                              ("nfl_kickoffs.json", kickoff)):
                (Path(tmp) / name).write_text(json.dumps(obj))
            self.assertEqual(len(eligible_report_from_directory(tmp)), 4)
            self.assertIsNone(eligible_report_from_directory(tmp)[3])
            (Path(tmp) / "opportunity_v2_forecast.json").write_text(
                json.dumps(self.v2_fixture(work)))
            self.assertIsNotNone(eligible_report_from_directory(tmp)[3])

    def test_recent_frozen_runs_not_skipped_and_pr_runs_excluded(self):
        snap, base, work, kickoff = self.fixtures()
        # Old code sorted oldest-first, then inspected only the first six.
        # The relevant pregame forecast is the newest main-branch archive.
        runs = []
        for number in range(15):
            runs.append({
                "id": 100 + number,
                "created_at": f"2026-10-{number+1:02d}T10:00:00Z",
                "head_branch": "main",
                "event": "workflow_run",
                "conclusion": "success",
            })
        runs.append({
            "id": 900, "created_at": "2026-10-27T14:00:00Z",
            "head_branch": "main", "event": "workflow_dispatch",
            "conclusion": "success"})
        runs.append({
            "id": 901, "created_at": "2026-10-28T14:00:00Z",
            "head_branch": "feature/test", "event": "pull_request",
            "conclusion": "success"})
        seen = []
        def loader(repo, token, run_id):
            seen.append(run_id)
            return (base, work, kickoff) if run_id == 900 else (
                self.fixtures(week=7)[1:])
        with patch("aaa_engine.prospective.github_json",
                   return_value={"workflow_runs": runs}):
            r = prospective_report(snap, "test/AAA", "dummy", archive_loader=loader)
        self.assertEqual(r["source_run_id"], 900)
        self.assertEqual(r["paired_players"], 10)
        self.assertEqual(seen[0], 900)
        self.assertNotIn(901, seen)
        self.assertGreater(r["candidate_archives_inspected"], 0)

    def test_only_unfinished_archives_do_not_become_prospective(self):
        snap, base, work, kickoff = self.fixtures()
        upcoming, forecast, workload, schedule = self.fixtures(week=9)
        rows = [{"id": 1, "created_at": "2026-11-03T15:00:00Z",
                 "conclusion": "success", "head_branch": "main",
                 "event": "push"}]
        with patch("aaa_engine.prospective.github_json",
                   return_value={"workflow_runs": rows}):
            result = prospective_report(
                snap, "test/AAA", "dummy",
                archive_loader=lambda repo, token, run_id:
                    (forecast, workload, schedule, None))
        self.assertEqual(result["status"], "PENDING_NO_ELIGIBLE_PRIOR_FORECAST")
        self.assertEqual(result["candidate_archives_eligible"], 0)

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
