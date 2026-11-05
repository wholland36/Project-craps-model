import json,hashlib
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import numpy as np
import pytest
import research.injury_shock as m

def test_transition_not_missing_as_healthy():
 assert m.shock('Out','Available')==1
 assert m.shock('Available','Out')==-1
 assert m.shock('Out','Out')==0
 assert m.shock('Available','Available')==0
 for state in [None,'Questionable','Exempt','-']:assert m.shock('Out',state) is None

def test_opportunities_are_aggregate_not_mean_percent_and_missing_is_unknown():
 gs=[{'opportunities':{'p':1,'other':9}},{'opportunities':{'p':50,'other':50}}]
 assert m.workload_share('p',gs)==51/110
 assert m.workload_share('p',[]) is None
 with pytest.raises(ValueError):m.workload_share('p',[{'opportunities':{'p':-1}}])

def test_joint_cap_and_return_orientation():
 a={'group':'RUSH','gap':10.,'workload':.8,'shock':1.,'replacement_ids':['backup']}
 b=dict(a,workload=.7)
 r=m.aggregate([a,b]);assert r['workload_cap_divisor']['RUSH']==1.5
 assert r['signed_loss_by_group']['RUSH']==10.
 assert r['shared_backup_ids']['RUSH']=={'backup':2}
 assert m.aggregate([dict(a,shock=-1.)])['signed_loss_by_group']['RUSH']==-8
 with pytest.raises(ValueError):m.aggregate([dict(a,workload=2)])

def test_constrained_effects_and_unidentified_constant():
 X=np.array([[0,1,0],[0,2,0],[0,3,0],[0,4,0]],float)
 fitted=m.fit_nonnegative(X,np.array([4,3,2,1.]),10)
 assert fitted['raw_coefficients']==[0.,0.,0.]
 fitted=m.fit_nonnegative(X,np.array([1,2,3,4.]),10)
 assert fitted['raw_coefficients'][1]>0
 assert m.correction(fitted,{'QB':0,'RUSH':2,'RECEIVE':0})>m.correction(fitted,{'QB':0,'RUSH':1,'RECEIVE':0})
 with pytest.raises(ValueError):m.fit_nonnegative(X,np.ones(3),10)

def setup(tmp_path,monkeypatch,clock=None):
 now=clock or datetime.now(timezone.utc)
 class Clock(datetime):
  @classmethod
  def now(cls,tz=None):return now
 monkeypatch.setattr(m,'datetime',Clock)
 protocol=tmp_path/'protocol.json';protocol.write_text('{}')
 source=m.capture_snapshot(tmp_path/'snapshots','https://example.org/synthetic-source',b'{"synthetic":true}')
 model={'frozen_at':(now-timedelta(hours=1)).isoformat(),'baseline_model_sha256':'a'*64,'feature_code_sha256':m.digest(m.Path(m.__file__).read_bytes()),'protocol_path':str(protocol),'protocol_sha256':m.digest(protocol.read_bytes()),'shadow_injury_model':{'intercept':.5,'raw_coefficients':[1,2,3]},'selected_research_model':{'intercept':2.,'raw_coefficients':[0,0,0]},'benchmarks':{'train_mean_intercept':1.,'train_median_intercept':2.},'prospective_season':2026,'prospective_start':(now-timedelta(days=1)).isoformat(),'prospective_end':(now+timedelta(days=3)).isoformat(),'prospective_thresholds':{'min_games':2,'min_nonzero_shock_games':1,'min_week_blocks':1}}
 artifact=tmp_path/'candidate.json';artifact.write_text(json.dumps(model))
 rec={'event_id':'synthetic1','home_id':'1','away_id':'2','season':2026,'season_type':2,'week':10,'cutoff':now.isoformat(),'kickoff':(now+timedelta(hours=1)).isoformat(),'baseline_model_sha256':'a'*64,'baseline_expected_home_margin':10.,'feature_code_sha256':model['feature_code_sha256'],'sources':[source],'features':dict.fromkeys(m.GROUPS,0.),'resolved_player_shocks':{'home':[],'away':[]},'missing_inputs':['Synthetic test: unknown contributions omitted'],'feature_audit_status':'CALLER_RECONSTRUCTED_FROM_SNAPSHOTS_NOT_INDEPENDENTLY_AUTHENTICATED'}
 return artifact,rec,tmp_path/'injury-shock-synthetic',protocol,source,now

def test_registration_reconstructs_features_and_preserves_first(tmp_path,monkeypatch):
 artifact,r,folder,_,_,_=setup(tmp_path,monkeypatch)
 out=m.register_forecast(folder,artifact,r);assert out['shadow_expected_home_margin']==10.5 and out['selected_research_expected_home_margin']==12
 raw=(folder/'synthetic1.json').read_bytes()
 with pytest.raises(FileExistsError):m.register_forecast(folder,artifact,r)
 assert (folder/'synthetic1.json').read_bytes()==raw
 bad=deepcopy(r);bad['features']['QB']=1
 with pytest.raises(ValueError,match='features do not match'):m.register_forecast(folder,artifact,bad)

