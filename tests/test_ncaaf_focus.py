import unittest
from research.ncaaf_focus import pair_masses,blend,reference_pairs
from research.ncaaf_focus_guard import eligible_identity
class FocusTests(unittest.TestCase):
 def test_reversed_calibrator_rejected(self):
  with self.assertRaises(ValueError):pair_masses([.4,.1,.5],0,-.2)
 def test_push_and_complement_preserved(self):
  p=pair_masses([.4,.1,.5],.1,.3)
  self.assertAlmostEqual(sum(p),1);self.assertEqual(p[1],.1)
  self.assertAlmostEqual(sum(blend(p,.52)),1)
 def test_slope_zero_is_constant_not_inverted(self):
  a=pair_masses([.2,0,.8],0,0);b=pair_masses([.8,0,.2],0,0)
  self.assertEqual(a,b)
 def test_no_cross_team_prices(self):
  self.assertEqual(reference_pairs({'pickcenter':[{'homeTeamOdds':{'teamId':'1'},'awayTeamOdds':{'teamId':'2'}}]},dict(home_id='2',away_id='1')),[])
 def test_conflicting_event_never_grades(self):
  self.assertFalse(eligible_identity({'event_id':'401862818'},{'header':{'id':'401862818'}}))
