import copy
import tempfile
import unittest
from pathlib import Path
import requests
from project_craps import sheets
from project_craps.pipeline import forecast
from project_craps.registry import Registry
from helpers import fixtures


class FakeSheets:
    def __init__(self):
        self.state = {'spreadsheet_id': sheets.SPREADSHEET_ID,
            'registry_sheet_id': sheets.REGISTRY_SHEET_ID, 'registry_title': 'Forecast Registry',
            'official_sheet_id': sheets.OFFICIAL_SHEET_ID, 'writable_schema_safe': True,
            'rows': [sheets.HEADERS[:]], 'official_rows': [['SYNTHETIC OFFICIAL TEST DATA']]}
        self.calls, self.fail_after_commit, self.mutate_official = 0, False, False

    def read(self):
        return copy.deepcopy(self.state)

    def append(self, prepared):
        self.calls += 1
        for request in prepared['requests']:
            assert set(request) == {'appendCells'}
            assert request['appendCells']['sheetId'] == sheets.REGISTRY_SHEET_ID
            for row in request['appendCells']['rows']:
                self.state['rows'].append([next(iter(c['userEnteredValue'].values())) for c in row['values']])
        if self.mutate_official:
            self.state['official_rows'].append(['CONCURRENT CHANGE'])
        if self.fail_after_commit:
            raise requests.Timeout('simulated lost response after server commit')


class SheetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.issued, cls.model, cls.snap, cls.quote, cls.context = fixtures()
        cls.record = forecast(cls.model, cls.snap, 'future', cls.quote, cls.context, clock=lambda: cls.issued)

    def setUp(self):
        self.original_ids = sheets.SPREADSHEET_ID, sheets.REGISTRY_SHEET_ID, sheets.OFFICIAL_SHEET_ID
        sheets.SPREADSHEET_ID, sheets.REGISTRY_SHEET_ID, sheets.OFFICIAL_SHEET_ID = 'synthetic-sheet', 10, 20
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = Registry(Path(self.tmp.name) / 'registry.sqlite', clock=lambda: self.issued)
        self.reg.append(copy.deepcopy(self.record))
        self.server = FakeSheets()

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()
        sheets.SPREADSHEET_ID, sheets.REGISTRY_SHEET_ID, sheets.OFFICIAL_SHEET_ID = self.original_ids

    def test_sync_readback_and_no_official_changes(self):
        before = self.server.read()['official_rows']
        self.assertEqual(sheets.sync(self.reg, self.server)['delivered'], 1)
        self.assertEqual(self.reg.pending(), [])
        self.assertEqual(self.server.state['official_rows'], before)
        self.assertEqual(len(self.server.state['rows']), 2)
        self.assertEqual(sheets.sync(self.reg, self.server)['delivered'], 0)
        self.assertEqual(self.server.calls, 1)

    def test_lost_response_recovers_without_duplicate(self):
        self.server.fail_after_commit = True
        with self.assertRaises(requests.Timeout):
            sheets.sync(self.reg, self.server)
        self.assertEqual(len(self.reg.pending()), 1)
        self.server.fail_after_commit = False
        sheets.sync(self.reg, self.server)
        self.assertEqual(self.server.calls, 1)
        self.assertEqual(len(self.server.state['rows']), 2)
        self.assertEqual(self.reg.pending(), [])

    def test_remote_content_conflict_stops(self):
        prepared = sheets.plan(self.reg, self.server.read())
        self.server.append(prepared)
        self.server.state['rows'][1][18] = .99
        with self.assertRaises(ValueError):
            sheets.sync(self.reg, self.server)
        self.assertEqual(len(self.reg.pending()), 1)

    def test_duplicate_ids_stop(self):
        self.server.append(sheets.plan(self.reg, self.server.read()))
        self.server.state['rows'].append(self.server.state['rows'][1][:])
        with self.assertRaises(ValueError):
            sheets.sync(self.reg, self.server)

    def test_official_change_during_sync_detected(self):
        self.server.mutate_official = True
        with self.assertRaises(ValueError):
            sheets.sync(self.reg, self.server)
        self.assertEqual(len(self.reg.pending()), 1)

    def test_schema_and_target_drift_stop_before_write(self):
        for field, value in [('spreadsheet_id', 'different'), ('registry_sheet_id', 20),
                             ('rows', [['wrong headers']]), ('writable_schema_safe', False)]:
            server = FakeSheets()
            server.state[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    sheets.sync(self.reg, server)
                self.assertEqual(server.calls, 0)

    def test_forged_receipt_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.acknowledge(self.record['forecast_id'], {'readback_verified': False})

    def test_values_are_literal_not_formulas(self):
        record = self.reg.rows()[0]
        record['home'] = '=IMPORTDATA("https://example.test")'
        row = sheets.projection(record, 0)
        self.assertTrue(row[8].startswith('='))
        # StringValue is used for all text; never formulaValue.
        self.assertNotIn('formulaValue', str(sheets.plan(self.reg, self.server.read())['requests']))


    def test_acknowledged_rows_are_still_checked_for_tampering(self):
        sheets.sync(self.reg, self.server)
        self.server.state['rows'][1][18] = .99
        with self.assertRaises(ValueError):
            sheets.sync(self.reg, self.server)
        self.assertEqual(self.server.calls, 1)

    def test_acknowledged_remote_deletion_is_not_silently_recreated(self):
        sheets.sync(self.reg, self.server)
        self.server.state['rows'].pop()
        with self.assertRaises(ValueError):
            sheets.sync(self.reg, self.server)
        self.assertEqual(self.server.calls, 1)
