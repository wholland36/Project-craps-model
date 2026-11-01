"""Allowlisted append-only canonical ledger projection with readback and outbox.

Google offers no unique-key constraint on append. One shared registry and writer
lock are required; external writers must not reuse PCR IDs. Ambiguous writes are
reconciled by ID before any retry. No history-edit operations are implemented.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
from pathlib import Path
import requests
from .common import canonical, digest, instant, now, stamp

# The private target binding stays in ignored runtime config, never in this repo.
_config_path = Path(os.environ.get('PROJECT_CRAPS_LEDGER_CONFIG', 'runtime/ledger.json'))
_config = json.loads(_config_path.read_text()) if _config_path.exists() else {}
SPREADSHEET_ID = _config.get('spreadsheet_id')
REGISTRY_SHEET_ID = _config.get('registry_sheet_id')
OFFICIAL_SHEET_ID = _config.get('official_sheet_id')
HEADERS = ['index', 'snapshot_id', 'model_protocol', 'snapshot_asof_ET', 'event_date_ET',
 'start_ET', 'sport', 'away', 'home', 'market', 'selection', 'line', 'american_odds',
 'book', 'quote_original_asof_ET', 'quote_verified_executable', 'breakeven_probability',
 'qualifying_threshold_probability', 'model_probability', 'fair_line',
 'model_EV_dollars_per_400', 'kelly_bet_USD', 'forecast_status', 'qualification_status',
 'user_confirmed_placed', 'risk_approved_USD', 'forecast_confidence', 'missing_validation_inputs', 'source_url']


def projection(record, index):
    quote, metrics = record.get('quote') or {}, record.get('price_metrics') or {}
    def value(key):
        result = metrics.get(key)
        return 'NOT_COMPUTED' if result is None else result
    details = {key: record.get(key) for key in ('event_id', 'identity', 'model_sha256',
       'snapshot_sha256', 'feature_sha256', 'distribution_sha256', 'first_forecast_id',
       'probabilities', 'uncertainty', 'reasons', 'data_vintage', 'quote_cutoff')}
    details['registry_payload_sha256'] = digest(record)
    details['probability_definition'] = 'unconditional selection win; P(push) and P(loss) stored separately'
    details['ev_definition'] = 'research EV per $400 hypothetical risk; approved risk always zero'
    p = record['probabilities']
    return [index, record['forecast_id'], record['model_version'], record['issued_at_ET'],
        record['event_date_ET'], instant(record['kickoff']).astimezone(ZoneInfo('America/New_York')).isoformat(),
        record['sport'], record['away'], record['home'], quote.get('market', 'schedule_screen'),
        quote.get('selection', 'NO_SELECTION'), quote.get('line', ''), quote.get('american_odds', ''),
        quote.get('book', 'BOOK_NOT_VERIFIED'), quote.get('observed_at', 'NOT_QUOTED'),
        'YES' if quote.get('verified_executable') else 'NO', value('break_even_conditional_nonpush'),
        'NOT_COMPUTED', p['win'] if p else 'NOT_COMPUTED', value('fair_american_odds'),
        metrics['ev_per_unit_risk'] * 400 if metrics else 'NOT_COMPUTED', 0,
        record['status'] + '_RESEARCH_V1', 'PASS', 'NO', 0, 'NOT_VALIDATED',
        canonical(details), record['source_url']]


def validate_remote(remote):
    if not SPREADSHEET_ID or REGISTRY_SHEET_ID is None or OFFICIAL_SHEET_ID is None:
        raise ValueError('private ledger allowlist config missing')
    if remote['spreadsheet_id'] != SPREADSHEET_ID or remote['registry_sheet_id'] != REGISTRY_SHEET_ID:
        raise ValueError('canonical spreadsheet/tab allowlist mismatch')
    if remote['registry_title'] != 'Forecast Registry' or remote['official_sheet_id'] != OFFICIAL_SHEET_ID:
        raise ValueError('sheet identity drift')
    rows = remote['rows']
    if not rows or rows[0] != HEADERS:
        raise ValueError('registry header/schema drift')
    if remote.get('writable_schema_safe') is not True:
        raise ValueError('registry cell structures/validation not verified safe for append')


def clean_row(row):
    def text(v):
        if v is None:
            return ''
        return format(v, '.15g') if type(v) in (int, float) else str(v)
    return [text(v) for v in (row + [''] * len(HEADERS))[:len(HEADERS)]]


def plan(registry, remote):
    validate_remote(remote)
    pending = registry.pending()
    existing = {}
    for row in remote['rows'][1:]:
        if len(row) > 1 and row[1]:
            existing.setdefault(row[1], []).append(row)
    pending_ids = {r['forecast_id'] for r in pending}
    for record in registry.rows():
        matches = existing.get(record['forecast_id'], [])
        if len(matches) > 1:
            raise ValueError('duplicate remote forecast IDs')
        if matches and clean_row(projection(record, matches[0][0])) != clean_row(matches[0]):
            raise ValueError('remote registered forecast changed after delivery')
        if not matches and record['forecast_id'] not in pending_ids:
            raise ValueError('acknowledged remote forecast was removed; investigate')
    append, reconciled = [], []
    indices = [int(float(r[0])) for r in remote['rows'][1:] if r and str(r[0]).replace('.', '', 1).isdigit()]
    index = max(indices, default=-1) + 1
    for record in pending:
        matches = existing.get(record['forecast_id'], [])
        if len(matches) > 1:
            raise ValueError('duplicate remote forecast IDs')
        if matches:
            expected = projection(record, matches[0][0])
            if clean_row(expected) != clean_row(matches[0]):
                raise ValueError('remote forecast ID has changed content')
            reconciled.append(record['forecast_id'])
        else:
            append.append(projection(record, index))
            index += 1
    formats = remote.get('column_formats', [{} for _ in HEADERS])
    if len(formats) != len(HEADERS):
        raise ValueError('column format contract missing')
    cells = []
    for row in append:
        cells.append({'values': [{'userEnteredValue': {'numberValue': v} if isinstance(v, (float, int))
                                    else {'stringValue': str(v)}, 'userEnteredFormat': formats[i]} for i, v in enumerate(row)]})
    requests_body = [{'appendCells': {'sheetId': REGISTRY_SHEET_ID, 'rows': cells,
                                      'fields': 'userEnteredValue,userEnteredFormat'}}] if cells else []
    return {'spreadsheet_id': SPREADSHEET_ID, 'requests': requests_body,
            'forecast_ids': [row[1] for row in append], 'reconciled_ids': reconciled,
            'official_before_sha256': digest(remote['official_rows']),
            'registry_before_sha256': digest(remote['rows'])}


def acknowledge(registry, prepared, remote):
    validate_remote(remote)
    if digest(remote['official_rows']) != prepared['official_before_sha256']:
        raise ValueError('official history changed during sync; stop and investigate')
    # Re-plan against readback. Every originally pending record must now match exactly.
    result = plan(registry, remote)
    if result['requests']:
        raise ValueError('readback missing delivered records')
    expected = set(prepared['forecast_ids'] + prepared['reconciled_ids'])
    if not expected.issubset(result['reconciled_ids']):
        raise ValueError('delivery readback incomplete')
    for fid in expected:
        registry.acknowledge(fid, {'forecast_id': fid, 'readback_verified': True,
            'readback_at': stamp(now()), 'spreadsheet_id': SPREADSHEET_ID,
            'registry_sheet_id': REGISTRY_SHEET_ID,
            'official_sha256': prepared['official_before_sha256']})
    return {'delivered': len(expected), 'official_history_unchanged': True}


def sync(registry, transport):
    with registry.writer_lock():
        before = transport.read()
        prepared = plan(registry, before)
        if prepared['requests']:
            transport.append(prepared)  # No automatic retry on ambiguous HTTP results.
        return acknowledge(registry, prepared, transport.read())


class GoogleTransport:
    """REST delivery with ADC credentials supplied by the operator, never in git."""
    def __init__(self):
        if not SPREADSHEET_ID:
            raise ValueError('private ledger allowlist config missing')
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/spreadsheets'])
        self.session = AuthorizedSession(credentials)
        self.base = 'https://sheets.googleapis.com/v4/spreadsheets/' + SPREADSHEET_ID

    def _get(self, path='', **params):
        response = self.session.get(self.base + path, params=params, timeout=45)
        response.raise_for_status()
        return response.json()

    def read(self):
        metadata = self._get(fields='spreadsheetId,sheets(properties)')
        by_id = {s['properties']['sheetId']: s['properties'] for s in metadata['sheets']}
        reg, official = by_id[REGISTRY_SHEET_ID], by_id[OFFICIAL_SHEET_ID]
        if reg['title'] != 'Forecast Registry' or official['title'] != 'Official Wagers':
            raise ValueError('canonical sheet title drift')
        grid = self._get('', ranges="'Forecast Registry'!A1:AC" + str(reg['gridProperties']['rowCount']),
                         includeGridData='true', fields='sheets(data(rowData(values(userEnteredValue,userEnteredFormat,dataValidation,chipRuns))))')
        safe = True
        formats = [{} for _ in HEADERS]
        for sheet in grid.get('sheets', []):
            for block in sheet.get('data', []):
                for row in block.get('rowData', []):
                    if any(c.get('userEnteredValue') for c in row.get('values', [])):
                        formats = [(row.get('values', [])[i].get('userEnteredFormat', {}) if i < len(row.get('values', [])) else {}) for i in range(len(HEADERS))]
                    for cell in row.get('values', []):
                        if cell.get('dataValidation') or cell.get('chipRuns') or 'formulaValue' in cell.get('userEnteredValue', {}):
                            safe = False
        def values(title, width, count):
            return self._get('/values/' + requests.utils.quote("'" + title + "'!A1:" + width + str(count), safe=''),
                             valueRenderOption='UNFORMATTED_VALUE').get('values', [])
        return {'spreadsheet_id': metadata['spreadsheetId'], 'registry_sheet_id': REGISTRY_SHEET_ID,
                'registry_title': reg['title'], 'official_sheet_id': OFFICIAL_SHEET_ID,
                'writable_schema_safe': safe, 'column_formats': formats,
                'rows': values('Forecast Registry', 'AC', reg['gridProperties']['rowCount']),
                'official_rows': values('Official Wagers', 'Z', official['gridProperties']['rowCount'])}

    def append(self, prepared):
        if prepared['spreadsheet_id'] != SPREADSHEET_ID:
            raise ValueError('spreadsheet allowlist violation')
        for request in prepared['requests']:
            if set(request) != {'appendCells'} or request['appendCells']['sheetId'] != REGISTRY_SHEET_ID:
                raise ValueError('only registry appends permitted')
            if request['appendCells']['fields'] != 'userEnteredValue,userEnteredFormat':
                raise ValueError('invalid append field mask')
        response = self.session.post(self.base + ':batchUpdate', json={'requests': prepared['requests']}, timeout=45)
        response.raise_for_status()
