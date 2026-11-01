import copy
import unittest
from datetime import timedelta
from project_craps.common import digest, envelope, stamp, unwrap
from project_craps.features import historical_features, live_features
from project_craps.model import outcome_masses, score_distribution, validate_artifact
from project_craps.pipeline import forecast
from project_craps.train import fit_model
from helpers import fixtures


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = {sport: fixtures(sport) for sport in ('NFL', 'NCAAF')}

    def run_forecast(self, sport='NFL', change=None):
        issued, model, snap, quote, context = copy.deepcopy(self.fixtures[sport])
        if change:
            change(snap, quote, context)
            snap = envelope(snap['payload'])
        return forecast(model, snap, 'future', quote, context, clock=lambda: issued)

    def test_both_sports_end_to_end(self):
        for sport in self.fixtures:
            result = self.run_forecast(sport)
            self.assertEqual(result['status'], 'EXPERIMENTAL', result['reasons'])
            self.assertAlmostEqual(sum(result['probabilities'].values()), 1)
            self.assertEqual(result['approved_risk'], 0)
            self.assertEqual(result['qualification'], 'PASS')

    def test_quotes_do_not_change_market_blind_distribution(self):
        a = self.run_forecast()
        b = self.run_forecast(change=lambda s, q, c: q.update(american_odds=180, line=7.5))
        self.assertNotEqual(a['request_key'], b['request_key'])
        self.assertEqual(a['distribution_sha256'], b['distribution_sha256'])
        self.assertEqual(a['feature_sha256'], b['feature_sha256'])

    def test_target_scores_and_extra_market_fields_not_features(self):
        a = self.run_forecast()
        def mutate(s, q, c):
            event = next(g for g in s['payload']['games'] if g['event_id'] == 'future')
            event.update(home_score=99, away_score=0, bookmaker_probability=.99)
        b = self.run_forecast(change=mutate)
        self.assertEqual(a['distribution_sha256'], b['distribution_sha256'])

    def test_missing_context_blocks_numbers(self):
        result = self.run_forecast(change=lambda s, q, c: c.pop('quarterback'))
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIsNone(result['probabilities'])

    def test_stale_future_and_identity_fail_closed(self):
        issued = self.fixtures['NFL'][0]
        changes = [lambda s, q, c: q.update(observed_at=stamp(issued-timedelta(minutes=6))),
                   lambda s, q, c: q.update(observed_at=stamp(issued+timedelta(seconds=1))),
                   lambda s, q, c: q.update(event_id='wrong'),
                   lambda s, q, c: q.update(kickoff=stamp(issued+timedelta(hours=3))),
                   lambda s, q, c: q.update(expires_at=stamp(issued)),
                   lambda s, q, c: q.update(american_odds=float('nan')),
                   lambda s, q, c: q.update(scope='regulation_only')]
        for change in changes:
            with self.subTest(change=change):
                try:
                    result = self.run_forecast(change=change)
                except ValueError:  # NaN fails canonical input hashing before persistence.
                    continue
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertIsNone(result['probabilities'])

    def test_started_game_rejected(self):
        issued, model, snap, quote, context = self.fixtures['NFL']
        with self.assertRaises(ValueError):
            forecast(model, snap, 'future', quote, context, clock=lambda: issued+timedelta(hours=3))

    def test_wrong_model_sport_and_corruption_rejected(self):
        issued, model, snap, quote, context = copy.deepcopy(self.fixtures['NFL'])
        model['payload']['margin']['intercept'] += 1
        with self.assertRaises(ValueError):
            forecast(model, snap, 'future', quote, context, clock=lambda: issued)
        with self.assertRaises(ValueError):
            validate_artifact(self.fixtures['NCAAF'][1], 'NFL')

    def test_same_utc_day_not_updated(self):
        issued, model, snap, quote, context = copy.deepcopy(self.fixtures['NFL'])
        g = next(x for x in snap['payload']['games'] if x['status'] == 'FINAL')
        h = copy.deepcopy(g)
        h['event_id'] = 'same-day'
        h['kickoff'] = stamp(__import__('project_craps.common', fromlist=['instant']).instant(g['kickoff'])+timedelta(hours=1))
        rows, state = historical_features([g, h])
        self.assertEqual(rows[0][1], rows[1][1])

    def test_future_history_rejected(self):
        issued, model, snap, quote, context = copy.deepcopy(self.fixtures['NFL'])
        snap['payload']['games'][0]['observed_at'] = stamp(issued+timedelta(seconds=1))
        result = forecast(model, envelope(snap['payload']), 'future', quote, context, clock=lambda: issued)
        self.assertEqual(result['status'], 'BLOCKED')

    def test_threeway_integer_halfpoint_and_tie_rules(self):
        scores = [(20, 17), (21, 17), (10, 17), (17, 17)]
        self.assertEqual(outcome_masses(scores, 'spread', 'home', -3), (.25, .25, .5))
        self.assertEqual(outcome_masses(scores, 'spread', 'away', 3), (.5, .25, .25))
        self.assertEqual(outcome_masses(scores, 'spread', 'home', -3.5), (.25, 0, .75))
        self.assertEqual(outcome_masses(scores, 'moneyline', 'home', tie_policy='refund'), (.5, .25, .25))
        with self.assertRaises(ValueError):
            outcome_masses(scores, 'moneyline', 'home')
        self.assertEqual(outcome_masses([(21, 21), (20, 21)], 'total', 'over', 42), (0, .5, .5))

    def test_ncaa_fullgame_support_excludes_ties(self):
        issued, model, snap, quote, context = self.fixtures['NCAAF']
        result = self.run_forecast('NCAAF')
        self.assertTrue(all(h != a for h, a in result['score_support']))

    def test_training_splits_and_future_results(self):
        issued, model, snap, quote, context = copy.deepcopy(self.fixtures['NFL'])
        rows, state = historical_features(snap['payload']['games'])
        first = fit_model(rows, 'NFL', 2023, 2024, minimum=2)
        for game in snap['payload']['games']:
            if game['season'] >= 2025 and game['status'] == 'FINAL':
                game['home_score'] = 99
        changed, _ = historical_features(snap['payload']['games'])
        self.assertEqual(first, fit_model(changed, 'NFL', 2023, 2024, minimum=2))
        with self.assertRaises(ValueError):
            fit_model(rows, 'NFL', 2024, 2024, minimum=2)
