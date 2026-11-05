import unittest
from research.priority_workflow import audit_games
class RetentionTests(unittest.TestCase):
    def test_missing_games_stay_and_never_healthy(self):
        g=dict(event_id='1',week=1,baseline=None,sides={'home':{'report_present':False},'away':{'report_present':False}})
        r=audit_games([g]);self.assertEqual(r['games_retained'],1);self.assertFalse(r['games'][0]['actionable']);self.assertTrue(r['games'][0]['numerical_zero_is_not_healthy'])
        with self.assertRaises(ValueError):audit_games([g,g])
