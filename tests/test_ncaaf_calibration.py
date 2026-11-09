import unittest
from research.ncaaf_calibration import calibrate,fit_slope,proper

class CalibrationTests(unittest.TestCase):
    def test_push_and_complement_and_identity(self):
        for slope in [0,.3,1,5]:
            w,p,l=calibrate([.6,.1,.3],slope);a,b,c=calibrate([.3,.1,.6],slope)
            self.assertAlmostEqual(w+p+l,1);self.assertEqual(p,.1);self.assertAlmostEqual(a,l);self.assertAlmostEqual(c,w)
        for a,b in zip(calibrate([.6,.1,.3],1),[.6,.1,.3]):self.assertAlmostEqual(a,b)
    def test_ordering_and_endpoints(self):
        for slope in [0,.1,5]:
            values=[calibrate([p,0,1-p],slope)[0] for p in [0,.1,.5,.9,1]]
            self.assertEqual(values,sorted(values))
        self.assertEqual(calibrate([0,0,1],.3),[0,0,1]);self.assertEqual(calibrate([0,0,1],0),[.5,0,.5])
    def test_bad_vectors_and_slope(self):
        for p in [[.8,.2,.2],[-.1,.1,1],[0,1,0],[float('nan'),0,1]]:
            with self.assertRaises(ValueError):calibrate(p,1)
        with self.assertRaises(ValueError):calibrate([.5,0,.5],-1)
    def test_overconfidence_temperature_and_weight_invariance(self):
        p=[.9]*80+[.1]*80;y=[1]*48+[0]*32+[0]*48+[1]*32
        a=fit_slope(p,y,[1]*160)['slope'];b=fit_slope(p*2,y*2,[.5]*320)['slope']
        self.assertGreater(a,0);self.assertLess(a,1);self.assertAlmostEqual(a,b,places=5)
    def test_infinite_loss_is_not_clipped(self):
        self.assertTrue(proper([0,0,1],1)['infinite_logloss']);self.assertIsNone(proper([0,0,1],1)['logloss'])
        self.assertAlmostEqual(proper([0,1,0],0)['threeway_brier'],0)

class CalibrationShadowTests(unittest.TestCase):
    def test_capture_idempotence_grade_and_score_revision_quarantine(self):
        import tempfile,json
        from pathlib import Path
        from datetime import datetime,timezone,timedelta
        from unittest.mock import patch,Mock
        from research.public_market_validation import append_shadow
        from research.ncaaf_calibration import run_shadow
        now=datetime.now(timezone.utc);kickoff=now+timedelta(hours=1)
        e=dict(event_id='TEST',identity=dict(home_id='1',away_id='2',kickoff=kickoff.isoformat()),received_at=(now-timedelta(seconds=1)).isoformat(),
            raw_source=dict(header=dict(competitions=[dict(neutralSite=False)])),parent_record_sha256='p',feature_cutoff='2026-11-03',
            quotes=[dict(book='reference',market='spread',selection='home',line=-3,american_odds=-110,opposing_american_odds=-110,
                         derived_point_kernel_WPL=[.6,.1,.3],scope='full_game_including_overtime_ASSUMPTION')])
        model=dict(coefficients=dict(spread=dict(slope=.5)));reg=dict(registered_at=(now-timedelta(seconds=2)).isoformat(),model_sha256='model')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);parent=root/'parent';state=root/'child';parent.mkdir();state.mkdir()
            (parent/'registration.json').write_text(json.dumps(dict(code_sha256={})))
            append_shadow(parent,dict(observed_at=(now-timedelta(seconds=1)).isoformat(),events=[e]))
            with patch('research.ncaaf_calibration.verify',return_value=(model,reg)):
                a=run_shadow(state,parent,root/'one.json');b=run_shadow(state,parent,root/'two.json')
                self.assertEqual(a['new_rows'],1);self.assertEqual(b['new_rows'],0);self.assertEqual(b['registered_rows'],1)
                data=dict(header=dict(id='TEST',competitions=[dict(date=kickoff.isoformat(),neutralSite=False,status=dict(type=dict(completed=True)),
                    competitors=[dict(homeAway='home',team=dict(id='1'),score='27'),dict(homeAway='away',team=dict(id='2'),score='20')])]))
                response=Mock();response.json.return_value=data;response.content=b'final'
                with patch('research.ncaaf_calibration.datetime') as clock,patch('requests.get',return_value=response):
                    clock.now.return_value=kickoff+timedelta(hours=4)
                    c=run_shadow(state,parent,root/'three.json');self.assertEqual(c['new_grades'],1)
                    data['header']['competitions'][0]['competitors'][0]['score']='28'
                    f=run_shadow(state,parent,root/'four.json');self.assertIn('TEST',f['quarantined_event_ids']);self.assertEqual(f['new_grades'],0)
                    self.assertEqual(f['paired_results'][1]['settled_records'],0)
                    previous=(state/'grades'/'journal.jsonl').read_bytes()
                    g=run_shadow(state,parent,root/'five.json');self.assertIn('TEST',g['quarantined_event_ids'])
    def test_late_capture_not_backfilled(self):
        import tempfile,json
        from pathlib import Path
        from datetime import datetime,timezone,timedelta
        from unittest.mock import patch
        from research.public_market_validation import append_shadow
        from research.ncaaf_calibration import run_shadow
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);parent=root/'p';parent.mkdir();(parent/'registration.json').write_text('{"code_sha256":{}}')
            e=dict(event_id='late',identity=dict(kickoff=(now-timedelta(hours=1)).isoformat()),received_at=now.isoformat())
            append_shadow(parent,dict(observed_at=now.isoformat(),events=[e]))
            with patch('research.ncaaf_calibration.verify',return_value=({},dict(registered_at=(now-timedelta(seconds=1)).isoformat()))):
                r=run_shadow(root/'c',parent,root/'r.json');self.assertEqual(r['new_rows'],0)

if __name__=='__main__':unittest.main()
