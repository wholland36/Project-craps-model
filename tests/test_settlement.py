import copy
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from project_craps.common import envelope, stamp
from project_craps.pipeline import forecast
from project_craps.registry import Registry
from project_craps.settle import settle
from helpers import fixtures


class SettlementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.issued, cls.model, cls.snap, cls.quote, cls.context = fixtures()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = Registry(Path(self.tmp.name) / 'registry.sqlite', clock=lambda: self.issued)
        self.record = self.reg.append(forecast(self.model, self.snap, 'future', self.quote, self.context, clock=lambda: self.issued))
        self.final = copy.deepcopy(self.snap['payload'])
        self.observed = self.issued + timedelta(hours=6)
        event = next(g for g in self.final['games'] if g['event_id'] == 'future')
        event.update(status='FINAL', home_score=20, away_score=17, observed_at=stamp(self.observed))

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def test_prospective_push_and_idempotent_research_settlement(self):
        result = settle(self.reg, envelope(self.final), clock=lambda: self.observed)[0]
        self.assertEqual(tuple(result['outcome_wpl']), (0, 1, 0))
        self.assertEqual(result['official_pnl'], 0)
        self.assertTrue(result['calibration_eligible_research'])
        repeated = settle(self.reg, envelope(self.final), clock=lambda: self.observed)[0]
        self.assertEqual(repeated['event_result'], result['event_result'])
        self.assertEqual(self.reg.verify()['research_settlement_count'], 1)

    def test_changed_result_or_identity_quarantined(self):
        settle(self.reg, envelope(self.final), clock=lambda: self.observed)
        event = next(g for g in self.final['games'] if g['event_id'] == 'future')
        event['home_score'] = 21
        with self.assertRaises(ValueError):
            settle(self.reg, envelope(self.final), clock=lambda: self.observed)
        event['home_id'] = 'C'
        with self.assertRaises(ValueError):
            settle(self.reg, envelope(self.final), clock=lambda: self.observed)

    def test_no_probability_backfill(self):
        self.reg.close()
        self.reg = Registry(Path(self.tmp.name) / 'blocked.sqlite', clock=lambda: self.issued)
        self.reg.append(forecast(self.model, self.snap, 'future', clock=lambda: self.issued))
        result = settle(self.reg, envelope(self.final), clock=lambda: self.observed)[0]
        self.assertFalse(result['calibration_eligible_research'])
        self.assertIsNone(result['threeway_brier'])
        self.assertIsNone(result['outcome_wpl'])
