import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from project_craps.common import stamp
from project_craps.pipeline import forecast
from project_craps.registry import Registry
from helpers import fixtures


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.issued, cls.model, cls.snap, cls.quote, cls.context = fixtures()
        cls.record = forecast(cls.model, cls.snap, 'future', cls.quote, cls.context, clock=lambda: cls.issued)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'registry.sqlite'
        self.reg = Registry(self.path, clock=lambda: self.issued)

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def test_retry_and_revision_preserve_first(self):
        first = self.reg.append(copy.deepcopy(self.record))
        self.assertEqual(first, self.reg.append(copy.deepcopy(self.record)))
        quote = dict(self.quote, american_odds=110)
        second = forecast(self.model, self.snap, 'future', quote, self.context, clock=lambda: self.issued)
        second = self.reg.append(second)
        self.assertNotEqual(first['forecast_id'], second['forecast_id'])
        self.assertEqual(second['first_forecast_id'], first['forecast_id'])
        self.assertEqual(self.reg.verify()['count'], 2)
        self.assertEqual(self.reg.rows()[0], first)

    def test_sql_mutation_rejected(self):
        self.reg.append(copy.deepcopy(self.record))
        for sql in ['DELETE FROM forecasts', "UPDATE forecasts SET payload='{}'"]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.reg.connection.execute(sql)

    def test_identity_changed_quarantined(self):
        self.reg.append(copy.deepcopy(self.record))
        changed = copy.deepcopy(self.record)
        changed.update(request_key='different', forecast_id='different')
        changed['identity']['home_id'] = 'C'
        with self.assertRaises(ValueError):
            self.reg.append(changed)
        self.assertEqual(len(self.reg.rows()), 1)

    def test_started_backdated_future_and_risk_rejected(self):
        for key, value in [('kickoff', stamp(self.issued)), ('issued_at', stamp(self.issued-timedelta(minutes=6))),
                           ('issued_at', stamp(self.issued+timedelta(seconds=1))), ('approved_risk', 400)]:
            record = dict(self.record, **{key: value})
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    self.reg.append(record)
        self.assertEqual(len(self.reg.rows()), 0)

    def test_concurrent_duplicate_writers(self):
        def write(_):
            registry = Registry(self.path, clock=lambda: self.issued)
            try:
                return registry.append(copy.deepcopy(self.record))['forecast_id']
            finally:
                registry.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(len(set(pool.map(write, range(8)))), 1)
        self.assertEqual(len(self.reg.rows()), 1)

    def test_corruption_and_external_anchor_detected(self):
        self.reg.append(copy.deepcopy(self.record))
        with self.assertRaises(ValueError):
            self.reg.verify({'count': 0, 'head_sha256': 'GENESIS'})
        self.reg.connection.execute('DROP TRIGGER immutable_forecasts_update')
        self.reg.connection.execute("UPDATE forecasts SET payload='{}'")
        with self.assertRaises(ValueError):
            self.reg.verify()
