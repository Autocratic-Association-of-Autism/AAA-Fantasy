"""Lagged participation cohort regression tests; no medical inference."""
import unittest

from aaa_engine.participation_risk import (
    adjusted, build_index, cases, cohort_factors, risk_state, control)


def fixture():
    stats, snaps, offense = [], [], {}
    # Week 4 is a bye. Week 5 has no matched player snap row;
    # Week 6 is a low-snap return. Week 7 is the future observation.
    for w in (1, 2, 3, 5, 6, 7):
        offense[(w, "KC")] = {}
        for i in range(22):
            snaps.append({"team":"KC", "week":w, "name_key":f"other{i}",
                          "offensive_snap_fraction":.5})
    for w, f in ((1,.8),(2,.8),(3,.8),(6,.3),(7,.9)):
        snaps.append({"team":"KC","week":w,"name_key":"test",
                      "offensive_snap_fraction":f})
        stats.append({"team":"KC","week":w,"name_key":"test","pos":"RB",
            "targets":3., "carries":10., "attempts":0., "receptions":2.,
            "receiving_yards":20., "rushing_yards":40., "passing_yards":0.,
            "receiving_tds":0., "rushing_tds":0., "passing_tds":0.,
            "interceptions":0., "receiving_fumbles_lost":0.,
            "rushing_fumbles_lost":0., "sack_fumbles_lost":0.})
    return stats,snaps,{"offense":offense,"included_through_week":7}


class ParticipationRiskTests(unittest.TestCase):
    def test_bye_does_not_count_and_future_cannot_change_risk(self):
        stats, snaps, pbp = fixture()
        key=("KC","test","RB")
        i=build_index(stats,snaps,pbp,7)
        self.assertEqual(risk_state(i,key,5)["class"],"NORMAL_OBSERVED")
        r=risk_state(i,key,6)
        self.assertEqual(r["class"],"GAP_1")
        self.assertEqual(r["missed_team_games"],[5])
        self.assertEqual(risk_state(i,key,7)["class"],"RECENT_SNAP_DROP")
        early=build_index(stats,snaps,pbp,5)
        self.assertEqual(risk_state(early,key,6),r)
        self.assertEqual(control(early,key,6),control(i,key,6))
        self.assertEqual(risk_state(i,("KC","missing","RB"),6)["class"],"UNKNOWN")

    def test_missing_team_feed_not_player_absence(self):
        stats,snaps,pbp=fixture()
        i=build_index(stats,[r for r in snaps if r["week"]!=5],pbp,5)
        self.assertEqual(risk_state(i,("KC","test","RB"),6)["class"],"UNKNOWN")

    def test_cases_use_earlier_risk_class_not_current_snap(self):
        stats,snaps,pbp=fixture()
        c=cases(build_index(stats,snaps,pbp,7))
        self.assertEqual([(r["week"],r["class"]) for r in c],
                         [(6,"GAP_1"),(7,"RECENT_SNAP_DROP")])

    def test_cohort_minimum_and_no_future_or_same_player(self):
        rows=[{"week":4,"position":"RB","class":"GAP_1","key":("KC",str(i),"RB"),
               "actual":{"carries":5,"targets":0,"attempts":0},
               "control":{"carries":10,"targets":0,"attempts":0}}
              for i in range(20)]
        blocked=cohort_factors(rows,"GAP_1","RB",4)
        self.assertEqual(blocked["status"],"INSUFFICIENT_PRIOR_COHORT")
        fit=cohort_factors(rows,"GAP_1","RB",5)
        self.assertEqual(fit["factors"]["carries"]["factor"],.75)
        self.assertNotIn("targets",fit["factors"])
        self.assertEqual(cohort_factors(rows,"GAP_1","RB",5,("KC","0","RB"))["cases"],19)
        self.assertEqual(cohort_factors(rows[:10],"GAP_1","RB",5)["factors"],{})

    def test_neutral_fallback_and_opportunity_only_adjustment(self):
        stats,snaps,pbp=fixture()
        base=control(build_index(stats,snaps,pbp,5),("KC","test","RB"),6)
        self.assertEqual(adjusted(base,{"factors":{}})["ppr_points"],base["ppr_points"])
        a=adjusted(base,{"factors":{"carries":{"factor":.5}}})
        self.assertEqual(a["expected_carries"],base["expected_carries"]*.5)
        self.assertEqual(a["expected_targets"],base["expected_targets"])
        self.assertLess(a["ppr_points"],base["ppr_points"])


if __name__=="__main__":
    unittest.main()
