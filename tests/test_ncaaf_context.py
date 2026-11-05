import unittest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from research.ncaaf_context import traps,momentum,injuries,injury_scenario,rank_at,build

ASOF='2026-10-24T12:00:00+00:00'

def proof(day='2026-10-01T00:00:00+00:00'):
    return {'published_at':day,'observed_at':day,'source_url':'https://example.org/test-fixture','source_sha256':'a'*64}

def event(eid='target',date='2026-10-24T18:00:00+00:00',home='H',away='U'):
    return dict(event_id=eid,kickoff=date,home_id=home,away_id=away,season=2026,sport='NCAAF',status='SCHEDULED')

def poll():
    return dict(proof(),poll='AP',complete=True,effective_from='2026-10-01T00:00:00+00:00',
                valid_until='2026-11-01T00:00:00+00:00',ranks={'R':25,**{'T'+str(i):i for i in range(1,25)}})

def schedule():
    return dict(proof(),complete=True,games=[dict(event('prev','2026-10-17T18:00:00+00:00',away='R'),status='FINAL',completed_at='2026-10-17T22:00:00+00:00'),event(),event('next','2026-11-07T18:00:00+00:00',away='R')])

def injury(team='H',attack=6.,defense=0.):
    value=dict(proof(),trained_through='2026-09-01T00:00:00+00:00',model_sha256='b'*64,replacement_player_id='backup',
               baseline_effective_availability=1.,points_for_over_replacement=attack,points_prevented_over_replacement=defense)
    return dict(proof(),event_id='target',team_id=team,player_id='star',position='QB',status='OUT',
                valid_until='2026-10-25T00:00:00+00:00',replacement_value=value)


