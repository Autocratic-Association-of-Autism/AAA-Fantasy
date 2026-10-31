"""Deterministic no-leakage tests for live NFL injury and route context."""
import csv
import io
import unittest
from aaa_engine.injury_context import (REQUIRED, parse_injuries, injury_match,
    team_injuries, route_report, enrich)


def injury_csv(rows):
    columns=sorted(REQUIRED | {"report_primary_injury"})
    out=io.StringIO()
    writer=csv.DictWriter(out,fieldnames=columns)
    writer.writeheader()
    for r in rows:
        writer.writerow({"season":"2026","season_type":"REG",
            "week":"8","team":"ARI","full_name":"Jeremiyah Love",
            "report_status":"Questionable","practice_status":"Limited",
            "date_modified":"2026-10-30T10:00:00Z",
            "report_primary_injury":"Ankle",**r})
    return out.getvalue()


class InjuryTests(unittest.TestCase):
    def test_current_week_and_future_record_cutoff(self):
        rows=parse_injuries(injury_csv([
            {"report_status":"Questionable"},
            {"report_status":"Out","date_modified":"2026-10-31T10:00:00Z"},
        ]),2026)
        value=injury_match(rows,"Jeremiyah Love","ARI",8,
                           "2026-10-30T21:00:00Z")
        self.assertEqual(value["game_status"],"QUESTIONABLE")
        self.assertTrue(value["record_timestamp_verified"])
        self.assertEqual(injury_match(rows,"Jeremiyah Love","ARI",9,
                                     "2026-10-30T21:00:00Z")["status"],
                         "NOT_ON_CURRENT_WEEK_REPORT")

    def test_not_listed_does_not_mean_healthy(self):
        rows=parse_injuries(injury_csv([] if False else [
            {"full_name":"Another Player"}]),2026)
        out=injury_match(rows,"Jeremiyah Love","ARI",8,
                         "2026-10-30T21:00:00Z")
        self.assertFalse(out["reported"])
        self.assertTrue(out["not_necessarily_healthy"])

    def test_team_updates_with_current_week_only(self):
        records=parse_injuries(injury_csv([
            {"report_status":"Out"},
            {"report_status":"Questionable","week":"7",
             "full_name":"Other RB"}]),2026)
        result=team_injuries(records,"ARI",8,"2026-10-30T20:00:00Z")
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["game_status"],"OUT")

    def test_route_source_validation(self):
        base={"name":"Jeremiyah Love","nfl_team":"ARI","week":7,
              "routes_run":16,"team_dropbacks":30,
              "source_url":"https://source.example/report",
              "as_of":"2026-10-29T12:00:00Z"}
        context={"verified_route_reports":[base]}
        out=route_report(context,"Jeremiyah Love","ARI",7,
                         "2026-10-30T21:00:00Z")
        self.assertEqual(out["status"],"SOURCED_HISTORICAL_ROUTE_COUNT")
        self.assertEqual(out["routes_per_team_dropback"],.533)
        self.assertFalse(out["applied_to_mean"])
        bad={**base,"week":8}
        with self.assertRaisesRegex(ValueError,"prior completed"):
            route_report({"verified_route_reports":[bad]},"Jeremiyah Love",
                         "ARI",7,"2026-10-30T21:00:00Z")
        with self.assertRaisesRegex(ValueError,"future"):
            route_report({"verified_route_reports":[{**base,
                "as_of":"2026-10-31T21:00:00Z"}]},"Jeremiyah Love",
                "ARI",7,"2026-10-30T21:00:00Z")

    def test_out_conflict_is_flag_not_unvalidated_multiplier(self):
        rows=parse_injuries(injury_csv([{"report_status":"Out"}]),2026)
        report={"week":8,"as_of":"2026-10-30T21:00:00Z",
                "historical_cutoff_week":7,"your_team_id":1,
                "all_rosters":{"1":{"player_projections":[{
                    "name":"Jeremiyah Love","position":"RB","nfl_team":"ARI",
                    "injury_status_from_espn":"ACTIVE",
                    "baseline":10.1,"workload":{"ppr_points":11.3}}],
                    "best":{"expected_points":100,"lineup":{"FLEX":101}}}}}
        after=enrich(report,rows,{"uri":"https://source.example"},None)
        player=after["your_team"]["player_projections"][0]
        self.assertTrue(player["injury_status_conflict"])
        self.assertEqual(after["your_team"]["best"]["expected_points"],100)
        self.assertTrue(after["your_team"]["requires_official_inactive_review"])


if __name__=="__main__":
    unittest.main()
