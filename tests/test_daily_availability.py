from research.daily_availability import validate_contributions,adjust,collect
import json,hashlib
import pytest
CUT='2026-11-05T18:00:00Z'
EVENT={'event_id':'1','home_id':'a','away_id':'b','kickoff':'2026-11-06T18:00:00Z'}

def row(sport='NCAAF'):
 return dict(player_id='p',side='home',team_id='a',event_id='1',sport=sport,status='Out',identity_verified=True,role_verified=True,workload_verified=True,source_report_authenticated=True,source_sha256='hash',published_at='2026-11-05T16:00:00Z',replacement_identity_verified=True,replacement_player_ids=['r'],workload=.5,signed_loss=3,position='WR',group='RECEIVE')
SRC=[{'status':'CAPTURED','sha256':'hash','observed_at':'2026-11-05T17:00:00Z'}]

def test_known_unknown_and_identity():
 k,u=validate_contributions([row()], 'NCAAF',EVENT,CUT,SRC);assert len(k)==1 and not u
 for key,value in [('published_at','2026-11-07T00:00:00Z'),('team_id','wrong'),('source_sha256','missing'),('workload',None),('source_report_authenticated',False),('status','Questionable')]:
  r=row();r[key]=value;k,u=validate_contributions([r],'NCAAF',EVENT,CUT,SRC);assert not k and u

def test_basketball_not_ea_scale():
 r=row('NCAAB');r['value_scale']='EA_OVR';r['workload_type']='minutes_share'
 assert not validate_contributions([r],'NCAAB',EVENT,CUT,SRC)[0]
 r['value_scale']='NCAAB_INDEPENDENT_POINTS_PER_FULL_ROLE'
 assert validate_contributions([r],'NCAAB',EVENT,CUT,SRC)[0]

def test_qb_role_required():
 r=row();r['position']='QB'
 assert not validate_contributions([r],'NCAAF',EVENT,CUT,SRC)[0]

def test_unknown_no_baseline_copy():
 c={'sport':'NFL','cutoff':CUT,'known_contributions':[]}
 x=adjust(7,c,None);assert x['status']=='NOT_COMPUTED' and x['adjusted_point'] is None

def test_generic_value_hash_and_sport_scope():
 c={'sport':'NFL','cutoff':CUT,'known_contributions':[dict(row('NFL'))]}
 m={'sport':'NFL','independently_trained':True,'trained_before':'2026-10-01T00:00:00Z','coefficients':{'RECEIVE':2},'identified_groups':['RECEIVE']}
 m['model_sha256']=hashlib.sha256(json.dumps(m,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 assert adjust(7,c,m)['adjusted_point']==1
 m['coefficients']['RECEIVE']=5
 with pytest.raises(ValueError):adjust(7,c,m)

def test_past_capture_no_network(tmp_path):
 r=collect('NFL',EVENT,'2020-01-01T00:00:00Z',tmp_path)
 assert not r['sources'] and 'capture_deadline_not_future_pregame' in r['issueflags']

def test_frozen_zero_coefficients_are_not_improvement():
 from pathlib import Path
 p=Path('../../outputs/injury-shock-20261105/candidate-frozen.json')
 c={'sport':'NCAAF','cutoff':CUT,'known_contributions':[row()]}
 x=adjust(7,c,{'frozen_candidate_path':str(p)})
 assert x['injury_delta']==0 and x['adjusted_point'] is None
 assert 'UNIDENTIFIED' in x['status']

def test_canonical_nfl_uses_espn_ids_and_daily_cache(tmp_path,monkeypatch):
 from datetime import datetime,timezone,timedelta
 import research.daily_availability as mod
 now=datetime.now(timezone.utc);calls=[]
 class Response:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self):return b'{}'
 def fetch(request,timeout):calls.append(request.full_url);return Response()
 monkeypatch.setattr(mod.urllib.request,'urlopen',fetch)
 event=dict(event_id='2026_09_HOU_LAC',home_id='LAC',away_id='HOU',espn_event_id='401',home_espn_id='24',away_espn_id='34',kickoff=(now+timedelta(hours=2)).isoformat())
 cutoff=(now+timedelta(minutes=5)).isoformat()
 a=collect('NFL',event,cutoff,tmp_path);b=collect('NFL',event,cutoff,tmp_path)
 assert a['event_id']=='2026_09_HOU_LAC' and len(calls)==4
 assert any('summary?event=401' in u for u in calls)
 assert any('/teams/24/roster' in u for u in calls)
 assert len(a['sources'])==len(b['sources'])==4

def test_duplicate_known_rows_both_unresolved():
 r=row();k,u=validate_contributions([r,r],'NCAAF',EVENT,CUT,SRC)
 assert not k and len(u)==2
