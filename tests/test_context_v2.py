import unittest
from research.context_v2 import context, great_circle_km, regulation_summary, shrink_offseason, fit_normalizer, normalize


class ContextV2Tests(unittest.TestCase):
    def setUp(self):
        self.event = dict(event_id='target', season=2026, home_id='h', away_id='a', kickoff='2026-11-06T20:00:00Z')
        self.cutoff = '2026-11-06T10:00:00Z'

    def test_missing_games_retained(self):
        result = context(self.event, [], self.cutoff)
        self.assertEqual(set(result['teams']), {'h','a'})
        self.assertIsNone(result['teams']['h']['momentum_innovation'])
        self.assertIsNone(result['teams']['a']['recovery_days'])

    def test_target_and_late_inputs_rejected(self):
        with self.assertRaises(ValueError):
            context(self.event, [self.event], self.cutoff)
        game = dict(event_id='prior', status='FINAL', observed_at='2026-11-07T00:00:00Z')
        with self.assertRaises(ValueError):
            context(self.event, [game], self.cutoff)
        with self.assertRaises(ValueError):
            context(self.event, [], self.event['kickoff'])

    def test_recovery_uses_completion_and_residual_momentum(self):
        games=[]
        for i in range(6):
            day=i+1
            games.append(dict(event_id=str(i), season=2026, home_id='h', away_id='x', status='FINAL',
                kickoff=f'2026-10-{day:02d}T12:00:00Z', completed_at=f'2026-10-{day:02d}T16:00:00Z',
                observed_at=f'2026-10-{day:02d}T17:00:00Z', home_score=30+i, away_score=20,
                pregame_expectation=dict(observed_at=f'2026-10-{day:02d}T10:00:00Z', trained_through='2026-09-01T00:00:00Z', market_blind=True, expected_home_margin=10)))
        result=context(self.event,games,self.cutoff)['teams']['h']
        self.assertEqual(result['momentum_innovation'],3)
        self.assertAlmostEqual(result['recovery_days'],31+4/24)
        games[-1]['pregame_expectation']['observed_at']=games[-1]['kickoff']
        with self.assertRaises(ValueError): context(self.event,games,self.cutoff)

    def test_geographic_proxy(self):
        self.assertEqual(great_circle_km([0,0],[0,0]),0)
        self.assertAlmostEqual(great_circle_km([0,0],[0,90]),10007.5572,places=3)
        with self.assertRaises(ValueError): great_circle_km([91,0],[0,0])

    def test_overtime_not_removed_from_settlement(self):
        result=regulation_summary(dict(home_score=37,away_score=31,regulation_scores=[24,24],regulation_possessions=[12,12]))
        self.assertEqual(result['settlement_scores'],[37,31])
        self.assertEqual(result['regulation_points_per_possession'],[2,2])
        self.assertIsNone(regulation_summary(dict(home_score=37,away_score=31))['regulation_points_per_possession'])

    def test_train_only_normalization_missingness(self):
        rows=[dict(kickoff='2026-10-01T00:00:00Z',observed_at='2026-10-02T00:00:00Z',features={'x':v,'missing':None}) for v in [1,3]]
        fitted=fit_normalizer(rows,train_end='2026-10-03T00:00:00Z')
        self.assertEqual(normalize({'x':5},fitted),{'features':{'missing':None,'x':3},'missing':['missing']})
        with self.assertRaises(ValueError): fit_normalizer(rows,train_end='2026-09-30T00:00:00Z')
        self.assertEqual(shrink_offseason({'elo':1600},{'elo':1500},.5),{'elo':1550})
        with self.assertRaises(ValueError): shrink_offseason({'elo':1600},{'elo':1500},1.1)

