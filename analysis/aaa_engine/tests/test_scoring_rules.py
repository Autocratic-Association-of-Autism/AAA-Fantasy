import unittest
import json
from aaa_engine.scoring_rules import extract_scoring_rules

def payload(items):
    return {"settings":{"scoringSettings":{"scoringItems":items}}}

class ScoringRulesTests(unittest.TestCase):
    def test_raw_definition_and_overrides_are_preserved(self):
        item={"statId":95,"points":-1.0,"pointsOverrides":{"16":2.0},"isReverseItem":True}
        rows=extract_scoring_rules(payload([item]))
        self.assertEqual(rows[0]["stat_id"],95)
        self.assertEqual(rows[0]["points"],-1.)
        self.assertEqual(json.loads(rows[0]["source_item_json"]),item)
        self.assertEqual(json.loads(rows[0]["points_overrides_json"]),{"16":2.0})
    def test_incomplete_or_duplicate_rules_are_rejected(self):
        for items in ([],[{"statId":95}],[{"statId":95,"points":float("nan")}],
                      [{"statId":95,"points":1.},{"statId":95,"points":2.}]):
            with self.assertRaises((ValueError,KeyError,TypeError)):
                extract_scoring_rules(payload(items))

if __name__=="__main__":
    unittest.main()
