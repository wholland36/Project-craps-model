import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import requests
from project_craps.common import bytes_hash, create, envelope, now, read, stamp
from project_craps.data import capture, load_snapshot, normalize


class SnapshotTests(unittest.TestCase):
    def test_archived_bytes_and_normalized_rows_are_both_verified(self):
        raw = b'game_id,season,home_team,away_team,game_type,gameday,gametime,home_score,away_score,location\nfixture,2025,A,B,REG,2025-10-01,13:00,20,17,Home\n'
        source = {'url': 'https://example.test/scores', 'sha256': bytes_hash(raw),
                  'observed_at': stamp(now()), 'publication_time': None, 'bytes': len(raw)}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / (source['sha256'] + '.csv')).write_bytes(raw)
            payload = {'sport': 'NFL', 'captured_at': stamp(now()), 'sources': [source],
                       'games': normalize('NFL', raw, source, [2025])}
            create(root / 'snapshot.json', envelope(payload))
            self.assertEqual(load_snapshot(root / 'snapshot.json')['payload']['games'], payload['games'])
            payload['games'][0]['home_score'] = 99
            (root / 'snapshot.json').write_text(__import__('json').dumps(envelope(payload)))
            with self.assertRaises(ValueError):
                load_snapshot(root / 'snapshot.json')
            (root / (source['sha256'] + '.csv')).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                load_snapshot(root / 'snapshot.json')

    def test_source_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('project_craps.data.requests.get', side_effect=requests.Timeout('source unavailable')) as get:
                with self.assertRaises(requests.Timeout):
                    capture('NFL', [2025], Path(temp) / 'capture')
                self.assertEqual(get.call_count, 1)
            self.assertFalse((Path(temp) / 'capture' / 'snapshot.json').exists())
