import tempfile,unittest
from pathlib import Path
from research.ncaaf_next import replacement,freeze,missing_inputs
class NextTests(unittest.TestCase):
 def test_replacement_respects_actual_and_available_count(self):
  self.assertEqual(replacement(95,[94,90,80,70]),88)
  self.assertEqual(replacement(95,[90,80]),85)
  self.assertEqual(replacement(95,[95,96,80]),80)
  self.assertEqual(replacement(95,[],actual=72),72)
  self.assertIsNone(replacement(95,[]))
 def test_frozen_records_refuse_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'policy';freeze(p,b'a');freeze(p,b'a')
   with self.assertRaises(ValueError):freeze(p,b'b')
   self.assertEqual(p.read_bytes(),b'a')
 def test_candidates_never_clear_material_inputs(self):
  flags=missing_inputs({})
  self.assertIn('same_book_paired_price_authentication_missing',flags)
  self.assertIn('replacement_roles_and_multiple_injury_workload_unverified',flags)
