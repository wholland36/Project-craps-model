import copy
from datetime import datetime, timedelta, timezone
import pytest
from research.three_sport_validation import masses, tail, forecast, context, build_model, append, create

@pytest.mark.parametrize('sport',['NFL','NCAAF','NCAAB'])
@pytest.mark.parametrize('market,line',[('moneyline',None),('spread',-3),('spread',-3.5),('total',50),('total',50.5)])
def test_joint_complements(sport,market,line):
 c=dict(scores=[[20,17],[0,0],[14,28]] if sport=='NFL' else [[20,17],[14,28]],tail_means=[20.,22.])
 side='over' if market=='total' else 'home';other='under' if market=='total' else 'away'
 p=masses(c,sport,market,side,line);q=masses(c,sport,market,other,-line if market=='spread' else line)
 assert sum(p)==pytest.approx(1);assert min(p)>=0;assert q==pytest.approx(p[::-1])

def test_tail_full_support_and_tie_scope():
 c=dict(scores=[[20,17]],tail_means=[20.,22.])
 assert masses(c,'NFL','spread','home',-100)[0]>0
 assert masses(c,'NFL','moneyline','home')[1]>0
 assert masses(c,'NCAAF','moneyline','home')[1]==0
 assert masses(c,'NCAAB','total','over',50.5)[1]==0

def test_monotone_lines():
 c=dict(scores=[[20,17],[14,28]],tail_means=[20.,22.])
 assert masses(c,'NFL','spread','home',3)[0]>=masses(c,'NFL','spread','home',-3)[0]
 assert masses(c,'NCAAB','total','over',60)[0]<=masses(c,'NCAAB','total','over',50)[0]

def test_line_validation():
 c=dict(scores=[[20,17]],tail_means=[20.,22.])
 for v in [None,True,float('nan'),1.25,501]:
  with pytest.raises(ValueError):masses(c,'NFL','spread','home',v)

def test_journal_tamper(tmp_path):
 append(tmp_path,'receipts',dict(a=1));f=next((tmp_path/'receipts').glob('*.json'));f.write_text('{}')
 with pytest.raises(ValueError):append(tmp_path,'receipts',dict(a=2))

def test_unseen_component_and_clocks():
 m=dict(cutoff='2026-01-01T00:00:00+00:00',context=context([]))
 e=dict(home_id='a',away_id='b',kickoff='2026-02-01T00:00:00+00:00',neutral=False)
 assert forecast(m,e,'2026-01-02T00:00:00+00:00')['status']=='REFUSED'
 with pytest.raises(ValueError):forecast(m,e,e['kickoff'])

def test_fit_cannot_use_future_outcome():
 start=datetime(2023,1,1,tzinfo=timezone.utc);rr=[]
 for i in range(120):
  t=start+timedelta(days=i)
  rr.append(dict(event_id=str(i),home_id='A' if i%2 else 'B',away_id='B' if i%2 else 'A',home_score=20+i%7,away_score=17+i%5,neutral=False,final=True,season=2023,kickoff=t.isoformat(),result_observed_at=(t+timedelta(days=1)).isoformat()))
 cutoff=(start+timedelta(days=110)).isoformat();a,_=build_model(rr,'NFL',cutoff,[])
 changed=copy.deepcopy(rr)
 for r in changed[110:]:r['home_score']=999
 b,_=build_model(changed,'NFL',cutoff,[])
 assert a==b

def test_quarter_boundary_is_forecast_before_kickoff():
 from research.three_sport_validation import replay
 start=datetime(2023,1,1,tzinfo=timezone.utc);rows=[]
 for i in range(200):
  t=start+timedelta(days=i)
  rows.append(dict(event_id=str(i),home_id='A',away_id='B',home_score=20,away_score=17,neutral=False,final=True,season=2023,kickoff=t.isoformat(),result_observed_at=(t+timedelta(days=1)).isoformat()))
 _,_,folds,oof=replay(rows,'NFL')
 assert folds
 assert all(datetime.fromisoformat(f['issued_at'])<datetime.fromisoformat(f['origin']) for f in folds)
 assert any(r['kickoff']=='2023-07-01T00:00:00+00:00' for r in oof)

def test_shadow_first_capture_idempotence_and_impossible_final(tmp_path,monkeypatch):
 import json,requests
 import research.three_sport_validation as m
 monkeypatch.setattr(m,'verify',lambda *a:None)
 monkeypatch.setattr(m,'forecast',lambda *a:dict(status='RESEARCH_ONLY',arms={'rest_form':dict(scores=[[20,17]],tail_means=[20.,17.])}))
 kickoff=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat();done=[False]
 e=dict(id='test',date=kickoff,competitions=[dict(neutralSite=False,status={'type':{'completed':False}},competitors=[dict(id='12',homeAway='home',team={'abbreviation':'KC'},score='20'),dict(id='13',homeAway='away',team={'abbreviation':'BUF'},score='17')])])
 class Response:
  def __init__(self,data):self.data=data;self.content=json.dumps(data).encode()
  def raise_for_status(self):pass
  def json(self):return self.data
 def get(url,**kwargs):
  if '/summary?' in url:return Response(dict(header={'competitions':[dict(date=kickoff,competitors=[dict(homeAway='home',team={'id':'12'}),dict(homeAway='away',team={'id':'13'})])]},pickcenter=[dict(provider={'id':'100','name':'Reference'},homeTeamOdds={'teamId':'12','moneyLine':-110},awayTeamOdds={'teamId':'13','moneyLine':-110})]))
  x=copy.deepcopy(e);x['competitions'][0]['status']['type']['completed']=done[0]
  far=copy.deepcopy(x);far['id']='outside-seven-day-window';far['date']=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat();far['competitions'][0]['status']['type']['completed']=False
  return Response(dict(events=[x,far] if '/nfl/' in url else []))
 monkeypatch.setattr(requests,'get',get)
 create(tmp_path/'protocol.json',dict(registered_at=datetime.now(timezone.utc).isoformat()))
 for s in m.SPORTS:create(tmp_path/s/'model.json',{})
 first=m.shadow(tmp_path,tmp_path/'first.json');assert first['new']['NFL:RESEARCH_ONLY']==1
 assert len(list((tmp_path/'forecasts').glob('*.json')))==1
 assert len(list((tmp_path/'quotes').glob('*.json')))==1
 second=m.shadow(tmp_path,tmp_path/'second.json');assert not second['new']
 done[0]=True;m.shadow(tmp_path,tmp_path/'third.json')
 assert not (tmp_path/'grades').exists()
 assert len(list((tmp_path/'quarantines').glob('*.json')))>=1

def test_comparator_elo_excludes_unavailable_result():
 from research.three_sport_comparators import independent_elo
 h=[dict(event_id='old',home_id='A',away_id='B',home_score=20,away_score=17,neutral=False,kickoff='2026-01-01T00:00:00+00:00',result_observed_at='2026-01-02T00:00:00+00:00')]
 event=dict(event_id='future',home_id='A',away_id='B',neutral=False,kickoff='2026-01-03T00:00:00+00:00')
 a=independent_elo(h,[event],'2026-01-01T12:00:00+00:00');h[0]['home_score']=0
 assert independent_elo(h,[event],'2026-01-01T12:00:00+00:00')==a
 assert independent_elo(h,[event],'2026-01-02T12:00:00+00:00')!=a

def test_official_college_score_kernel_explicit_refund_has_zero_tie_mass():
 from project_craps.model import outcome_masses
 p=outcome_masses([[70,60],[60,70]],'moneyline','home',None,tie_policy='refund')
 assert p==pytest.approx([.5,0,.5])
