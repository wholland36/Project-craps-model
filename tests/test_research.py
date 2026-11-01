import copy
import csv
from datetime import timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import numpy as np
from project_craps.common import digest,now,stamp
from research.data import nfl_metrics,cfb_metrics
from research.features import build,player_sacks,feature_names
from research.experiment import compare,distribution,fit,groups,masses,predict_records
from research.store import ShadowStore
from helpers import fixtures


def prepared(sport='NFL'):
    issued,model,snap,quote,context=fixtures(sport)
    games=snap['payload']['games']
    metadata={g['event_id']:{'spread_home_margin':None,'total_line':None,'overtime':None} for g in games}
    stats={}
    for i,g in enumerate(games):
        for team in ('A','B'):
            stats[(g['event_id'],team)]={'epa':.01*i,'volume':60.,'turnovers':.02,'disruption':.05,'explosive':.1}
    rows=build(games,metadata,{},nfl=stats)
    return issued,games,stats,metadata,rows


class ResearchFeatureTests(unittest.TestCase):
    def test_current_and_future_game_stats_cannot_leak(self):
        issued,games,stats,metadata,rows=prepared()
        target=games[10]
        stats[(target['event_id'],'A')]['epa']=10000
        for g in games:
            if g['kickoff']>target['kickoff']:
                stats[(g['event_id'],'A')]['epa']=9999
        changed=build(games,metadata,{},nfl=stats)
        before={r['game']['event_id']:r for r in rows}
        after={r['game']['event_id']:r for r in changed}
        self.assertEqual(before[target['event_id']]['features'],after[target['event_id']]['features'])
        earlier=[g['event_id'] for g in games if g['kickoff']<=target['kickoff'] and g['status']=='FINAL']
        for eid in earlier:self.assertEqual(before[eid]['features'],after[eid]['features'])

    def test_weekly_summary_cutoff_prevents_future_week_leakage(self):
        issued,games,stats,metadata,rows=prepared('NCAAF')
        first=games[0];second=games[1]
        cutoff=__import__('project_craps.common',fromlist=['instant']).instant(second['kickoff'])+timedelta(days=2)
        values={k:1. for k in ['EPAplay_off','playsgame_off','turnovers_off','havoc_off','explosive_off','EPAplay_def','playsgame_def','turnovers_def','havoc_def','explosive_def']}
        cfb={(first['season'],'A',1):values}
        result=build(games,metadata,{(first['season'],1):cutoff},cfb=cfb)
        values['EPAplay_off']=9999
        changed=build(games,metadata,{(first['season'],1):cutoff},cfb=cfb)
        self.assertEqual(result[0]['features'],changed[0]['features'])
        self.assertEqual(result[1]['features'],changed[1]['features'])
        self.assertNotEqual(result[2]['features']['efficiency'],changed[2]['features']['efficiency'])

    def test_franchise_aliases_do_not_drop_historical_metrics(self):
        issued,games,stats,metadata,rows=prepared()
        games=copy.deepcopy(games[:3])
        for g in games:g['home_id']='OAK'
        stats={(g['event_id'],t):{'epa':.2,'volume':60.,'turnovers':.02,'disruption':.05,'explosive':.1} for g in games for t in ('LV','B')}
        result=build(games,metadata,{},nfl=stats)
        self.assertTrue(result[1]['efficiency_complete'])

    def test_actual_sacks_deduplicate_play_and_match_event_identity(self):
        issued,games,stats,metadata,rows=prepared('NCAAF');game=games[0]
        fields=['game_id','play_id','team','opponent','sack_taken_stat','sack_taken_player_id','completion_player_id']
        row={'game_id':game['event_id'],'play_id':'1','team':game['home'],'opponent':game['away'],'sack_taken_stat':'1','sack_taken_player_id':'qb','completion_player_id':'NA'}
        other=dict(row,play_id='2',sack_taken_stat='NA',sack_taken_player_id='NA',completion_player_id='qb')
        with tempfile.TemporaryDirectory() as temp:
            with (Path(temp)/'plays.csv').open('w') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows([row,row,other])
            rates,coverage=player_sacks(temp,[{'file':'plays.csv'}],[game])
        self.assertEqual(rates[(game['event_id'],'A')],.5)
        self.assertEqual(coverage['matched_unique_plays'],2)

    def test_metric_schema_drift_fails(self):
        with self.assertRaises(ValueError):nfl_metrics([{'game_id':'x'}])
        with self.assertRaises(ValueError):cfb_metrics([{'season':2025}])

    def test_future_target_features_do_not_update_state(self):
        issued,games,stats,metadata,rows=prepared()
        target=copy.deepcopy(next(g for g in games if g['event_id']=='future'))
        first=build(games,metadata,{},nfl=stats,future_targets=[target],asof=issued)[-1]
        target['home_score']=99;target['away_score']=0
        other=build(games,metadata,{},nfl=stats,future_targets=[target],asof=issued)[-1]
        self.assertEqual(first['features'],other['features'])
        target['kickoff']=stamp(issued)
        with self.assertRaises(ValueError):build(games,metadata,{},nfl=stats,future_targets=[target],asof=issued)


class ResearchExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.issued,cls.games,cls.stats,cls.metadata,cls.rows=prepared()

    def test_test_year_changes_cannot_alter_fit_or_scaler(self):
        first=fit(self.rows,'efficiency',2025,minimum=2)
        changed=copy.deepcopy(self.rows)
        for row in changed:
            if row['game']['season']>=2025:
                row['game']['home_score']=100
                row['features']['efficiency']=[10000]*40
        self.assertEqual(first,fit(changed,'efficiency',2025,minimum=2))

    def test_feature_order_and_shapes(self):
        for variant in ('original','scaled','opponent_score','efficiency','score_kernel'):
            self.assertEqual(len(feature_names(variant)),len(self.rows[0]['features'][variant]))

    def test_distribution_mass_and_push_calculation(self):
        for variant in ('efficiency','score_kernel'):
            model=fit(self.rows,variant,2025,minimum=2)
            scores,w=distribution(model,self.rows[-1]['features'][variant])
            self.assertAlmostEqual(w.sum(),1)
            self.assertTrue(np.all(scores>=0))
            self.assertAlmostEqual(masses(scores,w,'spread',-3).sum(),1)
        scores=np.array([[20,17],[21,17],[10,17]]);w=np.array([.2,.5,.3])
        np.testing.assert_allclose(masses(scores,w,'spread',-3),[.5,.2,.3])

    def test_kernel_is_only_distribution_change(self):
        a=fit(self.rows,'efficiency',2025,minimum=2);b=fit(self.rows,'score_kernel',2025,minimum=2)
        self.assertEqual(a['margin'],b['margin']);self.assertEqual(a['total'],b['total'])
        self.assertEqual(a['residual_pairs'],b['residual_pairs'])

    def test_paired_cohort_mismatch_rejected(self):
        a=[{'event_id':'one'}];b=[{'event_id':'two'}]
        with self.assertRaises(ValueError):compare(a,b)

    def test_missing_book_lines_are_not_invented(self):
        model=fit(self.rows,'original',2025,minimum=2)
        records=predict_records(model,[r for r in self.rows if r['game']['season']==2025])
        report=groups(records)
        self.assertEqual(set(report['book_spread_size_unverified']),{'UNKNOWN'})
        self.assertIn('UNKNOWN',report['overtime_diagnostic'])


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.issued=now()
        self.store=ShadowStore(Path(self.temp.name)/'shadow.sqlite',clock=lambda:self.issued)
        self.record={'key':'one','event_id':'one','sport':'NFL','identity':{'home_id':'A','away_id':'B'},
             'kickoff':stamp(self.issued+timedelta(hours=2)),'issued_at':stamp(self.issued),
             'protocol_sha256':'protocol','model_approved':False,'approved_risk':0,
             'predictions':{'test':{'home_win':.6,'home_tie':.01}}}

    def tearDown(self):self.store.close();self.temp.cleanup()

    def test_retry_revision_and_first_record(self):
        first=self.store.append(self.record)
        self.assertEqual(first,self.store.append(self.record))
        second=self.store.append(dict(self.record,key='two'))
        self.assertEqual(second['first_shadow_key'],'one')
        self.assertEqual(self.store.verify()['count'],2)

    def test_sql_mutation_and_invalid_probability_rejected(self):
        self.store.append(self.record)
        with self.assertRaises(sqlite3.IntegrityError):self.store.db.execute('DELETE FROM records')
        with self.assertRaises(ValueError):self.store.append(dict(self.record,key='bad',approved_risk=100))
        bad=copy.deepcopy(self.record);bad['key']='bad';bad['predictions']['test']['home_win']=2
        with self.assertRaises(ValueError):self.store.append(bad)

    def test_started_identity_and_corruption_rejected(self):
        with self.assertRaises(ValueError):self.store.append(dict(self.record,kickoff=stamp(self.issued)))
        self.store.append(self.record)
        bad=copy.deepcopy(self.record);bad['key']='two';bad['identity']['home_id']='C'
        with self.assertRaises(ValueError):self.store.append(bad)
        self.store.db.execute('DROP TRIGGER records_no_update')
        self.store.db.execute("UPDATE records SET payload='{}'")
        with self.assertRaises((ValueError,KeyError)):self.store.verify()


