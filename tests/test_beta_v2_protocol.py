import unittest
from research.beta_v2.protocol import horizon,readiness,score_safety
class ProtocolTests(unittest.TestCase):
 def test_distinct_horizons(self):
  self.assertEqual(horizon('2026-11-06T12:00:00Z','2026-11-05T12:00:00Z'),'DAY_AHEAD')
  self.assertEqual(horizon('2026-11-05T20:00:00Z','2026-11-05T12:00:00Z'),'EARLY')
  self.assertEqual(horizon('2026-11-05T13:00:00Z','2026-11-05T12:00:00Z'),'FINAL')
  self.assertIsNone(horizon('2026-11-05T12:05:00Z','2026-11-05T12:00:00Z'))
 def test_zero_support_is_not_silently_dropped(self):
  r=score_safety([0,0,1],0);self.assertTrue(r['logloss_is_infinite']);self.assertTrue(r['zero_probability_observed'])
 def test_counts_never_approve(self):
  self.assertFalse(readiness(10000,100,'NFL',True)['approved'])
