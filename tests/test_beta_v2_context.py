from datetime import datetime,timedelta
import pytest
from research.beta_v2.context import capture_candidates,validate_roles,validate_features,validate_rotation,allocate_non_qb,validate_value_model,digest
T='2026-11-05T16:00:00+00:00'
E={'event_id':'canonical1','espn_event_id':'401','home_id':'A','away_id':'B','home_espn_id':'1','away_espn_id':'2','kickoff':'2026-11-05T23:00:00+00:00'}
def test_capture_horizon_cache_immutable(tmp_path):
 calls=[]
 def fetch(url):calls.append(url);return b'{}'
 now=datetime.fromisoformat(T)
 capture_candidates('NFL',E,T,tmp_path,'morning',fetch,now)
 capture_candidates('NFL',E,T,tmp_path,'morning',fetch,now)
 assert len(calls)==4
 capture_candidates('NFL',E,T,tmp_path,'final',fetch,now)
 assert len(calls)==8
 for p in tmp_path.rglob('*.body.json'):assert p.stat().st_mode&0o777==0o600

def test_capture_clock_identity_failures(tmp_path):
 assert capture_candidates('NFL',E,T,tmp_path,'x',lambda u:b'{}',datetime.fromisoformat(T)+timedelta(hours=1))['sources']==[]
 with pytest.raises(ValueError):capture_candidates('NFL',dict(E,espn_event_id=None),T,tmp_path,'x')
 calls=[]
 def fail(u):calls.append(u);raise OSError()
 capture_candidates('NFL',E,T,tmp_path,'x',fail,datetime.fromisoformat(T))
 capture_candidates('NFL',E,T,tmp_path,'x',fail,datetime.fromisoformat(T))
 assert len(calls)==4

def test_tamper(tmp_path):
 capture_candidates('NFL',E,T,tmp_path,'x',lambda u:b'{}',datetime.fromisoformat(T))
 next(tmp_path.rglob('*.body.json')).write_text('{"bad":1}')
 r=capture_candidates('NFL',E,T,tmp_path,'x',lambda u:b'{}',datetime.fromisoformat(T))
 assert any(s['status']=='HASH_MISMATCH' for s in r['sources'])

def role():return {'sport':'NFL','event_id':'canonical1','team_id':'A','player_id':'p','source_sha256':'a','source_authenticated':True,'published_at':'2026-11-05T15:59:00+00:00','identity_verified':True,'role_verified':True,'workload_verified':True,'replacement_verified':True,'status':'Out','value_scale':'NFL_INDEPENDENT_POINTS_PER_FULL_ROLE','workload':1.,'position':'QB','qb_role_verified':True,'replacement_player_ids':['q']}
def sources():return [{'sha256':'a','status':'CAPTURED','observed_at':T}]
def test_roles_qb_uncertain_duplicate_clocks():
 assert len(validate_roles('NFL',E,T,[role()],sources())[0])==1
 r=role();r['status']='Questionable';r['scenarios']=[{'restoration_fraction':.5,'probability':.7}]
 assert 'unfitted_scenario_probability_forbidden' in validate_roles('NFL',E,T,[r],sources())[1][0]['missing_flags']
 r=role();r['qb_role_verified']=False
 assert not validate_roles('NFL',E,T,[r],sources())[0]
 assert len(validate_roles('NFL',E,T,[role(),role()],sources())[1])==2
 assert not validate_roles('NFL',E,T,[role()],[{'sha256':'a','status':'CAPTURED','observed_at':'2026-11-05T16:01:00+00:00'}])[0]

def test_effective_features():
 r={'kind':'drive','team_id':'A','drives':10,'points':20,'non_garbage_drives':8,'through_game_id':'prior','statistics_through':'2026-11-04T00:00:00+00:00','effective_from':'2026-11-04T00:00:00+00:00','source_sha256':'a','published_at':'2026-11-05T15:59:00+00:00','source_authenticated':True}
 assert len(validate_features([r],sources(),T)[0])==1
 r['statistics_through']=T
 assert not validate_features([r],sources(),T)[0]

def test_replacement_and_rotations():
 losses=[{'team_id':'A','player_id':'o1','position':'WR','rating':95},{'team_id':'A','player_id':'o2','position':'WR','rating':94}]
 roster=[{'team_id':'A','player_id':str(i),'position':'WR','rating':r,'status':'Available'} for i,r in enumerate([90,80,70,60])]
 r=allocate_non_qb(losses,roster)
 assert r[0]['primary_rating']==80 and r[1]['primary_rating']==80 and r[1]['capacity_scenario_rating']==60
 assert allocate_non_qb(losses[:1],roster[:2])[0]['primary_rating']==85
 assert validate_rotation([{'player_id':str(i),'regulation_minutes':40} for i in range(5)],'NCAAB')['valid']
 assert not validate_rotation([{'player_id':'p','regulation_minutes':40}],'NCAAB')['valid']
 assert not validate_rotation([{'player_id':str(i),'role':'qb','role_share':1,'role_capacity':1} for i in range(2)],'NFL')['valid']