class EfficiencyAndPreflightTests(unittest.TestCase):
    def rows(self):
        return [dict(event_id=str(i),home_id=h,away_id=a,neutral=False,status='FINAL',kickoff='2026-10-01T12:00:00Z',completed_at='2026-10-01T16:00:00Z',observed_at='2026-10-01T17:00:00Z',home_score=30,away_score=20,regulation_scores=[30,20],regulation_possessions=[10,10]) for i,(h,a) in enumerate([('a','b'),('b','a')])]

    def test_identified_efficiency_home_neutral_and_future_guard(self):
        from research.context_v2 import fit_team_efficiency,predict_team_efficiency
        rows=self.rows(); m=fit_team_efficiency(rows,train_end='2026-10-02T00:00:00Z',ridge=1)
        self.assertAlmostEqual(sum(m['offense'].values()),0)
        self.assertAlmostEqual(sum(m['defense'].values()),0)
        home=predict_team_efficiency(m,'a','b',neutral=False)
        neutral=predict_team_efficiency(m,'a','b',neutral=True)
        self.assertGreater(home['home_ppp'],neutral['home_ppp'])
        self.assertEqual(home['away_ppp'],neutral['away_ppp'])
        self.assertIsNone(predict_team_efficiency(m,'new','b',neutral=False)['home_ppp'])
        with self.assertRaises(ValueError): fit_team_efficiency(rows,train_end='2026-09-01T00:00:00Z',ridge=1)
        with self.assertRaises(ValueError): fit_team_efficiency(rows,train_end='2026-10-02T00:00:00Z',ridge=0)

    def test_preflight_vintage_missing_and_end_to_end(self):
        from research.context_v2 import preflight_context,run_candidate
        event=dict(event_id='target',home_id='a',away_id='b',season=2026,stadium_id='venue',neutral=True,kickoff='2026-11-06T20:00:00Z')
        weather=dict(stadium_id='venue',forecast_for=event['kickoff'],forecast_issued_at='2026-11-06T08:00:00Z',observed_at='2026-11-06T09:00:00Z',wind_mph=10,gust_mph=20,precip_probability=.5,temperature_f=60,roof='open')
        out=preflight_context(event,'2026-11-06T10:00:00Z',{'weather':weather})
        self.assertEqual(len(out['inputs']['weather']),1)
        self.assertTrue(out['blockers'])
        weather['forecast_issued_at']='2026-11-06T11:00:00Z'
        with self.assertRaises(ValueError): preflight_context(event,'2026-11-06T10:00:00Z',{'weather':weather})
        run=run_candidate(event,[],'2026-11-06T10:00:00Z',contextual_inputs={},training_rows=self.rows(),train_end='2026-10-02T00:00:00Z',ridge=1)
        self.assertIsNotNone(run['efficiency_prediction'])
        self.assertFalse(run['production_approved'])
        self.assertEqual(run['approved_risk_usd'],0)

    def test_explicit_fixed_shrink_boundaries(self):
        from research.context_v2 import shrink_offseason
        self.assertEqual(shrink_offseason({'attack':30},{'attack':24},0),{'attack':24})
        self.assertEqual(shrink_offseason({'attack':30},{'attack':24},1),{'attack':30})

    def test_matchup_rates_and_future_window_guard(self):
        from research.context_v2 import preflight_context
        event=dict(event_id='target',home_id='a',away_id='b',kickoff='2026-11-06T20:00:00Z')
        row=dict(team_id='a',window_end='2026-11-01T00:00:00Z',observed_at='2026-11-02T00:00:00Z',sacks_allowed=2,dropbacks=40,pass_plays=30,offensive_plays=60,ol_returning_starters=4,ol_starter_slots=5)
        result=preflight_context(event,'2026-11-06T10:00:00Z',{'matchup':[row]})
        accepted=result['inputs']['matchup'][0]
        self.assertEqual(accepted['sack_rate'],.05)
        self.assertEqual(accepted['pass_tendency'],.5)
        self.assertEqual(accepted['ol_continuity'],.8)
        row['window_end']='2026-11-07T00:00:00Z'
        with self.assertRaises(ValueError): preflight_context(event,'2026-11-06T10:00:00Z',{'matchup':[row]})