class ContextTests(unittest.TestCase):
    def test_sandwich_and_bye(self):
        r=traps(event(),'H',schedule(),[poll()],ASOF)
        self.assertTrue(r['before_top25']);self.assertTrue(r['after_top25'])
    def test_ranked_current_opponent_not_trap(self):
        e=event(away='R');s=schedule();s['games'][1]=e
        r=traps(e,'H',s,[poll()],ASOF)
        self.assertFalse(r['before_top25']);self.assertFalse(r['after_top25'])
    def test_unknown_rank_not_unranked(self):
        r=traps(event(),'H',schedule(),[],ASOF)
        self.assertIsNone(r['before_top25']);self.assertIsNone(r['after_top25'])
    def test_future_poll_cannot_leak(self):
        p=poll();p['observed_at']='2026-10-25T00:00:00+00:00'
        self.assertIsNone(rank_at([p],'R',datetime.fromisoformat(ASOF)))
    def test_prior_rank_uses_prior_poll(self):
        old=poll();old['valid_until']='2026-10-20T00:00:00+00:00'
        new=poll();new.update(proof('2026-10-20T00:00:00+00:00'));new['effective_from']='2026-10-20T00:00:00+00:00';new['ranks']['S']=new['ranks'].pop('R')
        r=traps(event(),'H',schedule(),[old,new],ASOF)
        self.assertTrue(r['after_top25']);self.assertFalse(r['before_top25'])
    def test_incomplete_schedule_unknown(self):
        s=schedule();s['complete']=False
        self.assertIsNone(traps(event(),'H',s,[poll()],ASOF)['before_top25'])
    def test_malformed_competition_poll_rank_rejected(self):
        p=poll();p['ranks']['R']=23
        with self.assertRaises(ValueError):rank_at([p],'R',datetime.fromisoformat(ASOF))
    def history(self):
        gs=[]
        for i in range(6):
            start=datetime(2026,9,12,18,tzinfo=timezone.utc)+timedelta(days=7*i)
            g=event('g'+str(i),start.isoformat());g.update(proof((start+timedelta(hours=4)).isoformat()))
            g.update(status='FINAL',completed_at=(start+timedelta(hours=3)).isoformat(),home_score=14 if i<3 else 28,away_score=21,
                     pregame_expectation=dict(proof((start-timedelta(hours=1)).isoformat()),expected_home_margin=0,market_blind=True,model_sha256='c'*64,trained_through='2026-09-01T00:00:00+00:00'))
            gs.append(g)
        return gs
    def test_momentum_both_team_orientations(self):
        h=momentum(event(),'H',self.history(),ASOF);a=momentum(event(),'U',self.history(),ASOF)
        self.assertEqual(h['win_rate_trend'],1.);self.assertEqual(h['opponent_adjusted_margin_trend'],14.)
        self.assertEqual(a['win_rate_trend'],-1.);self.assertEqual(a['opponent_adjusted_margin_trend'],-14.)
    def test_late_result_not_used(self):
        gs=self.history();gs[-1]['observed_at']='2026-10-25T00:00:00+00:00'
        r=momentum(event(),'H',gs,ASOF)
        self.assertIsNone(r['win_rate_trend']);self.assertEqual(r['previous_three']['games'],2)
    def test_no_expectation_no_adjusted_momentum(self):
        gs=self.history();gs[-1].pop('pregame_expectation')
        self.assertIsNone(momentum(event(),'H',gs,ASOF)['opponent_adjusted_margin_trend'])
    def test_duplicate_game_rejected(self):
        gs=self.history()
        with self.assertRaises(ValueError):momentum(event(),'H',gs+[gs[0]],ASOF)
    def test_star_out_mean_impact(self):
        r=injuries(event(),[injury()],ASOF,roster_coverage_complete=True)
        self.assertEqual(r['margin_delta'],-6.);self.assertEqual(r['total_delta'],-6.)
    def test_away_star_out_orientation(self):
        r=injuries(event(),[injury(team='U')],ASOF,roster_coverage_complete=True)
        self.assertEqual(r['margin_delta'],6.);self.assertEqual(r['total_delta'],-6.)
    def test_defensive_star_out(self):
        r=injuries(event(),[injury(attack=0,defense=3)],ASOF,roster_coverage_complete=True)
        self.assertEqual(r['margin_delta'],-3.);self.assertEqual(r['total_delta'],3.)
    def test_no_double_injury_deduction(self):
        i=injury();i['replacement_value']['baseline_effective_availability']=0.
        self.assertEqual(injuries(event(),[i],ASOF,roster_coverage_complete=True)['margin_delta'],0.)
    def test_unknown_questionable_blocks(self):
        i=injury();i['status']='QUESTIONABLE'
        self.assertEqual(injuries(event(),[i],ASOF,roster_coverage_complete=True)['status'],'NOT_COMPUTED')
    def test_missing_player_value_blocks(self):
        i=injury();i.pop('replacement_value')
        self.assertIsNone(injuries(event(),[i],ASOF,roster_coverage_complete=True)['margin_delta'])
    def test_absence_of_injury_report_not_healthy(self):
        self.assertEqual(injuries(event(),[],ASOF)['status'],'NOT_COMPUTED')
    def test_stale_injury_and_duplicate_player_rejected(self):
        i=injury();i['valid_until']='2026-10-23T00:00:00+00:00'
        with self.assertRaises(ValueError):injuries(event(),[i],ASOF,roster_coverage_complete=True)
        with self.assertRaises(ValueError):injuries(event(),[injury(),injury()],ASOF,roster_coverage_complete=True)
    def test_future_value_fit_rejected(self):
        i=injury();i['replacement_value']['trained_through']='2026-10-25T00:00:00+00:00'
        with self.assertRaises(ValueError):injuries(event(),[i],ASOF,roster_coverage_complete=True)
    def test_injury_changes_probability_without_mutating_model(self):
        artifact={'sport':'NCAAF','margin':{'intercept':0.,'coefficients':[0.]*10},'total':{'intercept':50.,'coefficients':[0.]*10},'residual_pairs':[[-8,0],[-4,0],[2,0],[6,0],[10,0]]}
        original=deepcopy(artifact)
        baseline=injury_scenario(artifact,[0.]*10,{'status':'RESEARCH_SCENARIO_ONLY','margin_delta':0.,'total_delta':0.},'moneyline','home')
        adjustment=injuries(event(),[injury()],ASOF,roster_coverage_complete=True)
        changed=injury_scenario(artifact,[0.]*10,adjustment,'moneyline','home')
        self.assertLess(changed['p_win'],baseline['p_win']);self.assertEqual(artifact,original)
        self.assertAlmostEqual(sum(changed[k] for k in ['p_win','p_push','p_loss']),1.)
        self.assertFalse(changed['production_approved'])
    def test_started_event_rejected(self):
        with self.assertRaises(ValueError):build(event(),schedule(),[poll()],[],[],event()['kickoff'])

    def test_unplayed_previous_not_letdown(self):
        s=schedule();s['games'][0]['status']='SCHEDULED'
        self.assertIsNone(traps(event(),'H',s,[poll()],ASOF)['after_top25'])
    def test_conflicting_poll_editions_rejected(self):
        p=poll();q=poll();q['ranks']['S']=q['ranks'].pop('R')
        with self.assertRaises(ValueError):rank_at([p,q],'R',datetime.fromisoformat(ASOF))

    def test_questionable_expected_shift_not_probability_precision(self):
        i=injury();i.update(status='QUESTIONABLE',expected_effective_availability=.5,availability_estimate_method='synthetic test estimate')
        r=injuries(event(),[i],ASOF,roster_coverage_complete=True)
        self.assertEqual(r['margin_delta'],-3.)
        with self.assertRaises(ValueError):injury_scenario({'sport':'NCAAF'},[0.]*10,r,'moneyline','home')

    def test_market_derived_expectation_rejected(self):
        gs=self.history();gs[0]['pregame_expectation']['market_blind']=False
        with self.assertRaises(ValueError):momentum(event(),'H',gs,ASOF)
    def test_build_keeps_missing_injury_gate(self):
        r=build(event(),schedule(),[poll()],self.history(),[],ASOF)
        self.assertEqual(r['approval'],'RESEARCH_ONLY')
        self.assertEqual(r['injuries']['status'],'NOT_COMPUTED')
        self.assertEqual(r['trap_momentum_coefficients'],'NOT_FITTED')
        self.assertEqual(r['home']['momentum']['opponent_adjusted_margin_trend'],14.)


class PollTieTests(unittest.TestCase):
    def test_legitimate_tie_in_middle(self):
        p=poll();p['ranks']['T15']=14
        self.assertEqual(rank_at([p],'T15',datetime.fromisoformat(ASOF)),14)
    def test_tie_at24_without25(self):
        p=poll();p['ranks']['R']=24
        self.assertEqual(rank_at([p],'R',datetime.fromisoformat(ASOF)),24)
    def test_tie25_extends_ranked_teams(self):
        p=poll();p['ranks']['extra']=25
        self.assertEqual(rank_at([p],'extra',datetime.fromisoformat(ASOF)),25)
    def test_truncated_poll_and_outside_top25_rejected(self):
        p=poll();p['ranks'].pop('R')
        with self.assertRaises(ValueError):rank_at([p],'R',datetime.fromisoformat(ASOF))
        p=poll();p['ranks']['R']=26
        with self.assertRaises(ValueError):rank_at([p],'R',datetime.fromisoformat(ASOF))
