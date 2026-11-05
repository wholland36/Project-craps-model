import unittest
from research.beta_v2.benchmarks import nfl_alias
from research.beta_daily import official_check
class BenchmarkTests(unittest.TestCase):
 def test_rams_canonical_ids(self):
  self.assertEqual(nfl_alias('LAR'),'LA');self.assertEqual(nfl_alias('LA'),'LA');self.assertEqual(nfl_alias('WSH'),'WAS')
 def test_official_integrity_gate(self):
  p,r=official_check();self.assertIn('NCAAB',p['sports']);self.assertTrue(r['models_match_official_release'])
