import unittest,tempfile
from pathlib import Path
from research.beta_v2.runtime import candidate,make_arm,score_at,grade
from research.beta_daily import journaled_save,verify_journal,integrity
class RuntimeTests(unittest.TestCase):
 def fixture(self):
  c=candidate([(24,21),(21,21),(20,21)],'NFL');a,lines=make_arm(c,'NFL')
  r=dict(sport='NFL',event_id='1',horizon='EARLY',issued_at='2026-11-05T12:00:00Z',identity=dict(home_id='A',away_id='B',kickoff='2026-11-05T20:00:00Z'),arms={'rolling_strength':a},winner_benchmarks={'official_winner':.5,'independent_elo':.5},hypothetical_ticket=None,primary_supported=True)
  e=dict(status='FINAL',home_id='A',away_id='B',kickoff='2026-11-05T20:00:00Z',observed_at='2026-11-06T00:00:00Z',home_score=24,away_score=21,season=2026)
  return r,e
 def test_horizons_preserve_distinct_records(self):
  r,e=self.fixture()
  with tempfile.TemporaryDirectory() as d:
   state=Path(d)
   for h in ['DAY_AHEAD','EARLY','FINAL']:
    journaled_save(state,state/'forecasts'/(h+'.json'),dict(r,horizon=h))
   self.assertEqual(verify_journal(state)['count'],3)
   with self.assertRaises(FileExistsError):journaled_save(state,state/'forecasts'/'FINAL.json',r)
 def test_exact_identity_and_clocks(self):
  r,e=self.fixture();g=grade(r,e);self.assertEqual(g['official_pnl'],0)
  e['away_id']='WRONG'
  with self.assertRaises(ValueError):grade(r,e)
 def test_zero_support_reported(self):
  r,e=self.fixture();r['arms']['rolling_strength']['masses']={'spread:home:-3.0':[1.,0.,0.]}
  v=grade(r,e)['grades']['rolling_strength']['markets']['spread:home:-3.0'];self.assertTrue(v['logloss_is_infinite'])
 def test_ncaab_tie_support_rejected(self):
  with self.assertRaises(ValueError):candidate([(70,70)],'NCAAB')
 def test_actual_market_pair_benchmark_is_separate(self):
  r,e=self.fixture();r['quote_data']=[dict(key='spread:home:-3.0',conditional_no_vig=.5,book='test')]
  g=grade(r,e);self.assertIsNone(g['market_benchmarks'][0]['conditional_brier'])
