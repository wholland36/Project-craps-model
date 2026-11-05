import tempfile
import unittest
from pathlib import Path
from research.validation_v2 import append_record,source_gate,sha,planning_sample_size,production_gate
class GovernanceTests(unittest.TestCase):
    def test_no_false_source_authentication(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source';p.write_bytes(b'policy')
            r=dict(body_path=str(p),sha256=sha(p.read_bytes()),observed_at='2026-11-05T12:00:00Z',published_at='2026-11-04T12:00:00Z',independent_authentication=True)
            self.assertFalse(source_gate(r,'2026-11-05T13:00:00Z',require_independent=True)['independently_authenticated'])
            p.write_bytes(b'changed')
            self.assertIn('source_hash_mismatch',source_gate(r,'2026-11-05T13:00:00Z')['failures'])
            self.assertIn('observed_after_cutoff',source_gate(r,'2026-11-05T11:00:00Z')['failures'])
    def test_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            append_record(d,{'event_id':'1'},{'forecast':0})
            with self.assertRaises(FileExistsError):append_record(d,{'event_id':'1'},{'forecast':1})
    def test_planning_not_approval(self):
        a=planning_sample_size(minimum_effect=.02,paired_sd=.1,design_effect=2)
        b=planning_sample_size(minimum_effect=.02,paired_sd=.1,design_effect=2,hypotheses=5)
        self.assertGreater(b['approximate_exposed_pairs'],a['approximate_exposed_pairs']);self.assertFalse(a['approval']);self.assertFalse(production_gate({})['automatic_promotion'])