def _multiprocess_write(args):
    path,record=args
    from project_craps.common import instant
    store=ShadowStore(path,clock=lambda:instant(record['issued_at']))
    try:
        for i in range(10):store.append(dict(record,key='multi-'+str(i)))
        return store.verify()['count']
    finally:store.close()


class ShadowRecoveryTests(unittest.TestCase):
    setUp=ShadowTests.setUp
    tearDown=ShadowTests.tearDown

    def test_two_process_writers_preserve_one_immutable_cohort(self):
        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context
        with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
            results=list(pool.map(_multiprocess_write,[(str(Path(self.temp.name)/'shadow.sqlite'),self.record)]*2))
        self.assertEqual(self.store.verify()['count'],10)
        self.assertEqual(max(results),10)

    def test_uncertain_commit_is_not_masked_and_retry_preserves_original(self):
        original=self.store.db
        class UncertainCommit:
            def __init__(self,connection):self.connection=connection;self.fail=True
            @property
            def in_transaction(self):return self.connection.in_transaction
            def execute(self,sql,*args):
                result=self.connection.execute(sql,*args)
                if sql=='COMMIT' and self.fail:
                    self.fail=False
                    raise sqlite3.OperationalError('simulated response lost after commit')
                return result
            def close(self):self.connection.close()
        self.store.db=UncertainCommit(original)
        with self.assertRaisesRegex(sqlite3.OperationalError,'simulated response lost'):
            self.store.append(self.record)
        saved=self.store.append(self.record)
        self.assertEqual(saved['issued_at'],self.record['issued_at'])
        self.assertEqual(self.store.verify()['count'],1)


class ContextIdentityTests(unittest.TestCase):
    def test_provider_aliases_are_explicit_and_mismatches_quarantine(self):
        from unittest.mock import patch
        from research.context import collect
        issued=now();kickoff=stamp(issued+timedelta(hours=3))
        event={'sport':'NFL','event_id':'game','kickoff':kickoff,'status':'SCHEDULED','home_id':'LA','away_id':'WAS'}
        summary={'header':{'id':'provider-game','competitions':[{'date':kickoff,'status':{'type':{'state':'pre'}},
                  'competitors':[{'homeAway':'home','team':{'abbreviation':'LAR'}},{'homeAway':'away','team':{'abbreviation':'WSH'}}]}]}}
        receipt={'sha256':'fixture','observed_at':stamp(issued)}
        with tempfile.TemporaryDirectory() as temp:
            with patch('research.context.observe',side_effect=[({},receipt),(summary,receipt)]):
                result=collect([event],{'game':{'espn_event_id':'provider-game'}},Path(temp)/'correct')
            self.assertTrue(result['events'][0]['pregame_status_verified'])
            summary['header']['competitions'][0]['competitors'][0]['team']['abbreviation']='NYJ'
            with patch('research.context.observe',side_effect=[({},receipt),(summary,receipt)]):
                result=collect([event],{'game':{'espn_event_id':'provider-game'}},Path(temp)/'wrong')
            self.assertTrue(result['events'][0]['integrity_failure'])


