import csv
import io
import unittest
from datetime import timedelta
from project_craps.common import now, stamp
from project_craps.data import normalize


class DataTests(unittest.TestCase):
    def source(self):
        return {'observed_at': stamp(now()), 'sha256': 'fixture', 'url': 'https://example.test'}

    def csv(self, rows):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode()

    def nfl(self):
        return {'game_id': 'fixture', 'season': '2025', 'home_team': 'A', 'away_team': 'B',
          'game_type': 'REG', 'gameday': '2025-11-02', 'gametime': '13:00',
          'home_score': '', 'away_score': '', 'location': 'Home'}

    def test_nfl_eastern_dst_and_identity(self):
        games = normalize('NFL', self.csv([self.nfl()]), self.source(), [2025])
        self.assertEqual(games[0]['kickoff'], '2025-11-02T18:00:00+00:00')
        self.assertEqual(games[0]['home_id'], 'A')
        self.assertIsNone(games[0]['home_score'])

    def test_nfl_schema_drift_rejected(self):
        row = self.nfl()
        row.pop('gametime')
        with self.assertRaises(ValueError):
            normalize('NFL', self.csv([row]), self.source(), [2025])

    def test_ncaa_requires_fbs_and_final_flag(self):
        row = {'game_id': 'fixture', 'season': '2025', 'home_team': 'A', 'away_team': 'B',
         'home_id': '1', 'away_id': '2', 'start_date': '2025-10-01T19:00:00Z',
         'start_time_tbd': 'FALSE', 'completed': 'FALSE', 'neutral_site': 'TRUE',
         'home_division': 'fbs', 'away_division': 'fcs', 'home_points': '0', 'away_points': '0'}
        self.assertEqual(normalize('NCAAF', self.csv([row]), self.source(), [2025]), [])
        row['away_division'] = 'fbs'
        result = normalize('NCAAF', self.csv([row]), self.source(), [2025])[0]
        self.assertEqual(result['status'], 'SCHEDULED')
        self.assertTrue(result['neutral'])
        self.assertIsNone(result['home_score'])

    def test_future_final_rejected(self):
        row = self.nfl()
        row.update(gameday='2099-01-01', season='2099', home_score='10', away_score='7')
        with self.assertRaises(ValueError):
            normalize('NFL', self.csv([row]), self.source(), [2099])
