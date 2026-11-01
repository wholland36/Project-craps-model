"""Transactional append-only forecasts and delivery receipts. No wager table."""
import contextlib
import fcntl
import json
import sqlite3
from pathlib import Path
from .common import canonical, digest, instant, now, stamp


class Registry:
    def __init__(self, path, clock=now):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.executescript('''
          CREATE TABLE IF NOT EXISTS forecasts (
            seq INTEGER PRIMARY KEY, forecast_id TEXT NOT NULL UNIQUE,
            request_key TEXT NOT NULL UNIQUE, sport TEXT NOT NULL,
            event_id TEXT NOT NULL, identity TEXT NOT NULL,
            payload TEXT NOT NULL, previous_hash TEXT NOT NULL, row_hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS research_settlements (
            forecast_id TEXT PRIMARY KEY REFERENCES forecasts(forecast_id),
            payload TEXT NOT NULL, payload_hash TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS immutable_settlements_update BEFORE UPDATE ON research_settlements
            BEGIN SELECT RAISE(ABORT, 'research settlements are append only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_settlements_delete BEFORE DELETE ON research_settlements
            BEGIN SELECT RAISE(ABORT, 'research settlements are append only'); END;
          CREATE TABLE IF NOT EXISTS deliveries (
            forecast_id TEXT PRIMARY KEY REFERENCES forecasts(forecast_id),
            receipt TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS immutable_forecasts_update BEFORE UPDATE ON forecasts
            BEGIN SELECT RAISE(ABORT, 'forecasts are append only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_forecasts_delete BEFORE DELETE ON forecasts
            BEGIN SELECT RAISE(ABORT, 'forecasts are append only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_deliveries_update BEFORE UPDATE ON deliveries
            BEGIN SELECT RAISE(ABORT, 'delivery receipts are append only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_deliveries_delete BEFORE DELETE ON deliveries
            BEGIN SELECT RAISE(ABORT, 'delivery receipts are append only'); END;
        ''')
        self.verify()

    def close(self):
        self.connection.close()

    @contextlib.contextmanager
    def writer_lock(self):
        with self.path.with_suffix(self.path.suffix + '.writer.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def verify(self, anchor=None):
        previous = 'GENESIS'
        count = 0
        for seq, fid, key, sport, eid, identity, data, prev, row_hash in self.connection.execute('SELECT * FROM forecasts ORDER BY seq'):
            count += 1
            payload = json.loads(data)
            expected = digest({'previous_hash': previous, 'payload': payload})
            if seq != count or prev != previous or row_hash != expected:
                raise ValueError('registry hash chain corrupted')
            if (payload['forecast_id'], payload['request_key'], payload['sport'], payload['event_id'], canonical(payload['identity'])) != (fid, key, sport, eid, identity):
                raise ValueError('registry index/payload mismatch')
            previous = row_hash
        settlement_hashes = []
        for fid, payload, sha in self.connection.execute('SELECT * FROM research_settlements ORDER BY forecast_id'):
            if digest(json.loads(payload)) != sha or json.loads(payload)['forecast_id'] != fid:
                raise ValueError('research settlement corrupted')
            settlement_hashes.append(sha)
        result = {'count': count, 'head_sha256': previous, 'research_settlement_count': len(settlement_hashes),
                  'research_settlement_sha256': digest(settlement_hashes)}
        if anchor is not None and anchor != result:
            raise ValueError('registry differs from external anchor')
        return result

    def rows(self):
        self.verify()
        return [json.loads(row[0]) for row in self.connection.execute('SELECT payload FROM forecasts ORDER BY seq')]

    def get(self, request_key):
        self.verify()
        row = self.connection.execute('SELECT payload FROM forecasts WHERE request_key=?', (request_key,)).fetchone()
        return json.loads(row[0]) if row else None

    def append(self, payload):
        payload = json.loads(canonical(payload))
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            self.verify()
            prior = self.get(payload['request_key'])
            if prior:
                self.connection.execute('COMMIT')
                return prior
            if payload['approved_risk'] != 0 or payload['qualification'] != 'PASS' or payload['user_confirmed_placed']:
                raise ValueError('research registry cannot approve wagers')
            actual = self.clock()
            if instant(payload['kickoff']) <= actual:
                raise ValueError('cannot register a started event')
            issued = instant(payload['issued_at'])
            if issued > actual or (actual - issued).total_seconds() > 300:
                raise ValueError('backdated/future forecast issuance rejected')
            identity = canonical(payload['identity'])
            old = self.connection.execute('SELECT forecast_id, identity FROM forecasts WHERE sport=? AND event_id=? ORDER BY seq LIMIT 1',
                                          (payload['sport'], payload['event_id'])).fetchone()
            if old and old[1] != identity:
                raise ValueError('event identity or kickoff changed; quarantine required')
            payload = dict(payload, first_forecast_id=old[0] if old else payload['forecast_id'])
            head = self.verify()
            previous = head['head_sha256']
            row_hash = digest({'previous_hash': previous, 'payload': payload})
            self.connection.execute('INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (head['count'] + 1, payload['forecast_id'], payload['request_key'], payload['sport'], payload['event_id'],
                 identity, canonical(payload), previous, row_hash))
            self.connection.execute('COMMIT')
            return payload
        except BaseException:
            self.connection.execute('ROLLBACK')
            raise

    def pending(self):
        self.verify()
        return [json.loads(row[0]) for row in self.connection.execute(
            'SELECT payload FROM forecasts LEFT JOIN deliveries USING(forecast_id) WHERE deliveries.forecast_id IS NULL ORDER BY seq')]

    def acknowledge(self, forecast_id, receipt):
        if receipt.get('forecast_id') != forecast_id or not receipt.get('readback_verified'):
            raise ValueError('verified readback receipt required')
        self.connection.execute('INSERT OR IGNORE INTO deliveries VALUES (?, ?)', (forecast_id, canonical(receipt)))


    def settle_research(self, receipt):
        self.verify()
        fid = receipt['forecast_id']
        existing = self.connection.execute('SELECT payload FROM research_settlements WHERE forecast_id=?', (fid,)).fetchone()
        if existing:
            old = json.loads(existing[0])
            if old['event_result'] != receipt['event_result']:
                raise ValueError('research result revision requires quarantine; original preserved')
            return old
        if receipt['official_risk'] != 0 or receipt['official_pnl'] != 0:
            raise ValueError('research result cannot modify official history')
        self.connection.execute('INSERT INTO research_settlements VALUES (?, ?, ?)',
                                (fid, canonical(receipt), digest(receipt)))
        return receipt
