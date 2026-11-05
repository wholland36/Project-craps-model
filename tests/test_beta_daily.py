import tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from research.beta_daily import reference_digest,reference_scores,parse_events,match_reference,arm,settle,save_forecast,integrity,journaled_save,verify_journal
class BetaDailyTests(unittest.TestCase):
    def record(self):
        return dict(sport='NFL',event_id='official',issued_at='2026-11-05T12:00:00Z',identity=dict(home_id='A',away_id='B',kickoff='2026-11-06T12:00:00Z'),arms={'point_kernel_reference':arm([(21,21),(24,21),(20,21)],'NFL')},independent_elo_reference=.5)
    def event(self):
        return dict(sport='NFL',home_id='A',away_id='B',kickoff='2026-11-06T12:00:00Z',status='FINAL',home_score=24,away_score=21,source_sha256='source',observed_at='2026-11-07T00:00:00Z',season=2026)
    def test_create_only_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.json';save_forecast(p,self.record());self.assertEqual(integrity(p)['event_id'],'official')
            with self.assertRaises(FileExistsError):save_forecast(p,self.record())
            p.write_text(p.read_text().replace('official','tampered'))
            with self.assertRaises(ValueError):integrity(p)
    def test_push_graded_separately_no_wagers(self):
        g=settle(self.record(),self.event());self.assertEqual(g['official_risk'],0);self.assertAlmostEqual(g['grades']['point_kernel_reference']['metrics']['spread:home:-3.0']['threeway_brier'],8/9)
    def test_identity_and_late_forecast_fail(self):
        r=self.record();e=self.event();e['home_id']='WRONG'
        with self.assertRaises(ValueError):settle(r,e)
        e=self.event();r['issued_at']=e['kickoff']
        with self.assertRaises(ValueError):settle(r,e)
    def test_match_never_uses_nearest_time(self):
        r=self.record();r.update(r['identity']);e=self.event();e['kickoff']='2026-11-06T13:00:00Z'
        self.assertEqual(match_reference(r,[e])[1],'identity_or_kickoff_revision')
    def test_sport_ties(self):
        r=dict(sport='NFL',predicted_home_margin_research_only=0,predicted_total_research_only=42)
        a={'residual_pairs':[(0,0),(3,3)]}
        self.assertIn((21,21),reference_scores(r,a));r['sport']='NCAAF';self.assertNotIn((21,21),reference_scores(r,a))
        self.assertEqual(arm([(21,21),(24,21)],'NCAAB')['masses']['moneyline:home'],(1.,0.,0.))
    def test_digest_is_original_schema(self):
        r={'x':1};h=reference_digest(r);r['record_sha256']=h;self.assertEqual(reference_digest(r),h)

    def test_journal_detects_deletion_and_truncation(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d);p=state/'forecasts'/'f.json';journaled_save(state,p,self.record())
            self.assertEqual(verify_journal(state)['count'],1)
            p.unlink()
            with self.assertRaises(ValueError):verify_journal(state)
        with tempfile.TemporaryDirectory() as d:
            state=Path(d);p=state/'forecasts'/'f.json';journaled_save(state,p,self.record())
            (state/'journal.jsonl').write_text('')
            with self.assertRaises(ValueError):verify_journal(state)