class ShadowSettlementTests(unittest.TestCase):
    setUp=ShadowTests.setUp
    tearDown=ShadowTests.tearDown

    def test_settlement_requires_original_source_observation_and_preserves_first(self):
        self.store.append(self.record)
        self.store.append(dict(self.record,key='revision'))
        final_time=self.issued+timedelta(hours=6)
        self.store.clock=lambda:final_time
        game={'event_id':'one','status':'FINAL','home_id':'A','away_id':'B',
              'kickoff':self.record['kickoff'],'home_score':21,'away_score':17,
              'observed_at':stamp(final_time),'source_sha256':'source'}
        result=self.store.settle([game],stamp(final_time))
        self.assertEqual(result['new_results'],2)
        rows=[json.loads(r[0]) for r in self.store.db.execute('SELECT payload FROM results')]
        self.assertEqual(sum(r['first_event_prediction'] for r in rows),1)
        self.assertAlmostEqual(rows[0]['scores']['test']['home_win_brier'],.16)
        self.assertTrue(all(r['official_pnl']==0 for r in rows))
        self.assertEqual(self.store.settle([game],stamp(final_time))['new_results'],0)
        game['home_score']=17
        with self.assertRaises(ValueError):self.store.settle([game],stamp(final_time))

    def test_source_captured_before_kickoff_cannot_be_relabelled_as_postgame(self):
        self.store.append(self.record)
        final_time=self.issued+timedelta(hours=6);self.store.clock=lambda:final_time
        game={'event_id':'one','status':'FINAL','home_id':'A','away_id':'B',
              'kickoff':self.record['kickoff'],'home_score':21,'away_score':17,
              'observed_at':stamp(self.issued)}
        with self.assertRaises(ValueError):self.store.settle([game],stamp(final_time))


class AnalysisTests(unittest.TestCase):
    def test_book_benchmark_excludes_ties_and_conditions_model_probability(self):
        from project_craps.common import bytes_hash,create
        from research.analysis.benchmarks import benchmark_report
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            raw=b'game_id,home_moneyline,away_moneyline\none,-110,100\ntie,-110,100\n'
            sha=bytes_hash(raw);(root/(sha+'.csv')).write_bytes(raw)
            create(root/'snapshot.json',{'payload':{'sport':'NFL','games':[],'sources':[{'sha256':sha}]}})
            create(root/'report.json',{'protocol':{'variants':['original'],'evaluation_seasons':[2025]}})
            rows=[{'event_id':'one','actual_margin':3,'actual_home_win':1,'pred_tie':.1,'p_home_win':.6,'cluster':'2025-1'},
                  {'event_id':'tie','actual_margin':0,'actual_home_win':0,'pred_tie':.1,'p_home_win':.6,'cluster':'2025-1'}]
            create(root/'2025-original-predictions.json',rows)
            report=benchmark_report(root,root/'snapshot.json',root/'benchmark.json')
        actual=report['variants']['original']['seasons']['2025']
        self.assertEqual(actual['matched_n'],1)
        self.assertAlmostEqual(actual['model']['brier'],(2/3-1)**2)
        self.assertFalse(report['original_publication_times_verified'])

    def test_forward_report_counts_only_first_event_records(self):
        from research.analysis.forward import report
        issued=now()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'shadow.sqlite';store=ShadowStore(path,clock=lambda:issued)
            record={'key':'first','event_id':'one','sport':'NFL','identity':{'home_id':'A'},
                'kickoff':stamp(issued+timedelta(hours=2)),'issued_at':stamp(issued),
                'protocol_sha256':'p','model_approved':False,'approved_risk':0,
                'predictions':{'test':{'home_win':.6,'home_tie':0}}}
            store.append(record);store.append(dict(record,key='revision'));store.close()
            result=report(path,Path(temp)/'forward.json')
        self.assertEqual(result['all_records'],2)
        self.assertEqual(result['unique_first_event_records'],1)
        self.assertEqual(result['settled_first_event_records'],0)
