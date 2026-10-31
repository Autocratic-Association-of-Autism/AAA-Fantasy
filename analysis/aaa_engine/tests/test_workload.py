"""Deterministic tests for v6 workload input provenance and forecast boundaries."""
import csv
import io
import unittest

from aaa_engine.workload import (METRICS, NEEDED, clean_name, expected,
                                  lookup, parse_feed)


def row(name="Test Player", team="ARI", pos="RB", week=1,
        carries=10, targets=3, receptions=2, rushing_yards=45,
        receiving_yards=20):
    return {"name":name, "name_key":clean_name(name), "team":team,
            "pos":pos,"week":week,
            **{k:0. for k in METRICS},
            "carries":float(carries), "targets":float(targets),
            "receptions":float(receptions), "rushing_yards":float(rushing_yards),
            "receiving_yards":float(receiving_yards)}


class WorkloadTests(unittest.TestCase):
    def test_2026_csv_validation_and_week_filter(self):
        headers = sorted(NEEDED)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer,headers)
        writer.writeheader()
        for wk in (1,2,3,8):
            data={x:"0" for x in headers}
            data.update({"player_display_name":"A.J. Brown",
                         "recent_team":"NE","position":"WR",
                         "season":"2026","season_type":"REG","week":str(wk),
                         "targets":"8","receptions":"5"})
            writer.writerow(data)
        parsed=parse_feed(buffer.getvalue(),2026)
        past,reason=lookup(parsed,"AJ Brown","NE","WR",7)
        self.assertIsNone(reason)
        self.assertEqual([x["week"] for x in past],[1,2,3])
        self.assertIsNone(lookup(parsed,"AJ Brown","CHI","WR",7)[0] or None)

    def test_missing_critical_field_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"Missing required"):
            parse_feed("season,week,player_display_name\\n2026,1,x\\n",2026)

    def test_opportunity_volume_changes_projection(self):
        previous=[row(week=i) for i in range(1,5)]
        improved=previous+[row(week=5,carries=22,targets=7,
                               receptions=6,rushing_yards=101,
                               receiving_yards=56)]
        a=expected(previous,"RB",6,5)
        b=expected(improved,"RB",6,5)
        self.assertGreater(b["expected_carries"],a["expected_carries"])
        self.assertGreater(b["expected_targets"],a["expected_targets"])
        self.assertGreater(b["ppr_points"],a["ppr_points"])
        self.assertIn("expected_rushing_tds",b)

    def test_thursday_current_week_stats_not_used(self):
        rows=[row(week=i) for i in range(1,8)]
        rows.append(row(week=8,carries=100,targets=40))
        eligible,_=lookup(rows,"Test Player","ARI","RB",7)
        self.assertEqual(len(eligible),7)
        self.assertEqual(max(x["week"] for x in eligible),7)
        self.assertLess(expected(eligible,"RB",8,7)["expected_carries"],20)

    def test_injury_missed_game_flag_and_nonvalidated_intervals(self):
        data=[row(week=1),row(week=2),row(week=5)]
        p=expected(data,"RB",8,7)
        self.assertIn("long_absence_role_unverified",p["role_flags"])
        self.assertTrue(p["interval_80_heuristic"][0] <= p["ppr_points"])
        self.assertTrue(p["interval_80_heuristic"][1] >= p["ppr_points"])

    def test_name_and_team_must_match_without_invention(self):
        data=[row(name="K.C. Concepcion",team="CLE")]
        matched, reason=lookup(data,"KC Concepcion","CLE","RB",5)
        self.assertEqual(len(matched),1)
        _, reason=lookup(data,"KC Concepcion","ARI","RB",5)
        self.assertEqual(reason,"nfl_team_not_matched")
        _, reason=lookup(data,"KC Concepcion","CLE","WR",5)
        self.assertEqual(reason,"no_verified_name_match")


if __name__ == "__main__":
    unittest.main()
