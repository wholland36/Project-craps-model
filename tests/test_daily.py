import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from project_craps.common import create
from project_craps.daily import run
from helpers import fixtures


class DailyTests(unittest.TestCase):
    def test_one_sport_failure_does_not_stop_other(self):
        issued, model, snap, quote, context = fixtures('NCAAF')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create(root / 'models' / 'NFL' / 'model.json', model)
            create(root / 'models' / 'NCAAF' / 'model.json', model)
            with patch('project_craps.daily.capture', side_effect=[ValueError('simulated missing source'), snap]):
                result = run(root / 'models', root / 'output', root / 'registry.sqlite')
            self.assertEqual(result['sports']['NFL']['status'], 'FAILED')
            self.assertEqual(result['sports']['NCAAF']['status'], 'COMPLETE')
            self.assertEqual(len(result['sports']['NCAAF']['registered']), 1)
            self.assertEqual(result['approved_risk'], 0)
            self.assertTrue((root / 'output' / 'receipt.json').exists())