def test_register_rejects_started_future_sources_and_wrong_code(tmp_path,monkeypatch):
 a,r,f,_,_,now=setup(tmp_path,monkeypatch)
 bad=deepcopy(r);bad['kickoff']=(now-timedelta(hours=1)).isoformat()
 with pytest.raises(ValueError):m.register_forecast(f,a,bad)
 bad=deepcopy(r);bad['cutoff']=(now-timedelta(minutes=10)).isoformat()
 with pytest.raises(ValueError,match='future source'):m.register_forecast(f,a,bad)
 bad=deepcopy(r);bad['feature_code_sha256']='f'*64
 with pytest.raises(ValueError,match='code'):m.register_forecast(f,a,bad)
 with pytest.raises(ValueError,match='separate named'):m.register_forecast(tmp_path/'official',a,r)

def test_source_bytes_and_protocol_tampering(tmp_path,monkeypatch):
 a,r,f,p,source,now=setup(tmp_path,monkeypatch)
 p.write_text('{"tampered":true}')
 with pytest.raises(ValueError,match='protocol changed'):m.register_forecast(f,a,r)
 p.write_text('{}');receipt=json.loads(m.Path(source['receipt_path']).read_text());m.Path(receipt['snapshot_path']).write_bytes(b'tampered')
 with pytest.raises(ValueError,match='snapshot hash'):m.register_forecast(f,a,r)

def test_workload_healthy_window_is_validated(tmp_path,monkeypatch):
 a,r,f,_,_,now=setup(tmp_path,monkeypatch)
 player={'group':'QB','gap':1.,'workload':1.,'shock':1.,'replacement_ids':['b'],'current_status':'Out','previous_status':'Available','player_key':'p','healthy_games':[{'kickoff':(now-timedelta(hours=12)).isoformat(),'status':'Available','opportunities':{'p':1}}]}
 r['resolved_player_shocks']['away']=[player];r['features']['QB']=1
 with pytest.raises(ValueError,match='healthy workload cutoff'):m.register_forecast(f,a,r)
 player['healthy_games'][0]['kickoff']=(now-timedelta(days=7)).isoformat();out=m.register_forecast(f,a,r)
 assert out['shadow_expected_home_margin']==11.5

def test_settlement_keeps_all_benchmarks_and_detects_identity_and_record_tamper(tmp_path,monkeypatch):
 real_now=datetime.now(timezone.utc);a,r,f,_,_,clock=setup(tmp_path,monkeypatch,real_now-timedelta(hours=5));m.register_forecast(f,a,r)
 class Current(datetime):
  @classmethod
  def now(cls,tz=None):return real_now
 monkeypatch.setattr(m,'datetime',Current)
 source=m.capture_snapshot(tmp_path/'final-snapshots','https://example.org/synthetic-final',b'{"syntheticFinal":true}')
 final={'event_id':r['event_id'],'home_id':'1','away_id':'2','kickoff':r['kickoff'],'home_score':20,'away_score':7,'final':True,'observed_at':real_now.isoformat(),'source':source}
 out=m.evaluate_registered(f,{r['event_id']:final},a)
 assert out['settled_games']==1 and not out['predeclared_sample_horizon_reached']
 assert out['results'][0]['absolute_errors']=={'baseline':3.,'shadow':2.5,'selected':1.,'train_mean':2.,'train_median':1.}
 bad=dict(final,home_id='wrong')
 with pytest.raises(ValueError,match='identity'):m.evaluate_registered(f,{r['event_id']:bad},a)
 path=f/'synthetic1.json';path.write_text(path.read_text()+' ')
 with pytest.raises(ValueError,match='immutable'):m.evaluate_registered(f,{r['event_id']:final},a)


def test_deleted_or_copied_registry_records_cannot_disappear_or_duplicate(tmp_path,monkeypatch):
 a,r,f,_,_,now=setup(tmp_path,monkeypatch);m.register_forecast(f,a,r)
 original=f/'synthetic1.json';body=original.read_bytes();original.unlink()
 with pytest.raises(ValueError,match='deleted, copied'):m.evaluate_registered(f,{},a)
 original.write_bytes(body);(f/'copy.json').write_bytes(body)
 with pytest.raises(ValueError,match='deleted, copied'):m.evaluate_registered(f,{},a)


def test_local_verified_baseline_artifact_is_not_misattributed_to_a_public_url(tmp_path):
 source=m.capture_snapshot(tmp_path/'snapshots','local-artifact:/synthetic-baseline.json',b'{"baseline":true}')
 receipt=m.verify_snapshot(source,datetime.now(timezone.utc))
 assert receipt['url'].startswith('local-artifact:') and not receipt['independent_source_authentication']
