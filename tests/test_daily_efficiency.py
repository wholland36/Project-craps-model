import unittest
from research.daily_efficiency import fit,predict
class DailyEfficiencyTests(unittest.TestCase):
 def rows(self):
  return [dict(event_id=str(i),kickoff=f'2026-09-{1+i//3:02d}T12:00:00Z',season=2026,home_id='a',away_id='b',home_score=30+i%3,away_score=20,neutral=False,final=True) for i in range(60)]
 def test_split_and_prediction(self):
  m=fit(self.rows(),sport='NFL',cutoff='2026-10-01T00:00:00Z')
  self.assertLess(m['train_last'][:10],m['calibration_first'][:10]);self.assertGreater(m['calibration_n'],9)
  p=predict(m,dict(home_id='a',away_id='b',neutral=True,kickoff='2026-10-02T00:00:00Z'))
  self.assertIsNone(p['expected_possessions']);self.assertEqual(len(p['paired_score_samples']),m['calibration_n'])
  with self.assertRaises(ValueError):predict(m,dict(home_id='a',away_id='b',neutral=False,kickoff='2026-09-01T00:00:00Z'))
 def test_no_fabricated_basketball_possessions(self):
  with self.assertRaises(ValueError):fit(self.rows(),sport='NCAAB',cutoff='2026-10-01T00:00:00Z')
  rows=self.rows()
  for r in rows:r['possessions']=70
  m=fit(rows,sport='NCAAB',cutoff='2026-10-01T00:00:00Z')
  self.assertEqual(predict(m,dict(home_id='a',away_id='b',neutral=False,kickoff='2026-10-02T00:00:00Z'))['expected_possessions'],70)
 def test_future_rows_excluded_and_duplicate_rejected(self):
  rows=self.rows();rows[-1]['kickoff']='2027-01-01T00:00:00Z'
  m=fit(rows,sport='NFL',cutoff='2026-10-01T00:00:00Z');self.assertEqual(m['excluded']['not_before_cutoff'],1)
  with self.assertRaises(ValueError):fit(rows+[rows[0]],sport='NFL',cutoff='2026-10-01T00:00:00Z')
 def test_source_boolean_and_home_effect(self):
  from research.daily_efficiency import parse_neutral
  self.assertFalse(parse_neutral('FALSE'));self.assertTrue(parse_neutral('TRUE'))
  with self.assertRaises(ValueError):parse_neutral('unknown')
  rows=self.rows()
  for i,r in enumerate(rows):
   r['home_id'],r['away_id']=(('a','b') if i%2 else ('b','a'))
   r['home_score']=30;r['away_score']=20;r['neutral']=parse_neutral('FALSE')
  self.assertGreater(fit(rows,sport='NCAAF',cutoff='2026-10-01T00:00:00Z')['parameters']['home_effect'],0)
