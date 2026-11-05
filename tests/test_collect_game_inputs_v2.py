import copy
from research.collect_game_inputs_v2 import parse_summary,collect
G=dict(event_id='1',home_id='a',away_id='b',kickoff='2026-09-01T00:00:00Z')

def body():
    return {'header':{'competitions':[{'id':'1','date':G['kickoff'],'status':{'type':{'completed':True}},'competitors':[{'id':'a','homeAway':'home','score':'14','linescores':[{'displayValue':str(x)} for x in [7,0,7,0]]},{'id':'b','homeAway':'away','score':'10','linescores':[{'displayValue':str(x)} for x in [0,3,0,7]]}]}]},'drives':{'previous':[{'id':'d','plays':[{'id':'p'}]}]}}

def test_regulation_without_possession_claim():
    r=parse_summary(body(),G)
    assert r['regulation_score']=={'home':14,'away':10} and r['overtime'] is False
    assert r['observed_drive_count']==1 and r['observed_play_rows']==1
    assert r['complete_drive_count'] is None and r['possession_count'] is None
    assert r['original_completion_at'] is None

def test_overtime_separated():
    b=body();c=b['header']['competitions'][0]['competitors']
    for t in c:t['linescores'].append({'displayValue':'3'});t['score']=str(int(t['score'])+3)
    r=parse_summary(b,G);assert r['overtime'] and r['regulation_score']['home']==14

def test_missing_and_bad_periods():
    b=body();b['header']['competitions'][0]['competitors'][0]['linescores'].pop()
    assert parse_summary(b,G)['regulation_score'] is None
    b=body();b['header']['competitions'][0]['competitors'][0]['score']='99'
    assert parse_summary(b,G)['regulation_score'] is None

def test_identity_and_nonfinal_quarantine():
    b=body();b['header']['competitions'][0]['id']='wrong'
    assert parse_summary(b,G)['regulation_score'] is None
    b=body();b['header']['competitions'][0]['status']['type']['completed']=False
    assert parse_summary(b,G)['regulation_score'] is None

def test_incomplete_duplicate_drives():
    b=body();b['drives']['previous']*=2
    r=parse_summary(b,G);assert not r['drive_internal_checks']['unique_play_ids']
    b=body();b['drives']['previous'][0]['plays']=[]
    r=parse_summary(b,G);assert not r['drive_internal_checks']['every_drive_has_plays']
    assert r['complete_play_count'] is None
    b=body();b['drives']['current']={'id':'active'}
    assert not parse_summary(b,G)['drive_internal_checks']['no_current_drive']

def test_missing_drives_keeps_game():
    b=body();del b['drives'];r=parse_summary(b,G)
    assert r['regulation_score'] is not None and r['observed_drive_count']==0
    assert r['possession_count'] is None

def test_fractional_boolean_nonfinite_scores_rejected():
    for malformed in (3.5,True,float('nan'),float('inf'),-1,'3.5','-1',' 3'):
        b=body();c=b['header']['competitions'][0]['competitors'][0]
        c['linescores']=[{'value':malformed},{'value':0},{'value':0},{'value':0}];c['score']='3'
        assert parse_summary(b,G)['regulation_score'] is None
        b=body();b['header']['competitions'][0]['competitors'][0]['score']=malformed
        assert parse_summary(b,G)['regulation_score'] is None