def test_value_interface_no_invented_fit():
 m={'sport':'NFL','value_scale':'NFL_INDEPENDENT_POINTS_PER_FULL_ROLE','independently_trained':True,'trained_through':'2025-01-01T00:00:00+00:00','training_source_sha256':['abc'],'coefficients':{'QB':1.},'support':{'QB':{'exposures':40,'design_rank':1,'required_rank':1}}}
 m['sha256']=digest(m);assert validate_value_model(m,'NFL',T)['valid']
 m['support']['QB']['design_rank']=0;m['sha256']=digest({k:v for k,v in m.items() if k!='sha256'})
 assert not validate_value_model(m,'NFL',T)['valid']

def test_fit_interface_refuses_sparse_and_unverified():
 from research.beta_v2.context import fit_value_model
 assert fit_value_model([], 'NFL',T,['QB'])['status']=='UNFITTED'
 rows=[{'sport':'NFL','independent_oos_residual':True,'features_authenticated':True,'outcome_verified':True,'feature_source_sha256':'f','outcome_source_sha256':'o','features_observed_at':'2025-01-01T00:00:00+00:00','kickoff':'2025-01-02T00:00:00+00:00','outcome_at':'2025-01-03T00:00:00+00:00','features':{'QB':1.},'residual_margin':2.}]
 assert fit_value_model(rows,'NFL',T,['QB'])['status']=='UNFITTED'

def value_model():
 m={'sport':'NFL','value_scale':'NFL_INDEPENDENT_POINTS_PER_FULL_ROLE','independently_trained':True,'trained_through':'2025-01-01T00:00:00+00:00','training_source_sha256':['a'],'coefficients':{'QB':2.},'support':{'QB':{'exposures':40,'design_rank':1,'required_rank':1}},'feature_convention':'home_margin_signed_burden_innovation'}
 m['sha256']=digest(m);return m

def test_apply_injury_direction_no_double_workload():
 from research.beta_v2.context import apply_value_model
 r=dict(role(),group='QB',burden_innovation=3.,workload=.5)
 c={'sport':'NFL','event_id':'canonical1','asof':T,'known':[r],'sources':sources()}
 assert apply_value_model(c,E,value_model(),T)['delta_mean_margin']==-6.
 c['known'][0]['team_id']='B'
 assert apply_value_model(c,E,value_model(),T)['delta_mean_margin']==6.
 c['known'][0].pop('burden_innovation')
 assert apply_value_model(c,E,value_model(),T)['status']=='NOT_COMPUTED'

def test_apply_empty_uncertain_unverified_and_unfitted():
 from research.beta_v2.context import apply_value_model
 c={'sport':'NFL','event_id':'canonical1','asof':T,'known':[],'sources':sources()}
 assert apply_value_model(c,E,value_model(),T)['status']=='NOT_COMPUTED'
 c['known']=[dict(role(),group='QB',burden_innovation=1.,status='Questionable',scenarios=[{'restoration_fraction':0.},{'restoration_fraction':.5}])]
 r=apply_value_model(c,E,value_model(),T)
 assert r['delta_mean_margin'] is None and len(r['scenarios'])==1
 c['known'][0]['status']='Out';c['known'][0]['source_authenticated']=False
 assert apply_value_model(c,E,value_model(),T)['status']=='NOT_COMPUTED'
 assert apply_value_model(c,E,{},T)['status']=='NOT_COMPUTED'

def test_multiple_losses_require_feasible_authenticated_rotation():
 from research.beta_v2.context import apply_value_model
 c={'sport':'NFL','event_id':'canonical1','asof':T,'known':[dict(role(),player_id='a',group='QB',burden_innovation=1.),dict(role(),player_id='b',position='WR',group='QB',burden_innovation=1.)],'sources':sources()}
 assert apply_value_model(c,E,value_model(),T)['missing']==['verified_multiple_loss_rotation_missing']
 evidence={'complete_rotation_verified':True,'covered_loss_ids':['a','b'],'source_authenticated':True,'source_sha256':'a','published_at':'2026-11-05T15:59:00+00:00','rows':[{'player_id':'backup','role':'qb','role_share':1.,'role_capacity':1.}]}
 c['rotation_by_team']={'A':evidence}
 assert apply_value_model(c,E,value_model(),T)['delta_mean_margin']==-4.
 evidence['rows'].append({'player_id':'backup2','role':'qb','role_share':1.,'role_capacity':1.})
 assert apply_value_model(c,E,value_model(),T)['status']=='NOT_COMPUTED'
