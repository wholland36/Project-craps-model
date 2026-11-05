from datetime import datetime,timedelta,timezone
import pytest
from research.beta_v2.strength import boolean,fit,predict,instant
from research.beta_v2.training import join_box

def rows(sport='NFL'):
 start=datetime(2025,1,1,tzinfo=timezone.utc)
 return [dict(event_id=str(i),kickoff=(start+timedelta(days=i)).isoformat(),result_observed_at=(start+timedelta(days=i,hours=24)).isoformat(),season=2025,home_id='a' if i%2 else 'b',away_id='b' if i%2 else 'a',home_score=75 if sport=='NCAAB' else 24,away_score=68 if sport=='NCAAB' else 17,neutral=False,final=True,possessions=70,minutes=45 if i%10==0 else 40) for i in range(80)]
def test_boolean_false_string():
 assert boolean('FALSE') is False
 with pytest.raises(ValueError):boolean('unknown')
def test_no_future_result_and_no_stale_split():
 rr=rows();m=fit(rr,sport='NFL',cutoff='2025-03-23T00:00:00+00:00')
 assert m['train_n']==80
 assert m['train_last']==rr[-1]['kickoff']
 assert fit(rr,sport='NFL',cutoff='2025-03-12T00:00:00+00:00')['train_n']==69
def test_regulation_pace_ot_separate():
 m=fit(rows('NCAAB'),sport='NCAAB',cutoff='2025-04-01T00:00:00+00:00',residuals=[[0,0],[1,-1]])
 assert all(v<70 for v in m['pace'].values())
 assert m['ot_expected_extra_fraction']>0
 assert m['train_n']==80
 p=predict(m,dict(home_id='a',away_id='b',kickoff='2025-04-02T00:00:00+00:00',neutral=False))
 assert p['status']=='RESEARCH_ONLY'
def test_forecast_cutoff_guard():
 m=fit(rows(),sport='NFL',cutoff='2025-04-01T00:00:00+00:00')
 with pytest.raises(ValueError):predict(m,dict(home_id='a',away_id='b',kickoff='2025-03-01T00:00:00+00:00',neutral=False))
def test_box_participants_and_scores():
 r=dict(home_id='1',away_id='2',home_score=70,away_score=60)
 b=[dict(team_id=i,opponent_team_id=3-i,team_score=70 if i==1 else 60,field_goals_attempted=60,free_throws_attempted=20,offensive_rebounds=10,turnovers=12) for i in [1,2]]
 assert join_box(r,b)>0
 with pytest.raises(ValueError):join_box(r,b+[b[0]])
 b[1]['team_id']=1
 with pytest.raises(ValueError):join_box(r,b)
def test_naive_timestamp_rejected():
 with pytest.raises(ValueError):instant('2025-01-01')
def test_fit_rejects_duplicate_and_false_string_neutral_consistent():
 rr=rows()
 with pytest.raises(ValueError):fit(rr+[rr[0]],sport='NFL',cutoff='2025-04-01T00:00:00+00:00')
 m=fit(rr,sport='NFL',cutoff='2025-04-01T00:00:00+00:00',residuals=[[0,0]])
 event=dict(home_id='a',away_id='b',kickoff='2025-04-02T00:00:00+00:00',neutral='FALSE')
 a=predict(m,event);event['neutral']=False
 assert a['point_scores']==predict(m,event)['point_scores']
def test_box_score_mismatch_quarantines():
 r=dict(home_id='1',away_id='2',home_score=70,away_score=60)
 b=[dict(team_id=i,opponent_team_id=3-i,team_score=999,field_goals_attempted=60,free_throws_attempted=20,offensive_rebounds=10,turnovers=12) for i in [1,2]]
 with pytest.raises(ValueError,match='score_mismatch'):join_box(r,b)
