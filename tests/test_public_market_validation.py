import json
import tempfile
import unittest
from pathlib import Path
from research.public_market_validation import public_pairs, append_shadow, summarize
from research.market_audit import checked
from tests.test_market_audit import fixture

def pair():
    a=dict(snapshot_ts='2026-10-24T15:00:00Z',commence_time='2026-10-24T16:00:00Z',sport='americanfootball_ncaaf',game_id='one',home='A',away='B',book='x',market='spread',side='home',line='-3',american_odds='-110')
    return [a,dict(a,side='away',line='3')]

class PublicValidationTests(unittest.TestCase):
    def test_same_book_same_scan_mirrored_pair(self):
        q,e=public_pairs(pair());self.assertEqual(len(q),1);self.assertEqual(e,{})
        self.assertAlmostEqual(q[0]['independently_recomputed_proportional_novig'],.5)
        self.assertFalse(q[0]['provider_original_update_authenticated'])
    def test_refuse_cross_book_clock_line_and_conflicting_prices(self):
        for changes in ({'book':'y'},{'snapshot_ts':'2026-10-24T15:01:00Z'},{'line':'3.5'}):
            rows=pair();rows[1].update(changes);self.assertEqual(len(public_pairs(rows)[0]),0)
        rows=pair();rows.append(dict(rows[0],american_odds='-120'));self.assertEqual(len(public_pairs(rows)[0]),0)
    def test_poststart_and_duplicates(self):
        rows=pair();rows[0]['snapshot_ts']=rows[0]['commence_time'];self.assertEqual(len(public_pairs(rows)[0]),0)
        rows=pair();rows.append(dict(rows[0]));q,e=public_pairs(rows);self.assertEqual(len(q),1);self.assertEqual(e['duplicate_row'],1)
    def test_push_is_refund_and_drawdown(self):
        q=fixture(sport='NCAAF',line=-7,home_score=27,away_score=20);r=checked(q);r['start_time_utc']=q['start_time_utc']
        m=summarize([r]);self.assertEqual(m['pushes'],1);self.assertEqual(m['hypothetical_profit_units'],0);self.assertEqual(m['max_drawdown_units'],0)
    def test_append_preserves_original_and_detects_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            one=append_shadow(d,{'approved_risk':0});raw=(Path(d)/one['file']).read_bytes()
            two=append_shadow(d,{'approved_risk':0});self.assertEqual(two['records'],2);self.assertEqual((Path(d)/one['file']).read_bytes(),raw)
            (Path(d)/one['file']).write_text('{}')
            with self.assertRaises(AssertionError):append_shadow(d,{'approved_risk':0})
if __name__=='__main__':unittest.main()
